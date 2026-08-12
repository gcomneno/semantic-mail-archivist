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


@dataclass(frozen=True)
class MessageSnapshot:
    message_id: str
    labels: tuple[str, ...] = ()
    has_attachment: bool = False


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
