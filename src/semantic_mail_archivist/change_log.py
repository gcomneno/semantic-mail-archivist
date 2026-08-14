from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

from .model import ConfidenceBand
from .reporting import (
    SCHEMA_VERSION as DRY_RUN_SCHEMA_VERSION,
    DryRunCandidateReport,
    MutationClass,
    PlannedAction,
)


CHANGE_LOG_SCHEMA_VERSION = "1.0"


class MutationAction(str, Enum):
    ADD_LABEL = "add_label"
    REMOVE_LABEL = "remove_label"
    ARCHIVE = "archive"
    RESTORE_TO_INBOX = "restore_to_inbox"
    MOVE_TO_TRASH = "move_to_trash"
    RESTORE_FROM_TRASH = "restore_from_trash"


class MutationResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_FAILURE = "partial_failure"
    DENIED = "denied"


class MutationInitiator(str, Enum):
    USER = "user"
    AUTOMATION = "automation"
    SYSTEM = "system"


class MutationExecutionMode(str, Enum):
    EXPLICIT_WRITE = "explicit_write"
    DEDICATED_CLEANUP_WRITE = "dedicated_cleanup_write"
    ROLLBACK = "rollback"


class SafetyGateDecision(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


_ACTION_MUTATION_CLASS = {
    MutationAction.ADD_LABEL: MutationClass.M1,
    MutationAction.REMOVE_LABEL: MutationClass.M2,
    MutationAction.ARCHIVE: MutationClass.M3,
    MutationAction.RESTORE_TO_INBOX: MutationClass.M3,
    MutationAction.MOVE_TO_TRASH: MutationClass.M4,
    MutationAction.RESTORE_FROM_TRASH: MutationClass.M3,
}


_ROLLBACK_ACTION = {
    MutationAction.ADD_LABEL: MutationAction.REMOVE_LABEL,
    MutationAction.REMOVE_LABEL: MutationAction.ADD_LABEL,
    MutationAction.ARCHIVE: MutationAction.RESTORE_TO_INBOX,
    MutationAction.RESTORE_TO_INBOX: MutationAction.ARCHIVE,
    MutationAction.MOVE_TO_TRASH: MutationAction.RESTORE_FROM_TRASH,
    MutationAction.RESTORE_FROM_TRASH: MutationAction.MOVE_TO_TRASH,
}


def mutation_class_for_action(
    action: MutationAction,
) -> MutationClass:
    """Return the canonical mutation class owned by the change-log contract."""

    return _ACTION_MUTATION_CLASS[action]


def _require_nonempty(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")


def _confidence_band(score: float) -> ConfidenceBand:
    if score >= 0.90:
        return ConfidenceBand.HIGH
    if score >= 0.60:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def _validate_requested_transition(
    action: MutationAction,
    target_label: str | None,
    previous: "MailboxStateSnapshot",
    requested: "MailboxStateSnapshot",
) -> None:
    previous_labels = set(previous.user_labels)
    requested_labels = set(requested.user_labels)

    if action is MutationAction.ADD_LABEL:
        assert target_label is not None
        expected_labels = previous_labels | {target_label}
        if (
            target_label in previous_labels
            or requested_labels != expected_labels
            or requested.in_inbox != previous.in_inbox
            or requested.in_trash != previous.in_trash
        ):
            raise ValueError(
                "ADD_LABEL requested state must add exactly target_label "
                "without changing placement"
            )
        return

    if action is MutationAction.REMOVE_LABEL:
        assert target_label is not None
        expected_labels = previous_labels - {target_label}
        if (
            target_label not in previous_labels
            or requested_labels != expected_labels
            or requested.in_inbox != previous.in_inbox
            or requested.in_trash != previous.in_trash
        ):
            raise ValueError(
                "REMOVE_LABEL requested state must remove exactly "
                "target_label without changing placement"
            )
        return

    if requested_labels != previous_labels:
        raise ValueError(
            f"{action.value} requested state cannot change user labels"
        )

    if action is MutationAction.ARCHIVE:
        if (
            previous.in_inbox is not True
            or requested.in_inbox is not False
            or requested.in_trash != previous.in_trash
        ):
            raise ValueError(
                "ARCHIVE requested state must move a known Inbox message "
                "out of Inbox without changing Trash state"
            )
        return

    if action is MutationAction.RESTORE_TO_INBOX:
        if (
            previous.in_inbox is not False
            or requested.in_inbox is not True
            or requested.in_trash != previous.in_trash
        ):
            raise ValueError(
                "RESTORE_TO_INBOX requested state must restore a known "
                "non-Inbox message to Inbox"
            )
        return

    if action is MutationAction.MOVE_TO_TRASH:
        if (
            previous.in_trash is not False
            or requested.in_trash is not True
            or requested.in_inbox is not False
        ):
            raise ValueError(
                "MOVE_TO_TRASH requested state must move a known "
                "non-Trash message to Trash and out of Inbox"
            )
        return

    if action is MutationAction.RESTORE_FROM_TRASH:
        if (
            previous.in_trash is not True
            or requested.in_trash is not False
        ):
            raise ValueError(
                "RESTORE_FROM_TRASH requested state must restore a known "
                "Trash message out of Trash"
            )
        return

    raise ValueError(f"unsupported mutation action: {action.value}")


@dataclass(frozen=True)
class MailboxStateSnapshot:
    user_labels: tuple[str, ...] = ()
    in_inbox: bool | None = None
    in_trash: bool | None = None

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                set(self.user_labels),
                key=lambda value: (value.casefold(), value),
            )
        )
        if any(not label.strip() for label in normalized):
            raise ValueError("user_labels cannot contain empty labels")
        if self.in_inbox is True and self.in_trash is True:
            raise ValueError(
                "a state snapshot cannot be both in inbox and in trash"
            )
        object.__setattr__(self, "user_labels", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_labels": list(self.user_labels),
            "in_inbox": self.in_inbox,
            "in_trash": self.in_trash,
        }


