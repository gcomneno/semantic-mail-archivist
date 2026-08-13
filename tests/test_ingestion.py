import unittest

from semantic_mail_archivist import (
    AttachmentSnapshot,
    IngestedMessageAttachments,
    LabelClass,
    MailboxIngestionResult,
    MessageSnapshot,
    ProviderAwareLabelClassifier,
    ProviderDescriptor,
    ProviderErrorCode,
    ProviderIdentity,
    ProviderLabelKind,
    ProviderLabelSnapshot,
    ProviderLimitation,
    ProviderMessageSnapshot,
    ProviderMessageState,
    ProviderOperationError,
    ProviderPage,
    ProviderReadCapabilities,
    ProviderReadCapability,
    ProviderThreadRef,
    ThreadSnapshot,
    ingest_provider_mailbox,
)


class UserClassifier:
    def classify(self, label: str) -> LabelClass:
        if label.startswith("@"):
            return LabelClass.USER_OPERATIONAL
        if label == "Bad/System":
            return LabelClass.SYSTEM
        return LabelClass.USER_SEMANTIC


class SyntheticPagedProvider:
    def __init__(self):
        self.attachment_overrides = {}
        self.thread_pages = {
            None: ProviderPage(
                (
                    ProviderThreadRef("t-1"),
                    ProviderThreadRef("t-2"),
                ),
                next_page_token="threads-2",
            ),
            "threads-2": ProviderPage(
                (ProviderThreadRef("t-3"),)
            ),
        }

        self.message_pages = {
            ("t-1", None): ProviderPage(
                (
                    ProviderMessageSnapshot(
                        message_id="m-1",
                        label_ids=("user-alpha",),
                        subject="  Project   Alpha  ",
                        correspondents=("alpha@example.test",),
                    ),
                ),
                next_page_token="messages-2",
            ),
            ("t-1", "messages-2"): ProviderPage(
                (
                    ProviderMessageSnapshot(
                        message_id="m-2",
                        label_ids=("system-inbox", "missing-label"),
                        has_attachment=True,
                    ),
                )
            ),
            ("t-2", None): ProviderPage(
                (
                    ProviderMessageSnapshot(
                        message_id="m-3",
                        label_ids=("user-operational",),
                    ),
                )
            ),
            ("t-3", None): ProviderPage(
                (
                    ProviderMessageSnapshot(
                        message_id="m-4",
                        label_ids=("user-beta",),
                    ),
                )
            ),
        }

        self.attachments = {
            "m-2": (
                AttachmentSnapshot(
                    attachment_id="a-1",
                    filename="contract.pdf",
                    mime_type="application/pdf",
                ),
            ),
        }

    def descriptor(self):
        return ProviderDescriptor(
            identity=ProviderIdentity(
                provider="synthetic",
                account_safe_id="acct-safe",
            ),
            read_capabilities=ProviderReadCapabilities(
                frozenset(
                    {
                        ProviderReadCapability.LIST_LABELS,
                        ProviderReadCapability.LIST_THREADS,
                        ProviderReadCapability.LIST_MESSAGES,
                        ProviderReadCapability.ATTACHMENT_METADATA,
                        ProviderReadCapability.FRESH_MESSAGE_STATE,
                    }
                )
            ),
            limitations=(
                ProviderLimitation(
                    code="synthetic_limitation",
                    detail="Synthetic provider limitation.",
                ),
            ),
        )

    def list_labels(self):
        return (
            ProviderLabelSnapshot(
                label_id="system-inbox",
                display_name="INBOX",
                kind=ProviderLabelKind.PROVIDER_SYSTEM,
            ),
            ProviderLabelSnapshot(
                label_id="user-alpha",
                display_name="Projects/Alpha",
                kind=ProviderLabelKind.USER,
            ),
            ProviderLabelSnapshot(
                label_id="user-beta",
                display_name="Projects/Beta",
                kind=ProviderLabelKind.USER,
            ),
            ProviderLabelSnapshot(
                label_id="user-operational",
                display_name="@Waiting",
                kind=ProviderLabelKind.USER,
            ),
            ProviderLabelSnapshot(
                label_id="bad-system",
                display_name="Bad/System",
                kind=ProviderLabelKind.USER,
            ),
        )

    def list_threads(
        self,
        *,
        page_token=None,
        page_size=None,
    ):
        return self.thread_pages[page_token]

    def list_messages(
        self,
        thread_id,
        *,
        page_token=None,
        page_size=None,
    ):
        return self.message_pages[(thread_id, page_token)]

    def list_attachments(self, message_id):
        if message_id in self.attachment_overrides:
            return self.attachment_overrides[message_id]
        return self.attachments.get(message_id, ())

    def get_message_state(self, message_id):
        return ProviderMessageState(message_id)


