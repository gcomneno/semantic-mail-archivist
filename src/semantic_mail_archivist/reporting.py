from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .detection import detect_message_level_label_gaps
from .inference import infer_label_from_thread
from .model import (
    ConfidenceBand,
    InferenceEvidence,
    LabelClass,
    LabelClassifier,
    LabelInference,
    MessageSnapshot,
    ThreadSnapshot,
)

SCHEMA_VERSION = "1.0"


class RepairRecommendation(str, Enum):
    ELIGIBLE_FOR_ADDITIVE_REPAIR = "ELIGIBLE_FOR_ADDITIVE_REPAIR"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_ACTION = "NO_ACTION"


class PlannedAction(str, Enum):
    ADD_LABEL = "ADD_LABEL"
    NO_ACTION = "NO_ACTION"


class MutationClass(str, Enum):
    M0 = "M0"
    M1 = "M1"


class MutationAuthorization(str, Enum):
    DENIED = "DENIED"


class SafetyGateResult(str, Enum):
    NOT_EVALUATED_FOR_WRITE = "NOT_EVALUATED_FOR_WRITE"


class ExecutionStatus(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"


class AuthorizationReason(str, Enum):
    DRY_RUN_MODE = "dry_run_mode"
    EXPLICIT_WRITE_MODE_ABSENT = "explicit_write_mode_absent"
    CONFIDENCE_BELOW_M1_THRESHOLD = "confidence_below_m1_threshold"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    NO_SAFE_INFERENCE = "no_safe_inference"
    UNRESOLVED_MATERIAL_CONFLICT = "unresolved_material_conflict"


@dataclass(frozen=True)
class DryRunCandidateReport:
    thread_id: str
    message_id: str
    current_user_labels: tuple[str, ...]
    proposed_label: str | None
    confidence_score: float
    confidence_band: ConfidenceBand
    evidence: tuple[InferenceEvidence, ...]
    conflicts: tuple[str, ...]
    recommendation: RepairRecommendation
    planned_action: PlannedAction
    mutation_class: MutationClass
    mutation_authorization: MutationAuthorization
    safety_gate_result: SafetyGateResult
    authorization_reasons: tuple[AuthorizationReason, ...]
    execution_status: ExecutionStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "current_user_labels": list(self.current_user_labels),
            "proposed_label": self.proposed_label,
            "confidence_score": self.confidence_score,
            "confidence_band": self.confidence_band.value,
            "evidence": [
                {
                    "signal": item.signal,
                    "detail": item.detail,
                    "contribution": item.contribution,
                }
                for item in self.evidence
            ],
            "conflicts": list(self.conflicts),
            "recommendation": self.recommendation.value,
            "planned_action": self.planned_action.value,
            "mutation_class": self.mutation_class.value,
            "mutation_authorization": self.mutation_authorization.value,
            "safety_gate_result": self.safety_gate_result.value,
            "authorization_reasons": [
                reason.value for reason in self.authorization_reasons
            ],
            "execution_status": self.execution_status.value,
        }


@dataclass(frozen=True)
class DryRunReport:
    entries: tuple[DryRunCandidateReport, ...]
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": "dry_run",
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _message_by_id(thread: ThreadSnapshot, message_id: str) -> MessageSnapshot:
    for message in thread.messages:
        if message.message_id == message_id:
            return message
    raise ValueError(
        f"message {message_id!r} is not present in thread {thread.thread_id!r}"
    )


def _current_user_labels(
    message: MessageSnapshot,
    classifier: LabelClassifier,
) -> tuple[str, ...]:
    return tuple(
        label
        for label in message.labels
        if classifier.classify(label) is not LabelClass.SYSTEM
    )


def _decision_for(
    inference: LabelInference,
) -> tuple[
    RepairRecommendation,
    PlannedAction,
    MutationClass,
    tuple[AuthorizationReason, ...],
]:
    if (
        inference.proposed_label is not None
        and inference.confidence_band is ConfidenceBand.HIGH
        and not inference.conflicts
    ):
        return (
            RepairRecommendation.ELIGIBLE_FOR_ADDITIVE_REPAIR,
            PlannedAction.ADD_LABEL,
            MutationClass.M1,
            (
                AuthorizationReason.DRY_RUN_MODE,
                AuthorizationReason.EXPLICIT_WRITE_MODE_ABSENT,
            ),
        )

    if inference.proposed_label is not None:
        reasons = [
            AuthorizationReason.DRY_RUN_MODE,
            AuthorizationReason.HUMAN_REVIEW_REQUIRED,
        ]
        if inference.confidence_band is not ConfidenceBand.HIGH:
            reasons.append(AuthorizationReason.CONFIDENCE_BELOW_M1_THRESHOLD)
        if inference.conflicts:
            reasons.append(AuthorizationReason.UNRESOLVED_MATERIAL_CONFLICT)
        return (
            RepairRecommendation.REVIEW_REQUIRED,
            PlannedAction.NO_ACTION,
            MutationClass.M0,
            tuple(reasons),
        )

    return (
        RepairRecommendation.NO_ACTION,
        PlannedAction.NO_ACTION,
        MutationClass.M0,
        (
            AuthorizationReason.DRY_RUN_MODE,
            AuthorizationReason.NO_SAFE_INFERENCE,
        ),
    )


