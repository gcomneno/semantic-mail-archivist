from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any

from .change_log import (
    MutationAction,
    MutationExecutionMode,
    MutationInitiator,
    MutationResultStatus,
    mutation_class_for_action,
)
from .provider import ProviderMessageState
from .reporting import MutationClass


MUTATION_JOURNAL_SCHEMA_VERSION = "1.0"


class MutationJournalEventType(str, Enum):
    INTENT = "intent"
    FINALIZATION = "finalization"


class MutationRecoveryObservation(str, Enum):
    """What fresh provider state says about an interrupted attempt.

    These observations are facts for reconciliation. None of them is itself a
    mutation-result authorization or a proof that this process caused the
    observed provider state.
    """

    PREVIOUS_STATE_OBSERVED = "previous_state_observed"
    REQUESTED_STATE_OBSERVED = "requested_state_observed"
    DIVERGENT_STATE_OBSERVED = "divergent_state_observed"


class MutationJournalCorruptionError(ValueError):
    """Raised when durable journal history before the final line is invalid."""


def _require_nonempty(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")


def _require_aware_timestamp(
    timestamp: datetime,
) -> None:
    if (
        timestamp.tzinfo is None
        or timestamp.utcoffset() is None
    ):
        raise ValueError(
            "journal timestamp must be timezone-aware"
        )


def _provider_state_to_dict(
    state: ProviderMessageState,
) -> dict[str, Any]:
    return {
        "message_id": state.message_id,
        "label_ids": list(state.label_ids),
        "in_inbox": state.in_inbox,
        "in_trash": state.in_trash,
        "provider_revision": state.provider_revision,
    }


def _provider_state_from_dict(
    payload: object,
) -> ProviderMessageState:
    if not isinstance(payload, dict):
        raise ValueError(
            "provider state must be an object"
        )

    expected = {
        "message_id",
        "label_ids",
        "in_inbox",
        "in_trash",
        "provider_revision",
    }

    if set(payload) != expected:
        raise ValueError(
            "provider state has an unexpected shape"
        )

    label_ids = payload["label_ids"]

    if (
        not isinstance(label_ids, list)
        or any(
            not isinstance(value, str)
            for value in label_ids
        )
    ):
        raise ValueError(
            "provider state label_ids must be strings"
        )

    message_id = payload["message_id"]
    provider_revision = payload["provider_revision"]

    if not isinstance(message_id, str):
        raise ValueError(
            "provider state message_id must be a string"
        )

    if (
        provider_revision is not None
        and not isinstance(provider_revision, str)
    ):
        raise ValueError(
            "provider revision must be a string or null"
        )

    in_inbox = payload["in_inbox"]
    in_trash = payload["in_trash"]

    if (
        in_inbox is not None
        and not isinstance(in_inbox, bool)
    ):
        raise ValueError(
            "in_inbox must be boolean or null"
        )

    if (
        in_trash is not None
        and not isinstance(in_trash, bool)
    ):
        raise ValueError(
            "in_trash must be boolean or null"
        )

    return ProviderMessageState(
        message_id=message_id,
        label_ids=tuple(label_ids),
        in_inbox=in_inbox,
        in_trash=in_trash,
        provider_revision=provider_revision,
    )


@dataclass(frozen=True)
class MutationAttemptIntent:
    """Durable fact recorded before any future provider mutation call."""

    attempt_id: str
    timestamp: datetime
    provider: str
    account_safe_id: str
    message_id: str
    action: MutationAction
    mutation_class: MutationClass
    provider_before_state: ProviderMessageState
    provider_requested_state: ProviderMessageState
    initiator: MutationInitiator
    execution_mode: MutationExecutionMode
    target_label: str | None = None
    dry_run_correlation_id: str | None = None
    schema_version: str = MUTATION_JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("attempt_id", self.attempt_id),
            ("provider", self.provider),
            ("account_safe_id", self.account_safe_id),
            ("message_id", self.message_id),
        ):
            _require_nonempty(name, value)

        _require_aware_timestamp(self.timestamp)

        if (
            self.mutation_class
            is not mutation_class_for_action(self.action)
        ):
            raise ValueError(
                "journal mutation_class does not match action"
            )

        if (
            self.provider_before_state.message_id
            != self.message_id
            or self.provider_requested_state.message_id
            != self.message_id
        ):
            raise ValueError(
                "provider states must belong to the journal message"
            )

        if (
            self.provider_before_state
            == self.provider_requested_state
        ):
            raise ValueError(
                "journal intent requires a real requested provider transition"
            )

        label_action = self.action in {
            MutationAction.ADD_LABEL,
            MutationAction.REMOVE_LABEL,
        }

        if label_action:
            if self.target_label is None:
                raise ValueError(
                    "label mutation intent requires target_label"
                )
            _require_nonempty(
                "target_label",
                self.target_label,
            )
        elif self.target_label is not None:
            raise ValueError(
                "target_label is only valid for label mutations"
            )

        if self.dry_run_correlation_id is not None:
            _require_nonempty(
                "dry_run_correlation_id",
                self.dry_run_correlation_id,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event": MutationJournalEventType.INTENT.value,
            "attempt_id": self.attempt_id,
            "timestamp": self.timestamp.isoformat(),
            "provider": self.provider,
            "account_safe_id": self.account_safe_id,
            "message_id": self.message_id,
            "action": self.action.value,
            "mutation_class": self.mutation_class.value,
            "target_label": self.target_label,
            "provider_before_state": _provider_state_to_dict(
                self.provider_before_state
            ),
            "provider_requested_state": _provider_state_to_dict(
                self.provider_requested_state
            ),
            "initiator": self.initiator.value,
            "execution_mode": self.execution_mode.value,
            "dry_run_correlation_id": (
                self.dry_run_correlation_id
            ),
        }