@dataclass(frozen=True)
class ChangeEvidence:
    signal: str
    detail: str
    contribution: float

    def __post_init__(self) -> None:
        _require_nonempty("evidence signal", self.signal)
        _require_nonempty("evidence detail", self.detail)
        if not math.isfinite(self.contribution):
            raise ValueError("evidence contribution must be finite")

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "detail": self.detail,
            "contribution": self.contribution,
        }


@dataclass(frozen=True)
class SafetyGateRecord:
    gate: str
    decision: SafetyGateDecision
    detail: str

    def __post_init__(self) -> None:
        _require_nonempty("safety gate", self.gate)
        _require_nonempty("safety gate detail", self.detail)

    def to_dict(self) -> dict[str, str]:
        return {
            "gate": self.gate,
            "decision": self.decision.value,
            "detail": self.detail,
        }


def correlation_id_for_dry_run(
    candidate: DryRunCandidateReport,
) -> str:
    """Derive a stable reference from the complete dry-run candidate record."""

    payload = json.dumps(
        candidate.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = sha256(
        (
            DRY_RUN_SCHEMA_VERSION
            + "\0"
            + payload
        ).encode("utf-8")
    ).hexdigest()
    return f"dryrun:{DRY_RUN_SCHEMA_VERSION}:{digest}"


@dataclass(frozen=True)
class DryRunProposalReference:
    correlation_id: str
    dry_run_schema_version: str
    thread_id: str
    message_id: str
    planned_action: PlannedAction
    mutation_class: MutationClass
    proposed_label: str | None
    confidence_score: float
    confidence_band: ConfidenceBand

    @classmethod
    def from_candidate(
        cls,
        candidate: DryRunCandidateReport,
    ) -> DryRunProposalReference:
        return cls(
            correlation_id=correlation_id_for_dry_run(candidate),
            dry_run_schema_version=DRY_RUN_SCHEMA_VERSION,
            thread_id=candidate.thread_id,
            message_id=candidate.message_id,
            planned_action=candidate.planned_action,
            mutation_class=candidate.mutation_class,
            proposed_label=candidate.proposed_label,
            confidence_score=candidate.confidence_score,
            confidence_band=candidate.confidence_band,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "dry_run_schema_version": self.dry_run_schema_version,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "planned_action": self.planned_action.value,
            "mutation_class": self.mutation_class.value,
            "proposed_label": self.proposed_label,
            "confidence_score": self.confidence_score,
            "confidence_band": self.confidence_band.value,
        }


@dataclass(frozen=True)
class ProviderResultMetadata:
    provider_status: str | None = None
    failure_code: str | None = None
    request_safe_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("provider_status", self.provider_status),
            ("failure_code", self.failure_code),
            ("request_safe_id", self.request_safe_id),
        ):
            if value is not None:
                _require_nonempty(name, value)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "provider_status": self.provider_status,
            "failure_code": self.failure_code,
            "request_safe_id": self.request_safe_id,
        }


@dataclass(frozen=True)
class RollbackMetadata:
    reversible: bool
    rollback_action: MutationAction | None = None
    restore_state: MailboxStateSnapshot | None = None
    provider_capability: str | None = None

    def __post_init__(self) -> None:
        if self.reversible:
            if self.rollback_action is None:
                raise ValueError(
                    "reversible operations require rollback_action"
                )
            if self.restore_state is None:
                raise ValueError(
                    "reversible operations require restore_state"
                )
        elif (
            self.rollback_action is not None
            or self.restore_state is not None
        ):
            raise ValueError(
                "non-reversible operations cannot declare rollback state"
            )

        if self.provider_capability is not None:
            _require_nonempty(
                "provider_capability",
                self.provider_capability,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reversible": self.reversible,
            "rollback_action": (
                self.rollback_action.value
                if self.rollback_action is not None
                else None
            ),
            "restore_state": (
                self.restore_state.to_dict()
                if self.restore_state is not None
                else None
            ),
            "provider_capability": self.provider_capability,
        }


