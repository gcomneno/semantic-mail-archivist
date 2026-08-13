from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from semantic_mail_archivist.audit import ProviderLimitation
from semantic_mail_archivist.cli import (
    CliDependencies,
    CliExitCode,
    gmail_read_provider_factory,
    main,
)
from semantic_mail_archivist.cli_config import CliMailboxConfig
from semantic_mail_archivist.adapters.gmail import GmailLabelClassifier
from semantic_mail_archivist.gmail_auth import GmailAuthorizationMode
from semantic_mail_archivist.gmail_provider import GmailReadAdapter
from tests.test_gmail_provider import (
    FakeGmailTransport,
    read_session,
)
from semantic_mail_archivist.model import LabelClass
from semantic_mail_archivist.provider import (
    ProviderDescriptor,
    ProviderIdentity,
    ProviderLabelKind,
    ProviderLabelSnapshot,
    ProviderMessageSnapshot,
    ProviderMessageState,
    ProviderPage,
    ProviderReadCapabilities,
    ProviderThreadRef,
)


class SyntheticUserLabelClassifier:
    def classify(self, label):
        if label == "Work":
            return LabelClass.USER_SEMANTIC
        return LabelClass.UNKNOWN


class FakeAuditProvider:
    def __init__(self):
        self.calls = []

        self._labels = (
            ProviderLabelSnapshot(
                label_id="INBOX",
                display_name="INBOX",
                kind=ProviderLabelKind.PROVIDER_SYSTEM,
            ),
            ProviderLabelSnapshot(
                label_id="Label_1",
                display_name="Work",
                kind=ProviderLabelKind.USER,
            ),
        )

        self._threads = (
            ProviderThreadRef("thread-1"),
            ProviderThreadRef("thread-2"),
        )

        self._messages = {
            "thread-1": (
                ProviderMessageSnapshot(
                    message_id="message-1",
                    label_ids=(
                        "INBOX",
                        "Label_1",
                    ),
                ),
                ProviderMessageSnapshot(
                    message_id="message-2",
                    label_ids=("INBOX",),
                ),
            ),
            "thread-2": (
                ProviderMessageSnapshot(
                    message_id="message-3",
                    label_ids=(
                        "INBOX",
                        "Label_1",
                    ),
                ),
            ),
        }

    def descriptor(self):
        self.calls.append("descriptor")

        return ProviderDescriptor(
            identity=ProviderIdentity(
                provider="synthetic",
                account_safe_id="safe-account",
            ),
            read_capabilities=ProviderReadCapabilities(),
            limitations=(
                ProviderLimitation(
                    code="synthetic_provider_notice",
                    detail=(
                        "Synthetic provider limitation is visible."
                    ),
                ),
            ),
        )

    def list_labels(self):
        self.calls.append("list_labels")
        return self._labels

    def list_threads(
        self,
        *,
        page_token=None,
        page_size=None,
    ):
        self.calls.append(
            (
                "list_threads",
                page_token,
                page_size,
            )
        )

        if page_token is not None:
            raise AssertionError(
                "unexpected continuation token"
            )

        return ProviderPage(
            items=self._threads,
        )

    def list_messages(
        self,
        thread_id,
        *,
        page_token=None,
        page_size=None,
    ):
        self.calls.append(
            (
                "list_messages",
                thread_id,
                page_token,
                page_size,
            )
        )

        if page_token is not None:
            raise AssertionError(
                "unexpected message continuation token"
            )

        return ProviderPage(
            items=self._messages[thread_id],
        )

    def list_attachments(self, message_id):
        self.calls.append(
            (
                "list_attachments",
                message_id,
            )
        )
        return ()

    def get_message_state(self, message_id):
        raise AssertionError(
            "audit must not request fresh mutation-preflight state"
        )


class FakeAuthSession:
    mode = GmailAuthorizationMode.READ_ONLY


class FakeAuthManager:
    def __init__(self):
        self.modes = []

    def authorize(self, mode, *, interactive=True):
        self.modes.append(mode)
        return FakeAuthSession()


class CliAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        self.config = self.root / "config.toml"
        self.config.write_text(
            """
[mailbox]
provider = "synthetic"
account = "fixture-account"
""",
            encoding="utf-8",
        )

        self.provider = FakeAuditProvider()

        self.dependencies = CliDependencies(
            provider_factories={
                "synthetic": (
                    lambda mailbox: self.provider
                ),
            },
            label_classifier_factories={
                "synthetic": (
                    lambda mailbox: (
                        SyntheticUserLabelClassifier()
                    )
                ),
            },
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, args):
        stdout = StringIO()
        stderr = StringIO()

        code = main(
            args,
            dependencies=self.dependencies,
            stdout=stdout,
            stderr=stderr,
        )

        return (
            code,
            stdout.getvalue(),
            stderr.getvalue(),
        )

    def test_fake_provider_drives_end_to_end_human_audit(self):
        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "audit",
                "--max-threads",
                "1",
            ]
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stderr,
            "",
        )

        self.assertIn(
            "Semantic Mail Archivist — Mailbox audit report",
            stdout,
        )
        self.assertIn(
            "Mode: READ ONLY",
            stdout,
        )
        self.assertIn(
            "Messages analysed: 2",
            stdout,
        )
        self.assertIn(
            "Synthetic provider limitation is visible.",
            stdout,
        )
        self.assertIn(
            (
                "Mailbox ingestion was intentionally bounded "
                "before the provider thread enumeration was complete."
            ),
            stdout,
        )

    def test_machine_output_is_existing_audit_schema(self):
        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "--format",
                "json",
                "audit",
                "--max-threads",
                "1",
            ]
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stderr,
            "",
        )

        payload = json.loads(stdout)

        self.assertEqual(
            payload["mode"],
            "read_only_audit",
        )
        self.assertIs(
            payload["read_only"],
            True,
        )
        self.assertIn(
            "schema_version",
            payload,
        )
        self.assertIn(
            "summary",
            payload,
        )
        self.assertIn(
            "taxonomy",
            payload,
        )
        self.assertIn(
            "records",
            payload,
        )
        self.assertIn(
            "warnings",
            payload,
        )
        self.assertIn(
            "provider_limitations",
            payload,
        )
        self.assertNotIn(
            "command",
            payload,
        )

        limitation_codes = {
            item["code"]
            for item in payload[
                "provider_limitations"
            ]
        }

        self.assertIn(
            "bounded_mailbox_selection",
            limitation_codes,
        )
        self.assertIn(
            "synthetic_provider_notice",
            limitation_codes,
        )

    def test_full_mailbox_requires_explicit_destination(self):
        calls = []

        dependencies = CliDependencies(
            provider_factories={
                "synthetic": (
                    lambda mailbox: calls.append(mailbox)
                ),
            },
            label_classifier_factories={
                "synthetic": (
                    lambda mailbox: (
                        SyntheticUserLabelClassifier()
                    )
                ),
            },
        )

        stdout = StringIO()
        stderr = StringIO()

        code = main(
            [
                "--config",
                str(self.config),
                "audit",
            ],
            dependencies=dependencies,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(
            code,
            CliExitCode.CONFIGURATION_ERROR,
        )
        self.assertEqual(
            stdout.getvalue(),
            "",
        )
        self.assertIn(
            "Full-mailbox audit requires an explicit local output destination",
            stderr.getvalue(),
        )
        self.assertEqual(
            calls,
            [],
        )

    def test_full_mailbox_json_also_requires_explicit_destination(self):
        calls = []

        dependencies = CliDependencies(
            provider_factories={
                "synthetic": (
                    lambda mailbox: calls.append(mailbox)
                ),
            },
            label_classifier_factories={
                "synthetic": (
                    lambda mailbox: (
                        SyntheticUserLabelClassifier()
                    )
                ),
            },
        )

        stdout = StringIO()
        stderr = StringIO()

        code = main(
            [
                "--config",
                str(self.config),
                "--format",
                "json",
                "audit",
            ],
            dependencies=dependencies,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(
            code,
            CliExitCode.CONFIGURATION_ERROR,
        )
        self.assertEqual(
            stdout.getvalue(),
            "",
        )
        self.assertIn(
            "Full-mailbox audit requires an explicit local output destination",
            stderr.getvalue(),
        )
        self.assertEqual(
            calls,
            [],
        )

    def test_full_mailbox_json_can_write_private_local_file(self):
        destination = (
            self.root
            / "reports"
            / "audit.json"
        )

        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "--format",
                "json",
                "--output",
                str(destination),
                "audit",
            ]
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stdout,
            "",
        )
        self.assertEqual(
            stderr,
            "",
        )

        payload = json.loads(
            destination.read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            payload["summary"][
                "messages_analyzed"
            ],
            3,
        )

        if os.name == "posix":
            mode = stat.S_IMODE(
                destination.stat().st_mode
            )
            self.assertEqual(
                mode,
                0o600,
            )

    def test_bounded_audit_passes_thread_page_size(self):
        code, _, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "audit",
                "--max-threads",
                "1",
                "--thread-page-size",
                "17",
            ]
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )

        self.assertIn(
            (
                "list_threads",
                None,
                17,
            ),
            self.provider.calls,
        )

    def test_nonpositive_bound_is_usage_error_before_provider(self):
        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "audit",
                "--max-threads",
                "0",
            ]
        )

        self.assertEqual(
            code,
            CliExitCode.USAGE,
        )
        self.assertEqual(
            stdout,
            "",
        )
        self.assertIn(
            "must be a positive integer",
            stderr,
        )
        self.assertEqual(
            self.provider.calls,
            [],
        )

    def test_audit_uses_only_read_provider_surface(self):
        code, _, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "audit",
                "--max-threads",
                "1",
            ]
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )

        call_names = {
            call
            if isinstance(call, str)
            else call[0]
            for call in self.provider.calls
        }

        self.assertEqual(
            call_names,
            {
                "descriptor",
                "list_labels",
                "list_threads",
                "list_messages",
                "list_attachments",
            },
        )

    def test_real_gmail_adapter_drives_cli_audit_without_network(self):
        gmail_config = self.root / "gmail-config.toml"
        gmail_config.write_text(
            """
[mailbox]
provider = "gmail"
account = "personal"
""",
            encoding="utf-8",
        )

        transport = FakeGmailTransport()

        adapter = GmailReadAdapter(
            read_session(),
            account_safe_id="gmail:test-safe-id",
            transport=transport,
        )

        dependencies = CliDependencies(
            provider_factories={
                "gmail": lambda mailbox: adapter,
            },
            label_classifier_factories={
                "gmail": lambda mailbox: GmailLabelClassifier(),
            },
        )

        stdout = StringIO()
        stderr = StringIO()

        code = main(
            [
                "--config",
                str(gmail_config),
                "--format",
                "json",
                "audit",
                "--max-threads",
                "1",
            ],
            dependencies=dependencies,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stderr.getvalue(),
            "",
        )

        payload = json.loads(
            stdout.getvalue()
        )

        self.assertEqual(
            payload["mode"],
            "read_only_audit",
        )
        self.assertIs(
            payload["read_only"],
            True,
        )
        self.assertEqual(
            payload["summary"][
                "messages_analyzed"
            ],
            1,
        )

        taxonomy = {
            item["label"]
            for item in payload["taxonomy"]
        }

        self.assertIn(
            "Projects/Alpha",
            taxonomy,
        )

        limitation_codes = {
            item["code"]
            for item in payload[
                "provider_limitations"
            ]
        }

        self.assertIn(
            "bounded_mailbox_selection",
            limitation_codes,
        )

        # The Gmail test transport would expose fresh-state reads, but audit
        # never needs them. Only the read-only ingestion surface is consumed.
        self.assertEqual(
            transport.states["m-1"]["historyId"],
            "102",
        )

    def test_gmail_factory_requests_read_only_authorization(self):
        managers = []
        built = []

        def manager_factory():
            manager = FakeAuthManager()
            managers.append(manager)
            return manager

        provider = object()

        def adapter_factory(manager, session):
            built.append(
                (
                    manager,
                    session.mode,
                )
            )
            return provider

        result = gmail_read_provider_factory(
            CliMailboxConfig(
                provider="gmail",
                account="personal",
            ),
            auth_manager_factory=manager_factory,
            adapter_factory=adapter_factory,
        )

        self.assertIs(
            result,
            provider,
        )
        self.assertEqual(
            managers[0].modes,
            [
                GmailAuthorizationMode.READ_ONLY,
            ],
        )
        self.assertEqual(
            built[0][1],
            GmailAuthorizationMode.READ_ONLY,
        )


if __name__ == "__main__":
    unittest.main()
