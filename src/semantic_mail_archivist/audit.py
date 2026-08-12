from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Iterable, Mapping

from .documents import (
    AttachmentSnapshot,
    DocumentCandidate,
    DocumentSignificance,
    assess_document_significance,
)
from .model import (
    LabelClass,
    LabelClassifier,
    MessageSnapshot,
    ThreadSnapshot,
)
from .obsolescence import (
    ObsolescenceAssessment,
    ObsolescenceClass,
    ObsolescenceContext,
    assess_message_obsolescence,
)
from .operational import (
    OperationalLayerConfig,
    OperationalStateAssessment,
    assess_operational_state,
)
from .protection import (
    ProtectedDomainAssessment,
    ProtectionCoverage,
    infer_protected_domains,
)
from .reporting import (
    DryRunCandidateReport,
    ExecutionStatus,
    MutationAuthorization,
    RepairRecommendation,
    build_dry_run_report,
)


AUDIT_SCHEMA_VERSION = "1.0"


class AuditWarningCode(str, Enum):
    MISSING_ATTACHMENT_METADATA = "missing_attachment_metadata"
    MISSING_OBSOLESCENCE_CONTEXT = "missing_obsolescence_context"
    PROTECTION_COVERAGE_DOWNGRADED = "protection_coverage_downgraded"
    PARTIAL_PROTECTION_COVERAGE = "partial_protection_coverage"


@dataclass(frozen=True)
class AuditWarning:
    code: AuditWarningCode
    detail: str
    message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "message_id": self.message_id,
        }


@dataclass(frozen=True)
class ProviderLimitation:
    code: str
    detail: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("provider limitation code cannot be empty")
        if not self.detail.strip():
            raise ValueError("provider limitation detail cannot be empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TaxonomyLabelSummary:
    label: str
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "message_count": self.message_count,
        }


@dataclass(frozen=True)
class AuditSummary:
    messages_analyzed: int
    semantic_taxonomy_labels: int
    message_level_label_gaps: int
    high_confidence_repair_candidates: int
    repair_candidates_requiring_review: int
    ambiguous_repair_candidates: int
    unresolved_label_gaps: int
    significant_document_candidates: int
    unknown_document_candidates: int
    protected_domain_candidates: int
    messages_with_protected_domain_candidates: int
    obsolete_low_value_candidates: int
    future_trash_review_candidates: int
    operational_state_opportunities: int
    warnings: int
    provider_limitations: int

    def to_dict(self) -> dict[str, int]:
        return {
            "messages_analyzed": self.messages_analyzed,
            "semantic_taxonomy_labels": self.semantic_taxonomy_labels,
            "message_level_label_gaps": self.message_level_label_gaps,
            "high_confidence_repair_candidates": (
                self.high_confidence_repair_candidates
            ),
            "repair_candidates_requiring_review": (
                self.repair_candidates_requiring_review
            ),
            "ambiguous_repair_candidates": self.ambiguous_repair_candidates,
            "unresolved_label_gaps": self.unresolved_label_gaps,
            "significant_document_candidates": (
                self.significant_document_candidates
            ),
            "unknown_document_candidates": self.unknown_document_candidates,
            "protected_domain_candidates": self.protected_domain_candidates,
            "messages_with_protected_domain_candidates": (
                self.messages_with_protected_domain_candidates
            ),
            "obsolete_low_value_candidates": self.obsolete_low_value_candidates,
            "future_trash_review_candidates": (
                self.future_trash_review_candidates
            ),
            "operational_state_opportunities": (
                self.operational_state_opportunities
            ),
            "warnings": self.warnings,
            "provider_limitations": self.provider_limitations,
        }


def _evidence_to_dict(items: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "signal": item.signal,
            "detail": item.detail,
            "contribution": item.contribution,
        }
        for item in items
    ]


