import unittest

from semantic_mail_archivist import (
    AttachmentDisposition,
    AttachmentSnapshot,
    AuditWarningCode,
    LabelClass,
    MailboxAuditReport,
    MessageSnapshot,
    ObsolescenceClass,
    ObsolescenceConflict,
    ObsolescenceContext,
    ObsolescenceRecommendation,
    OperationalLayerConfig,
    OperationalRecommendation,
    ProviderLimitation,
    ProtectionCoverage,
    ProtectionStatus,
    RepairRecommendation,
    ThreadSnapshot,
    build_mailbox_audit,
    render_mailbox_audit_json,
    render_mailbox_audit_text,
)


class SyntheticClassifier:
    def classify(self, label: str) -> LabelClass:
        if label in {"INBOX", "SENT", "TRASH", "SPAM"}:
            return LabelClass.SYSTEM
        if label.startswith("@"):
            return LabelClass.USER_OPERATIONAL
        if label.startswith("?"):
            return LabelClass.UNKNOWN
        return LabelClass.USER_SEMANTIC


def complete_context(**overrides) -> ObsolescenceContext:
    values = {
        "meaningful_correspondence": False,
        "payment_history": False,
        "account_access_record": False,
        "ambiguous_semantics": False,
    }
    values.update(overrides)
    return ObsolescenceContext(**values)


