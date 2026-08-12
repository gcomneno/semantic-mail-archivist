from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class LabelClass(str, Enum):
    USER_SEMANTIC = "user_semantic"
    USER_OPERATIONAL = "user_operational"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class ContextStatus(str, Enum):
    STABLE = "stable"
    CONFLICTING = "conflicting"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class MessageSnapshot:
    message_id: str
    labels: tuple[str, ...] = ()
    has_attachment: bool = False
    normalized_subject: str | None = None
    participants: tuple[str, ...] = ()
    semantic_label_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThreadSnapshot:
    thread_id: str
    messages: tuple[MessageSnapshot, ...]


class LabelClassifier(Protocol):
    def classify(self, label: str) -> LabelClass:
        ...


@dataclass(frozen=True)
class LabelEvidence:
    label: str
    supporting_message_ids: tuple[str, ...]

    @property
    def support_count(self) -> int:
        return len(self.supporting_message_ids)


@dataclass(frozen=True)
class LabelGapCandidate:
    thread_id: str
    message_id: str
    has_attachment: bool
    context_status: ContextStatus
    surrounding_evidence: tuple[LabelEvidence, ...]


@dataclass(frozen=True)
class InferenceEvidence:
    signal: str
    detail: str
    contribution: float


@dataclass(frozen=True)
class LabelInference:
    thread_id: str
    message_id: str
    proposed_label: str | None
    confidence_score: float
    confidence_band: ConfidenceBand
    evidence: tuple[InferenceEvidence, ...]
    conflicts: tuple[str, ...]
