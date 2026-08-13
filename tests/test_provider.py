import unittest

from semantic_mail_archivist import (
    AttachmentSnapshot,
    LabelClass,
    MessageSnapshot,
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
    ProviderReadAdapter,
    ProviderReadCapabilities,
    ProviderReadCapability,
    ProviderThreadRef,
    ProviderWriteCapabilities,
    ProviderWriteCapability,
    ThreadSnapshot,
    build_mailbox_audit,
)


class SyntheticClassifier:
    def classify(self, label: str) -> LabelClass:
        if label in {"INBOX", "SENT", "TRASH"}:
            return LabelClass.SYSTEM
        if label.startswith("@"):
            return LabelClass.USER_OPERATIONAL
        return LabelClass.USER_SEMANTIC


class FakeProvider:
    def __init__(self):
        self._descriptor = ProviderDescriptor(
            identity=ProviderIdentity(
                provider="synthetic",
                account_safe_id="acct-safe-001",
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
                    code="synthetic_partial_metadata",
                    detail="One synthetic provider fact is unavailable.",
                ),
            ),
        )

        self._threads = {
            "t-1": (
                ProviderMessageSnapshot(
                    "m-1",
                    label_ids=("user-alpha",),
                ),
                ProviderMessageSnapshot(
                    "m-2",
                    label_ids=("system-inbox",),
                ),
            ),
            "t-2": (
                ProviderMessageSnapshot(
                    "m-3",
                    label_ids=("user-beta",),
                ),
            ),
        }

    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def list_labels(self) -> tuple[ProviderLabelSnapshot, ...]:
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
        )

    def list_threads(
        self,
        *,
        page_token=None,
        page_size=None,
    ):
        if page_token is None:
            return ProviderPage(
                (ProviderThreadRef("t-1"),),
                next_page_token="page-2",
            )
        if page_token == "page-2":
            return ProviderPage((ProviderThreadRef("t-2"),))
        raise ProviderOperationError(
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
            "Unknown synthetic page token.",
        )

    def list_messages(
        self,
        thread_id,
        *,
        page_token=None,
        page_size=None,
    ):
        messages = self._threads[thread_id]
        if thread_id == "t-1" and page_token is None:
            return ProviderPage(
                (messages[0],),
                next_page_token="message-page-2",
            )
        if thread_id == "t-1" and page_token == "message-page-2":
            return ProviderPage((messages[1],))
        return ProviderPage(tuple(messages))

    def list_attachments(self, message_id):
        if message_id == "m-2":
            return (AttachmentSnapshot("a-1"),)
        return ()

    def get_message_state(self, message_id):
        message = next(
            message
            for values in self._threads.values()
            for message in values
            if message.message_id == message_id
        )
        return ProviderMessageState(
            message_id=message.message_id,
            label_ids=message.label_ids,
            in_inbox="system-inbox" in message.label_ids,
            in_trash="system-trash" in message.label_ids,
            provider_revision=f"rev-{message.message_id}",
        )


def collect_provider_threads(provider):
    result = []
    page_token = None

    while True:
        page = provider.list_threads(page_token=page_token)

        for thread_ref in page.items:
            messages = []
            message_token = None

            while True:
                message_page = provider.list_messages(
                    thread_ref.thread_id,
                    page_token=message_token,
                )
                messages.extend(message_page.items)

                if message_page.next_page_token is None:
                    break
                message_token = message_page.next_page_token

            result.append(
                (thread_ref.thread_id, tuple(messages))
            )

        if page.next_page_token is None:
            break
        page_token = page.next_page_token

    return tuple(result)


def translate_to_core_threads(provider):
    """Synthetic stand-in for the ingestion layer implemented by #26."""

    labels_by_id = {
        label.label_id: label.display_name
        for label in provider.list_labels()
    }

    return tuple(
        ThreadSnapshot(
            thread_id,
            tuple(
                MessageSnapshot(
                    message.message_id,
                    labels=tuple(
                        labels_by_id[label_id]
                        for label_id in message.label_ids
                    ),
                    has_attachment=message.has_attachment,
                    normalized_subject=message.subject,
                    correspondents=message.correspondents,
                )
                for message in messages
            ),
        )
        for thread_id, messages in collect_provider_threads(provider)
    )


