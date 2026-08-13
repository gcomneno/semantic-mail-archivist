from __future__ import annotations

from dataclasses import dataclass
from email.utils import getaddresses
import time
from typing import Any, Callable, Protocol
from urllib.parse import quote

from .audit import ProviderLimitation
from .documents import (
    AttachmentDisposition,
    AttachmentSnapshot,
)
from .gmail_auth import (
    GmailAuthManager,
    GmailAuthSession,
    GmailAuthorizationMode,
)
from .provider import (
    ProviderDescriptor,
    ProviderErrorCode,
    ProviderIdentity,
    ProviderLabelKind,
    ProviderLabelSnapshot,
    ProviderMessageSnapshot,
    ProviderMessageState,
    ProviderOperationError,
    ProviderPage,
    ProviderReadCapabilities,
    ProviderReadCapability,
    ProviderThreadRef,
)


GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
GMAIL_MIME_MAX_DEPTH = 12

_METADATA_HEADERS = (
    "Subject",
    "From",
    "To",
    "Cc",
    "Reply-To",
)


def _mime_fields(depth: int) -> str:
    fields = [
        "partId",
        "mimeType",
        "filename",
        "body(attachmentId,size)",
    ]

    if depth > 0:
        fields.append(
            f"parts({_mime_fields(depth - 1)})"
        )

    return ",".join(fields)


GMAIL_MESSAGE_STRUCTURE_FIELDS = (
    "id,threadId,payload("
    + _mime_fields(GMAIL_MIME_MAX_DEPTH)
    + ")"
)

GMAIL_THREAD_METADATA_FIELDS = (
    "id,messages("
    "id,threadId,labelIds,"
    "payload(headers(name,value))"
    ")"
)


@dataclass(frozen=True)
class GmailReadRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError(
                "max_attempts must be positive"
            )

        if self.base_delay_seconds < 0:
            raise ValueError(
                "base_delay_seconds must be non-negative"
            )