def _document_to_dict(candidate: DocumentCandidate) -> dict[str, Any]:
    # Deliberately omit filename and attachment contents from the audit schema.
    return {
        "message_id": candidate.message_id,
        "attachment_id": candidate.attachment_id,
        "document_class": candidate.document_class.value,
        "significance": candidate.significance.value,
        "confidence_score": candidate.confidence_score,
        "confidence_band": candidate.confidence_band.value,
        "evidence": _evidence_to_dict(candidate.evidence),
        "protection_hints": list(candidate.protection_hints),
    }


def _protection_to_dict(
    assessment: ProtectedDomainAssessment,
) -> dict[str, Any]:
    return {
        "message_id": assessment.message_id,
        "status": assessment.status.value,
        "coverage": assessment.coverage.value,
        "hints": [
            {
                "domain": hint.domain.value,
                "confidence_score": hint.confidence_score,
                "confidence_band": hint.confidence_band.value,
                "evidence": _evidence_to_dict(hint.evidence),
            }
            for hint in assessment.hints
        ],
    }


def _obsolescence_to_dict(
    assessment: ObsolescenceAssessment,
) -> dict[str, Any]:
    return {
        "message_id": assessment.message_id,
        "obsolescence_class": assessment.obsolescence_class.value,
        "confidence_score": assessment.confidence_score,
        "confidence_band": assessment.confidence_band.value,
        "evidence": _evidence_to_dict(assessment.evidence),
        "protection_conflicts": [
            conflict.value
            for conflict in assessment.protection_conflicts
        ],
        "recommendation": assessment.recommendation.value,
        "future_trash_candidate": assessment.future_trash_candidate,
    }


def _operational_to_dict(
    assessment: OperationalStateAssessment,
) -> dict[str, Any]:
    return {
        "message_id": assessment.message_id,
        "enabled": assessment.enabled,
        "current_states": [
            state.value for state in assessment.current_states
        ],
        "proposals": [
            {
                "state": proposal.state.value,
                "label": proposal.label,
                "confidence_score": proposal.confidence_score,
                "confidence_band": proposal.confidence_band.value,
                "evidence": _evidence_to_dict(proposal.evidence),
                "reuses_existing_label": proposal.reuses_existing_label,
                "requires_label_creation": proposal.requires_label_creation,
            }
            for proposal in assessment.proposals
        ],
        "conflicts": [
            conflict.value for conflict in assessment.conflicts
        ],
        "unmapped_operational_labels": list(
            assessment.unmapped_operational_labels
        ),
        "recommendation": assessment.recommendation.value,
        "mutation_authorization": assessment.mutation_authorization.value,
        "execution_status": assessment.execution_status.value,
    }


@dataclass(frozen=True)
class AuditMessageRecord:
    thread_id: str
    message_id: str
    repair: DryRunCandidateReport | None
    documents: tuple[DocumentCandidate, ...]
    protection: ProtectedDomainAssessment
    obsolescence: ObsolescenceAssessment
    operational: OperationalStateAssessment

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "repair": (
                self.repair.to_dict()
                if self.repair is not None
                else None
            ),
            "documents": [
                _document_to_dict(candidate)
                for candidate in self.documents
            ],
            "protection": _protection_to_dict(self.protection),
            "obsolescence": _obsolescence_to_dict(self.obsolescence),
            "operational": _operational_to_dict(self.operational),
        }


@dataclass(frozen=True)
class MailboxAuditReport:
    summary: AuditSummary
    taxonomy: tuple[TaxonomyLabelSummary, ...]
    records: tuple[AuditMessageRecord, ...]
    warnings: tuple[AuditWarning, ...]
    provider_limitations: tuple[ProviderLimitation, ...]
    schema_version: str = AUDIT_SCHEMA_VERSION
    mutation_authorization: MutationAuthorization = MutationAuthorization.DENIED
    execution_status: ExecutionStatus = ExecutionStatus.NOT_EXECUTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": "read_only_audit",
            "read_only": True,
            "mutation_authorization": self.mutation_authorization.value,
            "execution_status": self.execution_status.value,
            "summary": self.summary.to_dict(),
            "taxonomy": [
                item.to_dict()
                for item in self.taxonomy
            ],
            "records": [
                record.to_dict()
                for record in self.records
            ],
            "warnings": [
                warning.to_dict()
                for warning in self.warnings
            ],
            "provider_limitations": [
                limitation.to_dict()
                for limitation in self.provider_limitations
            ],
        }