@dataclass(frozen=True)
class MutationAttemptFinalization:
    """Durable terminal marker linked to the finalized change-log record.

    `audit_record_id` deliberately equals `attempt_id`. A future write workflow
    must use that same value as ChangeAuditRecord.record_id, preserving the
    existing change-log schema while sharing one attributable identity.
    """

    attempt_id: str
    timestamp: datetime
    result: MutationResultStatus
    audit_record_id: str
    schema_version: str = MUTATION_JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(
            "attempt_id",
            self.attempt_id,
        )
        _require_nonempty(
            "audit_record_id",
            self.audit_record_id,
        )
        _require_aware_timestamp(self.timestamp)

        if self.audit_record_id != self.attempt_id:
            raise ValueError(
                "audit_record_id must equal attempt_id"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event": (
                MutationJournalEventType
                .FINALIZATION
                .value
            ),
            "attempt_id": self.attempt_id,
            "timestamp": self.timestamp.isoformat(),
            "result": self.result.value,
            "audit_record_id": self.audit_record_id,
        }


@dataclass(frozen=True)
class MutationJournalAttempt:
    intent: MutationAttemptIntent
    finalization: MutationAttemptFinalization | None = None

    @property
    def interrupted(self) -> bool:
        return self.finalization is None


@dataclass(frozen=True)
class MutationJournalLoadResult:
    attempts: tuple[MutationJournalAttempt, ...]
    trailing_corruption: bool = False

    @property
    def interrupted_attempts(
        self,
    ) -> tuple[MutationJournalAttempt, ...]:
        return tuple(
            attempt
            for attempt in self.attempts
            if attempt.interrupted
        )


def _same_observable_provider_state(
    left: ProviderMessageState,
    right: ProviderMessageState,
) -> bool:
    """Compare provider state without requiring a matching revision token.

    A revision is evidence about freshness/order, not part of the requested
    mailbox transition itself. A future write cannot know the provider's
    post-mutation revision in advance.
    """

    return (
        left.message_id == right.message_id
        and left.label_ids == right.label_ids
        and left.in_inbox == right.in_inbox
        and left.in_trash == right.in_trash
    )


