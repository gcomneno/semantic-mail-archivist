import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from semantic_mail_archivist import (
    ChangeAuditRecord,
    ChangeEvidence,
    ConfidenceBand,
    DryRunCandidateReport,
    DryRunProposalReference,
    ExecutionStatus,
    InferenceEvidence,
    MailboxStateSnapshot,
    MutationAction,
    MutationAuthorization,
    MutationClass,
    MutationExecutionMode,
    MutationInitiator,
    MutationResultStatus,
    PlannedAction,
    ProviderResultMetadata,
    RepairRecommendation,
    RollbackMetadata,
    SafetyGateDecision,
    SafetyGateRecord,
    SafetyGateResult,
    append_change_record_jsonl,
    correlation_id_for_dry_run,
    render_change_log_jsonl,
    render_change_record_json,
    render_change_record_text,
)


def dry_run_candidate(
    *,
    proposed_label="Projects/Alpha",
    score=0.95,
):
    return DryRunCandidateReport(
        thread_id="t-1",
        message_id="m-1",
        current_user_labels=(),
        proposed_label=proposed_label,
        confidence_score=score,
        confidence_band=ConfidenceBand.HIGH,
        evidence=(
            InferenceEvidence(
                signal="thread_consensus",
                detail="Stable synthetic semantic context.",
                contribution=0.95,
            ),
        ),
        conflicts=(),
        recommendation=RepairRecommendation.ELIGIBLE_FOR_ADDITIVE_REPAIR,
        planned_action=PlannedAction.ADD_LABEL,
        mutation_class=MutationClass.M1,
        mutation_authorization=MutationAuthorization.DENIED,
        safety_gate_result=SafetyGateResult.NOT_EVALUATED_FOR_WRITE,
        authorization_reasons=(),
        execution_status=ExecutionStatus.NOT_EXECUTED,
    )


def base_record(**overrides):
    previous = MailboxStateSnapshot(
        user_labels=(),
        in_inbox=True,
        in_trash=False,
    )
    requested = MailboxStateSnapshot(
        user_labels=("Projects/Alpha",),
        in_inbox=True,
        in_trash=False,
    )

    values = {
        "record_id": "record-001",
        "timestamp": datetime(
            2026,
            8,
            12,
            17,
            0,
            tzinfo=timezone.utc,
        ),
        "provider": "synthetic-provider",
        "account_safe_id": "acct-safe-001",
        "message_id": "m-1",
        "action": MutationAction.ADD_LABEL,
        "mutation_class": MutationClass.M1,
        "target_label": "Projects/Alpha",
        "previous_state": previous,
        "requested_new_state": requested,
        "resulting_state": requested,
        "evidence": (
            ChangeEvidence(
                signal="dry_run_proposal",
                detail="Synthetic HIGH-confidence additive repair.",
                contribution=0.95,
            ),
        ),
        "confidence_score": 0.95,
        "confidence_band": ConfidenceBand.HIGH,
        "safety_gates": (
            SafetyGateRecord(
                gate="explicit_write_mode",
                decision=SafetyGateDecision.PASSED,
                detail="Synthetic explicit write-mode gate passed.",
            ),
        ),
        "initiator": MutationInitiator.USER,
        "execution_mode": MutationExecutionMode.EXPLICIT_WRITE,
        "result": MutationResultStatus.SUCCEEDED,
        "provider_result": ProviderResultMetadata(
            provider_status="ok",
            request_safe_id="req-safe-001",
        ),
        "dry_run_reference": DryRunProposalReference.from_candidate(
            dry_run_candidate()
        ),
        "rollback": RollbackMetadata(
            reversible=True,
            rollback_action=MutationAction.REMOVE_LABEL,
            restore_state=previous,
        ),
    }
    values.update(overrides)
    return ChangeAuditRecord(**values)