class IngestionTests(unittest.TestCase):
    def test_multi_page_provider_translates_to_core_snapshots(self):
        result = ingest_provider_mailbox(
            SyntheticPagedProvider()
        )

        self.assertTrue(result.complete)
        self.assertEqual(
            tuple(thread.thread_id for thread in result.threads),
            ("t-1", "t-2", "t-3"),
        )

        self.assertEqual(
            tuple(
                message.message_id
                for thread in result.threads
                for message in thread.messages
            ),
            ("m-1", "m-2", "m-3", "m-4"),
        )

        first = result.threads[0].messages[0]

        self.assertEqual(
            first.normalized_subject,
            "Project Alpha",
        )
        self.assertEqual(
            first.labels,
            ("Projects/Alpha",),
        )
        self.assertEqual(
            first.correspondents,
            ("alpha@example.test",),
        )

    def test_system_and_user_label_catalogs_remain_separate(self):
        result = ingest_provider_mailbox(
            SyntheticPagedProvider()
        )

        self.assertEqual(
            result.provider_system_labels,
            ("INBOX",),
        )
        self.assertEqual(
            result.user_labels,
            (
                "@Waiting",
                "Bad/System",
                "Projects/Alpha",
                "Projects/Beta",
            ),
        )

    def test_provider_aware_classifier_never_promotes_system_label(self):
        provider = SyntheticPagedProvider()
        labels = provider.list_labels()

        classifier = ProviderAwareLabelClassifier(
            labels,
            UserClassifier(),
        )

        self.assertIs(
            classifier.classify("INBOX"),
            LabelClass.SYSTEM,
        )
        self.assertIs(
            classifier.classify("Projects/Alpha"),
            LabelClass.USER_SEMANTIC,
        )
        self.assertIs(
            classifier.classify("@Waiting"),
            LabelClass.USER_OPERATIONAL,
        )

        # A caller cannot turn a provider-owned user label into SYSTEM.
        self.assertIs(
            classifier.classify("Bad/System"),
            LabelClass.UNKNOWN,
        )

        self.assertIs(
            classifier.classify("not-in-catalog"),
            LabelClass.UNKNOWN,
        )

    def test_unknown_provider_label_id_is_preserved_as_unknown_fact(self):
        result = ingest_provider_mailbox(
            SyntheticPagedProvider()
        )

        message = result.threads[0].messages[1]

        self.assertIn(
            "[provider-label-id:missing-label]",
            message.labels,
        )

        self.assertTrue(
            any(
                limitation.code
                == "provider_label_catalog_incomplete"
                for limitation in result.provider_limitations
            )
        )

    def test_attachment_metadata_is_exposed_without_content_bytes(self):
        result = ingest_provider_mailbox(
            SyntheticPagedProvider()
        )

        attachments = result.attachments_by_message["m-2"]

        self.assertEqual(len(attachments), 1)
        self.assertEqual(
            attachments[0].attachment_id,
            "a-1",
        )
        self.assertEqual(
            attachments[0].filename,
            "contract.pdf",
        )
        self.assertFalse(
            hasattr(attachments[0], "content")
        )
        self.assertFalse(
            hasattr(attachments[0], "data")
        )

    def test_audit_inputs_match_existing_mailbox_audit_surface(self):
        result = ingest_provider_mailbox(
            SyntheticPagedProvider()
        )

        inputs = result.audit_inputs()

        self.assertEqual(
            set(inputs),
            {
                "threads",
                "attachments_by_message",
                "available_labels",
                "provider_limitations",
            },
        )
        self.assertEqual(
            inputs["threads"],
            result.threads,
        )
        self.assertEqual(
            inputs["attachments_by_message"],
            result.attachments_by_message,
        )

    def test_bounded_selection_is_explicitly_incomplete(self):
        result = ingest_provider_mailbox(
            SyntheticPagedProvider(),
            max_threads=2,
        )

        self.assertFalse(result.complete)
        self.assertEqual(
            tuple(thread.thread_id for thread in result.threads),
            ("t-1", "t-2"),
        )
        self.assertTrue(
            any(
                limitation.code == "bounded_mailbox_selection"
                for limitation in result.provider_limitations
            )
        )

    def test_complete_selection_does_not_add_bounded_limitation(self):
        result = ingest_provider_mailbox(
            SyntheticPagedProvider()
        )

        self.assertTrue(result.complete)
        self.assertFalse(
            any(
                limitation.code == "bounded_mailbox_selection"
                for limitation in result.provider_limitations
            )
        )

    def test_message_attachment_flag_conflict_fails_closed(self):
        provider = SyntheticPagedProvider()
        provider.message_pages[("t-2", None)] = ProviderPage(
            (
                ProviderMessageSnapshot(
                    message_id="m-3",
                    label_ids=("user-operational",),
                    has_attachment=False,
                ),
            )
        )
        provider.attachment_overrides["m-3"] = (
            AttachmentSnapshot("unexpected"),
        )

        with self.assertRaises(
            ProviderOperationError
        ) as context:
            ingest_provider_mailbox(provider)

        self.assertEqual(
            context.exception.code,
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
        )

    def test_missing_attachment_metadata_becomes_limitation(self):
        provider = SyntheticPagedProvider()
        provider.attachment_overrides["m-2"] = ()

        result = ingest_provider_mailbox(provider)

        self.assertTrue(
            result.threads[0].messages[1].has_attachment
        )
        self.assertNotIn(
            "m-2",
            result.attachments_by_message,
        )
        self.assertTrue(
            any(
                limitation.code
                == "provider_attachment_metadata_incomplete"
                for limitation in result.provider_limitations
            )
        )

    def test_duplicate_thread_id_fails_closed(self):
        provider = SyntheticPagedProvider()
        provider.thread_pages["threads-2"] = ProviderPage(
            (ProviderThreadRef("t-1"),)
        )

        with self.assertRaises(
            ProviderOperationError
        ) as context:
            ingest_provider_mailbox(provider)

        self.assertEqual(
            context.exception.code,
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
        )

    def test_repeated_thread_token_fails_closed(self):
        provider = SyntheticPagedProvider()
        provider.thread_pages["threads-2"] = ProviderPage(
            (),
            next_page_token="threads-2",
        )

        with self.assertRaises(
            ProviderOperationError
        ) as context:
            ingest_provider_mailbox(provider)

        self.assertEqual(
            context.exception.code,
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
        )

    def test_invalid_selection_bounds_are_rejected(self):
        provider = SyntheticPagedProvider()

        with self.assertRaises(ValueError):
            ingest_provider_mailbox(
                provider,
                max_threads=0,
            )

        with self.assertRaises(ValueError):
            ingest_provider_mailbox(
                provider,
                thread_page_size=0,
            )

    def test_ingested_attachment_group_rejects_duplicate_ids(self):
        with self.assertRaises(ValueError):
            IngestedMessageAttachments(
                message_id="m-1",
                attachments=(
                    AttachmentSnapshot("same"),
                    AttachmentSnapshot("same"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