def _candidate_report(
    thread: ThreadSnapshot,
    inference: LabelInference,
    classifier: LabelClassifier,
) -> DryRunCandidateReport:
    message = _message_by_id(thread, inference.message_id)
    recommendation, planned_action, mutation_class, reasons = _decision_for(inference)

    return DryRunCandidateReport(
        thread_id=inference.thread_id,
        message_id=inference.message_id,
        current_user_labels=_current_user_labels(message, classifier),
        proposed_label=inference.proposed_label,
        confidence_score=inference.confidence_score,
        confidence_band=inference.confidence_band,
        evidence=inference.evidence,
        conflicts=inference.conflicts,
        recommendation=recommendation,
        planned_action=planned_action,
        mutation_class=mutation_class,
        mutation_authorization=MutationAuthorization.DENIED,
        safety_gate_result=SafetyGateResult.NOT_EVALUATED_FOR_WRITE,
        authorization_reasons=reasons,
        execution_status=ExecutionStatus.NOT_EXECUTED,
    )


def build_dry_run_report(
    thread: ThreadSnapshot,
    classifier: LabelClassifier,
) -> DryRunReport:
    """Build a provider-independent repair report without changing provider state."""

    entries = tuple(
        _candidate_report(
            thread,
            infer_label_from_thread(thread, candidate),
            classifier,
        )
        for candidate in detect_message_level_label_gaps(thread, classifier)
    )
    return DryRunReport(entries=entries)


def render_dry_run_json(report: DryRunReport) -> str:
    """Return the stable schema as deterministic JSON."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _human_outcome(entry: DryRunCandidateReport) -> str:
    if entry.recommendation is RepairRecommendation.ELIGIBLE_FOR_ADDITIVE_REPAIR:
        return "HIGH — ELIGIBLE FOR ADDITIVE REPAIR"
    if entry.recommendation is RepairRecommendation.REVIEW_REQUIRED:
        return "REVIEW REQUIRED"
    return "NO ACTION"


def render_dry_run_text(report: DryRunReport) -> str:
    """Render the report for human inspection without exposing message bodies."""

    lines = [
        "Semantic Mail Archivist — Dry-run repair report",
        f"Schema: {report.schema_version}",
        "Mode: DRY RUN — provider state will not be changed",
    ]

    if not report.entries:
        lines.extend(("", "No repair candidates."))
        return "\n".join(lines)

    for index, entry in enumerate(report.entries, start=1):
        current_labels = ", ".join(entry.current_user_labels) or "none"
        conflicts = ", ".join(entry.conflicts) or "none"
        proposed = entry.proposed_label or "none"
        reasons = ", ".join(reason.value for reason in entry.authorization_reasons)

        lines.extend(
            (
                "",
                f"[{index}] Message: {entry.message_id}",
                f"Thread: {entry.thread_id}",
                f"Outcome: {_human_outcome(entry)}",
                f"Current user labels: {current_labels}",
                f"Proposed label: {proposed}",
                (
                    "Confidence: "
                    f"{entry.confidence_band.value.upper()} "
                    f"{entry.confidence_score:.3f}"
                ),
                "Evidence:",
            )
        )

        if entry.evidence:
            for item in entry.evidence:
                lines.append(
                    f"  {item.contribution:+.3f} {item.signal}: {item.detail}"
                )
        else:
            lines.append("  none")

        lines.extend(
            (
                f"Conflicts: {conflicts}",
                f"Mutation class: {entry.mutation_class.value}",
                f"Planned action: {entry.planned_action.value}",
                (
                    "Mutation authorization: "
                    f"{entry.mutation_authorization.value} ({reasons})"
                ),
                f"Safety gates: {entry.safety_gate_result.value}",
                f"Execution: {entry.execution_status.value}",
            )
        )

    return "\n".join(lines)