class ProviderContractTests(unittest.TestCase):
    def test_provider_identity_requires_safe_nonempty_fields(self):
        with self.assertRaisesRegex(ValueError, "provider cannot be empty"):
            ProviderIdentity("", "acct-safe")

        with self.assertRaisesRegex(
            ValueError,
            "account_safe_id cannot be empty",
        ):
            ProviderIdentity("synthetic", "")

    def test_provider_label_kind_does_not_encode_semantic_policy(self):
        self.assertEqual(
            {item.value for item in ProviderLabelKind},
            {"provider_system", "user", "unknown"},
        )
        self.assertNotIn(
            "user_semantic",
            {item.value for item in ProviderLabelKind},
        )
        self.assertNotIn(
            "user_operational",
            {item.value for item in ProviderLabelKind},
        )

    def test_read_and_write_capabilities_are_separate(self):
        read = ProviderReadCapabilities(
            frozenset({ProviderReadCapability.LIST_THREADS})
        )
        write = ProviderWriteCapabilities(
            frozenset({ProviderWriteCapability.ADD_LABEL})
        )

        self.assertTrue(
            read.supports(ProviderReadCapability.LIST_THREADS)
        )
        self.assertFalse(
            read.supports(ProviderReadCapability.LIST_MESSAGES)
        )
        self.assertTrue(
            write.supports(ProviderWriteCapability.ADD_LABEL)
        )

    def test_read_adapter_has_no_mutation_methods(self):
        protocol_members = set(ProviderReadAdapter.__dict__)

        for method in (
            "add_label",
            "remove_label",
            "archive",
            "move_to_trash",
            "delete",
        ):
            self.assertNotIn(method, protocol_members)

    def test_fake_provider_satisfies_runtime_read_protocol(self):
        self.assertIsInstance(FakeProvider(), ProviderReadAdapter)

    def test_provider_page_rejects_empty_continuation_token(self):
        with self.assertRaisesRegex(
            ValueError,
            "next_page_token cannot be empty",
        ):
            ProviderPage((), next_page_token="")

    def test_provider_message_snapshot_exposes_facts_not_semantic_hints(self):
        message = ProviderMessageSnapshot(
            "m-raw",
            label_ids=("label-2", "label-1"),
            subject="Synthetic subject",
            correspondents=("sender@example.test",),
        )

        self.assertEqual(
            message.label_ids,
            ("label-1", "label-2"),
        )
        self.assertNotIn(
            "semantic_label_hints",
            ProviderMessageSnapshot.__dataclass_fields__,
        )
        self.assertNotIn(
            "labels",
            ProviderMessageSnapshot.__dataclass_fields__,
        )

    def test_fresh_state_uses_stable_provider_label_ids_not_names(self):
        provider = FakeProvider()

        before = provider.get_message_state("m-1")
        renamed_label = ProviderLabelSnapshot(
            label_id="user-alpha",
            display_name="Projects/Renamed",
            kind=ProviderLabelKind.USER,
        )

        self.assertEqual(
            before.label_ids,
            ("user-alpha",),
        )
        self.assertEqual(
            renamed_label.label_id,
            "user-alpha",
        )
        self.assertNotEqual(
            renamed_label.display_name,
            "Projects/Alpha",
        )

    def test_provider_message_state_is_deterministic(self):
        state = ProviderMessageState(
            "m-1",
            label_ids=("Zeta", "Alpha", "Zeta"),
            in_inbox=True,
            in_trash=False,
            provider_revision="rev-1",
        )

        self.assertEqual(
            state.label_ids,
            ("Alpha", "Zeta"),
        )

    def test_provider_message_state_rejects_impossible_placement(self):
        with self.assertRaisesRegex(
            ValueError,
            "both in inbox and trash",
        ):
            ProviderMessageState(
                "m-1",
                in_inbox=True,
                in_trash=True,
            )

    def test_provider_error_is_redacted_structured_failure(self):
        error = ProviderOperationError(
            ProviderErrorCode.RATE_LIMITED,
            "Provider request should be retried later.",
            retryable=True,
        )

        self.assertEqual(
            error.code,
            ProviderErrorCode.RATE_LIMITED,
        )
        self.assertTrue(error.retryable)
        self.assertEqual(
            error.safe_detail,
            "Provider request should be retried later.",
        )

    def test_fake_provider_pages_threads_and_messages(self):
        threads = collect_provider_threads(FakeProvider())

        self.assertEqual(
            tuple(thread_id for thread_id, _ in threads),
            ("t-1", "t-2"),
        )
        self.assertEqual(
            tuple(
                message.message_id
                for message in threads[0][1]
            ),
            ("m-1", "m-2"),
        )

    def test_attachment_surface_returns_metadata_only(self):
        attachments = FakeProvider().list_attachments("m-2")

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].attachment_id, "a-1")
        self.assertFalse(
            hasattr(attachments[0], "content")
        )

    def test_fresh_state_lookup_is_read_only_provider_fact(self):
        state = FakeProvider().get_message_state("m-2")

        self.assertEqual(state.message_id, "m-2")
        self.assertEqual(state.label_ids, ("system-inbox",))
        self.assertTrue(state.in_inbox)
        self.assertFalse(state.in_trash)
        self.assertEqual(state.provider_revision, "rev-m-2")

    def test_provider_limitations_flow_into_existing_audit(self):
        provider = FakeProvider()
        threads = translate_to_core_threads(provider)
        descriptor = provider.descriptor()

        report = build_mailbox_audit(
            threads,
            SyntheticClassifier(),
            provider_limitations=descriptor.limitations,
        )

        self.assertEqual(
            report.summary.provider_limitations,
            1,
        )
        self.assertEqual(
            report.provider_limitations[0].code,
            "synthetic_partial_metadata",
        )

    def test_write_capability_metadata_grants_no_write_surface(self):
        descriptor = ProviderDescriptor(
            identity=ProviderIdentity(
                provider="synthetic",
                account_safe_id="acct-safe-002",
            ),
            read_capabilities=ProviderReadCapabilities(),
            write_capabilities=ProviderWriteCapabilities(
                frozenset(
                    {ProviderWriteCapability.ADD_LABEL}
                )
            ),
        )

        self.assertTrue(
            descriptor.write_capabilities.supports(
                ProviderWriteCapability.ADD_LABEL
            )
        )
        self.assertFalse(
            hasattr(descriptor, "add_label")
        )


if __name__ == "__main__":
    unittest.main()
