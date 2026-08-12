from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
import re
from typing import Iterable

from .model import (
    ConfidenceBand,
    LabelClass,
    LabelClassifier,
    MessageSnapshot,
)


class AttachmentDisposition(str, Enum):
    ATTACHMENT = "attachment"
    INLINE = "inline"
    UNKNOWN = "unknown"


class DocumentClass(str, Enum):
    CONTRACT = "contract"
    TAX = "tax"
    INSURANCE = "insurance"
    RECEIPT = "receipt"
    INVOICE = "invoice"
    ADMINISTRATIVE = "administrative"
    MEDICAL = "medical"
    GENERIC_ATTACHMENT = "generic_attachment"
    UNKNOWN = "unknown"


class DocumentSignificance(str, Enum):
    SIGNIFICANT_DOCUMENT = "significant_document"
    GENERIC_ATTACHMENT = "generic_attachment"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AttachmentSnapshot:
    attachment_id: str
    filename: str | None = None
    mime_type: str | None = None
    disposition: AttachmentDisposition = AttachmentDisposition.UNKNOWN
    is_repeated_template: bool = False
    exact_duplicate_count: int = 0
    near_duplicate_count: int = 0

    def __post_init__(self) -> None:
        if self.exact_duplicate_count < 0:
            raise ValueError("exact_duplicate_count must be non-negative")
        if self.near_duplicate_count < 0:
            raise ValueError("near_duplicate_count must be non-negative")


@dataclass(frozen=True)
class DocumentEvidence:
    signal: str
    detail: str
    contribution: float


@dataclass(frozen=True)
class DocumentCandidate:
    message_id: str
    attachment_id: str
    filename: str | None
    document_class: DocumentClass
    significance: DocumentSignificance
    confidence_score: float
    confidence_band: ConfidenceBand
    evidence: tuple[DocumentEvidence, ...]
    protection_hints: tuple[str, ...]


_CLASS_KEYWORDS: dict[DocumentClass, tuple[str, ...]] = {
    DocumentClass.CONTRACT: (
        "contract",
        "agreement",
        "lease",
        "signed",
        "contratto",
        "accordo",
    ),
    DocumentClass.TAX: (
        "tax",
        "fiscal",
        "f24",
        "1099",
        "w2",
        "vat",
        "730",
        "certificazione unica",
    ),
    DocumentClass.INSURANCE: (
        "insurance",
        "policy",
        "premium",
        "claim",
        "polizza",
        "assicurazione",
    ),
    DocumentClass.RECEIPT: (
        "receipt",
        "payment receipt",
        "payment confirmation",
        "ricevuta",
        "quietanza",
    ),
    DocumentClass.INVOICE: (
        "invoice",
        "bill",
        "fattura",
    ),
    DocumentClass.ADMINISTRATIVE: (
        "administrative",
        "administration",
        "certificate",
        "application",
        "notice",
        "permit",
        "certificato",
        "amministrativo",
        "modulo",
    ),
    DocumentClass.MEDICAL: (
        "medical",
        "health",
        "prescription",
        "laboratory",
        "lab report",
        "diagnosis",
        "medico",
        "sanitario",
        "referto",
        "ricetta",
    ),
}

_DECORATIVE_KEYWORDS = (
    "logo",
    "icon",
    "banner",
    "spacer",
    "signature",
    "pixel",
    "avatar",
)

_DOCUMENT_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/rtf",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)