class MailboxAuditTests(unittest.TestCase):
    def setUp(self):
        self.classifier = SyntheticClassifier()

    def test_end_to_end_audit_combines_all_dimensions(self):
        thread = ThreadSnapshot(
            "t-main",
            (
                MessageSnapshot(
                    "m-before",
                    labels=("Projects/Alpha",),
                    correspondents=("team@example.test",),
                ),
                MessageSnapshot(
                    "m-target",
                    labels=("INBOX",),
                    has_attachment=True,
                    normalized_subject=(
                        "Insurance automated notification action required"
                    ),
                    correspondents=("team@example.test",),
                    semantic_label_hints=("Projects/Alpha",),
                ),
                MessageSnapshot(
                    "m-after",
                    labels=("Projects/Alpha",),
                    correspondents=("team@example.test",),
                ),
            ),
        )

        report = build_mailbox_audit(
            (thread,),
            self.classifier,
            attachments_by_message={
                "m-target": (
                    AttachmentSnapshot(
                        "a-policy",
                        filename="insurance-policy.pdf",
                        mime_type="application/pdf",
                        disposition=AttachmentDisposition.ATTACHMENT,
                    ),
                ),
            },
            obsolescence_context_by_message={
                "m-before": complete_context(),
                "m-target": complete_context(
                    age_days=365,
                    automated_sender=True,
                    document_assessment_complete=True,
                ),
                "m-after": complete_context(),
            },
            protection_coverage_by_message={
                "m-before": ProtectionCoverage.COMPLETE,
                "m-target": ProtectionCoverage.COMPLETE,
                "m-after": ProtectionCoverage.COMPLETE,
            },
            available_labels=(
                "@Action",
                "@Document",
                "Projects/Alpha",
            ),
        )

        self.assertIsInstance(report, MailboxAuditReport)
        self.assertEqual(report.summary.messages_analyzed, 3)
        self.assertEqual(report.summary.semantic_taxonomy_labels, 1)
        self.assertEqual(report.summary.message_level_label_gaps, 1)
        self.assertEqual(
            report.summary.high_confidence_repair_candidates,
            1,
        )
        self.assertEqual(
            report.summary.significant_document_candidates,
            1,
        )
        self.assertGreaterEqual(
            report.summary.protected_domain_candidates,
            1,
        )
        self.assertEqual(
            report.summary.obsolete_low_value_candidates,
            1,
        )
        self.assertEqual(
            report.summary.future_trash_review_candidates,
            0,
        )
        self.assertGreaterEqual(
            report.summary.operational_state_opportunities,
            2,
        )

        target = next(
            record
            for record in report.records
            if record.message_id == "m-target"
        )

        self.assertIsNotNone(target.repair)
        self.assertEqual(
            target.repair.recommendation,
            RepairRecommendation.ELIGIBLE_FOR_ADDITIVE_REPAIR,
        )
        self.assertEqual(
            target.documents[0].significance.value,
            "significant_document",
        )
        self.assertEqual(
            target.protection.status,
            ProtectionStatus.PROTECTED,
        )
        self.assertEqual(
            target.obsolescence.obsolescence_class,
            ObsolescenceClass.LOW_VALUE_AUTOMATED_MAIL,
        )
        self.assertEqual(
            target.obsolescence.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )
        self.assertIn(
            ObsolescenceConflict.PROTECTED_DOMAIN,
            target.obsolescence.protection_conflicts,
        )
        self.assertIn(
            ObsolescenceConflict.SIGNIFICANT_DOCUMENT,
            target.obsolescence.protection_conflicts,
        )
        self.assertEqual(
            target.operational.recommendation,
            OperationalRecommendation.PROPOSE_OPERATIONAL_STATE,
        )

    def test_conflicting_gap_is_counted_as_ambiguous_even_without_proposal(self):
        thread = ThreadSnapshot(
            "t-ambiguous",
            (
                MessageSnapshot(
                    "m-alpha",
                    labels=("Projects/Alpha",),
                ),
                MessageSnapshot("m-gap"),
                MessageSnapshot(
                    "m-beta",
                    labels=("Projects/Beta",),
                ),
            ),
        )

        contexts = {
            message.message_id: complete_context()
            for message in thread.messages
        }
        coverages = {
            message.message_id: ProtectionCoverage.COMPLETE
            for message in thread.messages
        }

        report = build_mailbox_audit(
            (thread,),
            self.classifier,
            obsolescence_context_by_message=contexts,
            protection_coverage_by_message=coverages,
        )

        self.assertEqual(report.summary.message_level_label_gaps, 1)
        self.assertEqual(report.summary.ambiguous_repair_candidates, 1)
        self.assertEqual(
            report.summary.repair_candidates_requiring_review,
            0,
        )
        self.assertEqual(report.summary.unresolved_label_gaps, 1)

        gap_record = next(
            record
            for record in report.records
            if record.message_id == "m-gap"
        )
        self.assertIsNotNone(gap_record.repair)
        self.assertTrue(gap_record.repair.conflicts)

        human = render_mailbox_audit_text(report)
        for conflict in gap_record.repair.conflicts:
            self.assertIn(conflict, human)

    def test_missing_attachment_metadata_downgrades_complete_protection_coverage(self):
        message = MessageSnapshot(
            "m-downgrade",
            has_attachment=True,
            normalized_subject="Personal archive",
        )

        report = build_mailbox_audit(
            (ThreadSnapshot("t-downgrade", (message,)),),
            self.classifier,
            obsolescence_context_by_message={
                "m-downgrade": complete_context(),
            },
            protection_coverage_by_message={
                "m-downgrade": ProtectionCoverage.COMPLETE,
            },
        )

        record = report.records[0]
        codes = {
            warning.code
            for warning in report.warnings
        }

        self.assertEqual(
            record.protection.coverage,
            ProtectionCoverage.PARTIAL,
        )
        self.assertEqual(
            record.protection.status,
            ProtectionStatus.UNKNOWN,
        )
        self.assertIn(
            AuditWarningCode.MISSING_ATTACHMENT_METADATA,
            codes,
        )
        self.assertIn(
            AuditWarningCode.PROTECTION_COVERAGE_DOWNGRADED,
            codes,
        )
        self.assertIn(
            AuditWarningCode.PARTIAL_PROTECTION_COVERAGE,
            codes,
        )

    def test_attachment_metadata_conflicting_with_message_flag_is_rejected(self):
        message = MessageSnapshot(
            "m-attachment-mismatch",
            has_attachment=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "has_attachment flag is false",
        ):
            build_mailbox_audit(
                (ThreadSnapshot("t-mismatch", (message,)),),
                self.classifier,
                attachments_by_message={
                    "m-attachment-mismatch": (
                        AttachmentSnapshot("a-unexpected"),
                    ),
                },
            )

    def test_summary_counts_are_traceable_to_records(self):
        thread = ThreadSnapshot(
            "t-trace",
            (
                MessageSnapshot(
                    "m-1",
                    labels=("Projects/Alpha",),
                ),
                MessageSnapshot(
                    "m-2",
                    semantic_label_hints=("Projects/Alpha",),
                ),
                MessageSnapshot(
                    "m-3",
                    labels=("Projects/Alpha",),
                ),
            ),
        )

        contexts = {
            message.message_id: complete_context()
            for message in thread.messages
        }
        coverages = {
            message.message_id: ProtectionCoverage.COMPLETE
            for message in thread.messages
        }

        report = build_mailbox_audit(
            (thread,),
            self.classifier,
            obsolescence_context_by_message=contexts,
            protection_coverage_by_message=coverages,
        )

        repair_records = [
            record.repair
            for record in report.records
            if record.repair is not None
        ]

        self.assertEqual(
            report.summary.message_level_label_gaps,
            len(repair_records),
        )
        self.assertEqual(
            report.summary.high_confidence_repair_candidates,
            sum(
                repair.recommendation
                is RepairRecommendation.ELIGIBLE_FOR_ADDITIVE_REPAIR
                for repair in repair_records
            ),
        )

    def test_missing_provider_facts_are_visible_and_conservative(self):
        message = MessageSnapshot(
            "m-missing",
            has_attachment=True,
            normalized_subject="Personal archive",
        )

        report = build_mailbox_audit(
            (ThreadSnapshot("t-missing", (message,)),),
            self.classifier,
        )

        codes = {
            warning.code
            for warning in report.warnings
        }

        self.assertIn(
            AuditWarningCode.MISSING_ATTACHMENT_METADATA,
            codes,
        )
        self.assertIn(
            AuditWarningCode.MISSING_OBSOLESCENCE_CONTEXT,
            codes,
        )
        self.assertIn(
            AuditWarningCode.PARTIAL_PROTECTION_COVERAGE,
            codes,
        )

        record = report.records[0]
        self.assertEqual(
            record.protection.status,
            ProtectionStatus.UNKNOWN,
        )
        self.assertEqual(
            record.obsolescence.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )
        self.assertIn(
            ObsolescenceConflict.ATTACHMENT_NOT_ASSESSED,
            record.obsolescence.protection_conflicts,
        )
        self.assertIn(
            ObsolescenceConflict.SAFETY_CONTEXT_INCOMPLETE,
            record.obsolescence.protection_conflicts,
        )

    def test_default_outputs_omit_sensitive_subject_correspondent_and_filename(self):
        message = MessageSnapshot(
            "m-private",
            has_attachment=True,
            normalized_subject="SECRET-SUBJECT-ALPHA",
            correspondents=("private-person@example.test",),
        )

        report = build_mailbox_audit(
            (ThreadSnapshot("t-private", (message,)),),
            self.classifier,
            attachments_by_message={
                "m-private": (
                    AttachmentSnapshot(
                        "a-private",
                        filename="SECRET-FILENAME-ALPHA.pdf",
                        mime_type="application/pdf",
                        disposition=AttachmentDisposition.ATTACHMENT,
                    ),
                ),
            },
            obsolescence_context_by_message={
                "m-private": complete_context(
                    document_assessment_complete=True,
                ),
            },
            protection_coverage_by_message={
                "m-private": ProtectionCoverage.COMPLETE,
            },
        )

        rendered = (
            render_mailbox_audit_json(report)
            + "\n"
            + render_mailbox_audit_text(report)
        )

        self.assertNotIn("SECRET-SUBJECT-ALPHA", rendered)
        self.assertNotIn("private-person@example.test", rendered)
        self.assertNotIn("SECRET-FILENAME-ALPHA.pdf", rendered)

    def test_machine_output_is_deterministic_across_thread_order(self):
        first = ThreadSnapshot(
            "t-a",
            (MessageSnapshot("m-a", labels=("Projects/A",)),),
        )
        second = ThreadSnapshot(
            "t-b",
            (MessageSnapshot("m-b", labels=("Projects/B",)),),
        )

        contexts = {
            "m-a": complete_context(),
            "m-b": complete_context(),
        }
        coverages = {
            "m-a": ProtectionCoverage.COMPLETE,
            "m-b": ProtectionCoverage.COMPLETE,
        }

        report_a = build_mailbox_audit(
            (first, second),
            self.classifier,
            obsolescence_context_by_message=contexts,
            protection_coverage_by_message=coverages,
        )
        report_b = build_mailbox_audit(
            (second, first),
            self.classifier,
            obsolescence_context_by_message=contexts,
            protection_coverage_by_message=coverages,
        )

        self.assertEqual(
            render_mailbox_audit_json(report_a),
            render_mailbox_audit_json(report_b),
        )

    def test_duplicate_message_ids_are_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "message_id must be unique",
        ):
            build_mailbox_audit(
                (
                    ThreadSnapshot(
                        "t-a",
                        (MessageSnapshot("m-same"),),
                    ),
                    ThreadSnapshot(
                        "t-b",
                        (MessageSnapshot("m-same"),),
                    ),
                ),
                self.classifier,
            )

    def test_provider_facts_for_unknown_message_are_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "unknown message_id",
        ):
            build_mailbox_audit(
                (
                    ThreadSnapshot(
                        "t-known",
                        (MessageSnapshot("m-known"),),
                    ),
                ),
                self.classifier,
                obsolescence_context_by_message={
                    "m-unknown": complete_context(),
                },
            )

    def test_operational_layer_can_be_disabled_mailbox_wide(self):
        message = MessageSnapshot(
            "m-op-disabled",
            normalized_subject="Action required by Friday",
        )

        report = build_mailbox_audit(
            (ThreadSnapshot("t-op", (message,)),),
            self.classifier,
            obsolescence_context_by_message={
                "m-op-disabled": complete_context(),
            },
            protection_coverage_by_message={
                "m-op-disabled": ProtectionCoverage.COMPLETE,
            },
            operational_config=OperationalLayerConfig(enabled=False),
        )

        self.assertEqual(
            report.summary.operational_state_opportunities,
            0,
        )
        self.assertEqual(
            report.records[0].operational.recommendation,
            OperationalRecommendation.DISABLED,
        )

    def test_provider_limitations_are_stable_report_records(self):
        limitation = ProviderLimitation(
            code="gmail_history_unavailable",
            detail=(
                "Historical provider metadata was not supplied for this audit."
            ),
        )

        report = build_mailbox_audit(
            (),
            self.classifier,
            provider_limitations=(limitation,),
        )

        machine = render_mailbox_audit_json(report)
        human = render_mailbox_audit_text(report)

        self.assertEqual(report.summary.provider_limitations, 1)
        self.assertIn("gmail_history_unavailable", machine)
        self.assertIn("gmail_history_unavailable", human)
        self.assertIn(
            "Historical provider metadata was not supplied",
            human,
        )

    def test_public_report_is_strictly_read_only(self):
        report = build_mailbox_audit(
            (),
            self.classifier,
        )

        data = report.to_dict()

        self.assertTrue(data["read_only"])
        self.assertEqual(
            data["mutation_authorization"],
            "DENIED",
        )
        self.assertEqual(
            data["execution_status"],
            "NOT_EXECUTED",
        )


if __name__ == "__main__":
    unittest.main()
