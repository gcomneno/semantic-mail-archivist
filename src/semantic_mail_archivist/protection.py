from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .documents import DocumentCandidate
from .model import ConfidenceBand, LabelClass, LabelClassifier, MessageSnapshot


class ProtectedDomain(str, Enum):
    HEALTH_MEDICAL = "health_medical"
    TAX_FISCAL = "tax_fiscal"
    BANKING_FINANCIAL = "banking_financial"
    INSURANCE = "insurance"
    CONTRACTS_EMPLOYMENT = "contracts_employment"
    PENSIONS_BENEFITS_PUBLIC_ADMIN = "pensions_benefits_public_admin"
    IDENTITY_AUTHENTICATION = "identity_authentication"
    EDUCATION = "education"
    LEGAL = "legal"
    PAYMENTS_RECEIPTS_INVOICES = "payments_receipts_invoices"


class ProtectionCoverage(str, Enum):
    PARTIAL = "partial"
    COMPLETE = "complete"


class ProtectionStatus(str, Enum):
    PROTECTED = "protected"
    POSSIBLY_PROTECTED = "possibly_protected"
    NOT_PROTECTED = "not_protected"
    UNKNOWN = "unknown"


class DestructiveProtectionGateResult(str, Enum):
    BLOCKED_PROTECTED_DOMAIN = "blocked_protected_domain"
    BLOCKED_POSSIBLE_DOMAIN = "blocked_possible_domain"
    BLOCKED_UNKNOWN = "blocked_unknown"
    PASSED_NO_PROTECTED_SIGNAL = "passed_no_protected_signal"


@dataclass(frozen=True)
class ProtectionEvidence:
    signal: str
    detail: str
    contribution: float


@dataclass(frozen=True)
class ProtectedDomainHint:
    domain: ProtectedDomain
    confidence_score: float
    confidence_band: ConfidenceBand
    evidence: tuple[ProtectionEvidence, ...]


@dataclass(frozen=True)
class ProtectedDomainAssessment:
    message_id: str
    hints: tuple[ProtectedDomainHint, ...]
    coverage: ProtectionCoverage

    @property
    def status(self) -> ProtectionStatus:
        if any(
            hint.confidence_band is ConfidenceBand.HIGH
            for hint in self.hints
        ):
            return ProtectionStatus.PROTECTED
        if self.hints:
            return ProtectionStatus.POSSIBLY_PROTECTED
        if self.coverage is ProtectionCoverage.COMPLETE:
            return ProtectionStatus.NOT_PROTECTED
        return ProtectionStatus.UNKNOWN


@dataclass(frozen=True)
class DestructiveProtectionGate:
    result: DestructiveProtectionGateResult
    blocking_domains: tuple[ProtectedDomain, ...]
    reasons: tuple[str, ...]

    @property
    def blocks_destructive_action(self) -> bool:
        return (
            self.result
            is not DestructiveProtectionGateResult.PASSED_NO_PROTECTED_SIGNAL
        )


