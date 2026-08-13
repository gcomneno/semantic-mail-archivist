from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from semantic_mail_archivist.adapters.gmail import GmailLabelClassifier
from semantic_mail_archivist.change_log import (
    correlation_id_for_dry_run,
)
from semantic_mail_archivist.cli import (
    CliDependencies,
    CliExitCode,
    main,
)
from semantic_mail_archivist.gmail_provider import GmailReadAdapter
from semantic_mail_archivist.model import LabelClass
from semantic_mail_archivist.provider import (
    ProviderDescriptor,
    ProviderIdentity,
    ProviderLabelKind,
    ProviderLabelSnapshot,
    ProviderMessageSnapshot,
    ProviderPage,
    ProviderReadCapabilities,
    ProviderThreadRef,
)
from semantic_mail_archivist.reporting import (
    RepairRecommendation,
)
from tests.test_gmail_provider import (
    FakeGmailTransport,
    read_session,
)


class SyntheticUserLabelClassifier:
    def classify(self, label):
        if label.startswith("Operational/"):
            return LabelClass.USER_OPERATIONAL
        return LabelClass.USER_SEMANTIC


class FakeRepairProvider:
    def __init__(self):
        self.calls = []

        self._labels = (
            ProviderLabelSnapshot(
                label_id="INBOX",
                display_name="INBOX",
                kind=ProviderLabelKind.PROVIDER_SYSTEM,
            ),
            ProviderLabelSnapshot(
                label_id="Label_H",
                display_name="Personal/Housing",
                kind=ProviderLabelKind.USER,
            ),
            ProviderLabelSnapshot(
                label_id="Label_V",
                display_name="Work/Vendor",
                kind=ProviderLabelKind.USER,
            ),
            ProviderLabelSnapshot(
                label_id="Label_A",
                display_name="Work/Project-A",
                kind=ProviderLabelKind.USER,
            ),
            ProviderLabelSnapshot(
                label_id="Label_F",
                display_name="Work/Finance",
                kind=ProviderLabelKind.USER,
            ),
        )

        self._threads = (
            ProviderThreadRef("thread-high"),
            ProviderThreadRef("thread-medium"),
            ProviderThreadRef("thread-conflict"),
        )

        self._messages = {
            "thread-high": (
                ProviderMessageSnapshot(
                    message_id="high-1",
                    label_ids=("Label_H",),
                    subject="maintenance",
                    correspondents=("vendor@example.test",),
                ),
                ProviderMessageSnapshot(
                    message_id="high-2",
                    label_ids=("INBOX",),
                    subject="maintenance",
                    correspondents=("vendor@example.test",),
                ),
                ProviderMessageSnapshot(
                    message_id="high-3",
                    label_ids=("Label_H",),
                    subject="maintenance",
                    correspondents=("vendor@example.test",),
                ),
            ),
            "thread-medium": (
                ProviderMessageSnapshot(
                    message_id="medium-1",
                    label_ids=("Label_V",),
                ),
                ProviderMessageSnapshot(
                    message_id="medium-2",
                    label_ids=("INBOX",),
                ),
            ),
            "thread-conflict": (
                ProviderMessageSnapshot(
                    message_id="conflict-1",
                    label_ids=("Label_A",),
                ),
                ProviderMessageSnapshot(
                    message_id="conflict-2",
                    label_ids=("INBOX",),
                ),
                ProviderMessageSnapshot(
                    message_id="conflict-3",
                    label_ids=("Label_F",),
                ),
            ),
        }

    def descriptor(self):
        self.calls.append("descriptor")

        return ProviderDescriptor(
            identity=ProviderIdentity(
                provider="synthetic",
                account_safe_id="safe-repair-account",
            ),
            read_capabilities=ProviderReadCapabilities(),
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
                "unexpected thread continuation token"
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
            "repair dry-run must not request mutation-preflight state"
        )


