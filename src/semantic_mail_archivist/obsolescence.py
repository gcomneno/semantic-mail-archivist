from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .documents import DocumentCandidate, DocumentSignificance
from .model import ConfidenceBand, MessageSnapshot
from .protection import ProtectedDomainAssessment, ProtectionStatus


class ObsolescenceClass(str, Enum):
    EXPIRED_ONE_TIME_CODE = "expired_one_time_code"
    OLD_MARKETING_CAMPAIGN = "old_marketing_campaign"
    TRANSIENT_SERVICE_NOTIFICATION = "transient_service_notification"
    OBSOLETE_PRODUCT_ANNOUNCEMENT = "obsolete_product_announcement"
    DISCONTINUED_SERVICE_NOTIFICATION = "discontinued_service_notification"
    LOW_VALUE_AUTOMATED_MAIL = "low_value_automated_mail"
    UNKNOWN = "unknown"


class ObsolescenceConflict(str, Enum):
    PROTECTED_DOMAIN = "protected_domain"
    POSSIBLE_PROTECTED_DOMAIN = "possible_protected_domain"
    PROTECTION_UNKNOWN = "protection_unknown"
    SIGNIFICANT_DOCUMENT = "significant_document"
    DOCUMENT_SIGNIFICANCE_UNKNOWN = "document_significance_unknown"
    ATTACHMENT_NOT_ASSESSED = "attachment_not_assessed"
    DOCUMENT_ASSESSMENT_INCOMPLETE = "document_assessment_incomplete"
    MEANINGFUL_CORRESPONDENCE = "meaningful_correspondence"
    PAYMENT_HISTORY = "payment_history"
    ACCOUNT_ACCESS_RECORD = "account_access_record"
    AMBIGUOUS_SEMANTICS = "ambiguous_semantics"
    SAFETY_CONTEXT_INCOMPLETE = "safety_context_incomplete"


class ObsolescenceRecommendation(str, Enum):
    RETAIN = "retain"
    REVIEW = "review"
    REVIEW_FOR_FUTURE_TRASH = "review_for_future_trash"


@dataclass(frozen=True)
class ObsolescenceContext:
    age_days: int | None = None
    automated_sender: bool | None = None
    expiration_confirmed: bool | None = None
    transient_event_completed: bool | None = None
    product_superseded: bool | None = None
    service_discontinued: bool | None = None
    document_assessment_complete: bool | None = None
    meaningful_correspondence: bool | None = None
    payment_history: bool | None = None
    account_access_record: bool | None = None
    ambiguous_semantics: bool | None = None

    def __post_init__(self) -> None:
        if self.age_days is not None and self.age_days < 0:
            raise ValueError("age_days must be non-negative")


@dataclass(frozen=True)
class ObsolescenceEvidence:
    signal: str
    detail: str
    contribution: float


@dataclass(frozen=True)
class ObsolescenceAssessment:
    message_id: str
    obsolescence_class: ObsolescenceClass
    confidence_score: float
    confidence_band: ConfidenceBand
    evidence: tuple[ObsolescenceEvidence, ...]
    protection_conflicts: tuple[ObsolescenceConflict, ...]
    recommendation: ObsolescenceRecommendation

    @property
    def future_trash_candidate(self) -> bool:
        return (
            self.recommendation
            is ObsolescenceRecommendation.REVIEW_FOR_FUTURE_TRASH
        )


_CLASS_KEYWORDS: dict[ObsolescenceClass, tuple[str, ...]] = {
    ObsolescenceClass.EXPIRED_ONE_TIME_CODE: (
        "verification code",
        "one time code",
        "otp code",
        "security code",
        "codice verifica",
        "codice monouso",
    ),
    ObsolescenceClass.OLD_MARKETING_CAMPAIGN: (
        "sale",
        "promotion",
        "promotional",
        "special offer",
        "discount",
        "campaign",
        "newsletter",
        "offerta",
        "promozione",
        "sconto",
    ),
    ObsolescenceClass.TRANSIENT_SERVICE_NOTIFICATION: (
        "job completed",
        "task completed",
        "backup completed",
        "delivery completed",
        "operation completed",
        "notification completed",
        "operazione completata",
        "attivita completata",
        "backup completato",
    ),
    ObsolescenceClass.OBSOLETE_PRODUCT_ANNOUNCEMENT: (
        "product announcement",
        "new product",
        "new release",
        "release announcement",
        "product launch",
        "annuncio prodotto",
        "nuovo prodotto",
        "nuova versione",
    ),
    ObsolescenceClass.DISCONTINUED_SERVICE_NOTIFICATION: (
        "service notice",
        "service update",
        "platform notice",
        "platform update",
        "avviso servizio",
        "aggiornamento servizio",
        "avviso piattaforma",
    ),
    ObsolescenceClass.LOW_VALUE_AUTOMATED_MAIL: (
        "automated notification",
        "automated message",
        "do not reply",
        "no reply",
        "noreply",
        "notification",
        "notifica automatica",
        "messaggio automatico",
    ),
}