def reconcile_interrupted_attempt(
    attempt: MutationJournalAttempt,
    fresh_state: ProviderMessageState,
) -> MutationRecoveryObservation:
    """Compare an interrupted attempt with fresh provider state.

    The result is observational only. In particular,
    REQUESTED_STATE_OBSERVED must not be interpreted as proof that the
    interrupted provider call succeeded or as authority to finalize/replay it.
    """

    if not attempt.interrupted:
        raise ValueError(
            "only interrupted attempts require reconciliation"
        )

    if fresh_state.message_id != attempt.intent.message_id:
        raise ValueError(
            "fresh provider state belongs to another message"
        )

    if _same_observable_provider_state(
        fresh_state,
        attempt.intent.provider_before_state,
    ):
        return (
            MutationRecoveryObservation
            .PREVIOUS_STATE_OBSERVED
        )

    if _same_observable_provider_state(
        fresh_state,
        attempt.intent.provider_requested_state,
    ):
        return (
            MutationRecoveryObservation
            .REQUESTED_STATE_OBSERVED
        )

    return (
        MutationRecoveryObservation
        .DIVERGENT_STATE_OBSERVED
    )


def _render_event(
    event: MutationAttemptIntent
    | MutationAttemptFinalization,
) -> bytes:
    return (
        json.dumps(
            event.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _ensure_private_directory(
    path: Path,
) -> bool:
    if path.exists():
        if not path.is_dir():
            raise ValueError(
                "journal parent path is not a directory"
            )
        if os.name == "posix":
            os.chmod(path, 0o700)
        return False

    path.mkdir(
        parents=True,
        mode=0o700,
    )

    if os.name == "posix":
        os.chmod(path, 0o700)

    return True


def _fsync_directory(
    path: Path,
) -> None:
    if os.name != "posix":
        return

    fd = os.open(
        path,
        os.O_RDONLY,
    )
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _append_event_durably(
    path: Path,
    event: MutationAttemptIntent
    | MutationAttemptFinalization,
) -> None:
    parent_created = _ensure_private_directory(
        path.parent
    )
    existed = path.exists()
    payload = _render_event(event)

    fd = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_APPEND,
        0o600,
    )

    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)

        total = 0

        while total < len(payload):
            written = os.write(
                fd,
                payload[total:],
            )
            if written <= 0:
                raise OSError(
                    "journal append made no progress"
                )
            total += written

        os.fsync(fd)

    finally:
        os.close(fd)

    if not existed or parent_created:
        _fsync_directory(
            path.parent
        )


def _parse_timestamp(
    value: object,
) -> datetime:
    if not isinstance(value, str):
        raise ValueError(
            "journal timestamp must be a string"
        )

    timestamp = datetime.fromisoformat(value)
    _require_aware_timestamp(timestamp)
    return timestamp


def _parse_intent(
    payload: dict[str, Any],
) -> MutationAttemptIntent:
    return MutationAttemptIntent(
        attempt_id=str(payload["attempt_id"]),
        timestamp=_parse_timestamp(
            payload["timestamp"]
        ),
        provider=str(payload["provider"]),
        account_safe_id=str(
            payload["account_safe_id"]
        ),
        message_id=str(payload["message_id"]),
        action=MutationAction(
            payload["action"]
        ),
        mutation_class=MutationClass(
            payload["mutation_class"]
        ),
        target_label=(
            None
            if payload["target_label"] is None
            else str(payload["target_label"])
        ),
        provider_before_state=_provider_state_from_dict(
            payload["provider_before_state"]
        ),
        provider_requested_state=_provider_state_from_dict(
            payload["provider_requested_state"]
        ),
        initiator=MutationInitiator(
            payload["initiator"]
        ),
        execution_mode=MutationExecutionMode(
            payload["execution_mode"]
        ),
        dry_run_correlation_id=(
            None
            if payload["dry_run_correlation_id"] is None
            else str(
                payload["dry_run_correlation_id"]
            )
        ),
        schema_version=str(
            payload["schema_version"]
        ),
    )


def _parse_finalization(
    payload: dict[str, Any],
) -> MutationAttemptFinalization:
    return MutationAttemptFinalization(
        attempt_id=str(payload["attempt_id"]),
        timestamp=_parse_timestamp(
            payload["timestamp"]
        ),
        result=MutationResultStatus(
            payload["result"]
        ),
        audit_record_id=str(
            payload["audit_record_id"]
        ),
        schema_version=str(
            payload["schema_version"]
        ),
    )