class CliRepairDryRunTests(unittest.TestCase):
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

        self.provider = FakeRepairProvider()

        self.dependencies = CliDependencies(
            provider_factories={
                "synthetic": lambda mailbox: self.provider,
            },
            label_classifier_factories={
                "synthetic": (
                    lambda mailbox: SyntheticUserLabelClassifier()
                ),
            },
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(
        self,
        args,
        *,
        dependencies=None,
    ):
        stdout = StringIO()
        stderr = StringIO()

        code = main(
            args,
            dependencies=(
                self.dependencies
                if dependencies is None
                else dependencies
            ),
            stdout=stdout,
            stderr=stderr,
        )

        return (
            code,
            stdout.getvalue(),
            stderr.getvalue(),
        )

    def machine_run(self):
        return self.run_cli(
            [
                "--config",
                str(self.config),
                "--format",
                "json",
                "repair",
                "--dry-run",
                "--max-threads",
                "3",
            ]
        )

    def test_fake_provider_covers_eligible_review_and_refusal(self):
        code, stdout, stderr = self.machine_run()

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
            "dry_run",
        )
        self.assertIs(
            payload["complete"],
            True,
        )

        recommendations = {
            entry["message_id"]: entry["recommendation"]
            for entry in payload["entries"]
        }

        self.assertEqual(
            recommendations,
            {
                "conflict-2": (
                    RepairRecommendation.NO_ACTION.value
                ),
                "high-2": (
                    RepairRecommendation
                    .ELIGIBLE_FOR_ADDITIVE_REPAIR
                    .value
                ),
                "medium-2": (
                    RepairRecommendation.REVIEW_REQUIRED.value
                ),
            },
        )

    def test_cli_serialization_preserves_canonical_correlation_ids(self):
        code, stdout, stderr = self.machine_run()

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stderr,
            "",
        )

        payload = json.loads(stdout)

        entries_by_message = {
            entry["message_id"]: entry
            for entry in payload["entries"]
        }
        references_by_message = {
            reference["message_id"]: reference
            for reference in payload[
                "proposal_references"
            ]
        }

        self.assertEqual(
            set(entries_by_message),
            set(references_by_message),
        )

        # Rebuild the provider-neutral report once and compare the reference
        # against the exact canonical foundation hash function.
        from semantic_mail_archivist.ingestion import (
            ProviderAwareLabelClassifier,
            ingest_provider_mailbox,
        )
        from semantic_mail_archivist.reporting import (
            build_dry_run_report,
        )

        fresh_provider = FakeRepairProvider()

        ingestion = ingest_provider_mailbox(
            fresh_provider
        )
        classifier = ProviderAwareLabelClassifier(
            ingestion.labels,
            SyntheticUserLabelClassifier(),
        )

        candidates = {}

        for thread in ingestion.threads:
            for entry in build_dry_run_report(
                thread,
                classifier,
            ).entries:
                candidates[entry.message_id] = entry

        for message_id, reference in references_by_message.items():
            expected = correlation_id_for_dry_run(
                candidates[message_id]
            )

            self.assertEqual(
                reference["correlation_id"],
                expected,
            )
            self.assertTrue(
                expected.startswith(
                    "dryrun:1.0:"
                )
            )

    def test_machine_serialization_is_deterministic(self):
        first_code, first, first_error = self.machine_run()

        self.provider = FakeRepairProvider()

        second_code, second, second_error = self.machine_run()

        self.assertEqual(
            first_code,
            CliExitCode.OK,
        )
        self.assertEqual(
            second_code,
            CliExitCode.OK,
        )
        self.assertEqual(
            first_error,
            "",
        )
        self.assertEqual(
            second_error,
            "",
        )
        self.assertEqual(
            first,
            second,
        )

    def test_human_output_is_read_only_and_contains_safe_references(self):
        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "repair",
                "--max-threads",
                "3",
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
            "Semantic Mail Archivist — Dry-run repair report",
            stdout,
        )
        self.assertIn(
            "provider state will not be changed",
            stdout,
        )
        self.assertIn(
            "Proposal references",
            stdout,
        )
        self.assertIn(
            "dryrun:1.0:",
            stdout,
        )

        self.assertNotIn(
            "mailbox-body-secret",
            stdout,
        )
        self.assertNotIn(
            "attachment-content-secret",
            stdout,
        )

    def test_full_mailbox_dry_run_requires_explicit_destination(self):
        calls = []

        dependencies = CliDependencies(
            provider_factories={
                "synthetic": (
                    lambda mailbox: calls.append(mailbox)
                ),
            },
            label_classifier_factories={
                "synthetic": (
                    lambda mailbox: SyntheticUserLabelClassifier()
                ),
            },
        )

        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "repair",
            ],
            dependencies=dependencies,
        )

        self.assertEqual(
            code,
            CliExitCode.CONFIGURATION_ERROR,
        )
        self.assertEqual(
            stdout,
            "",
        )
        self.assertIn(
            "Full-mailbox repair dry-run requires an explicit",
            stderr,
        )
        self.assertEqual(
            calls,
            [],
        )

    def test_apply_remains_disabled_without_resolving_provider(self):
        calls = []

        dependencies = CliDependencies(
            provider_factories={
                "synthetic": (
                    lambda mailbox: calls.append(mailbox)
                ),
            },
            label_classifier_factories={
                "synthetic": (
                    lambda mailbox: SyntheticUserLabelClassifier()
                ),
            },
        )

        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "repair",
                "--apply",
            ],
            dependencies=dependencies,
        )

        self.assertEqual(
            code,
            CliExitCode.WRITE_DISABLED,
        )
        self.assertEqual(
            stderr,
            "",
        )
        self.assertIn(
            "write_disabled",
            stdout,
        )
        self.assertEqual(
            calls,
            [],
        )

    def test_dry_run_uses_only_provider_read_surface(self):
        code, _, stderr = self.machine_run()

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stderr,
            "",
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

    def test_real_gmail_adapter_feeds_existing_dry_run_engine(self):
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

        transport.thread_pages = {
            None: {
                "threads": [
                    {
                        "id": "repair-thread",
                    }
                ],
            }
        }

        common_headers = [
            {
                "name": "Subject",
                "value": "Project Alpha",
            },
            {
                "name": "From",
                "value": "Alice <alice@example.test>",
            },
            {
                "name": "To",
                "value": "Bob <bob@example.test>",
            },
        ]

        transport.threads = {
            "repair-thread": {
                "id": "repair-thread",
                "messages": [
                    {
                        "id": "repair-1",
                        "threadId": "repair-thread",
                        "labelIds": ["Label_1"],
                        "payload": {
                            "headers": common_headers,
                        },
                    },
                    {
                        "id": "repair-2",
                        "threadId": "repair-thread",
                        "labelIds": ["INBOX"],
                        "payload": {
                            "headers": common_headers,
                        },
                    },
                    {
                        "id": "repair-3",
                        "threadId": "repair-thread",
                        "labelIds": ["Label_1"],
                        "payload": {
                            "headers": common_headers,
                        },
                    },
                ],
            }
        }

        transport.structures = {
            message_id: {
                "id": message_id,
                "threadId": "repair-thread",
                "payload": {
                    "partId": "",
                    "mimeType": "text/plain",
                    "body": {
                        "size": 20,
                    },
                },
            }
            for message_id in (
                "repair-1",
                "repair-2",
                "repair-3",
            )
        }

        adapter = GmailReadAdapter(
            read_session(),
            account_safe_id="gmail:repair-safe-id",
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
                "repair",
                "--dry-run",
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
            len(payload["entries"]),
            1,
        )
        self.assertEqual(
            payload["entries"][0]["message_id"],
            "repair-2",
        )
        self.assertEqual(
            payload["entries"][0]["proposed_label"],
            "Projects/Alpha",
        )
        self.assertEqual(
            len(payload["proposal_references"]),
            1,
        )
        self.assertTrue(
            payload["proposal_references"][0][
                "correlation_id"
            ].startswith(
                "dryrun:1.0:"
            )
        )


if __name__ == "__main__":
    unittest.main()
