from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any, Protocol


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


class GmailAuthorizationMode(str, Enum):
    READ_ONLY = "read_only"
    M1_WRITE = "m1_write"


def scopes_for_mode(
    mode: GmailAuthorizationMode,
) -> tuple[str, ...]:
    if mode is GmailAuthorizationMode.READ_ONLY:
        return (GMAIL_READONLY_SCOPE,)
    if mode is GmailAuthorizationMode.M1_WRITE:
        return (GMAIL_MODIFY_SCOPE,)
    raise ValueError(f"unsupported Gmail authorization mode: {mode!r}")


class GmailAuthErrorCode(str, Enum):
    MISSING_CLIENT_CONFIG = "missing_client_config"
    AUTHORIZATION_REQUIRED = "authorization_required"
    TOKEN_LOAD_FAILED = "token_load_failed"
    TOKEN_SCOPE_MISMATCH = "token_scope_mismatch"
    TOKEN_REFRESH_FAILED = "token_refresh_failed"
    TOKEN_INVALID = "token_invalid"
    OAUTH_FLOW_FAILED = "oauth_flow_failed"
    STORAGE_FAILURE = "storage_failure"
    ACCOUNT_ID_KEY_INVALID = "account_id_key_invalid"


class GmailAuthError(RuntimeError):
    """Privacy-safe authentication failure.

    Raw provider/library exceptions are deliberately not exposed.
    """

    def __init__(
        self,
        code: GmailAuthErrorCode,
        safe_detail: str,
    ) -> None:
        if not safe_detail.strip():
            raise ValueError("safe_detail cannot be empty")

        self.code = code
        self.safe_detail = safe_detail
        super().__init__(f"{code.value}: {safe_detail}")


@dataclass(frozen=True)
class GmailAuthPaths:
    client_config: Path
    read_token: Path
    write_token: Path
    account_id_key: Path

    def __post_init__(self) -> None:
        if self.read_token == self.write_token:
            raise ValueError(
                "read and write authorization tokens must use distinct paths"
            )

    @classmethod
    def default(cls) -> GmailAuthPaths:
        home = Path.home()

        config_base = Path(
            os.environ.get(
                "XDG_CONFIG_HOME",
                str(home / ".config"),
            )
        )
        state_base = Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(home / ".local" / "state"),
            )
        )

        config_root = config_base / "semantic-mail-archivist"
        auth_root = (
            state_base
            / "semantic-mail-archivist"
            / "auth"
            / "gmail"
        )

        return cls(
            client_config=(
                config_root / "gmail-oauth-client.json"
            ),
            read_token=(
                auth_root / "read-only-token.json"
            ),
            write_token=(
                auth_root / "m1-write-token.json"
            ),
            account_id_key=(
                auth_root / "account-id.key"
            ),
        )

    def token_for(
        self,
        mode: GmailAuthorizationMode,
    ) -> Path:
        if mode is GmailAuthorizationMode.READ_ONLY:
            return self.read_token
        if mode is GmailAuthorizationMode.M1_WRITE:
            return self.write_token
        raise ValueError(
            f"unsupported Gmail authorization mode: {mode!r}"
        )


@dataclass(frozen=True)
class GmailAuthSession:
    mode: GmailAuthorizationMode
    token_path: Path
    credentials: Any = field(repr=False)


class GmailOAuthBackend(Protocol):
    def load_token(self, token_path: Path) -> Any:
        ...

    def refresh(self, credentials: Any) -> None:
        ...

    def authorize_installed_app(
        self,
        client_config: Path,
        scopes: tuple[str, ...],
    ) -> Any:
        ...

    def serialize(self, credentials: Any) -> str:
        ...


class GoogleInstalledAppOAuthBackend:
    """Google OAuth implementation with lazy third-party imports."""

    def load_token(self, token_path: Path) -> Any:
        from google.oauth2.credentials import Credentials

        return Credentials.from_authorized_user_file(
            str(token_path)
        )

    def refresh(self, credentials: Any) -> None:
        from google.auth.transport.requests import Request

        credentials.refresh(Request())

    def authorize_installed_app(
        self,
        client_config: Path,
        scopes: tuple[str, ...],
    ) -> Any:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_config),
            list(scopes),
        )

        return flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )

    def serialize(self, credentials: Any) -> str:
        return credentials.to_json()