@dataclass(frozen=True)
class ChangeAuditRecord:
    record_id: str
    timestamp: datetime
    provider: str
    account_safe_id: str
    message_id: str
    action: MutationAction
    mutation_class: MutationClass
    previous_state: MailboxStateSnapshot
    requested_new_state: MailboxStateSnapshot
    resulting_state: MailboxStateSnapshot | None
    evidence: tuple[ChangeEvidence, ...]
    confidence_score: float
    confidence_band: ConfidenceBand
    safety_gates: tuple[SafetyGateRecord, ...]
    initiator: MutationInitiator
    execution_mode: MutationExecutionMode
    result: MutationResultStatus
    provider_result: ProviderResultMetadata
    rollback: RollbackMetadata
    target_label: str | None = None
    initiator_safe_id: str | None = None
    dry_run_reference: DryRunProposalReference | None = None
    schema_version: str = CHANGE_LOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("provider", self.provider),
            ("account_safe_id", self.account_safe_id),
            ("message_id", self.message_id),
        ):
            _require_nonempty(name, value)

        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")

        expected_class = mutation_class_for_action(
            self.action
        )
        if self.mutation_class is not expected_class:
            raise ValueError(
                f"{self.action.value} requires mutation class "
                f"{expected_class.value}"
            )

        if (
            not math.isfinite(self.confidence_score)
            or not 0.0 <= self.confidence_score <= 1.0
        ):
            raise ValueError(
                "confidence_score must be finite and between 0.0 and 1.0"
            )

        expected_band = _confidence_band(self.confidence_score)
        if self.confidence_band is not expected_band:
            raise ValueError(
                "confidence_band does not match confidence_score"
            )

        label_action = self.action in {
            MutationAction.ADD_LABEL,
            MutationAction.REMOVE_LABEL,
        }
        if label_action:
            if self.target_label is None:
                raise ValueError(
                    "label mutations require target_label"
                )
            _require_nonempty("target_label", self.target_label)
        elif self.target_label is not None:
            raise ValueError(
                "target_label is only valid for label mutations"
            )

        if not self.evidence:
            raise ValueError(
                "change audit records require reasoning evidence"
            )

        if not self.safety_gates:
            raise ValueError(
                "change audit records require at least one safety gate record"
            )

        blocked_gate = any(
            gate.decision is SafetyGateDecision.BLOCKED
            for gate in self.safety_gates
        )

        if self.result is MutationResultStatus.DENIED:
            if not blocked_gate:
                raise ValueError(
                    "denied mutations require at least one blocked safety gate"
                )
        elif blocked_gate:
            raise ValueError(
                "blocked safety gates require a denied mutation result"
            )

        _validate_requested_transition(
            self.action,
            self.target_label,
            self.previous_state,
            self.requested_new_state,
        )

        if self.action is MutationAction.MOVE_TO_TRASH:
            if (
                self.execution_mode
                is not MutationExecutionMode.DEDICATED_CLEANUP_WRITE
            ):
                raise ValueError(
                    "MOVE_TO_TRASH requires dedicated cleanup write mode"
                )
        elif (
            self.execution_mode
            is MutationExecutionMode.DEDICATED_CLEANUP_WRITE
        ):
            raise ValueError(
                "dedicated cleanup write mode is reserved for MOVE_TO_TRASH"
            )

        if self.dry_run_reference is not None:
            if self.action is not MutationAction.ADD_LABEL:
                raise ValueError(
                    "the current dry-run proposal reference supports "
                    "only ADD_LABEL mutations"
                )

            if (
                self.dry_run_reference.message_id
                != self.message_id
            ):
                raise ValueError(
                    "dry-run reference belongs to another message"
                )

            if (
                self.dry_run_reference.planned_action
                is not PlannedAction.ADD_LABEL
            ):
                raise ValueError(
                    "ADD_LABEL correlation requires an ADD_LABEL dry-run"
                )

            if (
                self.dry_run_reference.mutation_class
                is not MutationClass.M1
            ):
                raise ValueError(
                    "ADD_LABEL correlation requires an M1 dry-run"
                )

            if (
                self.dry_run_reference.proposed_label
                != self.target_label
            ):
                raise ValueError(
                    "target_label does not match dry-run proposal"
                )

        if self.result is MutationResultStatus.SUCCEEDED:
            if self.resulting_state is None:
                raise ValueError(
                    "successful mutations require resulting_state"
                )
            if self.resulting_state != self.requested_new_state:
                raise ValueError(
                    "successful mutation state must match requested_new_state"
                )

        elif self.result is MutationResultStatus.FAILED:
            if (
                self.resulting_state is not None
                and self.resulting_state != self.previous_state
            ):
                raise ValueError(
                    "changed state must be recorded as partial failure"
                )

        elif self.result is MutationResultStatus.PARTIAL_FAILURE:
            if self.resulting_state is None:
                raise ValueError(
                    "partial failures require resulting_state"
                )
            if self.resulting_state == self.previous_state:
                raise ValueError(
                    "unchanged state is a failure, not partial failure"
                )
            if self.resulting_state == self.requested_new_state:
                raise ValueError(
                    "fully requested state is success, not partial failure"
                )

        elif self.result is MutationResultStatus.DENIED:
            if self.resulting_state != self.previous_state:
                raise ValueError(
                    "denied mutations must preserve previous state"
                )

        if self.rollback.reversible:
            expected_rollback = _ROLLBACK_ACTION[self.action]

            if self.rollback.rollback_action is not expected_rollback:
                raise ValueError(
                    "rollback_action must be "
                    f"{expected_rollback.value} for {self.action.value}"
                )

            if self.rollback.restore_state != self.previous_state:
                raise ValueError(
                    "rollback restore_state must reconstruct previous_state"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "timestamp": self.timestamp.isoformat(),
            "provider": self.provider,
            "account_safe_id": self.account_safe_id,
            "message_id": self.message_id,
            "action": self.action.value,
            "mutation_class": self.mutation_class.value,
            "target_label": self.target_label,
            "previous_state": self.previous_state.to_dict(),
            "requested_new_state": self.requested_new_state.to_dict(),
            "resulting_state": (
                self.resulting_state.to_dict()
                if self.resulting_state is not None
                else None
            ),
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
            "confidence_score": self.confidence_score,
            "confidence_band": self.confidence_band.value,
            "safety_gates": [
                gate.to_dict()
                for gate in self.safety_gates
            ],
            "initiator": self.initiator.value,
            "initiator_safe_id": self.initiator_safe_id,
            "execution_mode": self.execution_mode.value,
            "result": self.result.value,
            "provider_result": self.provider_result.to_dict(),
            "dry_run_reference": (
                self.dry_run_reference.to_dict()
                if self.dry_run_reference is not None
                else None
            ),
            "rollback": self.rollback.to_dict(),
        }


