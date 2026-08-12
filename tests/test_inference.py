import unittest

from semantic_mail_archivist.adapters import GmailLabelClassifier
from semantic_mail_archivist.detection import detect_message_level_label_gaps
from semantic_mail_archivist.inference import infer_label_from_thread
from semantic_mail_archivist.model import ConfidenceBand, MessageSnapshot, ThreadSnapshot


class LabelInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = GmailLabelClassifier()

    def candidate_for(self, thread: ThreadSnapshot):
        candidates = detect_message_level_label_gaps(thread, self.classifier)
        self.assertEqual(len(candidates), 1)
        return candidates[0]

    def test_clean_context_produces_high_confidence_proposal(self):
        thread = ThreadSnapshot(
            "thread-1",
            (
                MessageSnapshot(
                    "m1",
                    ("Personal/Housing",),
                    normalized_subject="maintenance",
                    participants=("owner@example.test", "vendor@example.test"),
                ),
                MessageSnapshot(
                    "m2",
                    ("INBOX",),
                    normalized_subject="maintenance",
                    participants=("owner@example.test", "vendor@example.test"),
                ),
                MessageSnapshot(
                    "m3",
                    ("Personal/Housing",),
                    normalized_subject="maintenance",
                    participants=("owner@example.test", "vendor@example.test"),
                ),
            ),
        )

        result = infer_label_from_thread(thread, self.candidate_for(thread))

        self.assertEqual(result.proposed_label, "Personal/Housing")
        self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
        self.assertGreaterEqual(result.confidence_score, 0.90)
        self.assertFalse(result.conflicts)

    def test_conflicting_thread_refuses_to_infer(self):
        thread = ThreadSnapshot(
            "thread-2",
            (
                MessageSnapshot("m1", ("Work/Project-A",)),
                MessageSnapshot("m2"),
                MessageSnapshot("m3", ("Work/Finance",)),
            ),
        )

        result = infer_label_from_thread(thread, self.candidate_for(thread))

        self.assertIsNone(result.proposed_label)
        self.assertEqual(result.confidence_band, ConfidenceBand.LOW)
        self.assertIn("competing_thread_semantic_labels", result.conflicts)

    def test_direct_semantic_hint_can_veto_stable_thread(self):
        thread = ThreadSnapshot(
            "thread-3",
            (
                MessageSnapshot("m1", ("Work/Project",)),
                MessageSnapshot(
                    "m2",
                    semantic_label_hints=("Work/Finance",),
                ),
                MessageSnapshot("m3", ("Work/Project",)),
            ),
        )

        result = infer_label_from_thread(thread, self.candidate_for(thread))

        self.assertIsNone(result.proposed_label)
        self.assertEqual(result.confidence_band, ConfidenceBand.LOW)
        self.assertIn(
            "direct_semantic_hint_conflicts_with_thread",
            result.conflicts,
        )

    def test_single_support_is_medium_not_high(self):
        thread = ThreadSnapshot(
            "thread-4",
            (
                MessageSnapshot("m1", ("Work/Vendor",)),
                MessageSnapshot("m2"),
            ),
        )

        result = infer_label_from_thread(thread, self.candidate_for(thread))

        self.assertEqual(result.proposed_label, "Work/Vendor")
        self.assertEqual(result.confidence_band, ConfidenceBand.MEDIUM)
        self.assertEqual(result.confidence_score, 0.60)

    def test_low_score_deliberately_returns_no_proposed_label(self):
        thread = ThreadSnapshot(
            "thread-5",
            (
                MessageSnapshot(
                    "m1",
                    ("Work/Vendor",),
                    normalized_subject="invoice",
                    participants=("vendor@example.test",),
                ),
                MessageSnapshot(
                    "m2",
                    normalized_subject="holiday",
                    participants=("friend@example.test",),
                ),
            ),
        )

        result = infer_label_from_thread(thread, self.candidate_for(thread))

        self.assertIsNone(result.proposed_label)
        self.assertEqual(result.confidence_band, ConfidenceBand.LOW)
        self.assertLess(result.confidence_score, 0.60)
        self.assertIn("subject_discontinuity", result.conflicts)
        self.assertIn("participant_discontinuity", result.conflicts)

    def test_positive_semantic_hint_is_inspectable_evidence(self):
        thread = ThreadSnapshot(
            "thread-6",
            (
                MessageSnapshot("m1", ("Personal/Insurance",)),
                MessageSnapshot(
                    "m2",
                    has_attachment=True,
                    semantic_label_hints=("Personal/Insurance",),
                ),
                MessageSnapshot("m3", ("Personal/Insurance",)),
            ),
        )

        result = infer_label_from_thread(thread, self.candidate_for(thread))
        signals = {item.signal: item for item in result.evidence}

        self.assertEqual(result.proposed_label, "Personal/Insurance")
        self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)
        self.assertIn("direct_semantic_compatibility", signals)
        self.assertEqual(signals["attachment_presence"].contribution, 0.0)

    def test_evidence_contributions_reconstruct_score(self):
        thread = ThreadSnapshot(
            "thread-7",
            (
                MessageSnapshot("m1", ("Work/Training",)),
                MessageSnapshot("m2", semantic_label_hints=("Work/Training",)),
                MessageSnapshot("m3", ("Work/Training",)),
            ),
        )

        result = infer_label_from_thread(thread, self.candidate_for(thread))
        reconstructed = round(sum(item.contribution for item in result.evidence), 3)

        self.assertEqual(result.confidence_score, reconstructed)
        self.assertEqual(result.confidence_band, ConfidenceBand.HIGH)


if __name__ == "__main__":
    unittest.main()