def _confidence_band(score: float) -> ConfidenceBand:
    if score >= 0.90:
        return ConfidenceBand.HIGH
    if score >= 0.60:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def _normalized(value: str | None) -> str:
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
        normalized_keyword = _normalized(keyword)
        phrase = re.escape(normalized_keyword).replace(r"\ ", r"\s+")
        pattern = rf"(?<!\w){phrase}(?!\w)"
        if re.search(pattern, value):
            matches.append(keyword)
    return tuple(matches)


def _class_matches(value: str) -> dict[ObsolescenceClass, tuple[str, ...]]:
    if not value:
        return {}
    return {
        obsolete_class: matches
        for obsolete_class, keywords in _CLASS_KEYWORDS.items()
        if (matches := _matches(value, keywords))
    }


def _semantic_text(message: MessageSnapshot) -> str:
    parts = [message.normalized_subject or ""]
    parts.extend(message.semantic_label_hints)
    return _normalized(" ".join(parts))


def _base_scores(
    message: MessageSnapshot,
) -> tuple[
    dict[ObsolescenceClass, float],
    dict[ObsolescenceClass, list[ObsolescenceEvidence]],
]:
    scores = {
        obsolete_class: 0.0
        for obsolete_class in ObsolescenceClass
        if obsolete_class is not ObsolescenceClass.UNKNOWN
    }
    evidence = {obsolete_class: [] for obsolete_class in scores}

    for obsolete_class, matches in _class_matches(_semantic_text(message)).items():
        contribution = 0.70
        scores[obsolete_class] += contribution
        evidence[obsolete_class].append(
            ObsolescenceEvidence(
                signal="direct_semantic_cue",
                detail=(
                    f"Matched {obsolete_class.value} cue(s): "
                    + ", ".join(sorted(set(matches)))
                ),
                contribution=contribution,
            )
        )
    return scores, evidence


def _add_positive_context(
    scores: dict[ObsolescenceClass, float],
    evidence: dict[ObsolescenceClass, list[ObsolescenceEvidence]],
    context: ObsolescenceContext,
) -> None:
    def add(
        obsolete_class: ObsolescenceClass,
        *,
        condition: bool,
        signal: str,
        detail: str,
        contribution: float,
    ) -> None:
        if not condition or scores[obsolete_class] <= 0.0:
            return
        scores[obsolete_class] += contribution
        evidence[obsolete_class].append(
            ObsolescenceEvidence(
                signal=signal,
                detail=detail,
                contribution=contribution,
            )
        )

    add(
        ObsolescenceClass.EXPIRED_ONE_TIME_CODE,
        condition=context.expiration_confirmed is True,
        signal="expiration_confirmed",
        detail="Expiration state confirms the one-time artifact is no longer active.",
        contribution=0.20,
    )
    add(
        ObsolescenceClass.TRANSIENT_SERVICE_NOTIFICATION,
        condition=context.transient_event_completed is True,
        signal="transient_event_completed",
        detail="The transient event represented by the notification is complete.",
        contribution=0.20,
    )
    add(
        ObsolescenceClass.OBSOLETE_PRODUCT_ANNOUNCEMENT,
        condition=context.product_superseded is True,
        signal="product_superseded",
        detail="Product-state evidence says the announced version is superseded.",
        contribution=0.20,
    )
    add(
        ObsolescenceClass.DISCONTINUED_SERVICE_NOTIFICATION,
        condition=context.service_discontinued is True,
        signal="service_discontinued",
        detail="Service-state evidence says the referenced service is discontinued.",
        contribution=0.20,
    )
    add(
        ObsolescenceClass.OLD_MARKETING_CAMPAIGN,
        condition=context.expiration_confirmed is True,
        signal="campaign_expiration_confirmed",
        detail="Campaign-state evidence confirms the promotion is expired.",
        contribution=0.15,
    )

    if context.automated_sender is True:
        for obsolete_class in scores:
            if scores[obsolete_class] <= 0.0:
                continue
            contribution = (
                0.20
                if obsolete_class is ObsolescenceClass.LOW_VALUE_AUTOMATED_MAIL
                else 0.10
            )
            scores[obsolete_class] += contribution
            evidence[obsolete_class].append(
                ObsolescenceEvidence(
                    signal="automated_sender",
                    detail="Sender/context metadata identifies automated mail.",
                    contribution=contribution,
                )
            )

    if (
        context.meaningful_correspondence is False
        and scores[ObsolescenceClass.LOW_VALUE_AUTOMATED_MAIL] > 0.0
    ):
        contribution = 0.10
        scores[ObsolescenceClass.LOW_VALUE_AUTOMATED_MAIL] += contribution
        evidence[ObsolescenceClass.LOW_VALUE_AUTOMATED_MAIL].append(
            ObsolescenceEvidence(
                signal="no_meaningful_conversation",
                detail=(
                    "Conversation analysis explicitly found no meaningful "
                    "correspondence context."
                ),
                contribution=contribution,
            )
        )