_DOMAIN_KEYWORDS: dict[ProtectedDomain, tuple[str, ...]] = {
    ProtectedDomain.HEALTH_MEDICAL: (
        "health",
        "medical",
        "doctor",
        "hospital",
        "clinic",
        "prescription",
        "diagnosis",
        "lab report",
        "salute",
        "medico",
        "sanitario",
        "referto",
        "ricetta",
    ),
    ProtectedDomain.TAX_FISCAL: (
        "tax",
        "fiscal",
        "tax return",
        "f24",
        "730",
        "vat",
        "iva",
        "certificazione unica",
        "agenzia entrate",
        "dichiarazione redditi",
    ),
    ProtectedDomain.BANKING_FINANCIAL: (
        "banking",
        "bank account",
        "bank statement",
        "account statement",
        "loan",
        "mortgage",
        "iban",
        "banca",
        "conto corrente",
        "estratto conto",
        "mutuo",
        "finanziamento",
    ),
    ProtectedDomain.INSURANCE: (
        "insurance",
        "insurance policy",
        "claim",
        "premium",
        "polizza",
        "assicurazione",
        "sinistro",
    ),
    ProtectedDomain.CONTRACTS_EMPLOYMENT: (
        "contract",
        "agreement",
        "employment",
        "employment contract",
        "payroll",
        "salary",
        "contratto",
        "assunzione",
        "busta paga",
        "rapporto di lavoro",
    ),
    ProtectedDomain.PENSIONS_BENEFITS_PUBLIC_ADMIN: (
        "pension",
        "benefit",
        "social security",
        "public administration",
        "inps",
        "pensione",
        "prestazione",
        "sussidio",
        "pubblica amministrazione",
        "previdenza",
    ),
    ProtectedDomain.IDENTITY_AUTHENTICATION: (
        "identity card",
        "passport",
        "authentication record",
        "authentication code",
        "credential record",
        "carta identita",
        "carta d identita",
        "passaporto",
        "credenziali",
        "autenticazione",
    ),
    ProtectedDomain.EDUCATION: (
        "education",
        "school record",
        "university",
        "academic transcript",
        "transcript",
        "diploma",
        "degree",
        "scuola",
        "universita",
        "carriera scolastica",
        "carriera universitaria",
    ),
    ProtectedDomain.LEGAL: (
        "legal",
        "lawyer",
        "attorney",
        "court",
        "lawsuit",
        "summons",
        "legal notice",
        "avvocato",
        "tribunale",
        "giudice",
        "diffida",
        "atto giudiziario",
    ),
    ProtectedDomain.PAYMENTS_RECEIPTS_INVOICES: (
        "payment",
        "receipt",
        "invoice",
        "payment receipt",
        "payment confirmation",
        "pagamento",
        "ricevuta",
        "fattura",
        "quietanza",
    ),
}

