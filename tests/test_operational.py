import unittest

from semantic_mail_archivist.adapters.gmail import GmailLabelClassifier
from semantic_mail_archivist.documents import (
    AttachmentDisposition,
    AttachmentSnapshot,
    DocumentSignificance,
    assess_document_significance,
)
from semantic_mail_archivist.model import MessageSnapshot
from semantic_mail_archivist.operational import (
    DEFAULT_OPERATIONAL_LABEL_SPECS,
    OperationalConflict,
    OperationalEvidence,
    OperationalExecutionStatus,
    OperationalLabelSpec,
    OperationalLayerConfig,
    OperationalMutationAuthorization,
    OperationalRecommendation,
    OperationalState,
    assess_operational_state,
)


DEFAULT_OPERATIONAL_LABELS = frozenset(
    spec.preferred_label
    for spec in DEFAULT_OPERATIONAL_LABEL_SPECS
)


def default_classifier(*extra_labels):
    return GmailLabelClassifier(
        operational_labels=frozenset(
            (*DEFAULT_OPERATIONAL_LABELS, *extra_labels)
        )
    )


def config_with_action_alias(alias):
    specs = tuple(
        OperationalLabelSpec(
            state=spec.state,
            preferred_label=spec.preferred_label,
            equivalent_labels=(
                (alias,)
                if spec.state is OperationalState.ACTION
                else spec.equivalent_labels
            ),
        )
        for spec in DEFAULT_OPERATIONAL_LABEL_SPECS
    )
    return OperationalLayerConfig(label_specs=specs)