_PROTECTION_HINTS: dict[DocumentClass, tuple[str, ...]] = {
    DocumentClass.CONTRACT: ("protected_domain:contracts_employment",),
    DocumentClass.TAX: ("protected_domain:tax_fiscal",),
    DocumentClass.INSURANCE: ("protected_domain:insurance",),
    DocumentClass.RECEIPT: ("protected_domain:payments_receipts_invoices",),
    DocumentClass.INVOICE: ("protected_domain:payments_receipts_invoices",),
    DocumentClass.ADMINISTRATIVE: ("review_retention:administrative_record",),
    DocumentClass.MEDICAL: ("protected_domain:health_medical",),
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
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def _normalized_mime(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().casefold()


def _semantic_taxonomy_terms(
    message: MessageSnapshot,
    classifier: LabelClassifier | None,
) -> tuple[str, ...]:
    terms = list(message.semantic_label_hints)

    if classifier is not None:
        terms.extend(
            label
            for label in message.labels
            if classifier.classify(label) is LabelClass.USER_SEMANTIC
        )

    return tuple(terms)


def _filename_text(filename: str | None) -> str:
    if not filename:
        return ""
    return _normalized(PurePath(filename).name)


def _matches(value: str, keywords: Iterable[str]) -> tuple[str, ...]:
    matches: list[str] = []

    for keyword in keywords:
        normalized_keyword = _normalized(keyword)
        phrase = re.escape(normalized_keyword).replace(r"\ ", r"\s+")
        pattern = rf"(?<!\w){phrase}(?!\w)"

        if re.search(pattern, value):
            matches.append(keyword)

    return tuple(matches)


def _class_matches(value: str) -> dict[DocumentClass, tuple[str, ...]]:
    if not value:
        return {}
    return {
        document_class: matches
        for document_class, keywords in _CLASS_KEYWORDS.items()
        if (matches := _matches(value, keywords))
    }


def _add_source(
    scores: dict[DocumentClass, float],
    evidence: dict[DocumentClass, list[DocumentEvidence]],
    *,
    signal: str,
    value: str,
    contribution: float,
) -> None:
    for document_class, matches in _class_matches(value).items():
        scores[document_class] += contribution
        evidence[document_class].append(
            DocumentEvidence(
                signal=signal,
                detail=(
                    f"{signal} matched {document_class.value} cue(s): "
                    + ", ".join(sorted(set(matches)))
                ),
                contribution=contribution,
            )
        )


def _document_mime(mime_type: str | None) -> bool:
    return _normalized_mime(mime_type) in _DOCUMENT_MIME_TYPES


def _image_mime(mime_type: str | None) -> bool:
    return _normalized_mime(mime_type).startswith("image/")


def _neutral_duplicate_evidence(
    attachment: AttachmentSnapshot,
) -> tuple[DocumentEvidence, ...]:
    result: list[DocumentEvidence] = []
    if attachment.exact_duplicate_count:
        result.append(
            DocumentEvidence(
                signal="exact_duplicate_occurrences",
                detail=(
                    "Exact duplicate occurrences are recorded without reducing "
                    "document significance."
                ),
                contribution=0.0,
            )
        )
    if attachment.near_duplicate_count:
        result.append(
            DocumentEvidence(
                signal="near_duplicate_occurrences",
                detail=(
                    "Near-duplicate occurrences require separate review and are "
                    "not collapsed automatically."
                ),
                contribution=0.0,
            )
        )
    return tuple(result)


def _duplicate_hints(attachment: AttachmentSnapshot) -> tuple[str, ...]:
    hints: list[str] = []
    if attachment.exact_duplicate_count:
        hints.append("duplicate_occurrence")
    if attachment.near_duplicate_count:
        hints.append("near_duplicate_review")
    return tuple(hints)


def _generic_candidate(
    message: MessageSnapshot,
    attachment: AttachmentSnapshot,
    *,
    score: float,
    evidence: tuple[DocumentEvidence, ...],
) -> DocumentCandidate:
    score = min(max(score, 0.0), 1.0)
    return DocumentCandidate(
        message_id=message.message_id,
        attachment_id=attachment.attachment_id,
        filename=attachment.filename,
        document_class=DocumentClass.GENERIC_ATTACHMENT,
        significance=DocumentSignificance.GENERIC_ATTACHMENT,
        confidence_score=score,
        confidence_band=_confidence_band(score),
        evidence=evidence + _neutral_duplicate_evidence(attachment),
        protection_hints=_duplicate_hints(attachment),
    )


def _unknown_candidate(
    message: MessageSnapshot,
    attachment: AttachmentSnapshot,
    *,
    score: float,
    evidence: tuple[DocumentEvidence, ...],
) -> DocumentCandidate:
    score = min(max(score, 0.0), 1.0)
    return DocumentCandidate(
        message_id=message.message_id,
        attachment_id=attachment.attachment_id,
        filename=attachment.filename,
        document_class=DocumentClass.UNKNOWN,
        significance=DocumentSignificance.UNKNOWN,
        confidence_score=score,
        confidence_band=_confidence_band(score),
        evidence=evidence + _neutral_duplicate_evidence(attachment),
        protection_hints=_duplicate_hints(attachment),
    )


def assess_document_significance(
    message: MessageSnapshot,
    attachment: AttachmentSnapshot,
    classifier: LabelClassifier | None = None,
) -> DocumentCandidate:
    """Classify attachment metadata without reading contents or mutating a provider."""

    filename = _filename_text(attachment.filename)
    mime_type = _normalized_mime(attachment.mime_type)

    decorative_matches = _matches(filename, _DECORATIVE_KEYWORDS)

    if decorative_matches and _image_mime(mime_type):
        score = (
            0.99
            if attachment.disposition is AttachmentDisposition.INLINE
            else 0.97
        )
        return _generic_candidate(
            message,
            attachment,
            score=score,
            evidence=(
                DocumentEvidence(
                    signal="decorative_image_asset",
                    detail=(
                        "Image filename matched decorative cue(s): "
                        + ", ".join(sorted(set(decorative_matches)))
                    ),
                    contribution=score,
                ),
            ),
        )

    scores = {document_class: 0.0 for document_class in _CLASS_KEYWORDS}
    evidence = {document_class: [] for document_class in _CLASS_KEYWORDS}

    _add_source(
        scores,
        evidence,
        signal="filename",
        value=filename,
        contribution=0.50,
    )
    _add_source(
        scores,
        evidence,
        signal="subject_context",
        value=_normalized(message.normalized_subject),
        contribution=0.20,
    )
    _add_source(
        scores,
        evidence,
        signal="taxonomy_context",
        value=_normalized(
            " ".join(_semantic_taxonomy_terms(message, classifier))
        ),
        contribution=0.20,
    )
    _add_source(
        scores,
        evidence,
        signal="correspondent_context",
        value=_normalized(" ".join(message.correspondents)),
        contribution=0.10,
    )

    candidate_classes = [
        document_class
        for document_class, score in scores.items()
        if score > 0.0
    ]

    if _document_mime(mime_type):
        for document_class in candidate_classes:
            scores[document_class] += 0.15
            evidence[document_class].append(
                DocumentEvidence(
                    signal="document_mime_type",
                    detail="MIME metadata is compatible with a document file.",
                    contribution=0.15,
                )
            )

    if attachment.disposition is AttachmentDisposition.ATTACHMENT:
        for document_class in candidate_classes:
            scores[document_class] += 0.05
            evidence[document_class].append(
                DocumentEvidence(
                    signal="attachment_disposition",
                    detail="Provider metadata identifies a regular attachment.",
                    contribution=0.05,
                )
            )

    if attachment.is_repeated_template:
        for document_class in candidate_classes:
            scores[document_class] -= 0.20
            evidence[document_class].append(
                DocumentEvidence(
                    signal="repeated_template",
                    detail=(
                        "Repeated/template metadata reduces confidence that this "
                        "occurrence is a distinct significant record."
                    ),
                    contribution=-0.20,
                )
            )

    if not candidate_classes:
        if _image_mime(mime_type):
            if attachment.disposition is AttachmentDisposition.INLINE:
                return _unknown_candidate(
                    message,
                    attachment,
                    score=0.55,
                    evidence=(
                        DocumentEvidence(
                            signal="inline_image_without_document_semantics",
                            detail=(
                                "Inline image placement alone is insufficient to "
                                "classify the asset as decorative or significant."
                            ),
                            contribution=0.55,
                        ),
                    ),
                )

            score = 0.90 if attachment.is_repeated_template else 0.80
            signal = (
                "repeated_image_template"
                if attachment.is_repeated_template
                else "generic_image_attachment"
            )
            return _generic_candidate(
                message,
                attachment,
                score=score,
                evidence=(
                    DocumentEvidence(
                        signal=signal,
                        detail=(
                            "Image metadata has no document-class evidence and is "
                            "treated as a generic attachment."
                        ),
                        contribution=score,
                    ),
                ),
            )

        if mime_type == "text/calendar":
            return _generic_candidate(
                message,
                attachment,
                score=0.90,
                evidence=(
                    DocumentEvidence(
                        signal="calendar_attachment",
                        detail=(
                            "Calendar metadata is treated as a generic operational "
                            "attachment, not a significant document."
                        ),
                        contribution=0.90,
                    ),
                ),
            )

        unknown_score = 0.55 if _document_mime(mime_type) else 0.40
        return _unknown_candidate(
            message,
            attachment,
            score=unknown_score,
            evidence=(
                DocumentEvidence(
                    signal="insufficient_document_semantics",
                    detail=(
                        "Attachment metadata does not safely identify a document class."
                    ),
                    contribution=unknown_score,
                ),
            ),
        )

    ranked = sorted(
        ((score, document_class) for document_class, score in scores.items()),
        reverse=True,
        key=lambda item: (item[0], item[1].value),
    )
    best_score, best_class = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0

    if best_score < 0.60:
        return _unknown_candidate(
            message,
            attachment,
            score=0.55,
            evidence=(
                *tuple(evidence[best_class]),
                DocumentEvidence(
                    signal="below_significance_threshold",
                    detail=(
                        "Document-class evidence exists but is below the minimum "
                        "confidence for a significant-document classification."
                    ),
                    contribution=0.0,
                ),
            ),
        )

    if second_score >= 0.60 and best_score - second_score < 0.10:
        return _unknown_candidate(
            message,
            attachment,
            score=0.85,
            evidence=(
                DocumentEvidence(
                    signal="competing_document_classes",
                    detail=(
                        "Multiple document classes have materially similar support; "
                        "classification is refused."
                    ),
                    contribution=0.85,
                ),
            ),
        )

    raw_score = best_score
    best_score = min(max(best_score, 0.0), 1.0)
    chosen_evidence = list(evidence[best_class])
    if best_score != raw_score:
        chosen_evidence.append(
            DocumentEvidence(
                signal="score_clamp",
                detail="Confidence score was clamped to the 0.00-1.00 policy range.",
                contribution=best_score - raw_score,
            )
        )

    protection_hints = (
        "significant_document",
        *_PROTECTION_HINTS.get(best_class, ()),
        *_duplicate_hints(attachment),
    )

    return DocumentCandidate(
        message_id=message.message_id,
        attachment_id=attachment.attachment_id,
        filename=attachment.filename,
        document_class=best_class,
        significance=DocumentSignificance.SIGNIFICANT_DOCUMENT,
        confidence_score=best_score,
        confidence_band=_confidence_band(best_score),
        evidence=tuple(chosen_evidence) + _neutral_duplicate_evidence(attachment),
        protection_hints=protection_hints,
    )