def _credential_scopes(
    credentials: Any,
) -> frozenset[str]:
    scopes = getattr(credentials, "scopes", None)
    if scopes is None:
        return frozenset()

    return frozenset(str(scope) for scope in scopes)


def _validate_scopes(
    credentials: Any,
    mode: GmailAuthorizationMode,
) -> None:
    required = frozenset(scopes_for_mode(mode))
    granted = _credential_scopes(credentials)

    if granted != required:
        raise GmailAuthError(
            GmailAuthErrorCode.TOKEN_SCOPE_MISMATCH,
            (
                "Stored authorization does not match the exact "
                f"{mode.value} scope policy; reset and re-authorize "
                "that mode."
            ),
        )


def _ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        os.chmod(path, 0o700)
    except OSError:
        raise GmailAuthError(
            GmailAuthErrorCode.STORAGE_FAILURE,
            "Unable to prepare private local authentication storage.",
        ) from None


def _atomic_private_write(
    path: Path,
    content: str,
) -> None:
    _ensure_private_directory(path.parent)

    temporary_path: str | None = None

    try:
        fd, temporary_path = tempfile.mkstemp(
            prefix=".auth-",
            dir=path.parent,
            text=True,
        )

        os.fchmod(fd, 0o600)

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, path)
        temporary_path = None
        os.chmod(path, 0o600)

    except OSError:
        if temporary_path is not None:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                pass

        raise GmailAuthError(
            GmailAuthErrorCode.STORAGE_FAILURE,
            "Unable to persist private local authentication state.",
        ) from None


