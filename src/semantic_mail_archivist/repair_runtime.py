from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .audit import ProviderLimitation
from .change_log import DryRunProposalReference
from .ingestion import (
    ProviderAwareLabelClassifier,
    ingest_provider_mailbox,
)
from .model import LabelClassifier
from .provider import ProviderReadAdapter
from .reporting import (
    DryRunCandidateReport,
    DryRunReport,
    build_dry_run_report,
    render_dry_run_text,
)


@dataclass(frozen=True)
class ProviderMailboxDryRunResult:
    """Mailbox-wide dry-run plus provider-read context."""

    report: DryRunReport
    provider_limitations: tuple[ProviderLimitation, ...]
    complete: bool

    @property
    def proposal_references(
        self,
    ) -> tuple[DryRunProposalReference, ...]:
        return tuple(
            DryRunProposalReference.from_candidate(entry)
            for entry in self.report.entries
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize without changing the foundation candidate schema.

        `entries` remain exactly the existing DryRunReport entries.
        Stable correlation identifiers travel separately through the canonical
        DryRunProposalReference contract established by the change log.
        """

        payload = self.report.to_dict()

        payload["complete"] = self.complete
        payload["proposal_references"] = [
            reference.to_dict()
            for reference in self.proposal_references
        ]
        payload["provider_limitations"] = [
            {
                "code": limitation.code,
                "detail": limitation.detail,
            }
            for limitation in self.provider_limitations
        ]

        return payload


def _entry_sort_key(
    entry: DryRunCandidateReport,
) -> tuple[str, str]:
    return (
        entry.thread_id,
        entry.message_id,
    )


def build_provider_mailbox_dry_run(
    provider: ProviderReadAdapter,
    user_label_classifier: LabelClassifier,
    *,
    max_threads: int | None = None,
    thread_page_size: int | None = None,
) -> ProviderMailboxDryRunResult:
    """Run the existing per-thread dry-run pipeline over provider snapshots.

    This function owns orchestration only. Detection, inference, confidence,
    recommendation and mutation-denial policy remain in the existing
    foundation modules.
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

    entries: list[DryRunCandidateReport] = []

    for thread in ingestion.threads:
        entries.extend(
            build_dry_run_report(
                thread,
                classifier,
            ).entries
        )

    report = DryRunReport(
        entries=tuple(
            sorted(
                entries,
                key=_entry_sort_key,
            )
        )
    )

    return ProviderMailboxDryRunResult(
        report=report,
        provider_limitations=ingestion.provider_limitations,
        complete=ingestion.complete,
    )


def render_provider_mailbox_dry_run_json(
    result: ProviderMailboxDryRunResult,
) -> str:
    """Render deterministic machine output for the provider-backed dry-run."""

    return json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_provider_mailbox_dry_run_text(
    result: ProviderMailboxDryRunResult,
) -> str:
    """Extend the existing privacy-safe human renderer with safe references."""

    lines = [
        render_dry_run_text(
            result.report
        ),
        "",
        (
            "Provider selection: "
            + (
                "complete"
                if result.complete
                else "incomplete"
            )
        ),
        "",
        "Proposal references",
    ]

    references = result.proposal_references

    if references:
        for reference in references:
            lines.append(
                "  "
                + reference.message_id
                + ": "
                + reference.correlation_id
            )
    else:
        lines.append("  none")

    lines.extend(
        (
            "",
            "Provider limitations",
        )
    )

    if result.provider_limitations:
        for limitation in result.provider_limitations:
            lines.append(
                "  "
                + limitation.code
                + ": "
                + limitation.detail
            )
    else:
        lines.append("  none")

    return "\n".join(lines)