def _add_age_context(
    scores: dict[ObsolescenceClass, float],
    evidence: dict[ObsolescenceClass, list[ObsolescenceEvidence]],
    context: ObsolescenceContext,
) -> tuple[ObsolescenceEvidence, ...]:
    if context.age_days is None:
        return ()

    if not any(score > 0.0 for score in scores.values()):
        return (
            ObsolescenceEvidence(
                signal="age_without_obsolescence_signal",
                detail=(
                    "Message age is recorded but contributes no obsolescence "
                    "confidence without an independent positive signal."
                ),
                contribution=0.0,
            ),
        )

    if context.age_days < 30:
        return ()

    for obsolete_class, score in scores.items():
        if score <= 0.0:
            continue
        contribution = 0.10
        scores[obsolete_class] += contribution
        evidence[obsolete_class].append(
            ObsolescenceEvidence(
                signal="age_context",
                detail=(
                    "Age strengthens existing positive obsolescence evidence; "
                    "it is not sufficient by itself."
                ),
                contribution=contribution,
            )
        )
    return ()


def _rank(
    scores: dict[ObsolescenceClass, float],
) -> tuple[ObsolescenceClass, float, float]:
    ranked = sorted(
        (
            (score, obsolete_class)
            for obsolete_class, score in scores.items()
            if score > 0.0
        ),
        key=lambda item: (item[0], item[1].value),
        reverse=True,
    )
    if not ranked:
        return ObsolescenceClass.UNKNOWN, 0.0, 0.0
    best_score, best_class = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    return best_class, best_score, second_score


def _build_classification(
    message: MessageSnapshot,
    context: ObsolescenceContext,
) -> tuple[
    ObsolescenceClass,
    float,
    tuple[ObsolescenceEvidence, ...],
    bool,
]:
    scores, evidence = _base_scores(message)
    _add_positive_context(scores, evidence, context)
    age_only_evidence = _add_age_context(scores, evidence, context)
    best_class, raw_score, second_score = _rank(scores)

    if best_class is ObsolescenceClass.UNKNOWN:
        return (
            ObsolescenceClass.UNKNOWN,
            0.0,
            age_only_evidence
            or (
                ObsolescenceEvidence(
                    signal="insufficient_obsolescence_semantics",
                    detail=(
                        "No positive low-value or obsolescence signal was "
                        "identified."
                    ),
                    contribution=0.0,
                ),
            ),
            False,
        )

    ambiguous = second_score >= 0.60 and raw_score - second_score < 0.10
    if ambiguous:
        combined_evidence: list[ObsolescenceEvidence] = []
        for obsolete_class in scores:
            if scores[obsolete_class] >= 0.60:
                combined_evidence.extend(evidence[obsolete_class])
        combined_evidence.append(
            ObsolescenceEvidence(
                signal="competing_obsolescence_classes",
                detail=(
                    "Multiple obsolescence classes have materially similar "
                    "support."
                ),
                contribution=0.0,
            )
        )
        return (
            ObsolescenceClass.UNKNOWN,
            min(max(raw_score, 0.0), 1.0),
            tuple(combined_evidence),
            True,
        )

    score = min(max(raw_score, 0.0), 1.0)
    final_evidence = list(evidence[best_class])
    if score != raw_score:
        final_evidence.append(
            ObsolescenceEvidence(
                signal="score_clamp",
                detail=(
                    "Obsolescence score was clamped to the 0.00-1.00 "
                    "policy range."
                ),
                contribution=score - raw_score,
            )
        )

    return best_class, score, tuple(final_evidence), False