class GmailReadTransport(Protocol):
    """Read-only Gmail transport surface."""

    def get_profile(self) -> dict[str, Any]:
        ...

    def list_labels(self) -> dict[str, Any]:
        ...

    def list_threads(
        self,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        ...

    def get_thread_metadata(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        ...

    def get_message_structure(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        ...

    def get_message_state(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        ...


_RATE_LIMIT_REASONS = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "dailyLimitExceeded",
    }
)


def _safe_error_for_http(
    status: int,
    reasons: frozenset[str],
) -> ProviderOperationError:
    if status == 401:
        return ProviderOperationError(
            ProviderErrorCode.AUTHENTICATION_REQUIRED,
            "Gmail rejected the local authentication state.",
        )

    if status == 403:
        if reasons & _RATE_LIMIT_REASONS:
            return ProviderOperationError(
                ProviderErrorCode.RATE_LIMITED,
                "Gmail rate limiting prevented the read operation.",
                retryable=True,
            )

        return ProviderOperationError(
            ProviderErrorCode.AUTHORIZATION_INSUFFICIENT,
            "Gmail authorization is insufficient for the read operation.",
        )

    if status == 404:
        return ProviderOperationError(
            ProviderErrorCode.NOT_FOUND,
            "The requested Gmail resource was not found.",
        )

    if status == 429:
        return ProviderOperationError(
            ProviderErrorCode.RATE_LIMITED,
            "Gmail rate limiting prevented the read operation.",
            retryable=True,
        )

    if status in {500, 502, 503, 504}:
        return ProviderOperationError(
            ProviderErrorCode.RETRYABLE_PROVIDER_FAILURE,
            "Gmail returned a temporary server failure.",
            retryable=True,
        )

    if status == 400:
        return ProviderOperationError(
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
            "Gmail rejected a read request as invalid.",
        )

    return ProviderOperationError(
        ProviderErrorCode.UNKNOWN_PROVIDER_FAILURE,
        "Gmail returned an unexpected read failure.",
    )


def _response_reasons(response: Any) -> frozenset[str]:
    try:
        payload = response.json()
    except Exception:
        return frozenset()

    if not isinstance(payload, dict):
        return frozenset()

    error = payload.get("error")

    if not isinstance(error, dict):
        return frozenset()

    entries = error.get("errors")

    if not isinstance(entries, list):
        return frozenset()

    reasons: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        reason = entry.get("reason")

        if isinstance(reason, str) and reason.strip():
            reasons.add(reason)

    return frozenset(reasons)


class GoogleGmailReadTransport:
    """Minimal Gmail REST client containing GET operations only."""

    def __init__(
        self,
        credentials: Any = None,
        *,
        authorized_session: Any = None,
        api_base_url: str = GMAIL_API_BASE_URL,
        retry_policy: GmailReadRetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        request_error_types: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        if authorized_session is None:
            if credentials is None:
                raise ValueError(
                    "credentials are required without an authorized session"
                )

            from google.auth.transport.requests import (
                AuthorizedSession,
            )
            from requests import RequestException

            authorized_session = AuthorizedSession(
                credentials
            )

            if request_error_types is None:
                request_error_types = (
                    RequestException,
                )

        self._session = authorized_session
        self._api_base_url = (
            api_base_url.rstrip("/")
        )
        self._retry = (
            retry_policy
            if retry_policy is not None
            else GmailReadRetryPolicy()
        )
        self._sleep = sleep
        self._request_error_types = (
            request_error_types
            if request_error_types is not None
            else (OSError,)
        )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._api_base_url + path

        last_error: ProviderOperationError | None = None

        for attempt in range(self._retry.max_attempts):
            try:
                response = self._session.get(
                    url,
                    params=params or {},
                    timeout=30,
                )
            except self._request_error_types:
                last_error = ProviderOperationError(
                    ProviderErrorCode.RETRYABLE_PROVIDER_FAILURE,
                    "A temporary network failure prevented the Gmail read.",
                    retryable=True,
                )
            else:
                status = int(
                    getattr(
                        response,
                        "status_code",
                        0,
                    )
                )

                if 200 <= status < 300:
                    try:
                        payload = response.json()
                    except Exception:
                        raise ProviderOperationError(
                            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
                            "Gmail returned unreadable JSON.",
                        ) from None

                    if not isinstance(payload, dict):
                        raise ProviderOperationError(
                            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
                            "Gmail returned an unexpected JSON shape.",
                        )

                    return payload

                last_error = _safe_error_for_http(
                    status,
                    _response_reasons(response),
                )

            if (
                last_error is not None
                and last_error.retryable
                and attempt + 1 < self._retry.max_attempts
            ):
                delay = (
                    self._retry.base_delay_seconds
                    * (2 ** attempt)
                )

                self._sleep(delay)
                continue

            assert last_error is not None
            raise last_error

        assert last_error is not None
        raise last_error

    def get_profile(self) -> dict[str, Any]:
        return self._get_json(
            "/users/me/profile",
            params={
                "fields": "emailAddress",
            },
        )

    def list_labels(self) -> dict[str, Any]:
        return self._get_json(
            "/users/me/labels",
            params={
                "fields": (
                    "labels("
                    "id,name,type,labelListVisibility"
                    ")"
                ),
            },
        )

    def list_threads(
        self,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "includeSpamTrash": True,
            "fields": (
                "threads(id),nextPageToken"
            ),
        }

        if page_token is not None:
            params["pageToken"] = page_token

        if page_size is not None:
            params["maxResults"] = page_size

        return self._get_json(
            "/users/me/threads",
            params=params,
        )

    def get_thread_metadata(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            (
                "/users/me/threads/"
                + quote(thread_id, safe="")
            ),
            params={
                "format": "metadata",
                "metadataHeaders": list(
                    _METADATA_HEADERS
                ),
                "fields": GMAIL_THREAD_METADATA_FIELDS,
            },
        )

    def get_message_structure(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            (
                "/users/me/messages/"
                + quote(message_id, safe="")
            ),
            params={
                "format": "full",
                "fields": (
                    GMAIL_MESSAGE_STRUCTURE_FIELDS
                ),
            },
        )

    def get_message_state(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            (
                "/users/me/messages/"
                + quote(message_id, safe="")
            ),
            params={
                "format": "full",
                "fields": (
                    "id,labelIds,historyId"
                ),
            },
        )


def _require_dict(
    value: Any,
    detail: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderOperationError(
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
            detail,
        )

    return value


def _require_list(
    value: Any,
    detail: str,
) -> list[Any]:
    if value is None:
        return []

    if not isinstance(value, list):
        raise ProviderOperationError(
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
            detail,
        )

    return value


def _required_string(
    value: Any,
    detail: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise ProviderOperationError(
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
            detail,
        )

    return value


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()

    return value or None


def _sorted_unique(
    values: list[str],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            set(values),
            key=lambda value: (
                value.casefold(),
                value,
            ),
        )
    )


def _header_facts(
    raw_message: dict[str, Any],
) -> tuple[str | None, tuple[str, ...], bool]:
    payload = raw_message.get("payload")

    if not isinstance(payload, dict):
        return None, (), False

    headers = payload.get("headers")

    if not isinstance(headers, list):
        return None, (), False

    selected: dict[str, list[str]] = {}

    for raw_header in headers:
        if not isinstance(raw_header, dict):
            continue

        name = raw_header.get("name")
        value = raw_header.get("value")

        if (
            not isinstance(name, str)
            or not isinstance(value, str)
        ):
            continue

        selected.setdefault(
            name.casefold(),
            [],
        ).append(value)

    subject_values = selected.get(
        "subject",
        [],
    )

    subject = (
        subject_values[0]
        if subject_values
        else None
    )

    address_values: list[str] = []

    for name in (
        "from",
        "to",
        "cc",
        "reply-to",
    ):
        address_values.extend(
            selected.get(name, [])
        )

    addresses = [
        address.strip()
        for _, address in getaddresses(
            address_values
        )
        if address.strip()
    ]

    return (
        subject,
        _sorted_unique(addresses),
        True,
    )


def _attachment_like(
    *,
    filename: str | None,
    attachment_id: str | None,
    mime_type: str | None,
    body_size: int,
) -> bool:
    if filename is not None:
        return True

    if attachment_id is not None:
        return True

    if body_size <= 0 or mime_type is None:
        return False

    normalized = mime_type.casefold()

    if normalized == "text/calendar":
        return True

    return normalized.startswith(
        (
            "application/",
            "audio/",
            "image/",
            "video/",
            "message/rfc822",
        )
    )


@dataclass(frozen=True)
class _MessageStructureFacts:
    attachments: tuple[AttachmentSnapshot, ...]
    potentially_incomplete: bool = False


def _message_structure_facts(
    message_id: str,
    raw_message: dict[str, Any],
) -> _MessageStructureFacts:
    payload = raw_message.get("payload")

    if not isinstance(payload, dict):
        return _MessageStructureFacts(
            attachments=(),
            potentially_incomplete=True,
        )

    attachments: list[AttachmentSnapshot] = []
    potentially_incomplete = False

    def visit(
        raw_part: Any,
        *,
        depth: int,
        path: tuple[int, ...],
    ) -> None:
        nonlocal potentially_incomplete

        part = _require_dict(
            raw_part,
            "Gmail returned an invalid MIME part.",
        )

        part_id = _optional_string(
            part.get("partId")
        )
        mime_type = _optional_string(
            part.get("mimeType")
        )
        filename = _optional_string(
            part.get("filename")
        )

        raw_body = part.get("body")

        if raw_body is None:
            body: dict[str, Any] = {}
        else:
            body = _require_dict(
                raw_body,
                "Gmail returned an invalid MIME body.",
            )

        attachment_id = _optional_string(
            body.get("attachmentId")
        )

        raw_size = body.get("size", 0)

        body_size = (
            raw_size
            if isinstance(raw_size, int)
            and not isinstance(raw_size, bool)
            and raw_size >= 0
            else 0
        )

        if _attachment_like(
            filename=filename,
            attachment_id=attachment_id,
            mime_type=mime_type,
            body_size=body_size,
        ):
            if attachment_id is not None:
                stable_id = attachment_id
            elif part_id is not None:
                stable_id = (
                    f"gmail-part:{part_id}"
                )
            else:
                stable_id = (
                    "gmail-part:"
                    + ".".join(
                        str(index)
                        for index in path
                    )
                )

            attachments.append(
                AttachmentSnapshot(
                    attachment_id=stable_id,
                    filename=filename,
                    mime_type=mime_type,
                    disposition=(
                        AttachmentDisposition.UNKNOWN
                    ),
                )
            )

        children = part.get("parts")

        if depth >= GMAIL_MIME_MAX_DEPTH:
            if (
                mime_type is not None
                and (
                    mime_type.casefold().startswith(
                        "multipart/"
                    )
                    or mime_type.casefold()
                    == "message/rfc822"
                )
            ):
                potentially_incomplete = True

            return

        for index, child in enumerate(
            _require_list(
                children,
                "Gmail returned an invalid MIME child-part list.",
            )
        ):
            visit(
                child,
                depth=depth + 1,
                path=(*path, index),
            )

    visit(
        payload,
        depth=0,
        path=(0,),
    )

    ids = [
        item.attachment_id
        for item in attachments
    ]

    if len(ids) != len(set(ids)):
        raise ProviderOperationError(
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
            "Gmail returned duplicate attachment identifiers within one message.",
        )

    return _MessageStructureFacts(
        attachments=tuple(attachments),
        potentially_incomplete=potentially_incomplete,
    )


class GmailReadAdapter:
    """ProviderReadAdapter implementation for Gmail.

    This class deliberately accepts READ_ONLY authorization only.
    """

    def __init__(
        self,
        auth_session: GmailAuthSession,
        *,
        account_safe_id: str,
        transport: GmailReadTransport | None = None,
    ) -> None:
        if (
            auth_session.mode
            is not GmailAuthorizationMode.READ_ONLY
        ):
            raise ValueError(
                "GmailReadAdapter requires READ_ONLY authorization"
            )

        if not account_safe_id.strip():
            raise ValueError(
                "account_safe_id cannot be empty"
            )

        self._identity = ProviderIdentity(
            provider="gmail",
            account_safe_id=account_safe_id,
        )

        self._transport = (
            transport
            if transport is not None
            else GoogleGmailReadTransport(
                auth_session.credentials
            )
        )

        self._limitations: dict[
            tuple[str, str],
            ProviderLimitation,
        ] = {}

        self._attachments_by_message: dict[
            str,
            tuple[AttachmentSnapshot, ...],
        ] = {}

    @classmethod
    def from_auth_manager(
        cls,
        auth_manager: GmailAuthManager,
        auth_session: GmailAuthSession,
        *,
        transport: GmailReadTransport | None = None,
    ) -> "GmailReadAdapter":
        """Resolve Gmail identity without retaining the raw account address."""

        if (
            auth_session.mode
            is not GmailAuthorizationMode.READ_ONLY
        ):
            raise ValueError(
                "GmailReadAdapter requires READ_ONLY authorization"
            )

        resolved_transport = (
            transport
            if transport is not None
            else GoogleGmailReadTransport(
                auth_session.credentials
            )
        )

        profile = resolved_transport.get_profile()

        email_address = _required_string(
            profile.get("emailAddress"),
            (
                "Gmail profile did not expose the authenticated "
                "account identifier."
            ),
        )

        account_safe_id = (
            auth_manager.account_safe_id(
                email_address
            )
        )

        return cls(
            auth_session,
            account_safe_id=account_safe_id,
            transport=resolved_transport,
        )

    def _record_limitation(
        self,
        code: str,
        detail: str,
    ) -> None:
        limitation = ProviderLimitation(
            code=code,
            detail=detail,
        )

        self._limitations[
            (code, detail)
        ] = limitation

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            identity=self._identity,
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
            limitations=tuple(
                self._limitations.values()
            ),
        )

    def list_labels(
        self,
    ) -> tuple[ProviderLabelSnapshot, ...]:
        payload = self._transport.list_labels()

        raw_labels = _require_list(
            payload.get("labels"),
            "Gmail returned an invalid label catalog.",
        )

        labels: list[ProviderLabelSnapshot] = []

        for raw_label in raw_labels:
            label = _require_dict(
                raw_label,
                "Gmail returned an invalid label record.",
            )

            label_id = _required_string(
                label.get("id"),
                "Gmail returned a label without an identifier.",
            )
            name = _required_string(
                label.get("name"),
                "Gmail returned a label without a display name.",
            )

            raw_type = label.get("type")

            if raw_type == "system":
                kind = (
                    ProviderLabelKind.PROVIDER_SYSTEM
                )
            elif raw_type == "user":
                kind = ProviderLabelKind.USER
            else:
                kind = ProviderLabelKind.UNKNOWN

                self._record_limitation(
                    "gmail_label_ownership_unknown",
                    (
                        "One or more Gmail labels had an "
                        "unrecognized ownership type."
                    ),
                )

            labels.append(
                ProviderLabelSnapshot(
                    label_id=label_id,
                    display_name=name,
                    kind=kind,
                    user_visible=(
                        label.get(
                            "labelListVisibility"
                        )
                        != "labelHide"
                    ),
                )
            )

        return tuple(
            sorted(
                labels,
                key=lambda item: (
                    item.display_name.casefold(),
                    item.display_name,
                    item.label_id,
                ),
            )
        )

    def list_threads(
        self,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
    ) -> ProviderPage[ProviderThreadRef]:
        if page_size is not None and not (
            1 <= page_size <= 500
        ):
            raise ValueError(
                "Gmail thread page_size must be between 1 and 500"
            )

        payload = self._transport.list_threads(
            page_token=page_token,
            page_size=page_size,
        )

        raw_threads = _require_list(
            payload.get("threads"),
            "Gmail returned an invalid thread page.",
        )

        refs = tuple(
            ProviderThreadRef(
                _required_string(
                    _require_dict(
                        item,
                        "Gmail returned an invalid thread reference.",
                    ).get("id"),
                    "Gmail returned a thread without an identifier.",
                )
            )
            for item in raw_threads
        )

        next_token = _optional_string(
            payload.get("nextPageToken")
        )

        return ProviderPage(
            refs,
            next_page_token=next_token,
        )

    def _structure_for_message(
        self,
        message_id: str,
    ) -> _MessageStructureFacts:
        raw = self._transport.get_message_structure(
            message_id
        )

        returned_id = _required_string(
            raw.get("id"),
            "Gmail returned message structure without an identifier.",
        )

        if returned_id != message_id:
            raise ProviderOperationError(
                ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
                "Gmail message structure identity did not match the request.",
            )

        facts = _message_structure_facts(
            message_id,
            raw,
        )

        self._attachments_by_message[
            message_id
        ] = facts.attachments

        if facts.potentially_incomplete:
            self._record_limitation(
                "gmail_mime_structure_depth_bounded",
                (
                    "One or more Gmail MIME structures exceeded "
                    "the bounded metadata traversal depth."
                ),
            )

        return facts

    def list_messages(
        self,
        thread_id: str,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
    ) -> ProviderPage[ProviderMessageSnapshot]:
        if page_token is not None:
            raise ProviderOperationError(
                ProviderErrorCode.UNSUPPORTED_CAPABILITY,
                (
                    "Gmail thread message enumeration is returned "
                    "as one thread resource and has no continuation token."
                ),
            )

        if page_size is not None:
            raise ProviderOperationError(
                ProviderErrorCode.UNSUPPORTED_CAPABILITY,
                (
                    "Gmail thread message enumeration does not "
                    "support a message page-size parameter."
                ),
            )

        raw_thread = (
            self._transport.get_thread_metadata(
                thread_id
            )
        )

        returned_thread_id = _required_string(
            raw_thread.get("id"),
            "Gmail returned a thread without an identifier.",
        )

        if returned_thread_id != thread_id:
            raise ProviderOperationError(
                ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
                "Gmail thread identity did not match the request.",
            )

        raw_messages = _require_list(
            raw_thread.get("messages"),
            "Gmail returned an invalid thread message collection.",
        )

        messages: list[ProviderMessageSnapshot] = []

        for raw_item in raw_messages:
            raw_message = _require_dict(
                raw_item,
                "Gmail returned an invalid message record.",
            )

            message_id = _required_string(
                raw_message.get("id"),
                "Gmail returned a message without an identifier.",
            )

            raw_message_thread_id = (
                _required_string(
                    raw_message.get("threadId"),
                    "Gmail returned a message without a thread identifier.",
                )
            )

            if raw_message_thread_id != thread_id:
                raise ProviderOperationError(
                    ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
                    "Gmail returned a message under the wrong thread.",
                )

            raw_label_ids = _require_list(
                raw_message.get("labelIds"),
                "Gmail returned invalid message label identifiers.",
            )

            label_ids = tuple(
                _required_string(
                    value,
                    "Gmail returned an empty message label identifier.",
                )
                for value in raw_label_ids
            )

            subject, correspondents, headers_complete = (
                _header_facts(raw_message)
            )

            if not headers_complete:
                self._record_limitation(
                    "gmail_message_headers_incomplete",
                    (
                        "One or more Gmail messages did not expose "
                        "the requested metadata headers."
                    ),
                )

            structure = (
                self._structure_for_message(
                    message_id
                )
            )

            has_attachment = (
                bool(structure.attachments)
                or structure.potentially_incomplete
            )

            messages.append(
                ProviderMessageSnapshot(
                    message_id=message_id,
                    label_ids=label_ids,
                    has_attachment=has_attachment,
                    subject=subject,
                    correspondents=correspondents,
                )
            )

        return ProviderPage(
            tuple(messages)
        )

    def list_attachments(
        self,
        message_id: str,
    ) -> tuple[AttachmentSnapshot, ...]:
        if message_id not in self._attachments_by_message:
            self._structure_for_message(
                message_id
            )

        return self._attachments_by_message[
            message_id
        ]

    def get_message_state(
        self,
        message_id: str,
    ) -> ProviderMessageState:
        raw = self._transport.get_message_state(
            message_id
        )

        returned_id = _required_string(
            raw.get("id"),
            "Gmail returned message state without an identifier.",
        )

        if returned_id != message_id:
            raise ProviderOperationError(
                ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
                "Gmail message-state identity did not match the request.",
            )

        raw_label_ids = _require_list(
            raw.get("labelIds"),
            "Gmail returned invalid message-state label identifiers.",
        )

        label_ids = tuple(
            _required_string(
                value,
                "Gmail returned an empty message-state label identifier.",
            )
            for value in raw_label_ids
        )

        history_id = _optional_string(
            raw.get("historyId")
        )

        if history_id is None:
            self._record_limitation(
                "gmail_message_revision_unavailable",
                (
                    "One or more Gmail message-state reads did "
                    "not expose a history identifier."
                ),
            )

        return ProviderMessageState(
            message_id=message_id,
            label_ids=label_ids,
            in_inbox="INBOX" in label_ids,
            in_trash="TRASH" in label_ids,
            provider_revision=(
                f"gmail-history:{history_id}"
                if history_id is not None
                else None
            ),
        )
