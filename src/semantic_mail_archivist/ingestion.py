from __future__ import annotations

from dataclasses import dataclass

from .audit import ProviderLimitation
from .documents import AttachmentSnapshot
from .model import (
    LabelClass,
    LabelClassifier,
    MessageSnapshot,
    ThreadSnapshot,
)
from .provider import (
    ProviderDescriptor,
    ProviderErrorCode,
    ProviderLabelKind,
    ProviderLabelSnapshot,
    ProviderOperationError,
    ProviderReadAdapter,
)


def _nonempty(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")


def _sorted_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            set(values),
            key=lambda value: (value.casefold(), value),
        )
    )


def _normalized_subject(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = " ".join(value.split())
    return normalized or None


def _unknown_label_name(label_id: str) -> str:
    return f"[provider-label-id:{label_id}]"


def _merge_limitations(
    *groups: tuple[ProviderLimitation, ...],
) -> tuple[ProviderLimitation, ...]:
    values = {
        (limitation.code, limitation.detail): limitation
        for group in groups
        for limitation in group
    }

    return tuple(
        values[key]
        for key in sorted(values)
    )


@dataclass(frozen=True)
class IngestedMessageAttachments:
    message_id: str
    attachments: tuple[AttachmentSnapshot, ...]

    def __post_init__(self) -> None:
        _nonempty("message_id", self.message_id)

        attachment_ids = [
            attachment.attachment_id
            for attachment in self.attachments
        ]

        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError(
                "attachment_id must be unique within a message"
            )


@dataclass(frozen=True)
class MailboxIngestionResult:
    """Provider-neutral facts prepared for the core analysis layers."""

    descriptor: ProviderDescriptor
    labels: tuple[ProviderLabelSnapshot, ...]
    threads: tuple[ThreadSnapshot, ...]
    message_attachments: tuple[IngestedMessageAttachments, ...]
    provider_limitations: tuple[ProviderLimitation, ...]
    complete: bool

    @property
    def available_labels(self) -> tuple[str, ...]:
        return _sorted_unique(
            tuple(
                label.display_name
                for label in self.labels
            )
        )

    @property
    def provider_system_labels(self) -> tuple[str, ...]:
        return _sorted_unique(
            tuple(
                label.display_name
                for label in self.labels
                if label.kind is ProviderLabelKind.PROVIDER_SYSTEM
            )
        )

    @property
    def user_labels(self) -> tuple[str, ...]:
        return _sorted_unique(
            tuple(
                label.display_name
                for label in self.labels
                if label.kind is ProviderLabelKind.USER
            )
        )

    @property
    def attachments_by_message(
        self,
    ) -> dict[str, tuple[AttachmentSnapshot, ...]]:
        return {
            item.message_id: item.attachments
            for item in self.message_attachments
        }

    def audit_inputs(self) -> dict[str, object]:
        """Return the provider-derived arguments accepted by build_mailbox_audit.

        The semantic classifier remains intentionally absent: ingestion does
        not decide the user's taxonomy.
        """

        return {
            "threads": self.threads,
            "attachments_by_message": self.attachments_by_message,
            "available_labels": self.available_labels,
            "provider_limitations": self.provider_limitations,
        }


class ProviderAwareLabelClassifier:
    """Protect provider ownership while delegating user-label semantics.

    Provider-managed labels are always SYSTEM. User labels are classified by
    the caller's taxonomy classifier. Unknown provider ownership fails closed
    as UNKNOWN.
    """

    def __init__(
        self,
        labels: tuple[ProviderLabelSnapshot, ...],
        user_classifier: LabelClassifier,
    ) -> None:
        by_name: dict[str, ProviderLabelKind] = {}

        for label in labels:
            previous = by_name.get(label.display_name)

            if previous is not None and previous is not label.kind:
                raise ValueError(
                    "one provider label name cannot have conflicting ownership"
                )

            by_name[label.display_name] = label.kind

        self._by_name = by_name
        self._user_classifier = user_classifier

    def classify(self, label: str) -> LabelClass:
        kind = self._by_name.get(label)

        if kind is ProviderLabelKind.PROVIDER_SYSTEM:
            return LabelClass.SYSTEM

        if kind is ProviderLabelKind.USER:
            classification = self._user_classifier.classify(label)

            # Provider ownership is stronger evidence than a caller accidentally
            # classifying a user-owned label as a provider system label.
            if classification is LabelClass.SYSTEM:
                return LabelClass.UNKNOWN

            return classification

        return LabelClass.UNKNOWN


def _invalid_provider(detail: str) -> ProviderOperationError:
    return ProviderOperationError(
        ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
        detail,
    )


def ingest_provider_mailbox(
    provider: ProviderReadAdapter,
    *,
    max_threads: int | None = None,
    thread_page_size: int | None = None,
) -> MailboxIngestionResult:
    """Collect provider facts and translate them into existing core snapshots.

    `max_threads=None` traverses the complete provider thread enumeration.
    A positive bound is intended for development/road-test runs and is surfaced
    explicitly as an incomplete ingestion whenever more provider data exists.
    """

    if max_threads is not None and max_threads <= 0:
        raise ValueError("max_threads must be positive")

    if thread_page_size is not None and thread_page_size <= 0:
        raise ValueError("thread_page_size must be positive")

    labels = tuple(
        sorted(
            provider.list_labels(),
            key=lambda label: (
                label.display_name.casefold(),
                label.display_name,
                label.label_id,
            ),
        )
    )

    labels_by_id: dict[str, ProviderLabelSnapshot] = {}

    for label in labels:
        if label.label_id in labels_by_id:
            raise _invalid_provider(
                "Provider returned a duplicate label identifier."
            )
        labels_by_id[label.label_id] = label

    threads: list[ThreadSnapshot] = []
    message_attachments: list[IngestedMessageAttachments] = []
    dynamic_limitations: list[ProviderLimitation] = []

    seen_thread_ids: set[str] = set()
    seen_message_ids: set[str] = set()
    seen_thread_tokens: set[str] = set()

    thread_token: str | None = None
    incomplete = False

    while True:
        thread_page = provider.list_threads(
            page_token=thread_token,
            page_size=thread_page_size,
        )

        for thread_index, thread_ref in enumerate(thread_page.items):
            if max_threads is not None and len(threads) >= max_threads:
                incomplete = True
                break

            if thread_ref.thread_id in seen_thread_ids:
                raise _invalid_provider(
                    "Provider returned a duplicate thread identifier."
                )

            seen_thread_ids.add(thread_ref.thread_id)

            core_messages: list[MessageSnapshot] = []
            seen_message_tokens: set[str] = set()
            message_token: str | None = None

            while True:
                message_page = provider.list_messages(
                    thread_ref.thread_id,
                    page_token=message_token,
                )

                for provider_message in message_page.items:
                    if provider_message.message_id in seen_message_ids:
                        raise _invalid_provider(
                            "Provider returned a duplicate message identifier."
                        )

                    seen_message_ids.add(
                        provider_message.message_id
                    )

                    translated_labels: list[str] = []

                    for label_id in provider_message.label_ids:
                        label = labels_by_id.get(label_id)

                        if label is None:
                            translated_labels.append(
                                _unknown_label_name(label_id)
                            )
                            dynamic_limitations.append(
                                ProviderLimitation(
                                    code="provider_label_catalog_incomplete",
                                    detail=(
                                        "One or more message label identifiers "
                                        "were absent from the provider label "
                                        "catalog."
                                    ),
                                )
                            )
                        else:
                            translated_labels.append(
                                label.display_name
                            )

                    attachments = tuple(
                        provider.list_attachments(
                            provider_message.message_id
                        )
                    )

                    if (
                        not provider_message.has_attachment
                        and attachments
                    ):
                        raise _invalid_provider(
                            "Provider attachment metadata conflicts with the "
                            "message attachment flag."
                        )

                    if (
                        provider_message.has_attachment
                        and not attachments
                    ):
                        dynamic_limitations.append(
                            ProviderLimitation(
                                code="provider_attachment_metadata_incomplete",
                                detail=(
                                    "One or more messages indicate attachments "
                                    "but complete attachment metadata was not "
                                    "available."
                                ),
                            )
                        )
                    elif attachments:
                        message_attachments.append(
                            IngestedMessageAttachments(
                                message_id=provider_message.message_id,
                                attachments=attachments,
                            )
                        )

                    core_messages.append(
                        MessageSnapshot(
                            message_id=provider_message.message_id,
                            labels=_sorted_unique(
                                tuple(translated_labels)
                            ),
                            has_attachment=(
                                provider_message.has_attachment
                            ),
                            normalized_subject=_normalized_subject(
                                provider_message.subject
                            ),
                            correspondents=provider_message.correspondents,
                        )
                    )

                next_message_token = (
                    message_page.next_page_token
                )

                if next_message_token is None:
                    break

                if next_message_token in seen_message_tokens:
                    raise _invalid_provider(
                        "Provider repeated a message continuation token."
                    )

                seen_message_tokens.add(
                    next_message_token
                )
                message_token = next_message_token

            threads.append(
                ThreadSnapshot(
                    thread_id=thread_ref.thread_id,
                    messages=tuple(core_messages),
                )
            )

            if (
                max_threads is not None
                and len(threads) >= max_threads
            ):
                if (
                    thread_index < len(thread_page.items) - 1
                    or thread_page.next_page_token is not None
                ):
                    incomplete = True
                break

        if incomplete:
            break

        next_thread_token = thread_page.next_page_token

        if next_thread_token is None:
            break

        if next_thread_token in seen_thread_tokens:
            raise _invalid_provider(
                "Provider repeated a thread continuation token."
            )

        seen_thread_tokens.add(next_thread_token)
        thread_token = next_thread_token

    if incomplete:
        dynamic_limitations.append(
            ProviderLimitation(
                code="bounded_mailbox_selection",
                detail=(
                    "Mailbox ingestion was intentionally bounded before the "
                    "provider thread enumeration was complete."
                ),
            )
        )

    descriptor = provider.descriptor()

    limitations = _merge_limitations(
        descriptor.limitations,
        tuple(dynamic_limitations),
    )

    return MailboxIngestionResult(
        descriptor=descriptor,
        labels=labels,
        threads=tuple(threads),
        message_attachments=tuple(message_attachments),
        provider_limitations=limitations,
        complete=not incomplete,
    )