class ChangeLogTests(unittest.TestCase):
    def test_record_requires_reasoning_evidence(self):
        with self.assertRaisesRegex(
            ValueError,
            "require reasoning evidence",
        ):
            base_record(evidence=())

    def test_record_requires_safety_gate_record(self):
        with self.assertRaisesRegex(
            ValueError,
            "require at least one safety gate",
        ):
            base_record(safety_gates=())

    def test_add_label_requested_state_must_add_only_target_label(self):
        requested = MailboxStateSnapshot(
            user_labels=("Projects/Alpha", "Unexpected"),
            in_inbox=True,
            in_trash=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "ADD_LABEL requested state",
        ):
            base_record(
                requested_new_state=requested,
                resulting_state=requested,
            )

    def test_archive_requested_state_cannot_change_user_labels(self):
        previous = MailboxStateSnapshot(
            user_labels=("Projects/Alpha",),
            in_inbox=True,
            in_trash=False,
        )
        requested = MailboxStateSnapshot(
            user_labels=("Projects/Beta",),
            in_inbox=False,
            in_trash=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "cannot change user labels",
        ):
            base_record(
                action=MutationAction.ARCHIVE,
                mutation_class=MutationClass.M3,
                target_label=None,
                previous_state=previous,
                requested_new_state=requested,
                resulting_state=requested,
                dry_run_reference=None,
                rollback=RollbackMetadata(
                    reversible=True,
                    rollback_action=MutationAction.RESTORE_TO_INBOX,
                    restore_state=previous,
                ),
            )

    def test_m4_requires_dedicated_cleanup_write_mode(self):
        previous = MailboxStateSnapshot(
            in_inbox=True,
            in_trash=False,
        )
        requested = MailboxStateSnapshot(
            in_inbox=False,
            in_trash=True,
        )

        with self.assertRaisesRegex(
            ValueError,
            "requires dedicated cleanup write mode",
        ):
            base_record(
                action=MutationAction.MOVE_TO_TRASH,
                mutation_class=MutationClass.M4,
                target_label=None,
                previous_state=previous,
                requested_new_state=requested,
                resulting_state=requested,
                execution_mode=MutationExecutionMode.EXPLICIT_WRITE,
                dry_run_reference=None,
                rollback=RollbackMetadata(
                    reversible=True,
                    rollback_action=MutationAction.RESTORE_FROM_TRASH,
                    restore_state=previous,
                ),
            )

    def test_current_dry_run_reference_cannot_be_attached_to_m2(self):
        previous = MailboxStateSnapshot(
            user_labels=("Projects/Alpha",),
            in_inbox=True,
            in_trash=False,
        )
        requested = MailboxStateSnapshot(
            user_labels=(),
            in_inbox=True,
            in_trash=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "supports only ADD_LABEL",
        ):
            base_record(
                action=MutationAction.REMOVE_LABEL,
                mutation_class=MutationClass.M2,
                target_label="Projects/Alpha",
                previous_state=previous,
                requested_new_state=requested,
                resulting_state=requested,
                rollback=RollbackMetadata(
                    reversible=True,
                    rollback_action=MutationAction.ADD_LABEL,
                    restore_state=previous,
                ),
            )

    def test_rollback_action_must_match_forward_action(self):
        previous = MailboxStateSnapshot(
            user_labels=(),
            in_inbox=True,
            in_trash=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "rollback_action must be remove_label",
        ):
            base_record(
                rollback=RollbackMetadata(
                    reversible=True,
                    rollback_action=MutationAction.RESTORE_TO_INBOX,
                    restore_state=previous,
                ),
            )

    def test_mutation_class_exposes_complete_canonical_taxonomy(self):
        self.assertEqual(
            [item.value for item in MutationClass],
            ["M0", "M1", "M2", "M3", "M4", "M5"],
        )

    def test_dry_run_correlation_is_deterministic(self):
        candidate = dry_run_candidate()

        first = correlation_id_for_dry_run(candidate)
        second = correlation_id_for_dry_run(candidate)

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("dryrun:1.0:"))

    def test_materially_changed_dry_run_gets_different_correlation(self):
        first = correlation_id_for_dry_run(
            dry_run_candidate(proposed_label="Projects/Alpha")
        )
        second = correlation_id_for_dry_run(
            dry_run_candidate(proposed_label="Projects/Beta")
        )

        self.assertNotEqual(first, second)

    def test_successful_label_add_is_correlated_and_reversible(self):
        record = base_record()

        self.assertEqual(record.mutation_class, MutationClass.M1)
        self.assertEqual(
            record.dry_run_reference.message_id,
            record.message_id,
        )
        self.assertEqual(
            record.rollback.rollback_action,
            MutationAction.REMOVE_LABEL,
        )
        self.assertEqual(
            record.rollback.restore_state,
            record.previous_state,
        )

    def test_action_must_match_canonical_mutation_class(self):
        with self.assertRaisesRegex(
            ValueError,
            "requires mutation class M1",
        ):
            base_record(mutation_class=MutationClass.M3)

    def test_success_requires_requested_resulting_state(self):
        with self.assertRaisesRegex(
            ValueError,
            "must match requested_new_state",
        ):
            base_record(
                resulting_state=MailboxStateSnapshot(
                    user_labels=(),
                    in_inbox=True,
                    in_trash=False,
                )
            )

    def test_failed_and_partial_failure_are_distinct(self):
        previous = MailboxStateSnapshot(
            in_inbox=True,
            in_trash=False,
        )
        requested = MailboxStateSnapshot(
            in_inbox=False,
            in_trash=True,
        )
        partial = MailboxStateSnapshot(
            in_inbox=False,
            in_trash=False,
        )

        failed = base_record(
            action=MutationAction.MOVE_TO_TRASH,
            mutation_class=MutationClass.M4,
            target_label=None,
            previous_state=previous,
            requested_new_state=requested,
            resulting_state=previous,
            result=MutationResultStatus.FAILED,
            confidence_score=0.999,
            confidence_band=ConfidenceBand.HIGH,
            execution_mode=(
                MutationExecutionMode.DEDICATED_CLEANUP_WRITE
            ),
            dry_run_reference=None,
            rollback=RollbackMetadata(
                reversible=True,
                rollback_action=MutationAction.RESTORE_FROM_TRASH,
                restore_state=previous,
                provider_capability="restore_from_trash",
            ),
        )

        partially_failed = base_record(
            action=MutationAction.MOVE_TO_TRASH,
            mutation_class=MutationClass.M4,
            target_label=None,
            previous_state=previous,
            requested_new_state=requested,
            resulting_state=partial,
            result=MutationResultStatus.PARTIAL_FAILURE,
            confidence_score=0.999,
            confidence_band=ConfidenceBand.HIGH,
            execution_mode=(
                MutationExecutionMode.DEDICATED_CLEANUP_WRITE
            ),
            dry_run_reference=None,
            rollback=RollbackMetadata(
                reversible=True,
                rollback_action=MutationAction.RESTORE_FROM_TRASH,
                restore_state=previous,
                provider_capability="restore_from_trash",
            ),
        )

        self.assertEqual(
            failed.result,
            MutationResultStatus.FAILED,
        )
        self.assertEqual(
            failed.resulting_state,
            previous,
        )
        self.assertEqual(
            partially_failed.result,
            MutationResultStatus.PARTIAL_FAILURE,
        )
        self.assertEqual(
            partially_failed.resulting_state,
            partial,
        )
        self.assertNotEqual(
            partially_failed.resulting_state,
            previous,
        )
        self.assertNotEqual(
            partially_failed.resulting_state,
            requested,
        )

    def test_denied_mutation_requires_blocked_safety_gate(self):
        previous = MailboxStateSnapshot(
            in_inbox=True,
            in_trash=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "require at least one blocked safety gate",
        ):
            base_record(
                previous_state=previous,
                requested_new_state=MailboxStateSnapshot(
                    user_labels=("Projects/Alpha",),
                    in_inbox=True,
                    in_trash=False,
                ),
                resulting_state=previous,
                result=MutationResultStatus.DENIED,
                rollback=RollbackMetadata(reversible=False),
            )

    def test_blocked_gate_cannot_be_recorded_as_provider_failure(self):
        previous = MailboxStateSnapshot(
            in_inbox=True,
            in_trash=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "blocked safety gates require a denied mutation result",
        ):
            base_record(
                previous_state=previous,
                requested_new_state=MailboxStateSnapshot(
                    user_labels=("Projects/Alpha",),
                    in_inbox=True,
                    in_trash=False,
                ),
                resulting_state=previous,
                result=MutationResultStatus.FAILED,
                safety_gates=(
                    SafetyGateRecord(
                        gate="mutation_authorization",
                        decision=SafetyGateDecision.BLOCKED,
                        detail="Synthetic safety policy blocked execution.",
                    ),
                ),
                provider_result=ProviderResultMetadata(
                    failure_code="not_executed",
                ),
                rollback=RollbackMetadata(reversible=False),
            )

    def test_denied_mutation_must_preserve_previous_state(self):
        previous = MailboxStateSnapshot(
            in_inbox=True,
            in_trash=False,
        )

        record = base_record(
            previous_state=previous,
            requested_new_state=MailboxStateSnapshot(
                user_labels=("Projects/Alpha",),
                in_inbox=True,
                in_trash=False,
            ),
            resulting_state=previous,
            result=MutationResultStatus.DENIED,
            safety_gates=(
                SafetyGateRecord(
                    gate="mutation_authorization",
                    decision=SafetyGateDecision.BLOCKED,
                    detail="Synthetic safety policy denied the mutation.",
                ),
            ),
            provider_result=ProviderResultMetadata(),
            rollback=RollbackMetadata(reversible=False),
        )

        self.assertEqual(record.resulting_state, previous)

    def test_reversible_operation_requires_restore_metadata(self):
        with self.assertRaisesRegex(
            ValueError,
            "require rollback_action",
        ):
            RollbackMetadata(reversible=True)

    def test_synthetic_label_remove_has_m2_rollback(self):
        previous = MailboxStateSnapshot(
            user_labels=("Projects/Old",),
        )
        requested = MailboxStateSnapshot(user_labels=())

        record = base_record(
            action=MutationAction.REMOVE_LABEL,
            mutation_class=MutationClass.M2,
            target_label="Projects/Old",
            previous_state=previous,
            requested_new_state=requested,
            resulting_state=requested,
            dry_run_reference=None,
            rollback=RollbackMetadata(
                reversible=True,
                rollback_action=MutationAction.ADD_LABEL,
                restore_state=previous,
            ),
        )

        self.assertEqual(record.mutation_class, MutationClass.M2)

    def test_synthetic_archive_has_m3_rollback(self):
        previous = MailboxStateSnapshot(
            in_inbox=True,
            in_trash=False,
        )
        requested = MailboxStateSnapshot(
            in_inbox=False,
            in_trash=False,
        )

        record = base_record(
            action=MutationAction.ARCHIVE,
            mutation_class=MutationClass.M3,
            target_label=None,
            previous_state=previous,
            requested_new_state=requested,
            resulting_state=requested,
            dry_run_reference=None,
            rollback=RollbackMetadata(
                reversible=True,
                rollback_action=MutationAction.RESTORE_TO_INBOX,
                restore_state=previous,
            ),
        )

        self.assertEqual(
            record.rollback.rollback_action,
            MutationAction.RESTORE_TO_INBOX,
        )

    def test_synthetic_trash_action_is_m4_not_permanent_delete(self):
        previous = MailboxStateSnapshot(
            in_inbox=True,
            in_trash=False,
        )
        requested = MailboxStateSnapshot(
            in_inbox=False,
            in_trash=True,
        )

        record = base_record(
            action=MutationAction.MOVE_TO_TRASH,
            mutation_class=MutationClass.M4,
            target_label=None,
            previous_state=previous,
            requested_new_state=requested,
            resulting_state=requested,
            confidence_score=0.999,
            confidence_band=ConfidenceBand.HIGH,
            execution_mode=(
                MutationExecutionMode.DEDICATED_CLEANUP_WRITE
            ),
            dry_run_reference=None,
            rollback=RollbackMetadata(
                reversible=True,
                rollback_action=MutationAction.RESTORE_FROM_TRASH,
                restore_state=previous,
                provider_capability="restore_from_trash",
            ),
        )

        self.assertEqual(record.mutation_class, MutationClass.M4)
        self.assertNotIn(
            "permanent",
            [action.value for action in MutationAction],
        )
        self.assertNotIn(
            "delete",
            [action.value for action in MutationAction],
        )

    def test_default_serialization_has_no_sensitive_content_fields(self):
        data = base_record().to_dict()
        serialized = json.dumps(data)

        forbidden_keys = (
            "message_body",
            "body",
            "attachment_content",
            "credential",
            "access_token",
            "refresh_token",
            "raw_response",
            "raw_error",
        )

        for key in forbidden_keys:
            self.assertNotIn(f'"{key}"', serialized)

    def test_json_and_human_renderers_are_stable_and_auditable(self):
        record = base_record()

        first = render_change_record_json(record)
        second = render_change_record_json(record)
        human = render_change_record_text(record)

        self.assertEqual(first, second)
        self.assertIn("record-001", human)
        self.assertIn("add_label", human)
        self.assertIn("M1", human)
        self.assertIn(
            record.dry_run_reference.correlation_id,
            human,
        )

    def test_local_jsonl_append_requires_no_hosted_service(self):
        first = base_record()
        second = base_record(record_id="record-002")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "change-log.jsonl"

            append_change_record_jsonl(path, first)
            append_change_record_jsonl(path, second)

            lines = path.read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(len(lines), 2)
        self.assertEqual(
            json.loads(lines[0])["record_id"],
            "record-001",
        )
        self.assertEqual(
            json.loads(lines[1])["record_id"],
            "record-002",
        )
        self.assertEqual(
            render_change_log_jsonl((first, second)).splitlines(),
            lines,
        )


if __name__ == "__main__":
    unittest.main()