class GmailAccountSafeId:
    """Derive a stable local pseudonymous account identifier.

    A local HMAC key prevents default logs from containing the raw Gmail
    address or a directly reusable unsalted hash of it.
    """

    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            try:
                raw = self.key_path.read_text(
                    encoding="ascii"
                ).strip()
                key = bytes.fromhex(raw)
            except (OSError, ValueError):
                raise GmailAuthError(
                    GmailAuthErrorCode.ACCOUNT_ID_KEY_INVALID,
                    "Local account-safe identifier key is unreadable.",
                ) from None

            if len(key) != 32:
                raise GmailAuthError(
                    GmailAuthErrorCode.ACCOUNT_ID_KEY_INVALID,
                    "Local account-safe identifier key is invalid.",
                )

            return key

        key = secrets.token_bytes(32)
        _atomic_private_write(
            self.key_path,
            key.hex() + "\n",
        )
        return key

    def for_identifier(self, identifier: str) -> str:
        normalized = identifier.strip().casefold()
        if not normalized:
            raise ValueError("account identifier cannot be empty")

        digest = hmac.new(
            self._load_or_create_key(),
            normalized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return f"gmail:{digest[:24]}"


def _protect_existing_client_config(path: Path) -> None:
    """Restrict the local OAuth client configuration before use.

    Desktop OAuth client configuration is local application state and must not
    be copied into logs or reports. On POSIX systems we additionally force the
    file to owner read/write only.
    """

    if os.name != "posix":
        return

    try:
        os.chmod(path, 0o600)
    except OSError:
        raise GmailAuthError(
            GmailAuthErrorCode.STORAGE_FAILURE,
            "Unable to protect local Gmail OAuth client configuration.",
        ) from None


class GmailAuthManager:
    def __init__(
        self,
        paths: GmailAuthPaths | None = None,
        *,
        backend: GmailOAuthBackend | None = None,
    ) -> None:
        self.paths = paths or GmailAuthPaths.default()
        self.backend = (
            backend
            if backend is not None
            else GoogleInstalledAppOAuthBackend()
        )

    def account_safe_id(
        self,
        account_identifier: str,
    ) -> str:
        return GmailAccountSafeId(
            self.paths.account_id_key
        ).for_identifier(account_identifier)

    def reset(
        self,
        mode: GmailAuthorizationMode,
    ) -> bool:
        token_path = self.paths.token_for(mode)

        try:
            if not token_path.exists():
                return False

            token_path.unlink()
            return True
        except OSError:
            raise GmailAuthError(
                GmailAuthErrorCode.STORAGE_FAILURE,
                "Unable to remove local authorization state.",
            ) from None

    def _session(
        self,
        mode: GmailAuthorizationMode,
        credentials: Any,
    ) -> GmailAuthSession:
        session = object.__new__(GmailAuthSession)
        object.__setattr__(session, "mode", mode)
        object.__setattr__(
            session,
            "token_path",
            self.paths.token_for(mode),
        )
        object.__setattr__(
            session,
            "credentials",
            credentials,
        )
        return session

    def _persist(
        self,
        mode: GmailAuthorizationMode,
        credentials: Any,
    ) -> None:
        try:
            serialized = self.backend.serialize(
                credentials
            )
        except Exception:
            raise GmailAuthError(
                GmailAuthErrorCode.STORAGE_FAILURE,
                "Unable to serialize local authorization state.",
            ) from None

        _atomic_private_write(
            self.paths.token_for(mode),
            serialized,
        )

    def authorize(
        self,
        mode: GmailAuthorizationMode,
        *,
        interactive: bool = True,
    ) -> GmailAuthSession:
        token_path = self.paths.token_for(mode)

        if token_path.exists():
            try:
                credentials = self.backend.load_token(
                    token_path
                )
            except Exception:
                raise GmailAuthError(
                    GmailAuthErrorCode.TOKEN_LOAD_FAILED,
                    (
                        "Stored authorization could not be loaded; "
                        "reset and re-authorize this mode."
                    ),
                ) from None

            _validate_scopes(credentials, mode)

            if bool(getattr(credentials, "valid", False)):
                return self._session(
                    mode,
                    credentials,
                )

            if (
                bool(getattr(credentials, "expired", False))
                and bool(
                    getattr(
                        credentials,
                        "refresh_token",
                        None,
                    )
                )
            ):
                try:
                    self.backend.refresh(credentials)
                except Exception:
                    raise GmailAuthError(
                        GmailAuthErrorCode.TOKEN_REFRESH_FAILED,
                        (
                            "Stored authorization could not be "
                            "refreshed; reset and re-authorize this "
                            "mode."
                        ),
                    ) from None

                _validate_scopes(credentials, mode)

                if not bool(
                    getattr(credentials, "valid", False)
                ):
                    raise GmailAuthError(
                        GmailAuthErrorCode.TOKEN_INVALID,
                        (
                            "Refreshed authorization is not valid; "
                            "reset and re-authorize this mode."
                        ),
                    )

                self._persist(
                    mode,
                    credentials,
                )

                return self._session(
                    mode,
                    credentials,
                )

            raise GmailAuthError(
                GmailAuthErrorCode.TOKEN_INVALID,
                (
                    "Stored authorization is no longer usable; "
                    "reset and re-authorize this mode."
                ),
            )

        if not interactive:
            raise GmailAuthError(
                GmailAuthErrorCode.AUTHORIZATION_REQUIRED,
                (
                    f"No local {mode.value} authorization exists; "
                    "interactive authorization is required."
                ),
            )

        if not self.paths.client_config.is_file():
            raise GmailAuthError(
                GmailAuthErrorCode.MISSING_CLIENT_CONFIG,
                (
                    "Local Gmail Desktop OAuth client configuration "
                    "was not found."
                ),
            )

        _protect_existing_client_config(
            self.paths.client_config
        )

        try:
            credentials = (
                self.backend.authorize_installed_app(
                    self.paths.client_config,
                    scopes_for_mode(mode),
                )
            )
        except Exception:
            raise GmailAuthError(
                GmailAuthErrorCode.OAUTH_FLOW_FAILED,
                (
                    "Interactive Gmail authorization did not "
                    "complete successfully."
                ),
            ) from None

        _validate_scopes(credentials, mode)

        if not bool(
            getattr(credentials, "valid", False)
        ):
            raise GmailAuthError(
                GmailAuthErrorCode.TOKEN_INVALID,
                "New Gmail authorization is not valid.",
            )

        self._persist(
            mode,
            credentials,
        )

        return self._session(
            mode,
            credentials,
        )