def render_change_record_json(record: ChangeAuditRecord) -> str:
    return json.dumps(
        record.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_change_log_jsonl(
    records: Iterable[ChangeAuditRecord],
) -> str:
    return "\n".join(
        render_change_record_json(record)
        for record in records
    )


def render_change_record_text(record: ChangeAuditRecord) -> str:
    gates = ", ".join(
        f"{gate.gate}={gate.decision.value}"
        for gate in record.safety_gates
    ) or "none"

    evidence = ", ".join(
        item.signal
        for item in record.evidence
    ) or "none"

    rollback = (
        record.rollback.rollback_action.value
        if record.rollback.reversible
        and record.rollback.rollback_action is not None
        else "unavailable"
    )

    lines = [
        "Semantic Mail Archivist — Change audit record",
        f"Schema: {record.schema_version}",
        f"Record: {record.record_id}",
        f"Timestamp: {record.timestamp.isoformat()}",
        f"Provider: {record.provider}",
        f"Account: {record.account_safe_id}",
        f"Message: {record.message_id}",
        (
            f"Action: {record.action.value} "
            f"({record.mutation_class.value})"
        ),
        f"Target label: {record.target_label or 'none'}",
        (
            "Confidence: "
            f"{record.confidence_band.value.upper()} "
            f"{record.confidence_score:.3f}"
        ),
        f"Evidence signals: {evidence}",
        f"Safety gates: {gates}",
        (
            f"Initiator: {record.initiator.value}; "
            f"mode={record.execution_mode.value}"
        ),
        f"Result: {record.result.value}",
        (
            "Provider result: "
            f"status={record.provider_result.provider_status or 'none'}; "
            f"failure_code={record.provider_result.failure_code or 'none'}"
        ),
        (
            "Dry-run correlation: "
            + (
                record.dry_run_reference.correlation_id
                if record.dry_run_reference is not None
                else "none"
            )
        ),
        f"Rollback: {rollback}",
    ]

    return "\n".join(lines)


def append_change_record_jsonl(
    path: str | Path,
    record: ChangeAuditRecord,
) -> None:
    """Append one deterministic audit record to a local JSONL file."""

    target = Path(path)
    line = render_change_record_json(record) + "\n"

    with target.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
