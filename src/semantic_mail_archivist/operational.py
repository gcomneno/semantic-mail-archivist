from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .documents import DocumentCandidate, DocumentSignificance
from .model import (
    ConfidenceBand,
    LabelClass,
    LabelClassifier,
    MessageSnapshot,
)


class OperationalState(str, Enum):
    ACTION = "action"
    WAITING = "waiting"
    DEADLINE = "deadline"
    DOCUMENT = "document"
    REFERENCE = "reference"


class OperationalConflict(str, Enum):
    INCOMPATIBLE_CURRENT_STATES = "incompatible_current_states"
    INCOMPATIBLE_PROPOSED_STATES = "incompatible_proposed_states"
    CURRENT_STATE_CONFLICTS_WITH_PROPOSAL = (
        "current_state_conflicts_with_proposal"
    )
    UNMAPPED_CURRENT_OPERATIONAL_LABEL = (
        "unmapped_current_operational_label"
    )


class OperationalRecommendation(str, Enum):
    DISABLED = "disabled"
    NO_PROPOSAL = "no_proposal"
    ALREADY_SATISFIED = "already_satisfied"
    PROPOSE_OPERATIONAL_STATE = "propose_operational_state"
    REVIEW_REQUIRED = "review_required"


class OperationalMutationAuthorization(str, Enum):
    DENIED = "denied"


class OperationalExecutionStatus(str, Enum):
    NOT_EXECUTED = "not_executed"


