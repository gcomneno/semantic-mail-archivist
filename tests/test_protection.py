import unittest

from semantic_mail_archivist.documents import (
    AttachmentDisposition,
    AttachmentSnapshot,
    assess_document_significance,
)
from semantic_mail_archivist.model import (
    ConfidenceBand,
    LabelClass,
    MessageSnapshot,
)
from semantic_mail_archivist.protection import (
    DestructiveProtectionGateResult,
    ProtectedDomain,
    ProtectionCoverage,
    ProtectionStatus,
    evaluate_destructive_protection_gate,
    infer_protected_domains,
)


class SyntheticLabelClassifier:
    def classify(self, label: str) -> LabelClass:
        if label in {"INBOX", "IMPORTANT"}:
            return LabelClass.SYSTEM
        if label.startswith("@"):
            return LabelClass.USER_OPERATIONAL
        if label == "Mystery":
            return LabelClass.UNKNOWN
        return LabelClass.USER_SEMANTIC


class ProtectedDomainTests(unittest.TestCase):
    def test_positive_and_negative_examples_cover_every_initial_domain(self):
        fixtures = (
            (
                ProtectedDomain.HEALTH_MEDICAL,
                "Medical appointment report",
                "Wealth planning notes",
            ),
            (
                ProtectedDomain.TAX_FISCAL,
                "Tax return notice",
                "Syntax workshop notes",
            ),
            (
                ProtectedDomain.BANKING_FINANCIAL,
                "Bank account statement",
                "Project planning update",
            ),
            (
                ProtectedDomain.INSURANCE,
                "Insurance policy renewal",
                "Quality assurance review",
            ),
            (
                ProtectedDomain.CONTRACTS_EMPLOYMENT,
                "Employment contract",
                "Contractor schedule",
            ),
            (
                ProtectedDomain.PENSIONS_BENEFITS_PUBLIC_ADMIN,
                "Pension benefit notice",
                "Pensive writing notes",
            ),
            (
                ProtectedDomain.IDENTITY_AUTHENTICATION,
                "Passport identity card renewal",
                "Matrix identity exercise",
            ),
            (
                ProtectedDomain.EDUCATION,
                "University academic transcript",
                "Educational design discussion",
            ),
            (
                ProtectedDomain.LEGAL,
                "Legal court notice",
                "Legalization workflow",
            ),
            (
                ProtectedDomain.PAYMENTS_RECEIPTS_INVOICES,
                "Invoice payment receipt",
                "Repayment strategy",
            ),
        )

        self.assertEqual(len(fixtures), len(ProtectedDomain))

        for domain, positive_subject, negative_subject in fixtures:
            with self.subTest(domain=domain.value, case="positive"):
                positive = infer_protected_domains(
                    MessageSnapshot(
                        f"m-positive-{domain.value}",
                        normalized_subject=positive_subject,
                    )
                )
                domains = {hint.domain for hint in positive.hints}
                self.assertIn(domain, domains)
                self.assertIn(
                    positive.status,
                    {
                        ProtectionStatus.PROTECTED,
                        ProtectionStatus.POSSIBLY_PROTECTED,
                    },
                )

            with self.subTest(domain=domain.value, case="negative"):
                negative = infer_protected_domains(
                    MessageSnapshot(
                        f"m-negative-{domain.value}",
                        normalized_subject=negative_subject,
                    ),
                    coverage=ProtectionCoverage.COMPLETE,
                )
                domains = {hint.domain for hint in negative.hints}
                self.assertNotIn(domain, domains)

    def test_multiple_domains_are_preserved_instead_of_forcing_one(self):
        result = infer_protected_domains(
            MessageSnapshot(
                "m-multiple",
                normalized_subject="Medical insurance claim",
            )
        )

        domains = {hint.domain for hint in result.hints}

        self.assertEqual(
            domains,
            {
                ProtectedDomain.HEALTH_MEDICAL,
                ProtectedDomain.INSURANCE,
            },
        )
        self.assertEqual(
            result.status,
            ProtectionStatus.POSSIBLY_PROTECTED,
        )

    def test_classified_semantic_labels_are_taxonomy_evidence(self):
        classifier = SyntheticLabelClassifier()
        result = infer_protected_domains(
            MessageSnapshot(
                "m-taxonomy",
                labels=(
                    "INBOX",
                    "@Waiting",
                    "Personal/Health",
                    "Mystery",
                ),
            ),
            classifier=classifier,
        )

        domains = {hint.domain for hint in result.hints}

        self.assertEqual(
            domains,
            {ProtectedDomain.HEALTH_MEDICAL},
        )
        self.assertEqual(
            result.hints[0].confidence_band,
            ConfidenceBand.MEDIUM,
        )
        self.assertTrue(
            any(
                item.signal == "taxonomy_context"
                for item in result.hints[0].evidence
            )
        )

    def test_raw_provider_and_operational_labels_are_not_semantic_evidence(self):
        classifier = SyntheticLabelClassifier()
        result = infer_protected_domains(
            MessageSnapshot(
                "m-label-safety",
                labels=(
                    "INBOX",
                    "@Invoice",
                    "IMPORTANT",
                    "Mystery",
                ),
            ),
            classifier=classifier,
        )

        self.assertEqual(result.hints, ())
        self.assertEqual(
            result.status,
            ProtectionStatus.UNKNOWN,
        )

    def test_document_candidate_protection_hint_preserves_medium_confidence(self):
        message = MessageSnapshot(
            "m-document",
            normalized_subject="Renewal documents",
        )
        document = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-document",
                filename="insurance-policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(
            document.confidence_band,
            ConfidenceBand.MEDIUM,
        )

        result = infer_protected_domains(
            message,
            document_candidates=(document,),
        )

        insurance = next(
            hint
            for hint in result.hints
            if hint.domain is ProtectedDomain.INSURANCE
        )
        self.assertEqual(
            insurance.confidence_score,
            document.confidence_score,
        )
        self.assertEqual(
            insurance.confidence_band,
            ConfidenceBand.MEDIUM,
        )
        self.assertEqual(
            result.status,
            ProtectionStatus.POSSIBLY_PROTECTED,
        )
        self.assertTrue(
            any(
                item.signal == "document_candidate"
                for item in insurance.evidence
            )
        )

    def test_high_confidence_document_candidate_produces_protected_domain(self):
        document_message = MessageSnapshot(
            "m-document-high",
            normalized_subject="Insurance renewal",
        )
        document = assess_document_significance(
            document_message,
            AttachmentSnapshot(
                "a-document-high",
                filename="insurance-policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(
            document.confidence_band,
            ConfidenceBand.HIGH,
        )

        result = infer_protected_domains(
            MessageSnapshot("m-document-high"),
            document_candidates=(document,),
        )

        insurance = next(
            hint
            for hint in result.hints
            if hint.domain is ProtectedDomain.INSURANCE
        )

        self.assertEqual(
            insurance.confidence_score,
            document.confidence_score,
        )
        self.assertEqual(
            insurance.confidence_band,
            ConfidenceBand.HIGH,
        )
        self.assertEqual(
            result.status,
            ProtectionStatus.PROTECTED,
        )

    def test_duplicate_document_candidates_do_not_inflate_domain_score(self):
        message = MessageSnapshot(
            "m-doc-duplicate",
            normalized_subject=None,
        )
        document = assess_document_significance(
            MessageSnapshot(
                "m-doc-duplicate",
                normalized_subject="Insurance renewal",
            ),
            AttachmentSnapshot(
                "a-doc-duplicate",
                filename="insurance-policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
                exact_duplicate_count=2,
            ),
        )

        result = infer_protected_domains(
            message,
            document_candidates=(document, document),
        )

        insurance = next(
            hint
            for hint in result.hints
            if hint.domain is ProtectedDomain.INSURANCE
        )
        document_evidence = [
            item
            for item in insurance.evidence
            if item.signal == "document_candidate"
        ]

        self.assertEqual(len(document_evidence), 1)
        self.assertEqual(
            insurance.confidence_score,
            document.confidence_score,
        )

    def test_partial_zero_hint_assessment_is_unknown_and_blocks_destruction(self):
        assessment = infer_protected_domains(
            MessageSnapshot("m-unknown"),
        )
        gate = evaluate_destructive_protection_gate(
            assessment
        )

        self.assertEqual(
            assessment.status,
            ProtectionStatus.UNKNOWN,
        )
        self.assertEqual(
            gate.result,
            DestructiveProtectionGateResult.BLOCKED_UNKNOWN,
        )
        self.assertTrue(gate.blocks_destructive_action)

    def test_complete_zero_hint_assessment_only_passes_protection_gate(self):
        assessment = infer_protected_domains(
            MessageSnapshot(
                "m-complete",
                normalized_subject="Routine project planning update",
            ),
            coverage=ProtectionCoverage.COMPLETE,
        )
        gate = evaluate_destructive_protection_gate(
            assessment
        )

        self.assertEqual(
            assessment.status,
            ProtectionStatus.NOT_PROTECTED,
        )
        self.assertEqual(
            gate.result,
            DestructiveProtectionGateResult.PASSED_NO_PROTECTED_SIGNAL,
        )
        self.assertFalse(gate.blocks_destructive_action)
        self.assertIn(
            "protection_gate_pass_does_not_authorize_destructive_action",
            gate.reasons,
        )

    def test_possible_domain_blocks_destructive_action(self):
        assessment = infer_protected_domains(
            MessageSnapshot(
                "m-possible",
                normalized_subject="Tax return notice",
            )
        )
        gate = evaluate_destructive_protection_gate(
            assessment
        )

        self.assertEqual(
            assessment.status,
            ProtectionStatus.POSSIBLY_PROTECTED,
        )
        self.assertEqual(
            gate.result,
            DestructiveProtectionGateResult.BLOCKED_POSSIBLE_DOMAIN,
        )
        self.assertIn(
            ProtectedDomain.TAX_FISCAL,
            gate.blocking_domains,
        )

    def test_high_confidence_domain_blocks_destructive_action(self):
        classifier = SyntheticLabelClassifier()
        assessment = infer_protected_domains(
            MessageSnapshot(
                "m-protected",
                labels=("Personal/Insurance",),
                normalized_subject="Insurance policy renewal",
            ),
            classifier=classifier,
        )
        gate = evaluate_destructive_protection_gate(
            assessment
        )

        self.assertEqual(
            assessment.status,
            ProtectionStatus.PROTECTED,
        )
        self.assertEqual(
            gate.result,
            DestructiveProtectionGateResult.BLOCKED_PROTECTED_DOMAIN,
        )
        self.assertIn(
            ProtectedDomain.INSURANCE,
            gate.blocking_domains,
        )

    def test_evidence_does_not_echo_full_sensitive_context(self):
        subject = "Tax return for Private Person 998877"
        correspondent = "private.tax.person.998877@example.test"

        assessment = infer_protected_domains(
            MessageSnapshot(
                "m-private",
                normalized_subject=subject,
                correspondents=(correspondent,),
            )
        )

        evidence_text = " ".join(
            item.detail
            for hint in assessment.hints
            for item in hint.evidence
        )

        self.assertNotIn(subject, evidence_text)
        self.assertNotIn(correspondent, evidence_text)
        self.assertIn("tax", evidence_text)

    def test_evidence_contributions_reconstruct_clamped_score(self):
        classifier = SyntheticLabelClassifier()
        assessment = infer_protected_domains(
            MessageSnapshot(
                "m-score",
                labels=("Personal/Insurance",),
                normalized_subject="Insurance renewal",
            ),
            classifier=classifier,
        )

        hint = next(
            hint
            for hint in assessment.hints
            if hint.domain is ProtectedDomain.INSURANCE
        )

        reconstructed = sum(
            item.contribution
            for item in hint.evidence
        )

        self.assertAlmostEqual(
            reconstructed,
            hint.confidence_score,
        )
        self.assertEqual(
            hint.confidence_score,
            1.0,
        )
        self.assertTrue(
            any(
                item.signal == "score_clamp"
                for item in hint.evidence
            )
        )


if __name__ == "__main__":
    unittest.main()
