import unittest

from semantic_mail_archivist.documents import (
    AttachmentDisposition,
    AttachmentSnapshot,
    DocumentClass,
    DocumentSignificance,
    assess_document_significance,
)
from semantic_mail_archivist.model import (
    ConfidenceBand,
    LabelClass,
    MessageSnapshot,
)


class SyntheticLabelClassifier:
    def classify(self, label: str) -> LabelClass:
        if label == "INBOX":
            return LabelClass.SYSTEM
        if label == "@Invoice":
            return LabelClass.USER_OPERATIONAL
        return LabelClass.USER_SEMANTIC


class DocumentSignificanceTests(unittest.TestCase):
    def test_inline_logo_is_high_confidence_generic_attachment(self):
        message = MessageSnapshot("m-inline")
        attachment = AttachmentSnapshot(
            "a-logo",
            filename="company-logo.png",
            mime_type="image/png",
            disposition=AttachmentDisposition.INLINE,
        )

        result = assess_document_significance(message, attachment)

        self.assertEqual(result.document_class, DocumentClass.GENERIC_ATTACHMENT)
        self.assertEqual(
            result.significance,
            DocumentSignificance.GENERIC_ATTACHMENT,
        )
        self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
        self.assertNotIn("significant_document", result.protection_hints)

    def test_clean_contract_metadata_is_high_confidence_significant_document(self):
        message = MessageSnapshot(
            "m-contract",
            normalized_subject="Signed employment agreement",
        )
        attachment = AttachmentSnapshot(
            "a-contract",
            filename="signed-contract.pdf",
            mime_type="application/pdf",
            disposition=AttachmentDisposition.ATTACHMENT,
        )

        result = assess_document_significance(message, attachment)

        self.assertEqual(result.document_class, DocumentClass.CONTRACT)
        self.assertEqual(
            result.significance,
            DocumentSignificance.SIGNIFICANT_DOCUMENT,
        )
        self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
        self.assertIn("significant_document", result.protection_hints)
        self.assertIn(
            "protected_domain:contracts_employment",
            result.protection_hints,
        )

    def test_protected_and_administrative_document_classes_are_detected(self):
        fixtures = (
            (
                "Tax records",
                "tax-certificate.pdf",
                DocumentClass.TAX,
                "protected_domain:tax_fiscal",
            ),
            (
                "Insurance renewal",
                "insurance-policy.pdf",
                DocumentClass.INSURANCE,
                "protected_domain:insurance",
            ),
            (
                "Payment confirmation",
                "payment-receipt.pdf",
                DocumentClass.RECEIPT,
                "protected_domain:payments_receipts_invoices",
            ),
            (
                "Vendor invoice",
                "invoice-2026-08.pdf",
                DocumentClass.INVOICE,
                "protected_domain:payments_receipts_invoices",
            ),
            (
                "Administrative notice",
                "administrative-notice.pdf",
                DocumentClass.ADMINISTRATIVE,
                "review_retention:administrative_record",
            ),
            (
                "Medical report",
                "medical-report.pdf",
                DocumentClass.MEDICAL,
                "protected_domain:health_medical",
            ),
        )

        for index, (subject, filename, expected_class, expected_hint) in enumerate(
            fixtures
        ):
            with self.subTest(document_class=expected_class.value):
                result = assess_document_significance(
                    MessageSnapshot(f"m-{index}", normalized_subject=subject),
                    AttachmentSnapshot(
                        f"a-{index}",
                        filename=filename,
                        mime_type="application/pdf",
                        disposition=AttachmentDisposition.ATTACHMENT,
                    ),
                )

                self.assertEqual(result.document_class, expected_class)
                self.assertEqual(
                    result.significance,
                    DocumentSignificance.SIGNIFICANT_DOCUMENT,
                )
                self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
                self.assertIn(expected_hint, result.protection_hints)

    def test_keyword_matching_does_not_use_arbitrary_substrings(self):
        result = assess_document_significance(
            MessageSnapshot("m-boundaries"),
            AttachmentSnapshot(
                "a-boundaries",
                filename="please-assigned-billing.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.UNKNOWN)
        self.assertEqual(result.significance, DocumentSignificance.UNKNOWN)

    def test_document_like_mime_without_semantics_stays_unknown(self):
        result = assess_document_significance(
            MessageSnapshot("m-unknown"),
            AttachmentSnapshot(
                "a-unknown",
                filename="scan-001.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.UNKNOWN)
        self.assertEqual(result.significance, DocumentSignificance.UNKNOWN)
        self.assertEqual(result.confidence_band, ConfidenceBand.LOW)

    def test_inline_image_without_decorative_or_document_semantics_stays_unknown(self):
        result = assess_document_significance(
            MessageSnapshot("m-inline-unknown"),
            AttachmentSnapshot(
                "a-inline-unknown",
                filename="scan-001.jpg",
                mime_type="image/jpeg",
                disposition=AttachmentDisposition.INLINE,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.UNKNOWN)
        self.assertEqual(result.significance, DocumentSignificance.UNKNOWN)
        self.assertTrue(
            any(
                item.signal == "inline_image_without_document_semantics"
                for item in result.evidence
            )
        )

    def test_plain_image_attachment_is_generic_without_forcing_document_class(self):
        result = assess_document_significance(
            MessageSnapshot("m-photo"),
            AttachmentSnapshot(
                "a-photo",
                filename="holiday-photo.jpg",
                mime_type="image/jpeg",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.GENERIC_ATTACHMENT)
        self.assertEqual(
            result.significance,
            DocumentSignificance.GENERIC_ATTACHMENT,
        )
        self.assertEqual(result.confidence_band, ConfidenceBand.MEDIUM)

    def test_exact_duplicates_do_not_reduce_document_significance(self):
        result = assess_document_significance(
            MessageSnapshot(
                "m-duplicate",
                normalized_subject="Vendor invoice",
            ),
            AttachmentSnapshot(
                "a-duplicate",
                filename="invoice-2026-08.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
                exact_duplicate_count=2,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.INVOICE)
        self.assertEqual(
            result.significance,
            DocumentSignificance.SIGNIFICANT_DOCUMENT,
        )
        self.assertIn("duplicate_occurrence", result.protection_hints)
        duplicate_evidence = [
            item
            for item in result.evidence
            if item.signal == "exact_duplicate_occurrences"
        ]
        self.assertEqual(len(duplicate_evidence), 1)
        self.assertEqual(duplicate_evidence[0].contribution, 0.0)

    def test_near_duplicates_are_flagged_but_not_collapsed(self):
        result = assess_document_significance(
            MessageSnapshot(
                "m-near",
                normalized_subject="Insurance renewal",
            ),
            AttachmentSnapshot(
                "a-near",
                filename="insurance-policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
                near_duplicate_count=3,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.INSURANCE)
        self.assertIn("near_duplicate_review", result.protection_hints)
        self.assertTrue(
            any(
                item.signal == "near_duplicate_occurrences"
                for item in result.evidence
            )
        )

    def test_repeated_template_is_negative_evidence_not_an_absolute_veto(self):
        result = assess_document_significance(
            MessageSnapshot(
                "m-template",
                normalized_subject="Signed contract",
            ),
            AttachmentSnapshot(
                "a-template",
                filename="contract.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
                is_repeated_template=True,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.CONTRACT)
        self.assertEqual(
            result.significance,
            DocumentSignificance.SIGNIFICANT_DOCUMENT,
        )
        self.assertEqual(result.confidence_band, ConfidenceBand.MEDIUM)
        self.assertTrue(
            any(item.signal == "repeated_template" for item in result.evidence)
        )

    def test_ambiguous_document_classes_are_refused(self):
        result = assess_document_significance(
            MessageSnapshot(
                "m-ambiguous",
                normalized_subject="Insurance invoice",
            ),
            AttachmentSnapshot(
                "a-ambiguous",
                filename="insurance-invoice.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.UNKNOWN)
        self.assertEqual(result.significance, DocumentSignificance.UNKNOWN)
        self.assertTrue(
            any(
                item.signal == "competing_document_classes"
                for item in result.evidence
            )
        )

    def test_evidence_summarizes_matches_without_echoing_full_personal_context(self):
        private_subject = "Invoice for Private Customer 998877"
        private_correspondent = "private.customer.998877@example.test"
        result = assess_document_significance(
            MessageSnapshot(
                "m-privacy",
                normalized_subject=private_subject,
                correspondents=(private_correspondent,),
            ),
            AttachmentSnapshot(
                "a-privacy",
                filename="invoice.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        evidence_text = " ".join(item.detail for item in result.evidence)

        self.assertNotIn(private_subject, evidence_text)
        self.assertNotIn(private_correspondent, evidence_text)
        self.assertIn("invoice", evidence_text)

    def test_taxonomy_evidence_uses_only_classified_semantic_labels(self):
        classifier = SyntheticLabelClassifier()

        ignored = assess_document_significance(
            MessageSnapshot(
                "m-operational",
                labels=("INBOX", "@Invoice"),
            ),
            AttachmentSnapshot(
                "a-operational",
                filename="scan-001.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
            classifier,
        )

        self.assertEqual(ignored.document_class, DocumentClass.UNKNOWN)
        self.assertFalse(
            any(item.signal == "taxonomy_context" for item in ignored.evidence)
        )

        semantic = assess_document_significance(
            MessageSnapshot(
                "m-semantic",
                labels=("Personal/Insurance",),
            ),
            AttachmentSnapshot(
                "a-semantic",
                filename="policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
            classifier,
        )

        self.assertEqual(semantic.document_class, DocumentClass.INSURANCE)
        self.assertEqual(semantic.confidence_band, ConfidenceBand.HIGH)
        self.assertTrue(
            any(item.signal == "taxonomy_context" for item in semantic.evidence)
        )

    def test_mime_identifiers_preserve_hyphens(self):
        result = assess_document_significance(
            MessageSnapshot(
                "m-excel",
                normalized_subject="Vendor invoice",
            ),
            AttachmentSnapshot(
                "a-excel",
                filename="invoice-2026.xls",
                mime_type="application/vnd.ms-excel",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(result.document_class, DocumentClass.INVOICE)
        self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
        self.assertTrue(
            any(item.signal == "document_mime_type" for item in result.evidence)
        )

    def test_classifier_does_not_mutate_message_or_apply_document_label(self):
        message = MessageSnapshot(
            "m-read-only",
            labels=("Personal/Insurance",),
            normalized_subject="Insurance renewal",
        )
        original_labels = message.labels

        result = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-read-only",
                filename="insurance-policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(message.labels, original_labels)
        self.assertNotIn("@Document", message.labels)
        self.assertNotIn("@Document", result.protection_hints)

    def test_duplicate_counts_must_be_non_negative(self):
        with self.assertRaises(ValueError):
            AttachmentSnapshot("a-invalid", exact_duplicate_count=-1)
        with self.assertRaises(ValueError):
            AttachmentSnapshot("a-invalid", near_duplicate_count=-1)


if __name__ == "__main__":
    unittest.main()