class OperationalStateTests(unittest.TestCase):
    def test_operational_evidence_is_part_of_public_package_api(self):
        from semantic_mail_archivist import (
            OperationalEvidence as PublicOperationalEvidence,
        )

        self.assertIs(
            PublicOperationalEvidence,
            OperationalEvidence,
        )

    def test_synthetic_examples_cover_every_initial_state(self):
        fixtures = (
            (
                OperationalState.ACTION,
                MessageSnapshot(
                    "m-action",
                    normalized_subject="Action required: please review",
                ),
                (),
            ),
            (
                OperationalState.WAITING,
                MessageSnapshot(
                    "m-waiting",
                    normalized_subject="Awaiting reply from vendor",
                ),
                (),
            ),
            (
                OperationalState.DEADLINE,
                MessageSnapshot(
                    "m-deadline",
                    normalized_subject="Submission deadline",
                ),
                (),
            ),
            (
                OperationalState.REFERENCE,
                MessageSnapshot(
                    "m-reference",
                    normalized_subject="For reference: architecture notes",
                ),
                (),
            ),
        )

        classifier = default_classifier()

        for expected_state, message, documents in fixtures:
            with self.subTest(state=expected_state.value):
                result = assess_operational_state(
                    message,
                    classifier,
                    document_candidates=documents,
                )
                self.assertIn(expected_state, result.proposed_states)
                self.assertEqual(
                    result.recommendation,
                    OperationalRecommendation.PROPOSE_OPERATIONAL_STATE,
                )

        document_message = MessageSnapshot(
            "m-document",
            has_attachment=True,
            normalized_subject="Renewal material",
        )
        document = assess_document_significance(
            document_message,
            AttachmentSnapshot(
                "a-document",
                filename="insurance-policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(
            document.significance,
            DocumentSignificance.SIGNIFICANT_DOCUMENT,
        )

        document_result = assess_operational_state(
            document_message,
            classifier,
            document_candidates=(document,),
        )

        self.assertIn(
            OperationalState.DOCUMENT,
            document_result.proposed_states,
        )

    def test_semantic_labels_are_not_changed_by_operational_proposal(self):
        message = MessageSnapshot(
            "m-semantic",
            labels=("Work/Training",),
            normalized_subject="Action required: please review",
        )
        original_labels = message.labels

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        self.assertEqual(message.labels, original_labels)
        self.assertEqual(
            message.labels,
            ("Work/Training",),
        )
        self.assertIn(
            OperationalState.ACTION,
            result.proposed_states,
        )
        self.assertEqual(
            result.mutation_authorization,
            OperationalMutationAuthorization.DENIED,
        )
        self.assertEqual(
            result.execution_status,
            OperationalExecutionStatus.NOT_EXECUTED,
        )

    def test_existing_equivalent_operational_label_is_reused(self):
        config = config_with_action_alias("Todo")
        classifier = default_classifier("Todo")
        message = MessageSnapshot(
            "m-reuse",
            normalized_subject="Action required",
        )

        result = assess_operational_state(
            message,
            classifier,
            config=config,
            available_labels=("Todo",),
        )

        proposal = next(
            proposal
            for proposal in result.proposals
            if proposal.state is OperationalState.ACTION
        )

        self.assertEqual(proposal.label, "Todo")
        self.assertTrue(proposal.reuses_existing_label)
        self.assertFalse(proposal.requires_label_creation)

    def test_semantic_equivalent_label_is_not_silently_reused(self):
        config = config_with_action_alias("Todo")
        message = MessageSnapshot(
            "m-semantic-alias",
            normalized_subject="Action required",
        )

        result = assess_operational_state(
            message,
            default_classifier(),
            config=config,
            available_labels=("Todo",),
        )

        proposal = next(
            proposal
            for proposal in result.proposals
            if proposal.state is OperationalState.ACTION
        )

        self.assertEqual(proposal.label, "@Action")
        self.assertFalse(proposal.reuses_existing_label)
        self.assertTrue(proposal.requires_label_creation)

    def test_system_equivalent_label_is_not_reused(self):
        config = config_with_action_alias("IMPORTANT")
        message = MessageSnapshot(
            "m-system-alias",
            normalized_subject="Action required",
        )

        result = assess_operational_state(
            message,
            default_classifier(),
            config=config,
            available_labels=("IMPORTANT",),
        )

        proposal = next(
            proposal
            for proposal in result.proposals
            if proposal.state is OperationalState.ACTION
        )

        self.assertEqual(proposal.label, "@Action")
        self.assertFalse(proposal.reuses_existing_label)

    def test_existing_state_does_not_generate_duplicate_proposal(self):
        message = MessageSnapshot(
            "m-existing-action",
            labels=("@Action",),
            normalized_subject="Action required",
        )

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        self.assertEqual(
            result.current_states,
            (OperationalState.ACTION,),
        )
        self.assertEqual(result.proposals, ())
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.ALREADY_SATISFIED,
        )

    def test_incompatible_current_action_and_waiting_require_review(self):
        message = MessageSnapshot(
            "m-current-conflict",
            labels=("@Action", "@Waiting"),
        )

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        self.assertIn(
            OperationalConflict.INCOMPATIBLE_CURRENT_STATES,
            result.conflicts,
        )
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.REVIEW_REQUIRED,
        )

    def test_current_action_conflicting_with_proposed_waiting_requires_review(self):
        message = MessageSnapshot(
            "m-current-proposed-conflict",
            labels=("@Action",),
            normalized_subject="Awaiting reply from vendor",
        )

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        self.assertEqual(
            result.current_states,
            (OperationalState.ACTION,),
        )
        self.assertEqual(
            result.proposed_states,
            (OperationalState.WAITING,),
        )
        self.assertIn(
            OperationalConflict.CURRENT_STATE_CONFLICTS_WITH_PROPOSAL,
            result.conflicts,
        )
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.REVIEW_REQUIRED,
        )

    def test_inferred_action_and_waiting_are_detected_as_conflict(self):
        message = MessageSnapshot(
            "m-inferred-conflict",
            normalized_subject=(
                "Action required while awaiting reply"
            ),
        )

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        self.assertEqual(
            set(result.proposed_states),
            {
                OperationalState.ACTION,
                OperationalState.WAITING,
            },
        )
        self.assertIn(
            OperationalConflict.INCOMPATIBLE_PROPOSED_STATES,
            result.conflicts,
        )
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.REVIEW_REQUIRED,
        )

    def test_action_and_deadline_can_be_proposed_together(self):
        message = MessageSnapshot(
            "m-action-deadline",
            normalized_subject=(
                "Action required: submission deadline"
            ),
        )

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        self.assertEqual(
            set(result.proposed_states),
            {
                OperationalState.ACTION,
                OperationalState.DEADLINE,
            },
        )
        self.assertEqual(result.conflicts, ())
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.PROPOSE_OPERATIONAL_STATE,
        )

    def test_layer_can_be_disabled_entirely_without_consuming_inputs(self):
        def forbidden_documents():
            raise AssertionError("disabled layer consumed document input")
            yield

        def forbidden_labels():
            raise AssertionError("disabled layer consumed label input")
            yield

        result = assess_operational_state(
            MessageSnapshot(
                "m-disabled",
                normalized_subject="Action required",
            ),
            default_classifier(),
            config=OperationalLayerConfig(enabled=False),
            available_labels=forbidden_labels(),
            document_candidates=forbidden_documents(),
        )

        self.assertFalse(result.enabled)
        self.assertEqual(result.current_states, ())
        self.assertEqual(result.proposals, ())
        self.assertEqual(result.conflicts, ())
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.DISABLED,
        )

    def test_cross_message_document_candidate_is_rejected(self):
        source = MessageSnapshot(
            "m-document-source",
            normalized_subject="Insurance renewal",
        )
        document = assess_document_significance(
            source,
            AttachmentSnapshot(
                "a-document-source",
                filename="insurance-policy.pdf",
                mime_type="application/pdf",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "document_candidates must belong to the assessed message",
        ):
            assess_operational_state(
                MessageSnapshot("m-document-target"),
                default_classifier(),
                document_candidates=(document,),
            )

    def test_unmapped_current_operational_label_requires_review(self):
        message = MessageSnapshot(
            "m-unmapped",
            labels=("@CustomWorkflow",),
            normalized_subject="Action required",
        )

        result = assess_operational_state(
            message,
            default_classifier("@CustomWorkflow"),
        )

        self.assertEqual(
            result.unmapped_operational_labels,
            ("@CustomWorkflow",),
        )
        self.assertIn(
            OperationalConflict.UNMAPPED_CURRENT_OPERATIONAL_LABEL,
            result.conflicts,
        )
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.REVIEW_REQUIRED,
        )

    def test_generic_attachment_does_not_imply_document_state(self):
        message = MessageSnapshot(
            "m-generic-attachment",
            has_attachment=True,
            normalized_subject="Weekly update",
        )
        document = assess_document_significance(
            message,
            AttachmentSnapshot(
                "a-generic-attachment",
                filename="image.png",
                mime_type="image/png",
                disposition=AttachmentDisposition.ATTACHMENT,
            ),
        )

        self.assertEqual(
            document.significance,
            DocumentSignificance.GENERIC_ATTACHMENT,
        )

        result = assess_operational_state(
            message,
            default_classifier(),
            document_candidates=(document,),
        )

        self.assertNotIn(
            OperationalState.DOCUMENT,
            result.proposed_states,
        )

    def test_keyword_matching_does_not_use_arbitrary_substrings(self):
        message = MessageSnapshot(
            "m-substrings",
            normalized_subject=(
                "Interaction required in waitingroom "
                "deadlineish referenceable notes"
            ),
        )

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        self.assertEqual(result.proposals, ())
        self.assertEqual(
            result.recommendation,
            OperationalRecommendation.NO_PROPOSAL,
        )

    def test_configuration_rejects_one_label_mapped_to_two_states(self):
        specs = tuple(
            OperationalLabelSpec(
                state=spec.state,
                preferred_label=spec.preferred_label,
                equivalent_labels=(
                    ("Shared",)
                    if spec.state
                    in {
                        OperationalState.ACTION,
                        OperationalState.WAITING,
                    }
                    else ()
                ),
            )
            for spec in DEFAULT_OPERATIONAL_LABEL_SPECS
        )

        with self.assertRaisesRegex(
            ValueError,
            "cannot map to multiple states",
        ):
            OperationalLayerConfig(label_specs=specs)

    def test_evidence_does_not_echo_full_subject_or_private_suffix(self):
        subject = "Action required for Private Person 998877"
        message = MessageSnapshot(
            "m-private-evidence",
            normalized_subject=subject,
        )

        result = assess_operational_state(
            message,
            default_classifier(),
        )

        evidence = " ".join(
            item.detail
            for proposal in result.proposals
            for item in proposal.evidence
        )

        self.assertNotIn(subject, evidence)
        self.assertNotIn("Private Person", evidence)
        self.assertNotIn("998877", evidence)
        self.assertIn("action", evidence)


if __name__ == "__main__":
    unittest.main()