_DOCUMENT_HINT_TO_DOMAIN: dict[str, ProtectedDomain] = {
    "protected_domain:health_medical": ProtectedDomain.HEALTH_MEDICAL,
    "protected_domain:tax_fiscal": ProtectedDomain.TAX_FISCAL,
    "protected_domain:banking_financial": ProtectedDomain.BANKING_FINANCIAL,
    "protected_domain:insurance": ProtectedDomain.INSURANCE,
    "protected_domain:contracts_employment": ProtectedDomain.CONTRACTS_EMPLOYMENT,
    "protected_domain:pensions_benefits_public_admin": (
        ProtectedDomain.PENSIONS_BENEFITS_PUBLIC_ADMIN
    ),
    "protected_domain:identity_authentication": (
        ProtectedDomain.IDENTITY_AUTHENTICATION
    ),
    "protected_domain:education": ProtectedDomain.EDUCATION,
    "protected_domain:legal": ProtectedDomain.LEGAL,
    "protected_domain:payments_receipts_invoices": (
        ProtectedDomain.PAYMENTS_RECEIPTS_INVOICES
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


def _domain_matches(value: str) -> dict[ProtectedDomain, tuple[str, ...]]:
    if not value:
        return {}

    return {
        domain: matches
        for domain, keywords in _DOMAIN_KEYWORDS.items()
        if (matches := _matches(value, keywords))
    }


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


def _add_text_source(
    scores: dict[ProtectedDomain, float],
    evidence: dict[ProtectedDomain, list[ProtectionEvidence]],
    *,
    signal: str,
    value: str,
    contribution: float,
) -> None:
    for domain, matches in _domain_matches(value).items():
        scores[domain] += contribution
        evidence[domain].append(
            ProtectionEvidence(
                signal=signal,
                detail=(
                    f"{signal} matched {domain.value} cue(s): "
                    + ", ".join(sorted(set(matches)))
                ),
                contribution=contribution,
            )
        )


def _add_document_sources(
    scores: dict[ProtectedDomain, float],
    evidence: dict[ProtectedDomain, list[ProtectionEvidence]],
    document_candidates: Iterable[DocumentCandidate],
) -> None:
    strongest: dict[ProtectedDomain, DocumentCandidate] = {}

    for candidate in document_candidates:
        mapped_domains = {
            _DOCUMENT_HINT_TO_DOMAIN[hint]
            for hint in candidate.protection_hints
            if hint in _DOCUMENT_HINT_TO_DOMAIN
        }
        for domain in mapped_domains:
            current = strongest.get(domain)
            if (
                current is None
                or candidate.confidence_score > current.confidence_score
            ):
                strongest[domain] = candidate

    for domain, candidate in strongest.items():
        contribution = min(max(candidate.confidence_score, 0.0), 1.0)
        scores[domain] += contribution
        evidence[domain].append(
            ProtectionEvidence(
                signal="document_candidate",
                detail=(
                    "Document-significance output mapped to "
                    f"{domain.value} from class {candidate.document_class.value}."
                ),
                contribution=contribution,
            )
        )


def _build_hint(
    domain: ProtectedDomain,
    raw_score: float,
    evidence: list[ProtectionEvidence],
) -> ProtectedDomainHint:
    score = min(max(raw_score, 0.0), 1.0)
    final_evidence = list(evidence)

    if score != raw_score:
        final_evidence.append(
            ProtectionEvidence(
                signal="score_clamp",
                detail=(
                    "Protection score was clamped to the 0.00-1.00 policy range."
                ),
                contribution=score - raw_score,
            )
        )

    return ProtectedDomainHint(
        domain=domain,
        confidence_score=score,
        confidence_band=_confidence_band(score),
        evidence=tuple(final_evidence),
    )


def infer_protected_domains(
    message: MessageSnapshot,
    document_candidates: Iterable[DocumentCandidate] = (),
    classifier: LabelClassifier | None = None,
    coverage: ProtectionCoverage = ProtectionCoverage.PARTIAL,
) -> ProtectedDomainAssessment:
    """Infer protected-domain hints without mutating provider state."""

    candidates = tuple(document_candidates)

    if any(
        candidate.message_id != message.message_id
        for candidate in candidates
    ):
        raise ValueError(
            "document_candidates must belong to the assessed message"
        )

    scores = {domain: 0.0 for domain in ProtectedDomain}
    evidence = {domain: [] for domain in ProtectedDomain}

    _add_text_source(
        scores,
        evidence,
        signal="subject_context",
        value=_normalized(message.normalized_subject),
        contribution=0.65,
    )
    _add_text_source(
        scores,
        evidence,
        signal="taxonomy_context",
        value=_normalized(
            " ".join(_semantic_taxonomy_terms(message, classifier))
        ),
        contribution=0.75,
    )
    _add_text_source(
        scores,
        evidence,
        signal="correspondent_context",
        value=_normalized(" ".join(message.correspondents)),
        contribution=0.20,
    )
    _add_document_sources(scores, evidence, candidates)

    hints = tuple(
        _build_hint(domain, scores[domain], evidence[domain])
        for domain in ProtectedDomain
        if scores[domain] > 0.0
    )

    return ProtectedDomainAssessment(
        message_id=message.message_id,
        hints=hints,
        coverage=coverage,
    )


def evaluate_destructive_protection_gate(
    assessment: ProtectedDomainAssessment,
) -> DestructiveProtectionGate:
    """Evaluate only the protected-domain gate; never authorize deletion."""

    domains = tuple(hint.domain for hint in assessment.hints)

    if assessment.status is ProtectionStatus.PROTECTED:
        return DestructiveProtectionGate(
            result=(
                DestructiveProtectionGateResult.BLOCKED_PROTECTED_DOMAIN
            ),
            blocking_domains=domains,
            reasons=("protected_domain_signal",),
        )

    if assessment.status is ProtectionStatus.POSSIBLY_PROTECTED:
        return DestructiveProtectionGate(
            result=(
                DestructiveProtectionGateResult.BLOCKED_POSSIBLE_DOMAIN
            ),
            blocking_domains=domains,
            reasons=("possible_protected_domain_signal",),
        )

    if assessment.status is ProtectionStatus.UNKNOWN:
        return DestructiveProtectionGate(
            result=DestructiveProtectionGateResult.BLOCKED_UNKNOWN,
            blocking_domains=(),
            reasons=("protected_domain_classification_unknown",),
        )

    return DestructiveProtectionGate(
        result=DestructiveProtectionGateResult.PASSED_NO_PROTECTED_SIGNAL,
        blocking_domains=(),
        reasons=(
            "complete_protection_assessment_has_no_protected_domain_signal",
            "protection_gate_pass_does_not_authorize_destructive_action",
        ),
    )
