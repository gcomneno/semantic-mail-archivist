from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from .audit import ProviderLimitation
from .documents import AttachmentSnapshot


T = TypeVar("T")


def _require_nonempty(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")


class ProviderLabelKind(str, Enum):
    """Provider-level label ownership, not semantic classification."""

    PROVIDER_SYSTEM = "provider_system"
    USER = "user"
    UNKNOWN = "unknown"


class ProviderReadCapability(str, Enum):
    LIST_LABELS = "list_labels"
    LIST_THREADS = "list_threads"
    LIST_MESSAGES = "list_messages"
    ATTACHMENT_METADATA = "attachment_metadata"
    FRESH_MESSAGE_STATE = "fresh_message_state"


class ProviderWriteCapability(str, Enum):
    """Capability metadata only.

    Issue #24 deliberately defines no provider mutation methods.
    """

    ADD_LABEL = "add_label"
    REMOVE_LABEL = "remove_label"
    ARCHIVE = "archive"
    MOVE_TO_TRASH = "move_to_trash"
    RESTORE_FROM_TRASH = "restore_from_trash"


class ProviderErrorCode(str, Enum):
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHORIZATION_INSUFFICIENT = "authorization_insufficient"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    RETRYABLE_PROVIDER_FAILURE = "retryable_provider_failure"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    UNKNOWN_PROVIDER_FAILURE = "unknown_provider_failure"


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    account_safe_id: str

    def __post_init__(self) -> None:
        _require_nonempty("provider", self.provider)
        _require_nonempty("account_safe_id", self.account_safe_id)


@dataclass(frozen=True)
class ProviderLabelSnapshot:
    """Provider facts about one visible label.

    `kind` distinguishes provider-managed/system labels from user-owned labels.
    It does not decide whether a user label is semantic or operational.
    """

    label_id: str
    display_name: str
    kind: ProviderLabelKind = ProviderLabelKind.UNKNOWN
    user_visible: bool = True

    def __post_init__(self) -> None:
        _require_nonempty("label_id", self.label_id)
        _require_nonempty("display_name", self.display_name)


@dataclass(frozen=True)
class ProviderThreadRef:
    thread_id: str

    def __post_init__(self) -> None:
        _require_nonempty("thread_id", self.thread_id)


@dataclass(frozen=True)
class ProviderMessageSnapshot:
    """Provider facts for one message before core translation.

    Label identifiers are provider-stable identifiers, not semantic labels.
    This type deliberately exposes no semantic_label_hints field.
    """

    message_id: str
    label_ids: tuple[str, ...] = ()
    has_attachment: bool = False
    subject: str | None = None
    correspondents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty("message_id", self.message_id)

        label_ids = tuple(
            sorted(
                set(self.label_ids),
                key=lambda value: (value.casefold(), value),
            )
        )
        if any(not value.strip() for value in label_ids):
            raise ValueError("label_ids cannot contain empty values")

        correspondents = tuple(
            value
            for value in self.correspondents
            if value.strip()
        )

        object.__setattr__(self, "label_ids", label_ids)
        object.__setattr__(self, "correspondents", correspondents)


@dataclass(frozen=True)
class ProviderMessageState:
    """Fresh provider state for later mutation preflight.

    Labels are provider-visible label names. Semantic interpretation remains
    outside the adapter.
    """

    message_id: str
    label_ids: tuple[str, ...] = ()
    in_inbox: bool | None = None
    in_trash: bool | None = None
    provider_revision: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty("message_id", self.message_id)

        normalized_label_ids = tuple(
            sorted(
                set(self.label_ids),
                key=lambda value: (value.casefold(), value),
            )
        )
        if any(not value.strip() for value in normalized_label_ids):
            raise ValueError("label_ids cannot contain empty values")

        if self.in_inbox is True and self.in_trash is True:
            raise ValueError(
                "a provider message state cannot be both in inbox and trash"
            )

        if self.provider_revision is not None:
            _require_nonempty(
                "provider_revision",
                self.provider_revision,
            )

        object.__setattr__(self, "label_ids", normalized_label_ids)


@dataclass(frozen=True)
class ProviderReadCapabilities:
    supported: frozenset[ProviderReadCapability] = frozenset()

    def supports(self, capability: ProviderReadCapability) -> bool:
        return capability in self.supported


@dataclass(frozen=True)
class ProviderWriteCapabilities:
    """Write capability discovery only; this type grants no authorization."""

    supported: frozenset[ProviderWriteCapability] = frozenset()

    def supports(self, capability: ProviderWriteCapability) -> bool:
        return capability in self.supported


@dataclass(frozen=True)
class ProviderDescriptor:
    identity: ProviderIdentity
    read_capabilities: ProviderReadCapabilities
    write_capabilities: ProviderWriteCapabilities = (
        ProviderWriteCapabilities()
    )
    limitations: tuple[ProviderLimitation, ...] = ()

    def __post_init__(self) -> None:
        limitations = tuple(
            sorted(
                self.limitations,
                key=lambda limitation: (
                    limitation.code,
                    limitation.detail,
                ),
            )
        )
        object.__setattr__(self, "limitations", limitations)


@dataclass(frozen=True)
class ProviderPage(Generic[T]):
    """One provider page with an opaque continuation token."""

    items: tuple[T, ...]
    next_page_token: str | None = None

    def __post_init__(self) -> None:
        if self.next_page_token is not None:
            _require_nonempty(
                "next_page_token",
                self.next_page_token,
            )


class ProviderOperationError(RuntimeError):
    """Redacted provider error suitable for local product handling."""

    def __init__(
        self,
        code: ProviderErrorCode,
        safe_detail: str,
        *,
        retryable: bool = False,
    ) -> None:
        _require_nonempty("safe_detail", safe_detail)

        self.code = code
        self.safe_detail = safe_detail
        self.retryable = retryable

        super().__init__(f"{code.value}: {safe_detail}")


@runtime_checkable
class ProviderReadAdapter(Protocol):
    """Provider-neutral read surface.

    Implementations expose provider facts only. They must not perform semantic
    classification, confidence decisions, mutation authorization, or writes.
    """

    def descriptor(self) -> ProviderDescriptor:
        ...

    def list_labels(self) -> tuple[ProviderLabelSnapshot, ...]:
        ...

    def list_threads(
        self,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
    ) -> ProviderPage[ProviderThreadRef]:
        ...

    def list_messages(
        self,
        thread_id: str,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
    ) -> ProviderPage[ProviderMessageSnapshot]:
        ...

    def list_attachments(
        self,
        message_id: str,
    ) -> tuple[AttachmentSnapshot, ...]:
        ...

    def get_message_state(
        self,
        message_id: str,
    ) -> ProviderMessageState:
        ...
