import json
import unittest

from semantic_mail_archivist.model import LabelClass, MessageSnapshot, ThreadSnapshot
from semantic_mail_archivist.reporting import (
    ExecutionStatus,
    MutationAuthorization,
    MutationClass,
    PlannedAction,
    RepairRecommendation,
    SafetyGateResult,
    build_dry_run_report,
    render_dry_run_json,
    render_dry_run_text,
)


class SyntheticLabelClassifier:
    def classify(self, label: str) -> LabelClass:
        if label in {"INBOX", "IMPORTANT"}:
            return LabelClass.SYSTEM
        if label == "@Waiting":
            return LabelClass.USER_OPERATIONAL
        if label == "Mystery":
            return LabelClass.UNKNOWN
        return LabelClass.USER_SEMANTIC


class DryRunReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = SyntheticLabelClassifier()

    def test_high_clean_inheritance_is_m1_proposal_but_never_authorized(self):
        thread = ThreadSnapshot(
            "thread-high",
            (
                MessageSnapshot(
                    "m1",
                    ("Personal/Housing",),
                    normalized_subject="maintenance",
                    correspondents=("vendor@example.test",),
                ),
                MessageSnapshot(
                    "m2",
                    ("INBOX",),
                    normalized_subject="maintenance",
                    correspondents=("vendor@example.test",),
                ),
                MessageSnapshot(
                    "m3",
                    ("Personal/Housing",),
                    normalized_subject="maintenance",
                    correspondents=("vendor@example.test",),
                ),
            ),
        )

        entry = build_dry_run_report(thread, self.classifier).entries[0]

        self.assertEqual(
            entry.recommendation,
            RepairRecommendation.ELIGIBLE_FOR_ADDITIVE_REPAIR,
        )
        self.assertEqual(entry.planned_action, PlannedAction.ADD_LABEL)
        self.assertEqual(entry.mutation_class, MutationClass.M1)
        self.assertEqual(entry.mutation_authorization, MutationAuthorization.DENIED)
        self.assertEqual(
            entry.safety_gate_result,
            SafetyGateResult.NOT_EVALUATED_FOR_WRITE,
        )
        self.assertEqual(entry.execution_status, ExecutionStatus.NOT_EXECUTED)

    def test_medium_proposal_requires_review_and_plans_no_action(self):
        thread = ThreadSnapshot(
            "thread-medium",
            (
                MessageSnapshot("m1", ("Work/Vendor",)),
                MessageSnapshot("m2", ("INBOX",)),
            ),
        )

        entry = build_dry_run_report(thread, self.classifier).entries[0]

        self.assertEqual(entry.proposed_label, "Work/Vendor")
        self.assertEqual(entry.confidence_score, 0.60)
        self.assertEqual(entry.recommendation, RepairRecommendation.REVIEW_REQUIRED)
        self.assertEqual(entry.planned_action, PlannedAction.NO_ACTION)
        self.assertEqual(entry.mutation_class, MutationClass.M0)
        self.assertEqual(entry.mutation_authorization, MutationAuthorization.DENIED)
        self.assertEqual(
            entry.safety_gate_result,
            SafetyGateResult.NOT_EVALUATED_FOR_WRITE,
        )
        self.assertEqual(entry.execution_status, ExecutionStatus.NOT_EXECUTED)

    def test_conflicting_inference_is_first_class_no_action(self):
        thread = ThreadSnapshot(
            "thread-conflict",
            (
                MessageSnapshot("m1", ("Work/Project-A",)),
                MessageSnapshot("m2", ("INBOX",)),
                MessageSnapshot("m3", ("Work/Finance",)),
            ),
        )

        entry = build_dry_run_report(thread, self.classifier).entries[0]

        self.assertIsNone(entry.proposed_label)
        self.assertEqual(entry.recommendation, RepairRecommendation.NO_ACTION)
        self.assertEqual(entry.planned_action, PlannedAction.NO_ACTION)
        self.assertEqual(entry.mutation_authorization, MutationAuthorization.DENIED)
        self.assertEqual(
            entry.safety_gate_result,
            SafetyGateResult.NOT_EVALUATED_FOR_WRITE,
        )
        self.assertEqual(entry.execution_status, ExecutionStatus.NOT_EXECUTED)
        self.assertIn("competing_thread_semantic_labels", entry.conflicts)

    def test_current_user_labels_exclude_system_and_retain_operational_and_unknown(self):
        thread = ThreadSnapshot(
            "thread-label-classes",
            (
                MessageSnapshot("m1", ("Personal/Housing",)),
                MessageSnapshot("m2", ("INBOX", "@Waiting", "Mystery")),
                MessageSnapshot("m3", ("Personal/Housing",)),
            ),
        )

        entry = build_dry_run_report(thread, self.classifier).entries[0]

        self.assertEqual(entry.current_user_labels, ("@Waiting", "Mystery"))

    def test_machine_readable_shape_is_stable_and_json_safe(self):
        thread = ThreadSnapshot(
            "thread-shape",
            (
                MessageSnapshot("m1", ("Work/Training",)),
                MessageSnapshot("m2", ("INBOX",)),
                MessageSnapshot("m3", ("Work/Training",)),
            ),
        )

        report = build_dry_run_report(thread, self.classifier)
        payload = report.to_dict()
        entry = payload["entries"][0]

        self.assertEqual(list(payload), ["schema_version", "mode", "entries"])
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(
            list(entry),
            [
                "thread_id",
                "message_id",
                "current_user_labels",
                "proposed_label",
                "confidence_score",
                "confidence_band",
                "evidence",
                "conflicts",
                "recommendation",
                "planned_action",
                "mutation_class",
                "mutation_authorization",
                "safety_gate_result",
                "authorization_reasons",
                "execution_status",
            ],
        )

        encoded = render_dry_run_json(report)
        self.assertEqual(json.loads(encoded), payload)
        self.assertEqual(encoded, render_dry_run_json(report))

    def test_machine_representation_has_no_sensitive_content_fields(self):
        thread = ThreadSnapshot(
            "thread-privacy",
            (
                MessageSnapshot("m1", ("Personal/Insurance",)),
                MessageSnapshot("m2", ("INBOX",), has_attachment=True),
                MessageSnapshot("m3", ("Personal/Insurance",)),
            ),
        )

        serialized = json.dumps(
            build_dry_run_report(thread, self.classifier).to_dict()
        )
        for forbidden in (
            '"body"',
            '"snippet"',
            '"attachment_contents"',
            '"access_token"',
            '"credentials"',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_human_renderer_distinguishes_high_review_and_no_action(self):
        high = ThreadSnapshot(
            "thread-human-high",
            (
                MessageSnapshot(
                    "m1",
                    ("Personal/Housing",),
                    normalized_subject="repair",
                    correspondents=("vendor@example.test",),
                ),
                MessageSnapshot(
                    "m2",
                    normalized_subject="repair",
                    correspondents=("vendor@example.test",),
                ),
                MessageSnapshot(
                    "m3",
                    ("Personal/Housing",),
                    normalized_subject="repair",
                    correspondents=("vendor@example.test",),
                ),
            ),
        )
        medium = ThreadSnapshot(
            "thread-human-medium",
            (
                MessageSnapshot("m1", ("Work/Vendor",)),
                MessageSnapshot("m2"),
            ),
        )
        conflicting = ThreadSnapshot(
            "thread-human-none",
            (
                MessageSnapshot("m1", ("Work/Project-A",)),
                MessageSnapshot("m2"),
                MessageSnapshot("m3", ("Work/Finance",)),
            ),
        )

        self.assertIn(
            "HIGH — ELIGIBLE FOR ADDITIVE REPAIR",
            render_dry_run_text(build_dry_run_report(high, self.classifier)),
        )
        self.assertIn(
            "REVIEW REQUIRED",
            render_dry_run_text(build_dry_run_report(medium, self.classifier)),
        )
        self.assertIn(
            "NO ACTION",
            render_dry_run_text(build_dry_run_report(conflicting, self.classifier)),
        )

    def test_empty_report_is_valid_when_no_gap_exists(self):
        thread = ThreadSnapshot(
            "thread-no-gap",
            (
                MessageSnapshot("m1", ("Personal/Housing",)),
                MessageSnapshot("m2", ("Personal/Housing", "INBOX")),
            ),
        )

        report = build_dry_run_report(thread, self.classifier)

        self.assertEqual(report.entries, ())
        self.assertIn("No repair candidates.", render_dry_run_text(report))


if __name__ == "__main__":
    unittest.main()