def _validate_threads(
    threads: tuple[ThreadSnapshot, ...],
) -> tuple[tuple[str, MessageSnapshot], ...]:
    seen_threads: set[str] = set()
    seen_messages: set[str] = set()
    messages: list[tuple[str, MessageSnapshot]] = []

    for thread in threads:
        if thread.thread_id in seen_threads:
            raise ValueError(
                f"duplicate thread_id in mailbox audit: {thread.thread_id!r}"
            )
        seen_threads.add(thread.thread_id)

        for message in thread.messages:
            if message.message_id in seen_messages:
                raise ValueError(
                    "message_id must be unique across the mailbox audit: "
                    f"{message.message_id!r}"
                )
            seen_messages.add(message.message_id)
            messages.append((thread.thread_id, message))

    return tuple(messages)


def _validate_fact_keys(
    name: str,
    mapping: Mapping[str, Any],
    known_message_ids: set[str],
) -> None:
    unknown = sorted(set(mapping) - known_message_ids)
    if unknown:
        raise ValueError(
            f"{name} contains unknown message_id values: "
            + ", ".join(unknown)
        )


def _taxonomy_summary(
    messages: tuple[tuple[str, MessageSnapshot], ...],
    classifier: LabelClassifier,
    available_labels: tuple[str, ...],
) -> tuple[TaxonomyLabelSummary, ...]:
    counts: Counter[str] = Counter()
    labels = set(available_labels)

    for _, message in messages:
        labels.update(message.labels)
        for label in message.labels:
            if classifier.classify(label) is LabelClass.USER_SEMANTIC:
                counts[label] += 1

    semantic_labels = (
        label
        for label in labels
        if classifier.classify(label) is LabelClass.USER_SEMANTIC
    )

    return tuple(
        TaxonomyLabelSummary(
            label=label,
            message_count=counts[label],
        )
        for label in sorted(
            semantic_labels,
            key=lambda value: (value.casefold(), value),
        )
    )


def _summary(
    records: tuple[AuditMessageRecord, ...],
    taxonomy: tuple[TaxonomyLabelSummary, ...],
    warnings: tuple[AuditWarning, ...],
    provider_limitations: tuple[ProviderLimitation, ...],
) -> AuditSummary:
    repairs = tuple(
        record.repair
        for record in records
        if record.repair is not None
    )

    return AuditSummary(
        messages_analyzed=len(records),
        semantic_taxonomy_labels=len(taxonomy),
        message_level_label_gaps=len(repairs),
        high_confidence_repair_candidates=sum(
            repair.recommendation
            is RepairRecommendation.ELIGIBLE_FOR_ADDITIVE_REPAIR
            for repair in repairs
        ),
        repair_candidates_requiring_review=sum(
            repair.recommendation
            is RepairRecommendation.REVIEW_REQUIRED
            for repair in repairs
        ),
        ambiguous_repair_candidates=sum(
            bool(repair.conflicts)
            for repair in repairs
        ),
        unresolved_label_gaps=sum(
            repair.recommendation
            is RepairRecommendation.NO_ACTION
            for repair in repairs
        ),
        significant_document_candidates=sum(
            candidate.significance
            is DocumentSignificance.SIGNIFICANT_DOCUMENT
            for record in records
            for candidate in record.documents
        ),
        unknown_document_candidates=sum(
            candidate.significance
            is DocumentSignificance.UNKNOWN
            for record in records
            for candidate in record.documents
        ),
        protected_domain_candidates=sum(
            len(record.protection.hints)
            for record in records
        ),
        messages_with_protected_domain_candidates=sum(
            bool(record.protection.hints)
            for record in records
        ),
        obsolete_low_value_candidates=sum(
            record.obsolescence.obsolescence_class
            is not ObsolescenceClass.UNKNOWN
            for record in records
        ),
        future_trash_review_candidates=sum(
            record.obsolescence.future_trash_candidate
            for record in records
        ),
        operational_state_opportunities=sum(
            len(record.operational.proposals)
            for record in records
        ),
        warnings=len(warnings),
        provider_limitations=len(provider_limitations),
    )


