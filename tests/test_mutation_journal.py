from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

from semantic_mail_archivist.change_log import (
    MutationAction,
    MutationExecutionMode,
    MutationInitiator,
    MutationResultStatus,
)
from semantic_mail_archivist.mutation_journal import (
    MUTATION_JOURNAL_SCHEMA_VERSION,
    MutationAttemptFinalization,
    MutationAttemptIntent,
    MutationJournal,
    MutationJournalCorruptionError,
    MutationRecoveryObservation,
    reconcile_interrupted_attempt,
)
from semantic_mail_archivist.provider import (
    ProviderMessageState,
)
from semantic_mail_archivist.reporting import (
    MutationClass,
)


NOW = datetime(
    2026,
    8,
    14,
    12,
    0,
    tzinfo=timezone.utc,
)


def before_state():
    return ProviderMessageState(
        message_id="message-1",
        label_ids=("INBOX",),
        in_inbox=True,
        in_trash=False,
        provider_revision="revision-before",
    )


def requested_state():
    return ProviderMessageState(
        message_id="message-1",
        label_ids=("INBOX", "Label_Project"),
        in_inbox=True,
        in_trash=False,
        provider_revision="revision-requested",
    )


def intent(
    *,
    attempt_id="attempt-001",
):
    return MutationAttemptIntent(
        attempt_id=attempt_id,
        timestamp=NOW,
        provider="synthetic-provider",
        account_safe_id="account-safe-1",
        message_id="message-1",
        action=MutationAction.ADD_LABEL,
        mutation_class=MutationClass.M1,
        target_label="Projects/Alpha",
        provider_before_state=before_state(),
        provider_requested_state=requested_state(),
        initiator=MutationInitiator.USER,
        execution_mode=(
            MutationExecutionMode.EXPLICIT_WRITE
        ),
        dry_run_correlation_id=(
            "dryrun:1.0:synthetic-safe-correlation"
        ),
    )


def finalization(
    result=MutationResultStatus.SUCCEEDED,
):
    return MutationAttemptFinalization(
        attempt_id="attempt-001",
        timestamp=NOW,
        result=result,
        audit_record_id="attempt-001",
    )


class MutationJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = (
            self.root
            / "private"
            / "mutation-journal.jsonl"
        )
        self.journal = MutationJournal(
            self.path
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_crash_before_provider_call_is_discoverable(self):
        self.journal.append_intent(
            intent()
        )

        loaded = MutationJournal(
            self.path
        ).load()

        self.assertFalse(
            loaded.trailing_corruption
        )
        self.assertEqual(
            len(loaded.interrupted_attempts),
            1,
        )

        attempt = loaded.interrupted_attempts[0]

        self.assertTrue(
            attempt.interrupted
        )
        self.assertEqual(
            reconcile_interrupted_attempt(
                attempt,
                before_state(),
            ),
            (
                MutationRecoveryObservation
                .PREVIOUS_STATE_OBSERVED
            ),
        )

    def test_crash_after_call_before_finalization_is_not_success(self):
        self.journal.append_intent(
            intent()
        )

        attempt = (
            self.journal
            .load()
            .interrupted_attempts[0]
        )

        fresh_after_call = ProviderMessageState(
            message_id="message-1",
            label_ids=("INBOX", "Label_Project"),
            in_inbox=True,
            in_trash=False,
            provider_revision="revision-provider-generated-after-call",
        )

        observation = reconcile_interrupted_attempt(
            attempt,
            fresh_after_call,
        )

        self.assertEqual(
            observation,
            (
                MutationRecoveryObservation
                .REQUESTED_STATE_OBSERVED
            ),
        )
        self.assertTrue(
            attempt.interrupted
        )
        self.assertIsNone(
            attempt.finalization
        )

    def test_provider_failure_finalizes_same_attempt_identity(self):
        self.journal.append_intent(
            intent()
        )
        self.journal.append_finalization(
            finalization(
                MutationResultStatus.FAILED
            )
        )

        loaded = self.journal.load()

        self.assertEqual(
            loaded.interrupted_attempts,
            (),
        )

        attempt = loaded.attempts[0]

        self.assertEqual(
            attempt.intent.attempt_id,
            "attempt-001",
        )
        self.assertEqual(
            attempt.finalization.result,
            MutationResultStatus.FAILED,
        )
        self.assertEqual(
            attempt.finalization.audit_record_id,
            attempt.intent.attempt_id,
        )

    def test_success_finalization_uses_same_change_log_record_id(self):
        self.journal.append_intent(
            intent()
        )
        self.journal.append_finalization(
            finalization()
        )

        attempt = self.journal.load().attempts[0]

        self.assertEqual(
            attempt.finalization.result,
            MutationResultStatus.SUCCEEDED,
        )
        self.assertEqual(
            attempt.finalization.audit_record_id,
            "attempt-001",
        )

    def test_denied_and_partial_failure_are_terminal_results(self):
        for result in (
            MutationResultStatus.DENIED,
            MutationResultStatus.PARTIAL_FAILURE,
        ):
            with self.subTest(result=result):
                path = (
                    self.root
                    / result.value
                    / "journal.jsonl"
                )
                journal = MutationJournal(path)

                journal.append_intent(
                    intent()
                )
                journal.append_finalization(
                    MutationAttemptFinalization(
                        attempt_id="attempt-001",
                        timestamp=NOW,
                        result=result,
                        audit_record_id="attempt-001",
                    )
                )

                loaded = journal.load()

                self.assertFalse(
                    loaded.attempts[0].interrupted
                )
                self.assertEqual(
                    loaded.attempts[0]
                    .finalization
                    .result,
                    result,
                )

    def test_divergent_fresh_state_is_observation_not_guess(self):
        self.journal.append_intent(
            intent()
        )

        divergent = ProviderMessageState(
            message_id="message-1",
            label_ids=("STARRED",),
            in_inbox=False,
            in_trash=False,
            provider_revision="revision-other",
        )

        observation = reconcile_interrupted_attempt(
            self.journal.load().attempts[0],
            divergent,
        )

        self.assertEqual(
            observation,
            (
                MutationRecoveryObservation
                .DIVERGENT_STATE_OBSERVED
            ),
        )

    def test_reconciliation_is_idempotent_and_read_only(self):
        self.journal.append_intent(
            intent()
        )

        attempt = self.journal.load().attempts[0]
        fresh = requested_state()

        first = reconcile_interrupted_attempt(
            attempt,
            fresh,
        )
        second = reconcile_interrupted_attempt(
            attempt,
            fresh,
        )

        self.assertEqual(
            first,
            second,
        )
        self.assertEqual(
            len(self.journal.load().attempts),
            1,
        )

    def test_partial_trailing_finalization_is_not_success(self):
        self.journal.append_intent(
            intent()
        )

        with self.path.open(
            "ab"
        ) as handle:
            handle.write(
                b'{"event":"finalization","attempt_id":'
            )
            handle.flush()
            os.fsync(handle.fileno())

        loaded = MutationJournal(
            self.path
        ).load()

        self.assertTrue(
            loaded.trailing_corruption
        )
        self.assertEqual(
            len(loaded.interrupted_attempts),
            1,
        )
        self.assertIsNone(
            loaded.attempts[0].finalization
        )

        with self.assertRaises(
            MutationJournalCorruptionError
        ):
            self.journal.append_finalization(
                finalization()
            )

    def test_complete_json_without_final_newline_is_not_trusted(self):
        self.journal.append_intent(
            intent()
        )

        payload = json.dumps(
            finalization().to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        with self.path.open(
            "ab"
        ) as handle:
            handle.write(
                payload.encode("utf-8")
            )
            handle.flush()
            os.fsync(handle.fileno())

        loaded = self.journal.load()

        self.assertTrue(
            loaded.trailing_corruption
        )
        self.assertEqual(
            len(loaded.interrupted_attempts),
            1,
        )
        self.assertIsNone(
            loaded.attempts[0].finalization
        )

    def test_corruption_before_final_line_fails_closed(self):
        self.journal.append_intent(
            intent()
        )

        content = self.path.read_text(
            encoding="utf-8"
        )

        self.path.write_text(
            content
            + "{not-json}\n"
            + json.dumps(
                finalization().to_dict()
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(
            MutationJournalCorruptionError
        ):
            self.journal.load()

    def test_duplicate_intent_and_finalization_are_rejected(self):
        self.journal.append_intent(
            intent()
        )

        with self.assertRaises(ValueError):
            self.journal.append_intent(
                intent()
            )

        self.journal.append_finalization(
            finalization()
        )

        with self.assertRaises(ValueError):
            self.journal.append_finalization(
                finalization()
            )

    def test_finalization_without_intent_is_rejected(self):
        with self.assertRaises(ValueError):
            self.journal.append_finalization(
                finalization()
            )

    def test_attempt_identity_must_equal_future_audit_record_id(self):
        with self.assertRaisesRegex(
            ValueError,
            "audit_record_id must equal attempt_id",
        ):
            MutationAttemptFinalization(
                attempt_id="attempt-001",
                timestamp=NOW,
                result=MutationResultStatus.SUCCEEDED,
                audit_record_id="another-record",
            )

    def test_action_uses_canonical_change_log_mutation_class(self):
        with self.assertRaisesRegex(
            ValueError,
            "mutation_class does not match action",
        ):
            MutationAttemptIntent(
                attempt_id="attempt-001",
                timestamp=NOW,
                provider="synthetic-provider",
                account_safe_id="safe-account",
                message_id="message-1",
                action=MutationAction.ADD_LABEL,
                mutation_class=MutationClass.M2,
                target_label="Projects/Alpha",
                provider_before_state=before_state(),
                provider_requested_state=requested_state(),
                initiator=MutationInitiator.USER,
                execution_mode=(
                    MutationExecutionMode
                    .EXPLICIT_WRITE
                ),
            )

    def test_serialized_journal_is_privacy_safe_and_deterministic(self):
        self.journal.append_intent(
            intent()
        )

        first = self.path.read_text(
            encoding="utf-8"
        )

        payload = json.loads(
            first.strip()
        )

        self.assertEqual(
            payload["schema_version"],
            MUTATION_JOURNAL_SCHEMA_VERSION,
        )
        self.assertEqual(
            payload["dry_run_correlation_id"],
            "dryrun:1.0:synthetic-safe-correlation",
        )

        forbidden = (
            "body",
            "attachment_content",
            "access_token",
            "refresh_token",
            "credential",
        )

        serialized = json.dumps(
            payload
        ).casefold()

        for value in forbidden:
            self.assertNotIn(
                value,
                serialized,
            )

        second_path = (
            self.root
            / "second"
            / "journal.jsonl"
        )
        MutationJournal(
            second_path
        ).append_intent(
            intent()
        )

        self.assertEqual(
            first,
            second_path.read_text(
                encoding="utf-8"
            ),
        )

    @unittest.skipUnless(
        os.name == "posix",
        "POSIX permission contract",
    )
    def test_journal_file_and_directory_are_private(self):
        self.journal.append_intent(
            intent()
        )

        self.assertEqual(
            self.path.stat().st_mode & 0o777,
            0o600,
        )
        self.assertEqual(
            self.path.parent.stat().st_mode & 0o777,
            0o700,
        )


if __name__ == "__main__":
    unittest.main()