def _decode_event(
    line: str,
) -> MutationAttemptIntent | MutationAttemptFinalization:
    payload = json.loads(line)

    if not isinstance(payload, dict):
        raise ValueError(
            "journal event must be a JSON object"
        )

    if (
        payload.get("schema_version")
        != MUTATION_JOURNAL_SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported mutation journal schema"
        )

    event = payload.get("event")

    if event == MutationJournalEventType.INTENT.value:
        return _parse_intent(payload)

    if (
        event
        == MutationJournalEventType.FINALIZATION.value
    ):
        return _parse_finalization(payload)

    raise ValueError(
        "unknown mutation journal event type"
    )


class MutationJournal:
    """Append-only local mutation-attempt journal."""

    def __init__(
        self,
        path: str | Path,
    ) -> None:
        self.path = Path(path)

    def load(
        self,
    ) -> MutationJournalLoadResult:
        if not self.path.exists():
            return MutationJournalLoadResult(
                attempts=(),
            )

        raw = self.path.read_text(
            encoding="utf-8"
        )

        if not raw:
            return MutationJournalLoadResult(
                attempts=(),
            )

        lines = raw.splitlines()
        trailing_corruption = not raw.endswith("\n")
        events: list[
            MutationAttemptIntent
            | MutationAttemptFinalization
        ] = []

        for index, line in enumerate(lines):
            if not line.strip():
                raise MutationJournalCorruptionError(
                    "journal contains an empty record"
                )

            if (
                trailing_corruption
                and index == len(lines) - 1
            ):
                break

            try:
                events.append(
                    _decode_event(line)
                )
            except (
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                if index == len(lines) - 1:
                    trailing_corruption = True
                    break

                raise MutationJournalCorruptionError(
                    "journal history is corrupt before its final record"
                ) from exc

        attempts_by_id: dict[
            str,
            MutationJournalAttempt,
        ] = {}
        order: list[str] = []

        for event in events:
            if isinstance(
                event,
                MutationAttemptIntent,
            ):
                if event.attempt_id in attempts_by_id:
                    raise MutationJournalCorruptionError(
                        "journal contains duplicate attempt intent"
                    )

                attempts_by_id[event.attempt_id] = (
                    MutationJournalAttempt(
                        intent=event,
                    )
                )
                order.append(event.attempt_id)
                continue

            attempt = attempts_by_id.get(
                event.attempt_id
            )

            if attempt is None:
                raise MutationJournalCorruptionError(
                    "journal finalization has no matching intent"
                )

            if attempt.finalization is not None:
                raise MutationJournalCorruptionError(
                    "journal attempt is finalized more than once"
                )

            attempts_by_id[event.attempt_id] = (
                MutationJournalAttempt(
                    intent=attempt.intent,
                    finalization=event,
                )
            )

        return MutationJournalLoadResult(
            attempts=tuple(
                attempts_by_id[attempt_id]
                for attempt_id in order
            ),
            trailing_corruption=trailing_corruption,
        )

    def append_intent(
        self,
        intent: MutationAttemptIntent,
    ) -> None:
        current = self.load()

        if current.trailing_corruption:
            raise MutationJournalCorruptionError(
                "cannot append while journal has trailing corruption"
            )

        if any(
            attempt.intent.attempt_id
            == intent.attempt_id
            for attempt in current.attempts
        ):
            raise ValueError(
                "attempt_id is already present in journal"
            )

        _append_event_durably(
            self.path,
            intent,
        )

    def append_finalization(
        self,
        finalization: MutationAttemptFinalization,
    ) -> None:
        current = self.load()

        if current.trailing_corruption:
            raise MutationJournalCorruptionError(
                "cannot finalize while journal has trailing corruption"
            )

        matching = [
            attempt
            for attempt in current.attempts
            if (
                attempt.intent.attempt_id
                == finalization.attempt_id
            )
        ]

        if not matching:
            raise ValueError(
                "cannot finalize an unknown attempt"
            )

        attempt = matching[0]

        if attempt.finalization is not None:
            raise ValueError(
                "attempt is already finalized"
            )

        _append_event_durably(
            self.path,
            finalization,
        )
