from __future__ import annotations

from .model import (
    ConfidenceBand,
    ContextStatus,
    InferenceEvidence,
    LabelGapCandidate,
    LabelInference,
    MessageSnapshot,
    ThreadSnapshot,
)

HIGH_THRESHOLD = 0.90
MEDIUM_THRESHOLD = 0.60


def confidence_band(score: float) -> ConfidenceBand:
    """Map a normalized score to the confidence bands defined by issue #1."""

    if score >= HIGH_THRESHOLD:
        return ConfidenceBand.HIGH
    if score >= MEDIUM_THRESHOLD:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def _message_by_id(thread: ThreadSnapshot, message_id: str) -> MessageSnapshot:
    for message in thread.messages:
        if message.message_id == message_id:
            return message
    raise ValueError(
        f"message {message_id!r} is not present in thread {thread.thread_id!r}"
    )


def infer_label_from_thread(
    thread: ThreadSnapshot,
    candidate: LabelGapCandidate,
) -> LabelInference:
    """Produce an explainable label inference without mutating provider state.

    The function consumes a gap candidate produced by the issue #2 detector. It
    may return a HIGH- or MEDIUM-confidence proposed label, or deliberately return
    no proposed label when evidence is conflicting or too weak.
    """

    if candidate.thread_id != thread.thread_id:
        raise ValueError("candidate and thread refer to different thread IDs")

    target = _message_by_id(thread, candidate.message_id)
    signals: list[InferenceEvidence] = []
    conflicts: list[str] = []

    if (
        candidate.context_status is ContextStatus.CONFLICTING
        or len(candidate.surrounding_evidence) != 1
    ):
        conflicts.append("competing_thread_semantic_labels")
        signals.append(
            InferenceEvidence(
                signal="thread_consensus",
                detail="Surrounding messages contain competing semantic labels.",
                contribution=0.0,
            )
        )
        return LabelInference(
            thread_id=thread.thread_id,
            message_id=target.message_id,
            proposed_label=None,
            confidence_score=0.0,
            confidence_band=ConfidenceBand.LOW,
            evidence=tuple(signals),
            conflicts=tuple(conflicts),
        )

    label_evidence = candidate.surrounding_evidence[0]
    proposed = label_evidence.label
    supporter_ids = set(label_evidence.supporting_message_ids)

    # Direct semantic evidence is allowed to veto thread inheritance. The hints
    # are provider-independent upstream evidence; this module does not generate
    # them and does not depend on a particular classifier or LLM.
    if target.semantic_label_hints and proposed not in target.semantic_label_hints:
        conflicts.append("direct_semantic_hint_conflicts_with_thread")
        signals.append(
            InferenceEvidence(
                signal="direct_semantic_compatibility",
                detail=(
                    f"Target semantic hints {target.semantic_label_hints!r} "
                    f"do not include thread label {proposed!r}."
                ),
                contribution=0.0,
            )
        )
        return LabelInference(
            thread_id=thread.thread_id,
            message_id=target.message_id,
            proposed_label=None,
            confidence_score=0.0,
            confidence_band=ConfidenceBand.LOW,
            evidence=tuple(signals),
            conflicts=tuple(conflicts),
        )

    score = 0.55
    signals.append(
        InferenceEvidence(
            signal="thread_consensus",
            detail=f"All surrounding semantic evidence supports {proposed!r}.",
            contribution=0.55,
        )
    )

    if label_evidence.support_count >= 2:
        score += 0.15
        signals.append(
            InferenceEvidence(
                signal="support_depth",
                detail=(
                    f"{label_evidence.support_count} surrounding messages support "
                    "the label."
                ),
                contribution=0.15,
            )
        )
    else:
        score += 0.05
        signals.append(
            InferenceEvidence(
                signal="support_depth",
                detail="Only one surrounding message supports the label.",
                contribution=0.05,
            )
        )

    target_index = next(
        index
        for index, message in enumerate(thread.messages)
        if message.message_id == target.message_id
    )
    supporter_indexes = [
        index
        for index, message in enumerate(thread.messages)
        if message.message_id in supporter_ids
    ]
    if any(index < target_index for index in supporter_indexes) and any(
        index > target_index for index in supporter_indexes
    ):
        score += 0.10
        signals.append(
            InferenceEvidence(
                signal="bilateral_support",
                detail=(
                    "Supporting semantic labels occur both before and after the "
                    "target message."
                ),
                contribution=0.10,
            )
        )

    supporters = [
        message for message in thread.messages if message.message_id in supporter_ids
    ]
    supporter_subjects = [
        message.normalized_subject for message in supporters if message.normalized_subject
    ]
    if target.normalized_subject and supporter_subjects:
        if all(subject == target.normalized_subject for subject in supporter_subjects):
            score += 0.08
            signals.append(
                InferenceEvidence(
                    signal="subject_continuity",
                    detail=(
                        "Normalized subject matches all supporters with subject "
                        "metadata."
                    ),
                    contribution=0.08,
                )
            )
        elif all(subject != target.normalized_subject for subject in supporter_subjects):
            score -= 0.10
            conflicts.append("subject_discontinuity")
            signals.append(
                InferenceEvidence(
                    signal="subject_continuity",
                    detail=(
                        "Normalized subject differs from all supporters with subject "
                        "metadata."
                    ),
                    contribution=-0.10,
                )
            )

    if target.participants:
        target_participants = set(target.participants)
        supporter_participants = [
            set(message.participants) for message in supporters if message.participants
        ]
        if supporter_participants:
            overlaps = [
                bool(target_participants.intersection(participants))
                for participants in supporter_participants
            ]
            if all(overlaps):
                score += 0.05
                signals.append(
                    InferenceEvidence(
                        signal="participant_continuity",
                        detail=(
                            "Target shares at least one participant with every "
                            "supporter carrying participant metadata."
                        ),
                        contribution=0.05,
                    )
                )
            elif not any(overlaps):
                score -= 0.10
                conflicts.append("participant_discontinuity")
                signals.append(
                    InferenceEvidence(
                        signal="participant_continuity",
                        detail=(
                            "Target shares no participants with supporters carrying "
                            "participant metadata."
                        ),
                        contribution=-0.10,
                    )
                )

    if proposed in target.semantic_label_hints:
        score += 0.12
        signals.append(
            InferenceEvidence(
                signal="direct_semantic_compatibility",
                detail=f"Target semantic hints explicitly include {proposed!r}.",
                contribution=0.12,
            )
        )

    if target.has_attachment:
        signals.append(
            InferenceEvidence(
                signal="attachment_presence",
                detail=(
                    "Attachment presence is recorded but neutral until document "
                    "significance is implemented."
                ),
                contribution=0.0,
            )
        )

    score = round(max(0.0, min(1.0, score)), 3)
    band = confidence_band(score)
    proposed_label = proposed if band is not ConfidenceBand.LOW else None

    return LabelInference(
        thread_id=thread.thread_id,
        message_id=target.message_id,
        proposed_label=proposed_label,
        confidence_score=score,
        confidence_band=band,
        evidence=tuple(signals),
        conflicts=tuple(conflicts),
    )