def _normalized_label(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class OperationalLabelSpec:
    state: OperationalState
    preferred_label: str
    equivalent_labels: tuple[str, ...] = ()

    @property
    def all_labels(self) -> tuple[str, ...]:
        return (self.preferred_label, *self.equivalent_labels)


DEFAULT_OPERATIONAL_LABEL_SPECS = (
    OperationalLabelSpec(
        state=OperationalState.ACTION,
        preferred_label="@Action",
    ),
    OperationalLabelSpec(
        state=OperationalState.WAITING,
        preferred_label="@Waiting",
    ),
    OperationalLabelSpec(
        state=OperationalState.DEADLINE,
        preferred_label="@Deadline",
    ),
    OperationalLabelSpec(
        state=OperationalState.DOCUMENT,
        preferred_label="@Document",
    ),
    OperationalLabelSpec(
        state=OperationalState.REFERENCE,
        preferred_label="@Reference",
    ),
)


@dataclass(frozen=True)
class OperationalLayerConfig:
    enabled: bool = True
    label_specs: tuple[OperationalLabelSpec, ...] = (
        DEFAULT_OPERATIONAL_LABEL_SPECS
    )
    incompatible_pairs: tuple[
        tuple[OperationalState, OperationalState],
        ...
    ] = (
        (OperationalState.ACTION, OperationalState.WAITING),
    )

    def __post_init__(self) -> None:
        states = tuple(spec.state for spec in self.label_specs)

        if (
            len(states) != len(OperationalState)
            or set(states) != set(OperationalState)
        ):
            raise ValueError(
                "label_specs must define exactly one label spec "
                "for every operational state"
            )

        label_owners: dict[str, OperationalState] = {}

        for spec in self.label_specs:
            if not spec.preferred_label.strip():
                raise ValueError("preferred operational labels cannot be empty")

            for label in spec.all_labels:
                if not label.strip():
                    raise ValueError(
                        "equivalent operational labels cannot be empty"
                    )

                normalized = _normalized_label(label)
                owner = label_owners.get(normalized)

                if owner is not None and owner is not spec.state:
                    raise ValueError(
                        "one operational label cannot map to multiple states"
                    )

                label_owners[normalized] = spec.state

        for left, right in self.incompatible_pairs:
            if left is right:
                raise ValueError(
                    "an operational state cannot conflict with itself"
                )

    def spec_for(self, state: OperationalState) -> OperationalLabelSpec:
        for spec in self.label_specs:
            if spec.state is state:
                return spec

        raise KeyError(state)

    def states_are_incompatible(
        self,
        left: OperationalState,
        right: OperationalState,
    ) -> bool:
        if left is right:
            return False

        return any(
            {left, right} == {pair_left, pair_right}
            for pair_left, pair_right in self.incompatible_pairs
        )


@dataclass(frozen=True)
class OperationalEvidence:
    signal: str
    detail: str
    contribution: float


@dataclass(frozen=True)
class OperationalStateProposal:
    state: OperationalState
    label: str
    confidence_score: float
    confidence_band: ConfidenceBand
    evidence: tuple[OperationalEvidence, ...]
    reuses_existing_label: bool
    requires_label_creation: bool


@dataclass(frozen=True)
class OperationalStateAssessment:
    message_id: str
    enabled: bool
    current_states: tuple[OperationalState, ...]
    proposals: tuple[OperationalStateProposal, ...]
    conflicts: tuple[OperationalConflict, ...]
    unmapped_operational_labels: tuple[str, ...]
    recommendation: OperationalRecommendation
    mutation_authorization: OperationalMutationAuthorization
    execution_status: OperationalExecutionStatus

    @property
    def proposed_states(self) -> tuple[OperationalState, ...]:
        return tuple(proposal.state for proposal in self.proposals)


_STATE_KEYWORDS: dict[OperationalState, tuple[str, ...]] = {
    OperationalState.ACTION: (
        "action required",
        "requires action",
        "please review",
        "please respond",
        "response required",
        "to do",
        "todo",
        "azione richiesta",
        "risposta richiesta",
    ),
    OperationalState.WAITING: (
        "waiting for",
        "awaiting",
        "pending reply",
        "pending response",
        "pending approval",
        "in attesa",
        "attesa risposta",
    ),
    OperationalState.DEADLINE: (
        "deadline",
        "due by",
        "due date",
        "submit by",
        "expires on",
        "scadenza",
        "entro il",
    ),
    OperationalState.DOCUMENT: (
        "document attached",
        "attached document",
        "document enclosed",
        "documento allegato",
    ),
    OperationalState.REFERENCE: (
        "for reference",
        "reference material",
        "for your information",
        "fyi",
        "per riferimento",
        "materiale di riferimento",
    ),
}


def _confidence_band(score: float) -> ConfidenceBand:
    if score >= 0.90:
        return ConfidenceBand.HIGH
    if score >= 0.60:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def _normalized_text(value: str | None) -> str:
    if not value:
        return ""

    return " ".join(
        value.casefold()
        .replace("_", " ")
        .replace("-", " ")
        .replace("’", "'")
        .split()
    )


def _matches(value: str, keywords: Iterable[str]) -> tuple[str, ...]:
    matches: list[str] = []

    for keyword in keywords:
        normalized_keyword = _normalized_text(keyword)
        phrase = re.escape(normalized_keyword).replace(r"\ ", r"\s+")
        pattern = rf"(?<!\w){phrase}(?!\w)"

        if re.search(pattern, value):
            matches.append(keyword)

    return tuple(matches)


def _catalog(
    config: OperationalLayerConfig,
) -> dict[str, OperationalLabelSpec]:
    return {
        _normalized_label(label): spec
        for spec in config.label_specs
        for label in spec.all_labels
    }


def _current_state_context(
    message: MessageSnapshot,
    classifier: LabelClassifier,
    config: OperationalLayerConfig,
) -> tuple[
    tuple[OperationalState, ...],
    tuple[str, ...],
]:
    catalog = _catalog(config)
    states: list[OperationalState] = []
    unmapped: list[str] = []

    for label in message.labels:
        if classifier.classify(label) is not LabelClass.USER_OPERATIONAL:
            continue

        spec = catalog.get(_normalized_label(label))

        if spec is None:
            if label not in unmapped:
                unmapped.append(label)
            continue

        if spec.state not in states:
            states.append(spec.state)

    return (
        tuple(sorted(states, key=lambda state: state.value)),
        tuple(unmapped),
    )


def _base_scores(
    message: MessageSnapshot,
) -> tuple[
    dict[OperationalState, float],
    dict[OperationalState, list[OperationalEvidence]],
]:
    scores = {state: 0.0 for state in OperationalState}
    evidence = {state: [] for state in OperationalState}
    subject = _normalized_text(message.normalized_subject)

    if not subject:
        return scores, evidence

    for state, keywords in _STATE_KEYWORDS.items():
        matches = _matches(subject, keywords)

        if not matches:
            continue

        contribution = 0.70
        scores[state] += contribution
        evidence[state].append(
            OperationalEvidence(
                signal="direct_operational_cue",
                detail=(
                    f"Matched {state.value} operational cue(s): "
                    + ", ".join(sorted(set(matches)))
                ),
                contribution=contribution,
            )
        )

    return scores, evidence


def _add_document_evidence(
    scores: dict[OperationalState, float],
    evidence: dict[OperationalState, list[OperationalEvidence]],
    candidates: tuple[DocumentCandidate, ...],
) -> None:
    significant = tuple(
        candidate
        for candidate in candidates
        if candidate.significance
        is DocumentSignificance.SIGNIFICANT_DOCUMENT
    )

    if not significant:
        return

    strongest = max(
        significant,
        key=lambda candidate: candidate.confidence_score,
    )
    contribution = min(
        max(strongest.confidence_score, 0.0),
        1.0,
    )

    scores[OperationalState.DOCUMENT] += contribution
    evidence[OperationalState.DOCUMENT].append(
        OperationalEvidence(
            signal="significant_document",
            detail=(
                "Document-significance analysis found a durable document "
                "candidate for this message."
            ),
            contribution=contribution,
        )
    )


def _final_state_evidence(
    raw_score: float,
    items: list[OperationalEvidence],
) -> tuple[float, tuple[OperationalEvidence, ...]]:
    score = min(max(raw_score, 0.0), 1.0)
    final_items = list(items)

    if score != raw_score:
        final_items.append(
            OperationalEvidence(
                signal="score_clamp",
                detail=(
                    "Operational-state score was clamped to the "
                    "0.00-1.00 policy range."
                ),
                contribution=score - raw_score,
            )
        )

    return score, tuple(final_items)


def _existing_label_for_state(
    state: OperationalState,
    message: MessageSnapshot,
    available_labels: tuple[str, ...],
    classifier: LabelClassifier,
    config: OperationalLayerConfig,
) -> str | None:
    catalog = _catalog(config)
    spec = config.spec_for(state)

    pool = tuple(
        dict.fromkeys(
            (*message.labels, *available_labels)
        )
    )

    candidates = []

    for label in pool:
        if classifier.classify(label) is not LabelClass.USER_OPERATIONAL:
            continue

        mapped = catalog.get(_normalized_label(label))

        if mapped is not None and mapped.state is state:
            candidates.append(label)

    if not candidates:
        return None

    preferred = _normalized_label(spec.preferred_label)

    for label in candidates:
        if _normalized_label(label) == preferred:
            return label

    return sorted(candidates, key=lambda label: label.casefold())[0]


def _has_incompatible_pair(
    states: Iterable[OperationalState],
    config: OperationalLayerConfig,
) -> bool:
    values = tuple(states)

    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            if config.states_are_incompatible(left, right):
                return True

    return False


def _conflicts(
    current_states: tuple[OperationalState, ...],
    proposed_states: tuple[OperationalState, ...],
    unmapped_operational_labels: tuple[str, ...],
    config: OperationalLayerConfig,
) -> tuple[OperationalConflict, ...]:
    conflicts: list[OperationalConflict] = []

    def add(conflict: OperationalConflict) -> None:
        if conflict not in conflicts:
            conflicts.append(conflict)

    if _has_incompatible_pair(current_states, config):
        add(OperationalConflict.INCOMPATIBLE_CURRENT_STATES)

    if _has_incompatible_pair(proposed_states, config):
        add(OperationalConflict.INCOMPATIBLE_PROPOSED_STATES)

    if any(
        config.states_are_incompatible(current, proposed)
        for current in current_states
        for proposed in proposed_states
    ):
        add(
            OperationalConflict.CURRENT_STATE_CONFLICTS_WITH_PROPOSAL
        )

    if unmapped_operational_labels:
        add(OperationalConflict.UNMAPPED_CURRENT_OPERATIONAL_LABEL)

    return tuple(conflicts)


def _recommendation(
    *,
    enabled: bool,
    current_states: tuple[OperationalState, ...],
    proposals: tuple[OperationalStateProposal, ...],
    conflicts: tuple[OperationalConflict, ...],
) -> OperationalRecommendation:
    if not enabled:
        return OperationalRecommendation.DISABLED

    if conflicts:
        return OperationalRecommendation.REVIEW_REQUIRED

    if proposals:
        return OperationalRecommendation.PROPOSE_OPERATIONAL_STATE

    if current_states:
        return OperationalRecommendation.ALREADY_SATISFIED

    return OperationalRecommendation.NO_PROPOSAL


def assess_operational_state(
    message: MessageSnapshot,
    classifier: LabelClassifier,
    *,
    config: OperationalLayerConfig | None = None,
    available_labels: Iterable[str] = (),
    document_candidates: Iterable[DocumentCandidate] = (),
) -> OperationalStateAssessment:
    """Assess optional operational states without mutating provider state."""

    active_config = config or OperationalLayerConfig()

    if not active_config.enabled:
        return OperationalStateAssessment(
            message_id=message.message_id,
            enabled=False,
            current_states=(),
            proposals=(),
            conflicts=(),
            unmapped_operational_labels=(),
            recommendation=OperationalRecommendation.DISABLED,
            mutation_authorization=OperationalMutationAuthorization.DENIED,
            execution_status=OperationalExecutionStatus.NOT_EXECUTED,
        )

    candidates = tuple(document_candidates)

    if any(
        candidate.message_id != message.message_id
        for candidate in candidates
    ):
        raise ValueError(
            "document_candidates must belong to the assessed message"
        )

    mailbox_labels = tuple(available_labels)
    current_states, unmapped = _current_state_context(
        message,
        classifier,
        active_config,
    )

    scores, evidence = _base_scores(message)
    _add_document_evidence(scores, evidence, candidates)

    proposals: list[OperationalStateProposal] = []

    for state in OperationalState:
        if scores[state] < 0.60:
            continue

        if state in current_states:
            continue

        score, state_evidence = _final_state_evidence(
            scores[state],
            evidence[state],
        )
        existing_label = _existing_label_for_state(
            state,
            message,
            mailbox_labels,
            classifier,
            active_config,
        )
        label = (
            existing_label
            if existing_label is not None
            else active_config.spec_for(state).preferred_label
        )

        proposals.append(
            OperationalStateProposal(
                state=state,
                label=label,
                confidence_score=score,
                confidence_band=_confidence_band(score),
                evidence=state_evidence,
                reuses_existing_label=existing_label is not None,
                requires_label_creation=existing_label is None,
            )
        )

    proposal_tuple = tuple(
        sorted(
            proposals,
            key=lambda proposal: proposal.state.value,
        )
    )
    conflicts = _conflicts(
        current_states,
        tuple(proposal.state for proposal in proposal_tuple),
        unmapped,
        active_config,
    )

    return OperationalStateAssessment(
        message_id=message.message_id,
        enabled=True,
        current_states=current_states,
        proposals=proposal_tuple,
        conflicts=conflicts,
        unmapped_operational_labels=unmapped,
        recommendation=_recommendation(
            enabled=True,
            current_states=current_states,
            proposals=proposal_tuple,
            conflicts=conflicts,
        ),
        mutation_authorization=OperationalMutationAuthorization.DENIED,
        execution_status=OperationalExecutionStatus.NOT_EXECUTED,
    )
