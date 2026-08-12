from __future__ import annotations

from collections import defaultdict

from .model import (
    ContextStatus,
    LabelClass,
    LabelClassifier,
    LabelEvidence,
    LabelGapCandidate,
    MessageSnapshot,
    ThreadSnapshot,
)


def _semantic_labels(message: MessageSnapshot, classifier: LabelClassifier) -> tuple[str, ...]:
    return tuple(
        label for label in message.labels if classifier.classify(label) is LabelClass.USER_SEMANTIC
    )


def detect_message_level_label_gaps(
    thread: ThreadSnapshot,
    classifier: LabelClassifier,
) -> tuple[LabelGapCandidate, ...]:
    """Detect semantic label gaps without inferring or mutating labels.

    A message is a candidate when it carries no semantic user label while at least
    one other message in the same thread provides semantic classification
    evidence. System-only threads are therefore excluded. Conflicting thread
    evidence is preserved instead of being resolved here.
    """

    semantic_by_message = {
        message.message_id: _semantic_labels(message, classifier)
        for message in thread.messages
    }

    candidates: list[LabelGapCandidate] = []

    for message in thread.messages:
        if semantic_by_message[message.message_id]:
            continue

        support: dict[str, list[str]] = defaultdict(list)
        for neighbour in thread.messages:
            if neighbour.message_id == message.message_id:
                continue
            for label in semantic_by_message[neighbour.message_id]:
                support[label].append(neighbour.message_id)

        if not support:
            continue

        evidence = tuple(
            LabelEvidence(label=label, supporting_message_ids=tuple(message_ids))
            for label, message_ids in sorted(support.items())
        )
        context_status = (
            ContextStatus.STABLE if len(evidence) == 1 else ContextStatus.CONFLICTING
        )

        candidates.append(
            LabelGapCandidate(
                thread_id=thread.thread_id,
                message_id=message.message_id,
                has_attachment=message.has_attachment,
                context_status=context_status,
                surrounding_evidence=evidence,
            )
        )

    return tuple(candidates)
