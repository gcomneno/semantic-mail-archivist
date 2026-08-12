import unittest

from semantic_mail_archivist.documents import (
    AttachmentDisposition,
    AttachmentSnapshot,
    DocumentSignificance,
    assess_document_significance,
)
from semantic_mail_archivist.model import ConfidenceBand, MessageSnapshot
from semantic_mail_archivist.obsolescence import (
    ObsolescenceClass,
    ObsolescenceConflict,
    ObsolescenceContext,
    ObsolescenceRecommendation,
    assess_message_obsolescence,
)
from semantic_mail_archivist.protection import (
    ProtectionCoverage,
    infer_protected_domains,
)


def complete_unprotected(message: MessageSnapshot):
    return infer_protected_domains(
        message,
        coverage=ProtectionCoverage.COMPLETE,
    )


def complete_safety_context(**overrides):
    values = {
        "meaningful_correspondence": False,
        "payment_history": False,
        "account_access_record": False,
        "ambiguous_semantics": False,
    }
    values.update(overrides)
    return values


class ObsolescenceTests(unittest.TestCase):
    def test_high_confidence_synthetic_obsolete_classes_are_recognized(self):
        fixtures = (
            (
                ObsolescenceClass.EXPIRED_ONE_TIME_CODE,
                "Your verification code",
                {"expiration_confirmed": True, "automated_sender": True},
            ),
            (
                ObsolescenceClass.OLD_MARKETING_CAMPAIGN,
                "Summer sale special offer",
                {"expiration_confirmed": True, "automated_sender": True},
            ),
            (
                ObsolescenceClass.TRANSIENT_SERVICE_NOTIFICATION,
                "Backup completed",
                {"transient_event_completed": True, "automated_sender": True},
            ),
            (
                ObsolescenceClass.OBSOLETE_PRODUCT_ANNOUNCEMENT,
                "New release product announcement",
                {"product_superseded": True, "automated_sender": True},
            ),
            (
                ObsolescenceClass.DISCONTINUED_SERVICE_NOTIFICATION,
                "Service notice",
                {"service_discontinued": True, "automated_sender": True},
            ),
            (
                ObsolescenceClass.LOW_VALUE_AUTOMATED_MAIL,
                "Automated notification",
                {"automated_sender": True},
            ),
        )

        for obsolete_class, subject, context_values in fixtures:
            with self.subTest(obsolete_class=obsolete_class.value):
                message = MessageSnapshot(
                    f"m-{obsolete_class.value}",
                    normalized_subject=subject,
                )
                context = ObsolescenceContext(
                    age_days=365,
                    **complete_safety_context(),
                    **context_values,
                )
                result = assess_message_obsolescence(
                    message,
                    context,
                    protection_assessment=complete_unprotected(message),
                )
                self.assertEqual(result.obsolescence_class, obsolete_class)
                self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
                self.assertGreaterEqual(result.confidence_score, 0.995)
                self.assertEqual(
                    result.recommendation,
                    ObsolescenceRecommendation.REVIEW_FOR_FUTURE_TRASH,
                )
                self.assertTrue(result.future_trash_candidate)

    def test_age_alone_never_creates_obsolescence_evidence(self):
        message = MessageSnapshot("m-age-only", normalized_subject="Personal note")
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=5000,
                **complete_safety_context(),
            ),
            protection_assessment=complete_unprotected(message),
        )
        self.assertEqual(result.obsolescence_class, ObsolescenceClass.UNKNOWN)
        self.assertEqual(result.confidence_score, 0.0)
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )
        self.assertTrue(
            any(
                item.signal == "age_without_obsolescence_signal"
                and item.contribution == 0.0
                for item in result.evidence
            )
        )

    def test_old_but_valuable_payment_document_is_explicitly_retained(self):
        message = MessageSnapshot(
            "m-valuable",
            has_attachment=True,
            normalized_subject="Old invoice payment history",
        )
        document = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-valuable",
                filename="invoice.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )
        protection = infer_protected_domains(
            message,
            document_candidates=(document,),
            coverage=ProtectionCoverage.COMPLETE,
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=3650,
                automated_sender=True,
                document_assessment_complete=True,
                **complete_safety_context(payment_history=True),
            ),
            document_candidates=(document,),
            protection_assessment=protection,
        )
        self.assertEqual(
            document.significance,
            DocumentSignificance.SIGNIFICANT_DOCUMENT,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )
        self.assertIn(
            ObsolescenceConflict.SIGNIFICANT_DOCUMENT,
            result.protection_conflicts,
        )
        self.assertIn(
            ObsolescenceConflict.PROTECTED_DOMAIN,
            result.protection_conflicts,
        )
        self.assertIn(
            ObsolescenceConflict.PAYMENT_HISTORY,
            result.protection_conflicts,
        )

    def test_protected_domain_suppresses_future_trash_candidate(self):
        message = MessageSnapshot(
            "m-protected-marketing",
            normalized_subject="Medical newsletter special offer",
            semantic_label_hints=("Personal/Health",),
        )
        protection = infer_protected_domains(
            message,
            coverage=ProtectionCoverage.COMPLETE,
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=730,
                automated_sender=True,
                expiration_confirmed=True,
                **complete_safety_context(),
            ),
            protection_assessment=protection,
        )
        self.assertEqual(
            result.obsolescence_class,
            ObsolescenceClass.OLD_MARKETING_CAMPAIGN,
        )
        self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
        self.assertIn(
            ObsolescenceConflict.PROTECTED_DOMAIN,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_significant_document_suppresses_future_trash_candidate(self):
        message = MessageSnapshot(
            "m-doc-marketing",
            has_attachment=True,
            normalized_subject="Special offer certificate",
        )
        document = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-doc-marketing",
                filename="certificate.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=730,
                automated_sender=True,
                expiration_confirmed=True,
                document_assessment_complete=True,
                **complete_safety_context(),
            ),
            document_candidates=(document,),
            protection_assessment=complete_unprotected(message),
        )
        self.assertEqual(
            document.significance,
            DocumentSignificance.SIGNIFICANT_DOCUMENT,
        )
        self.assertIn(
            ObsolescenceConflict.SIGNIFICANT_DOCUMENT,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_unknown_document_significance_is_conservative(self):
        message = MessageSnapshot(
            "m-unknown-doc",
            has_attachment=True,
            normalized_subject="Automated notification",
        )
        document = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-unknown-doc",
                filename="archive.dat",
                mime_type="application/octet-stream",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                document_assessment_complete=True,
                **complete_safety_context(),
            ),
            document_candidates=(document,),
            protection_assessment=complete_unprotected(message),
        )
        self.assertEqual(document.significance, DocumentSignificance.UNKNOWN)
        self.assertIn(
            ObsolescenceConflict.DOCUMENT_SIGNIFICANCE_UNKNOWN,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_unassessed_attachment_is_conservative(self):
        message = MessageSnapshot(
            "m-unassessed-attachment",
            has_attachment=True,
            normalized_subject="Automated notification",
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                **complete_safety_context(),
            ),
            protection_assessment=complete_unprotected(message),
        )
        self.assertIn(
            ObsolescenceConflict.ATTACHMENT_NOT_ASSESSED,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_partial_document_assessment_is_conservative(self):
        message = MessageSnapshot(
            "m-partial-doc-assessment",
            has_attachment=True,
            normalized_subject="Automated notification",
        )
        document = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-partial-doc-assessment",
                filename="image.png",
                mime_type="image/png",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                document_assessment_complete=False,
                **complete_safety_context(),
            ),
            document_candidates=(document,),
            protection_assessment=complete_unprotected(message),
        )

        self.assertEqual(
            document.significance,
            DocumentSignificance.GENERIC_ATTACHMENT,
        )
        self.assertIn(
            ObsolescenceConflict.DOCUMENT_ASSESSMENT_INCOMPLETE,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_complete_generic_document_assessment_can_clear_document_gate(self):
        message = MessageSnapshot(
            "m-complete-doc-assessment",
            has_attachment=True,
            normalized_subject="Automated notification",
        )
        document = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-complete-doc-assessment",
                filename="image.png",
                mime_type="image/png",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                document_assessment_complete=True,
                **complete_safety_context(),
            ),
            document_candidates=(document,),
            protection_assessment=complete_unprotected(message),
        )

        self.assertEqual(
            document.significance,
            DocumentSignificance.GENERIC_ATTACHMENT,
        )
        self.assertNotIn(
            ObsolescenceConflict.DOCUMENT_ASSESSMENT_INCOMPLETE,
            result.protection_conflicts,
        )
        self.assertNotIn(
            ObsolescenceConflict.ATTACHMENT_NOT_ASSESSED,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.REVIEW_FOR_FUTURE_TRASH,
        )

    def test_missing_protection_assessment_defaults_to_retain(self):
        message = MessageSnapshot(
            "m-no-protection",
            normalized_subject="Summer sale special offer",
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                expiration_confirmed=True,
                **complete_safety_context(),
            ),
        )
        self.assertIn(
            ObsolescenceConflict.PROTECTION_UNKNOWN,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_incomplete_safety_context_defaults_to_retain(self):
        message = MessageSnapshot(
            "m-incomplete-safety",
            normalized_subject="Summer sale special offer",
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                expiration_confirmed=True,
            ),
            protection_assessment=complete_unprotected(message),
        )
        self.assertIn(
            ObsolescenceConflict.SAFETY_CONTEXT_INCOMPLETE,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_meaningful_correspondence_payment_access_and_ambiguity_retain(self):
        cases = (
            (
                "meaningful",
                {"meaningful_correspondence": True},
                ObsolescenceConflict.MEANINGFUL_CORRESPONDENCE,
            ),
            (
                "payment",
                {"payment_history": True},
                ObsolescenceConflict.PAYMENT_HISTORY,
            ),
            (
                "access",
                {"account_access_record": True},
                ObsolescenceConflict.ACCOUNT_ACCESS_RECORD,
            ),
            (
                "ambiguous",
                {"ambiguous_semantics": True},
                ObsolescenceConflict.AMBIGUOUS_SEMANTICS,
            ),
        )
        for name, overrides, expected_conflict in cases:
            with self.subTest(name=name):
                message = MessageSnapshot(
                    f"m-{name}",
                    normalized_subject="Automated notification",
                )
                result = assess_message_obsolescence(
                    message,
                    ObsolescenceContext(
                        age_days=365,
                        automated_sender=True,
                        **complete_safety_context(**overrides),
                    ),
                    protection_assessment=complete_unprotected(message),
                )
                self.assertIn(
                    expected_conflict,
                    result.protection_conflicts,
                )
                self.assertEqual(
                    result.recommendation,
                    ObsolescenceRecommendation.RETAIN,
                )

    def test_medium_obsolescence_without_conflicts_is_review_only(self):
        message = MessageSnapshot("m-medium", normalized_subject="Special offer")
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=5,
                automated_sender=False,
                expiration_confirmed=None,
                **complete_safety_context(),
            ),
            protection_assessment=complete_unprotected(message),
        )
        self.assertEqual(
            result.obsolescence_class,
            ObsolescenceClass.OLD_MARKETING_CAMPAIGN,
        )
        self.assertEqual(result.confidence_band, ConfidenceBand.MEDIUM)
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.REVIEW,
        )

    def test_competing_obsolescence_classes_become_unknown_and_retain(self):
        message = MessageSnapshot(
            "m-competing",
            normalized_subject="Automated notification special offer",
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                expiration_confirmed=True,
                **complete_safety_context(),
            ),
            protection_assessment=complete_unprotected(message),
        )
        self.assertEqual(result.obsolescence_class, ObsolescenceClass.UNKNOWN)
        self.assertIn(
            ObsolescenceConflict.AMBIGUOUS_SEMANTICS,
            result.protection_conflicts,
        )
        self.assertEqual(
            result.recommendation,
            ObsolescenceRecommendation.RETAIN,
        )

    def test_keyword_matching_does_not_use_arbitrary_substrings(self):
        message = MessageSnapshot(
            "m-substrings",
            normalized_subject="Salesforce campaigner notebook",
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=1000,
                **complete_safety_context(),
            ),
            protection_assessment=complete_unprotected(message),
        )
        self.assertEqual(result.obsolescence_class, ObsolescenceClass.UNKNOWN)

    def test_evidence_does_not_echo_full_subject_or_secret_code(self):
        subject = "Verification code for Private Person 998877"
        message = MessageSnapshot(
            "m-private",
            normalized_subject=subject,
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                expiration_confirmed=True,
                **complete_safety_context(),
            ),
            protection_assessment=complete_unprotected(message),
        )
        evidence_text = " ".join(item.detail for item in result.evidence)
        self.assertNotIn(subject, evidence_text)
        self.assertNotIn("998877", evidence_text)
        self.assertIn("expired_one_time_code", evidence_text)

    def test_score_contributions_reconstruct_final_score(self):
        message = MessageSnapshot(
            "m-score",
            normalized_subject="Summer sale special offer",
        )
        result = assess_message_obsolescence(
            message,
            ObsolescenceContext(
                age_days=365,
                automated_sender=True,
                expiration_confirmed=True,
                **complete_safety_context(),
            ),
            protection_assessment=complete_unprotected(message),
        )
        reconstructed = sum(item.contribution for item in result.evidence)
        self.assertAlmostEqual(reconstructed, result.confidence_score)
        self.assertEqual(result.confidence_score, 1.0)
        self.assertTrue(
            any(item.signal == "score_clamp" for item in result.evidence)
        )

    def test_cross_message_safety_inputs_are_rejected(self):
        message = MessageSnapshot(
            "m-target",
            normalized_subject="Summer sale special offer",
        )
        other_message = MessageSnapshot("m-other")
        other_document = assess_document_significance(
            other_message,
            AttachmentSnapshot(
                "a-other",
                filename="certificate.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        with self.assertRaises(ValueError):
            assess_message_obsolescence(
                message,
                ObsolescenceContext(
                    age_days=365,
                    **complete_safety_context(),
                ),
                document_candidates=(other_document,),
                protection_assessment=complete_unprotected(message),
            )

        with self.assertRaises(ValueError):
            assess_message_obsolescence(
                message,
                ObsolescenceContext(
                    age_days=365,
                    **complete_safety_context(),
                ),
                protection_assessment=complete_unprotected(other_message),
            )

    def test_negative_age_is_rejected(self):
        with self.assertRaises(ValueError):
            ObsolescenceContext(age_days=-1)


if __name__ == "__main__":
    unittest.main()