def build_mailbox_audit(
    threads: Iterable[ThreadSnapshot],
    classifier: LabelClassifier,
    *,
    attachments_by_message: Mapping[
        str,
        Iterable[AttachmentSnapshot],
    ] | None = None,
    obsolescence_context_by_message: Mapping[
        str,
        ObsolescenceContext,
    ] | None = None,
    protection_coverage_by_message: Mapping[
        str,
        ProtectionCoverage,
    ] | None = None,
    operational_config: OperationalLayerConfig | None = None,
    available_labels: Iterable[str] = (),
    provider_limitations: Iterable[ProviderLimitation] = (),
) -> MailboxAuditReport:
    """Compose mailbox-level read-only analysis from explicit provider facts."""

    thread_tuple = tuple(threads)
    message_pairs = _validate_threads(thread_tuple)
    known_message_ids = {
        message.message_id
        for _, message in message_pairs
    }

    raw_attachments = attachments_by_message or {}
    raw_contexts = obsolescence_context_by_message or {}
    raw_coverages = protection_coverage_by_message or {}

    _validate_fact_keys(
        "attachments_by_message",
        raw_attachments,
        known_message_ids,
    )
    _validate_fact_keys(
        "obsolescence_context_by_message",
        raw_contexts,
        known_message_ids,
    )
    _validate_fact_keys(
        "protection_coverage_by_message",
        raw_coverages,
        known_message_ids,
    )

    attachments = {
        message_id: tuple(values)
        for message_id, values in raw_attachments.items()
    }

    for message_id, values in attachments.items():
        attachment_ids = [
            attachment.attachment_id
            for attachment in values
        ]
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError(
                "attachment_id must be unique within a message: "
                f"{message_id!r}"
            )

    mailbox_labels = tuple(
        sorted(
            {
                *available_labels,
                *(
                    label
                    for _, message in message_pairs
                    for label in message.labels
                ),
            },
            key=lambda value: (value.casefold(), value),
        )
    )

    repair_by_message: dict[str, DryRunCandidateReport] = {}
    for thread in thread_tuple:
        for entry in build_dry_run_report(thread, classifier).entries:
            repair_by_message[entry.message_id] = entry

    warnings: list[AuditWarning] = []
    records: list[AuditMessageRecord] = []

    for thread_id, message in message_pairs:
        attachment_values = tuple(
            sorted(
                attachments.get(message.message_id, ()),
                key=lambda attachment: attachment.attachment_id,
            )
        )

        if attachment_values and not message.has_attachment:
            raise ValueError(
                "attachment metadata was supplied for a message whose "
                "has_attachment flag is false: "
                f"{message.message_id!r}"
            )

        if message.has_attachment and not attachment_values:
            warnings.append(
                AuditWarning(
                    code=AuditWarningCode.MISSING_ATTACHMENT_METADATA,
                    message_id=message.message_id,
                    detail=(
                        "Message metadata indicates attachments, but no "
                        "attachment metadata was supplied to the audit."
                    ),
                )
            )

        document_candidates = tuple(
            assess_document_significance(
                message,
                attachment,
                classifier,
            )
            for attachment in attachment_values
        )

        requested_coverage = raw_coverages.get(
            message.message_id,
            ProtectionCoverage.PARTIAL,
        )
        coverage = requested_coverage

        if (
            message.has_attachment
            and not attachment_values
            and requested_coverage is ProtectionCoverage.COMPLETE
        ):
            coverage = ProtectionCoverage.PARTIAL
            warnings.append(
                AuditWarning(
                    code=AuditWarningCode.PROTECTION_COVERAGE_DOWNGRADED,
                    message_id=message.message_id,
                    detail=(
                        "Complete protected-domain coverage was requested, "
                        "but attachment metadata is missing; effective "
                        "coverage was downgraded to partial."
                    ),
                )
            )

        if coverage is ProtectionCoverage.PARTIAL:
            warnings.append(
                AuditWarning(
                    code=AuditWarningCode.PARTIAL_PROTECTION_COVERAGE,
                    message_id=message.message_id,
                    detail=(
                        "Protected-domain coverage is partial; absence of "
                        "hints is not proof that the message is unprotected."
                    ),
                )
            )

        protection = infer_protected_domains(
            message,
            document_candidates=document_candidates,
            classifier=classifier,
            coverage=coverage,
        )

        if message.message_id in raw_contexts:
            context = raw_contexts[message.message_id]
        else:
            context = ObsolescenceContext()
            warnings.append(
                AuditWarning(
                    code=AuditWarningCode.MISSING_OBSOLESCENCE_CONTEXT,
                    message_id=message.message_id,
                    detail=(
                        "No obsolescence context was supplied; unknown safety "
                        "fields remain explicit and conservative."
                    ),
                )
            )

        obsolescence = assess_message_obsolescence(
            message,
            context,
            document_candidates=document_candidates,
            protection_assessment=protection,
        )

        operational = assess_operational_state(
            message,
            classifier,
            config=operational_config,
            available_labels=mailbox_labels,
            document_candidates=document_candidates,
        )

        records.append(
            AuditMessageRecord(
                thread_id=thread_id,
                message_id=message.message_id,
                repair=repair_by_message.get(message.message_id),
                documents=document_candidates,
                protection=protection,
                obsolescence=obsolescence,
                operational=operational,
            )
        )

    record_tuple = tuple(
        sorted(
            records,
            key=lambda record: (
                record.thread_id,
                record.message_id,
            ),
        )
    )
    warning_tuple = tuple(
        sorted(
            warnings,
            key=lambda warning: (
                warning.code.value,
                warning.message_id or "",
                warning.detail,
            ),
        )
    )
    limitation_tuple = tuple(
        sorted(
            tuple(provider_limitations),
            key=lambda limitation: (
                limitation.code,
                limitation.detail,
            ),
        )
    )
    taxonomy = _taxonomy_summary(
        message_pairs,
        classifier,
        mailbox_labels,
    )

    return MailboxAuditReport(
        summary=_summary(
            record_tuple,
            taxonomy,
            warning_tuple,
            limitation_tuple,
        ),
        taxonomy=taxonomy,
        records=record_tuple,
        warnings=warning_tuple,
        provider_limitations=limitation_tuple,
    )


