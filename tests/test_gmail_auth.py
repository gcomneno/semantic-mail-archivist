from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from semantic_mail_archivist import (
    GMAIL_READONLY_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GmailAccountSafeId,
    GmailAuthError,
    GmailAuthErrorCode,
    GmailAuthManager,
    GmailAuthPaths,
    GmailAuthorizationMode,
    scopes_for_mode,
)


@dataclass
class FakeCredentials:
    scopes: tuple[str, ...]
    valid: bool
    expired: bool = False
    refresh_token: str | None = None
    token: str = "synthetic-access-token"


class FakeBackend:
    def __init__(self) -> None:
        self.loaded: FakeCredentials | None = None
        self.authorized: FakeCredentials | None = None
        self.refresh_should_fail = False
        self.authorization_should_fail = False
        self.load_calls = 0
        self.refresh_calls = 0
        self.authorization_calls = 0
        self.requested_scopes: tuple[str, ...] | None = None

    def load_token(self, token_path: Path):
        self.load_calls += 1
        if self.loaded is None:
            raise RuntimeError("synthetic raw token load failure")
        return self.loaded

    def refresh(self, credentials):
        self.refresh_calls += 1
        if self.refresh_should_fail:
            raise RuntimeError(
                "RAW-SECRET-REFRESH-FAILURE"
            )

        credentials.valid = True
        credentials.expired = False

    def authorize_installed_app(
        self,
        client_config: Path,
        scopes: tuple[str, ...],
    ):
        self.authorization_calls += 1
        self.requested_scopes = scopes

        if self.authorization_should_fail:
            raise RuntimeError(
                "RAW-SECRET-OAUTH-FAILURE"
            )

        if self.authorized is None:
            raise RuntimeError(
                "no synthetic authorization configured"
            )

        return self.authorized

    def serialize(self, credentials) -> str:
        return json.dumps(
            {
                "token": credentials.token,
                "scopes": list(credentials.scopes),
            },
            sort_keys=True,
        )


class GmailAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.paths = GmailAuthPaths(
            client_config=(
                self.root / "config" / "gmail-client.json"
            ),
            read_token=(
                self.root / "state" / "read-token.json"
            ),
            write_token=(
                self.root / "state" / "write-token.json"
            ),
            account_id_key=(
                self.root / "state" / "account-id.key"
            ),
        )

        self.backend = FakeBackend()
        self.manager = GmailAuthManager(
            self.paths,
            backend=self.backend,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _touch_token(
        self,
        mode: GmailAuthorizationMode,
    ) -> Path:
        path = self.paths.token_for(mode)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            "{}",
            encoding="utf-8",
        )
        return path

    def _touch_client(self) -> None:
        self.paths.client_config.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.paths.client_config.write_text(
            '{"installed": {}}',
            encoding="utf-8",
        )

    def test_scope_policy_is_least_privilege_and_explicit(self):
        self.assertEqual(
            scopes_for_mode(
                GmailAuthorizationMode.READ_ONLY
            ),
            (GMAIL_READONLY_SCOPE,),
        )
        self.assertEqual(
            scopes_for_mode(
                GmailAuthorizationMode.M1_WRITE
            ),
            (GMAIL_MODIFY_SCOPE,),
        )

        all_scopes = {
            *scopes_for_mode(
                GmailAuthorizationMode.READ_ONLY
            ),
            *scopes_for_mode(
                GmailAuthorizationMode.M1_WRITE
            ),
        }

        self.assertNotIn(
            "https://mail.google.com/",
            all_scopes,
        )
        self.assertNotIn(
            "https://www.googleapis.com/auth/gmail.metadata",
            all_scopes,
        )

    def test_read_and_write_tokens_are_separate(self):
        self.assertNotEqual(
            self.paths.read_token,
            self.paths.write_token,
        )
        self.assertEqual(
            self.paths.token_for(
                GmailAuthorizationMode.READ_ONLY
            ),
            self.paths.read_token,
        )
        self.assertEqual(
            self.paths.token_for(
                GmailAuthorizationMode.M1_WRITE
            ),
            self.paths.write_token,
        )

    def test_valid_read_token_is_reused_without_interactive_flow(self):
        self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )
        self.backend.loaded = FakeCredentials(
            scopes=(GMAIL_READONLY_SCOPE,),
            valid=True,
        )

        session = self.manager.authorize(
            GmailAuthorizationMode.READ_ONLY
        )

        self.assertEqual(
            session.mode,
            GmailAuthorizationMode.READ_ONLY,
        )
        self.assertEqual(
            self.backend.load_calls,
            1,
        )
        self.assertEqual(
            self.backend.authorization_calls,
            0,
        )

    def test_read_mode_rejects_write_scoped_token(self):
        self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )
        self.backend.loaded = FakeCredentials(
            scopes=(GMAIL_MODIFY_SCOPE,),
            valid=True,
        )

        with self.assertRaises(GmailAuthError) as context:
            self.manager.authorize(
                GmailAuthorizationMode.READ_ONLY
            )

        self.assertEqual(
            context.exception.code,
            GmailAuthErrorCode.TOKEN_SCOPE_MISMATCH,
        )

    def test_write_mode_never_reuses_read_token(self):
        self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )

        with self.assertRaises(GmailAuthError) as context:
            self.manager.authorize(
                GmailAuthorizationMode.M1_WRITE,
                interactive=False,
            )

        self.assertEqual(
            context.exception.code,
            GmailAuthErrorCode.AUTHORIZATION_REQUIRED,
        )
        self.assertEqual(
            self.backend.load_calls,
            0,
        )

    def test_noninteractive_missing_token_requires_authorization(self):
        with self.assertRaises(GmailAuthError) as context:
            self.manager.authorize(
                GmailAuthorizationMode.READ_ONLY,
                interactive=False,
            )

        self.assertEqual(
            context.exception.code,
            GmailAuthErrorCode.AUTHORIZATION_REQUIRED,
        )

    def test_missing_client_config_fails_closed(self):
        with self.assertRaises(GmailAuthError) as context:
            self.manager.authorize(
                GmailAuthorizationMode.READ_ONLY
            )

        self.assertEqual(
            context.exception.code,
            GmailAuthErrorCode.MISSING_CLIENT_CONFIG,
        )
        self.assertEqual(
            self.backend.authorization_calls,
            0,
        )

    def test_interactive_flow_persists_private_mode_token(self):
        self._touch_client()
        self.backend.authorized = FakeCredentials(
            scopes=(GMAIL_READONLY_SCOPE,),
            valid=True,
            refresh_token="synthetic-refresh",
        )

        session = self.manager.authorize(
            GmailAuthorizationMode.READ_ONLY
        )

        self.assertEqual(
            self.backend.requested_scopes,
            (GMAIL_READONLY_SCOPE,),
        )
        self.assertEqual(
            session.token_path,
            self.paths.read_token,
        )
        self.assertTrue(
            self.paths.read_token.is_file()
        )
        self.assertFalse(
            self.paths.write_token.exists()
        )

        if os.name == "posix":
            self.assertEqual(
                stat.S_IMODE(
                    self.paths.read_token.stat().st_mode
                ),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(
                    self.paths.read_token.parent.stat().st_mode
                ),
                0o700,
            )

    def test_interactive_flow_protects_client_config_file(self):
        self._touch_client()

        if os.name == "posix":
            os.chmod(
                self.paths.client_config,
                0o644,
            )

        self.backend.authorized = FakeCredentials(
            scopes=(GMAIL_READONLY_SCOPE,),
            valid=True,
            refresh_token="synthetic-refresh",
        )

        self.manager.authorize(
            GmailAuthorizationMode.READ_ONLY
        )

        if os.name == "posix":
            self.assertEqual(
                stat.S_IMODE(
                    self.paths.client_config.stat().st_mode
                ),
                0o600,
            )

    def test_expired_token_refreshes_and_is_persisted(self):
        self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )
        self.backend.loaded = FakeCredentials(
            scopes=(GMAIL_READONLY_SCOPE,),
            valid=False,
            expired=True,
            refresh_token="synthetic-refresh",
        )

        session = self.manager.authorize(
            GmailAuthorizationMode.READ_ONLY
        )

        self.assertEqual(
            self.backend.refresh_calls,
            1,
        )
        self.assertTrue(
            session.credentials.valid
        )
        self.assertIn(
            "synthetic-access-token",
            self.paths.read_token.read_text(
                encoding="utf-8"
            ),
        )

    def test_refresh_failure_is_redacted(self):
        self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )
        self.backend.loaded = FakeCredentials(
            scopes=(GMAIL_READONLY_SCOPE,),
            valid=False,
            expired=True,
            refresh_token="synthetic-refresh",
        )
        self.backend.refresh_should_fail = True

        with self.assertRaises(GmailAuthError) as context:
            self.manager.authorize(
                GmailAuthorizationMode.READ_ONLY
            )

        self.assertEqual(
            context.exception.code,
            GmailAuthErrorCode.TOKEN_REFRESH_FAILED,
        )
        self.assertNotIn(
            "RAW-SECRET",
            str(context.exception),
        )

    def test_invalid_unrefreshable_token_fails_closed(self):
        self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )
        self.backend.loaded = FakeCredentials(
            scopes=(GMAIL_READONLY_SCOPE,),
            valid=False,
            expired=False,
            refresh_token=None,
        )

        with self.assertRaises(GmailAuthError) as context:
            self.manager.authorize(
                GmailAuthorizationMode.READ_ONLY
            )

        self.assertEqual(
            context.exception.code,
            GmailAuthErrorCode.TOKEN_INVALID,
        )
        self.assertEqual(
            self.backend.authorization_calls,
            0,
        )

    def test_oauth_flow_failure_is_redacted(self):
        self._touch_client()
        self.backend.authorization_should_fail = True

        with self.assertRaises(GmailAuthError) as context:
            self.manager.authorize(
                GmailAuthorizationMode.READ_ONLY
            )

        self.assertEqual(
            context.exception.code,
            GmailAuthErrorCode.OAUTH_FLOW_FAILED,
        )
        self.assertNotIn(
            "RAW-SECRET",
            str(context.exception),
        )

    def test_reset_removes_only_requested_authorization(self):
        read = self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )
        write = self._touch_token(
            GmailAuthorizationMode.M1_WRITE
        )

        removed = self.manager.reset(
            GmailAuthorizationMode.READ_ONLY
        )

        self.assertTrue(removed)
        self.assertFalse(read.exists())
        self.assertTrue(write.exists())

    def test_account_safe_id_is_deterministic_and_pseudonymous(self):
        first = self.manager.account_safe_id(
            "Person.Example@example.test"
        )
        second = self.manager.account_safe_id(
            "person.example@EXAMPLE.TEST"
        )

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("gmail:"))
        self.assertNotIn(
            "person.example",
            first,
        )
        self.assertEqual(
            len(first),
            len("gmail:") + 24,
        )

    def test_account_safe_id_key_is_private(self):
        self.manager.account_safe_id(
            "person@example.test"
        )

        self.assertTrue(
            self.paths.account_id_key.is_file()
        )

        if os.name == "posix":
            self.assertEqual(
                stat.S_IMODE(
                    self.paths.account_id_key.stat().st_mode
                ),
                0o600,
            )

    def test_different_accounts_receive_different_safe_ids(self):
        first = self.manager.account_safe_id(
            "one@example.test"
        )
        second = self.manager.account_safe_id(
            "two@example.test"
        )

        self.assertNotEqual(first, second)

    def test_session_repr_omits_credential_material(self):
        self._touch_token(
            GmailAuthorizationMode.READ_ONLY
        )
        self.backend.loaded = FakeCredentials(
            scopes=(GMAIL_READONLY_SCOPE,),
            valid=True,
            token="DO-NOT-PRINT-THIS-TOKEN",
        )

        session = self.manager.authorize(
            GmailAuthorizationMode.READ_ONLY
        )

        rendered = repr(session)
        self.assertNotIn(
            "DO-NOT-PRINT-THIS-TOKEN",
            rendered,
        )
        self.assertNotIn(
            "credentials=",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