def _protection_conflicts(
    message: MessageSnapshot,
    context: ObsolescenceContext,
    document_candidates: tuple[DocumentCandidate, ...],
    protection_assessment: ProtectedDomainAssessment | None,
    classifier_ambiguous: bool,
) -> tuple[ObsolescenceConflict, ...]:
    conflicts: list[ObsolescenceConflict] = []

    def add(conflict: ObsolescenceConflict) -> None:
        if conflict not in conflicts:
            conflicts.append(conflict)

    if protection_assessment is None:
        add(ObsolescenceConflict.PROTECTION_UNKNOWN)
    elif protection_assessment.status is ProtectionStatus.PROTECTED:
        add(ObsolescenceConflict.PROTECTED_DOMAIN)
    elif protection_assessment.status is ProtectionStatus.POSSIBLY_PROTECTED:
        add(ObsolescenceConflict.POSSIBLE_PROTECTED_DOMAIN)
    elif protection_assessment.status is ProtectionStatus.UNKNOWN:
        add(ObsolescenceConflict.PROTECTION_UNKNOWN)

    if message.has_attachment:
        if not document_candidates:
            add(ObsolescenceConflict.ATTACHMENT_NOT_ASSESSED)
        elif context.document_assessment_complete is not True:
            add(ObsolescenceConflict.DOCUMENT_ASSESSMENT_INCOMPLETE)

    for candidate in document_candidates:
        if candidate.significance is DocumentSignificance.SIGNIFICANT_DOCUMENT:
            add(ObsolescenceConflict.SIGNIFICANT_DOCUMENT)
        elif candidate.significance is DocumentSignificance.UNKNOWN:
            add(ObsolescenceConflict.DOCUMENT_SIGNIFICANCE_UNKNOWN)

    if context.meaningful_correspondence is True:
        add(ObsolescenceConflict.MEANINGFUL_CORRESPONDENCE)
    if context.payment_history is True:
        add(ObsolescenceConflict.PAYMENT_HISTORY)
    if context.account_access_record is True:
        add(ObsolescenceConflict.ACCOUNT_ACCESS_RECORD)
    if context.ambiguous_semantics is True or classifier_ambiguous:
        add(ObsolescenceConflict.AMBIGUOUS_SEMANTICS)

    safety_fields = (
        context.meaningful_correspondence,
        context.payment_history,
        context.account_access_record,
        context.ambiguous_semantics,
    )
    if any(value is None for value in safety_fields):
        add(ObsolescenceConflict.SAFETY_CONTEXT_INCOMPLETE)

    return tuple(conflicts)


def _recommendation(
    obsolete_class: ObsolescenceClass,
    score: float,
    conflicts: tuple[ObsolescenceConflict, ...],
) -> ObsolescenceRecommendation:
    if obsolete_class is ObsolescenceClass.UNKNOWN:
        return ObsolescenceRecommendation.RETAIN

    if conflicts:
        return ObsolescenceRecommendation.RETAIN

    if score >= 0.995:
        return ObsolescenceRecommendation.REVIEW_FOR_FUTURE_TRASH

    return ObsolescenceRecommendation.REVIEW


def assess_message_obsolescence(
    message: MessageSnapshot,
    context: ObsolescenceContext,
    document_candidates: Iterable[DocumentCandidate] = (),
    protection_assessment: ProtectedDomainAssessment | None = None,
) -> ObsolescenceAssessment:
    """Classify low-value obsolescence without mutating provider state."""

    candidates = tuple(document_candidates)

    if (
        protection_assessment is not None
        and protection_assessment.message_id != message.message_id
    ):
        raise ValueError(
            "protection_assessment must belong to the assessed message"
        )

    if any(
        candidate.message_id != message.message_id
        for candidate in candidates
    ):
        raise ValueError(
            "document_candidates must belong to the assessed message"
        )

    obsolete_class, score, evidence, ambiguous = _build_classification(
        message,
        context,
    )
    conflicts = _protection_conflicts(
        message,
        context,
        candidates,
        protection_assessment,
        ambiguous,
    )
    recommendation = _recommendation(
        obsolete_class,
        score,
        conflicts,
    )

    return ObsolescenceAssessment(
        message_id=message.message_id,
        obsolescence_class=obsolete_class,
        confidence_score=score,
        confidence_band=_confidence_band(score),
        evidence=evidence,
        protection_conflicts=conflicts,
        recommendation=recommendation,
    )