def render_mailbox_audit_json(report: MailboxAuditReport) -> str:
    """Return deterministic machine-readable mailbox audit JSON."""

    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_mailbox_audit_text(report: MailboxAuditReport) -> str:
    """Render a privacy-safe human-readable mailbox audit."""

    summary = report.summary

    lines = [
        "Semantic Mail Archivist — Mailbox audit report",
        f"Schema: {report.schema_version}",
        "Mode: READ ONLY — provider state will not be changed",
        "",
        "Summary",
        f"  Messages analysed: {summary.messages_analyzed}",
        (
            "  Semantic taxonomy labels: "
            f"{summary.semantic_taxonomy_labels}"
        ),
        (
            "  Message-level label gaps: "
            f"{summary.message_level_label_gaps}"
        ),
        (
            "  HIGH-confidence repair candidates: "
            f"{summary.high_confidence_repair_candidates}"
        ),
        (
            "  Repair candidates requiring review: "
            f"{summary.repair_candidates_requiring_review}"
        ),
        (
            "  Ambiguous repair candidates: "
            f"{summary.ambiguous_repair_candidates}"
        ),
        (
            "  Unresolved label gaps: "
            f"{summary.unresolved_label_gaps}"
        ),
        (
            "  Significant documents: "
            f"{summary.significant_document_candidates}"
        ),
        (
            "  Unknown document candidates: "
            f"{summary.unknown_document_candidates}"
        ),
        (
            "  Protected-domain hints: "
            f"{summary.protected_domain_candidates}"
        ),
        (
            "  Messages with protected-domain hints: "
            f"{summary.messages_with_protected_domain_candidates}"
        ),
        (
            "  Obsolete/low-value candidates: "
            f"{summary.obsolete_low_value_candidates}"
        ),
        (
            "  Future-Trash review candidates: "
            f"{summary.future_trash_review_candidates}"
        ),
        (
            "  Operational-state opportunities: "
            f"{summary.operational_state_opportunities}"
        ),
        f"  Warnings: {summary.warnings}",
        f"  Provider limitations: {summary.provider_limitations}",
        "",
        "User taxonomy",
    ]

    if report.taxonomy:
        for item in report.taxonomy:
            lines.append(
                f"  {item.label}: {item.message_count} message(s)"
            )
    else:
        lines.append("  none")

    lines.extend(("", "Message records"))

    if not report.records:
        lines.append("  none")

    for index, record in enumerate(report.records, start=1):
        repair = record.repair
        if repair is None:
            repair_text = "no message-level semantic gap"
        else:
            proposed = repair.proposed_label or "none"
            repair_conflicts = ", ".join(repair.conflicts) or "none"
            repair_text = (
                f"{repair.recommendation.value}; "
                f"proposed={proposed}; "
                f"confidence={repair.confidence_band.value} "
                f"{repair.confidence_score:.3f}; "
                f"conflicts={repair_conflicts}"
            )

        significant = sum(
            candidate.significance
            is DocumentSignificance.SIGNIFICANT_DOCUMENT
            for candidate in record.documents
        )
        generic = sum(
            candidate.significance
            is DocumentSignificance.GENERIC_ATTACHMENT
            for candidate in record.documents
        )
        unknown = sum(
            candidate.significance
            is DocumentSignificance.UNKNOWN
            for candidate in record.documents
        )

        domains = ", ".join(
            hint.domain.value
            for hint in record.protection.hints
        ) or "none"

        protection_conflicts = ", ".join(
            conflict.value
            for conflict in record.obsolescence.protection_conflicts
        ) or "none"

        current_states = ", ".join(
            state.value
            for state in record.operational.current_states
        ) or "none"
        proposed_states = ", ".join(
            proposal.state.value
            for proposal in record.operational.proposals
        ) or "none"
        operational_conflicts = ", ".join(
            conflict.value
            for conflict in record.operational.conflicts
        ) or "none"

        lines.extend(
            (
                "",
                f"  [{index}] Message: {record.message_id}",
                f"      Thread: {record.thread_id}",
                f"      Repair: {repair_text}",
                (
                    "      Documents: "
                    f"significant={significant}, "
                    f"generic={generic}, unknown={unknown}"
                ),
                (
                    "      Protection: "
                    f"{record.protection.status.value}; "
                    f"domains={domains}; "
                    f"coverage={record.protection.coverage.value}"
                ),
                (
                    "      Obsolescence: "
                    f"{record.obsolescence.obsolescence_class.value}; "
                    f"recommendation="
                    f"{record.obsolescence.recommendation.value}; "
                    f"conflicts={protection_conflicts}"
                ),
                (
                    "      Operational: "
                    f"{record.operational.recommendation.value}; "
                    f"current={current_states}; "
                    f"proposed={proposed_states}; "
                    f"conflicts={operational_conflicts}"
                ),
            )
        )

    lines.extend(("", "Warnings"))
    if report.warnings:
        for warning in report.warnings:
            scope = (
                f"[{warning.message_id}] "
                if warning.message_id is not None
                else ""
            )
            lines.append(
                f"  {scope}{warning.code.value}: {warning.detail}"
            )
    else:
        lines.append("  none")

    lines.extend(("", "Provider limitations"))
    if report.provider_limitations:
        for limitation in report.provider_limitations:
            lines.append(
                f"  {limitation.code}: {limitation.detail}"
            )
    else:
        lines.append("  none")

    return "\n".join(lines)
