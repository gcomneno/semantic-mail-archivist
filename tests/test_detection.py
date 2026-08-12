import unittest

from semantic_mail_archivist import ContextStatus, LabelClass, MessageSnapshot, ThreadSnapshot
from semantic_mail_archivist.adapters import GmailLabelClassifier
from semantic_mail_archivist.detection import detect_message_level_label_gaps


class MessageLevelGapDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = GmailLabelClassifier(
            operational_labels=frozenset(
                {"@Action", "@Waiting", "@Deadline", "@Document", "@Reference"}
            )
        )

    def detect(self, *messages: MessageSnapshot):
        thread = ThreadSnapshot(thread_id="thread-1", messages=tuple(messages))
        return detect_message_level_label_gaps(thread, self.classifier)

    def test_clean_inheritance_context_reports_stable_gap(self):
        candidates = self.detect(
            MessageSnapshot("m1", ("Personal/Housing",)),
            MessageSnapshot("m2", ("INBOX", "IMPORTANT")),
            MessageSnapshot("m3", ("Personal/Housing",)),
        )

        self.assertEqual([candidate.message_id for candidate in candidates], ["m2"])
        candidate = candidates[0]
        self.assertEqual(candidate.context_status, ContextStatus.STABLE)
        self.assertEqual(candidate.surrounding_evidence[0].label, "Personal/Housing")
        self.assertEqual(
            candidate.surrounding_evidence[0].supporting_message_ids,
            ("m1", "m3"),
        )

    def test_conflicting_classifications_are_preserved_not_resolved(self):
        candidates = self.detect(
            MessageSnapshot("m1", ("Work/Project-A",)),
            MessageSnapshot("m2"),
            MessageSnapshot("m3", ("Work/Finance",)),
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.context_status, ContextStatus.CONFLICTING)
        self.assertEqual(
            [evidence.label for evidence in candidate.surrounding_evidence],
            ["Work/Finance", "Work/Project-A"],
        )

    def test_system_only_thread_does_not_create_false_positive(self):
        candidates = self.detect(
            MessageSnapshot("m1", ("INBOX", "IMPORTANT", "CHAT")),
            MessageSnapshot("m2", ("CATEGORY_UPDATES", "UNREAD")),
        )

        self.assertEqual(candidates, ())

    def test_provider_system_labels_can_be_supplied_by_adapter_metadata(self):
        classifier = GmailLabelClassifier(
            system_labels=frozenset({"INBOX", "PROVIDER_RESERVED"})
        )

        self.assertEqual(classifier.classify("PROVIDER_RESERVED"), LabelClass.SYSTEM)

    def test_attachment_flag_is_preserved_on_gap_candidate(self):
        candidates = self.detect(
            MessageSnapshot("m1", ("Personal/Insurance",)),
            MessageSnapshot("m2", ("INBOX",), has_attachment=True),
            MessageSnapshot("m3", ("Personal/Insurance",)),
        )

        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].has_attachment)

    def test_message_with_semantic_label_is_not_a_gap(self):
        candidates = self.detect(
            MessageSnapshot("m1", ("Personal/Housing",)),
            MessageSnapshot("m2", ("Personal/Housing", "INBOX")),
            MessageSnapshot("m3", ("Personal/Housing",)),
        )

        self.assertEqual(candidates, ())

    def test_operational_label_does_not_fill_semantic_gap(self):
        candidates = self.detect(
            MessageSnapshot("m1", ("Work/Vendor",)),
            MessageSnapshot("m2", ("@Waiting", "INBOX")),
            MessageSnapshot("m3", ("Work/Vendor",)),
        )

        self.assertEqual([candidate.message_id for candidate in candidates], ["m2"])
        self.assertEqual(candidates[0].context_status, ContextStatus.STABLE)


if __name__ == "__main__":
    unittest.main()
