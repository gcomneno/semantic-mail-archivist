from __future__ import annotations

from dataclasses import dataclass

from .audit import MailboxAuditReport, build_mailbox_audit
from .ingestion import (
    ProviderAwareLabelClassifier,
    ingest_provider_mailbox,
)
from .model import LabelClassifier
from .provider import ProviderReadAdapter


@dataclass(frozen=True)
class ProviderMailboxAuditResult:
    """Result of provider read -> ingestion -> existing audit engine."""

    report: MailboxAuditReport
    complete: bool


def build_provider_mailbox_audit(
    provider: ProviderReadAdapter,
    user_label_classifier: LabelClassifier,
    *,
    max_threads: int | None = None,
    thread_page_size: int | None = None,
) -> ProviderMailboxAuditResult:
    """Build the existing mailbox audit from provider read facts.

    This function owns orchestration only. It deliberately does not duplicate
    any classification, inference, protection, obsolescence or audit logic.
    """

    ingestion = ingest_provider_mailbox(
        provider,
        max_threads=max_threads,
        thread_page_size=thread_page_size,
    )

    classifier = ProviderAwareLabelClassifier(
        ingestion.labels,
        user_label_classifier,
    )

    report = build_mailbox_audit(
        classifier=classifier,
        **ingestion.audit_inputs(),
    )

    return ProviderMailboxAuditResult(
        report=report,
        complete=ingestion.complete,
    )
