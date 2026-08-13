# Gmail-backed repair dry-run

Issue #29 connects the existing repair detection, confidence inference and
dry-run reporting pipeline to real Gmail read-only data.

The path is:

    CLI
        -> Gmail READ_ONLY authorization
        -> GmailReadAdapter
        -> provider-neutral ingestion
        -> ProviderAwareLabelClassifier
        -> existing message-level gap detection
        -> existing confidence inference
        -> existing DryRunReport policy
        -> canonical dry-run proposal references
        -> human / JSON CLI output

No detection, confidence or mutation policy is duplicated in the CLI layer.

## Read-only invariant

The command:

    semantic-mail-archivist repair --dry-run

uses the same read-only Gmail provider factory as `audit`.

It therefore requests only:

    GmailAuthorizationMode.READ_ONLY

The dry-run path never requests or invokes:

- `M1_WRITE`;
- provider mutation methods;
- fresh mutation-preflight state;
- add/remove label operations;
- archive;
- Trash;
- permanent deletion.

Every dry-run candidate continues to carry:

    mutation_authorization = DENIED
    execution_status = NOT_EXECUTED

according to the existing foundation report.

`repair --apply` remains disabled.

## Default command

The following are equivalent:

    semantic-mail-archivist repair

and:

    semantic-mail-archivist repair --dry-run

Both are read-only.

## Bounded road-test mode

A small provider slice can be inspected with:

    semantic-mail-archivist \
        repair \
        --dry-run \
        --max-threads 10

An optional thread-list page-size hint is also available:

    semantic-mail-archivist \
        repair \
        --dry-run \
        --max-threads 10 \
        --thread-page-size 25

Both values must be positive integers.

Provider ingestion still marks an intentionally truncated traversal as
incomplete.

No real mailbox data belongs in repository fixtures or commits.

## Full-mailbox output

A mailbox-wide dry-run can contain one record for every detected gap.

For that reason an unbounded repair dry-run requires an explicit local output
destination:

    semantic-mail-archivist \
        --output ~/.local/state/semantic-mail-archivist/reports/repair.txt \
        repair --dry-run

JSON can be selected explicitly:

    semantic-mail-archivist \
        --format json \
        --output ~/.local/state/semantic-mail-archivist/reports/repair.json \
        repair --dry-run

The CLI output writer established by issue #28 uses a private temporary file,
flush/fsync, atomic replacement and mode `0600` on POSIX.

Bounded road-test output may remain on stdout.

## Mailbox-wide aggregation

The foundation function:

    build_dry_run_report(thread, classifier)

remains a per-thread operation.

Issue #29 does not replace it.

The provider orchestration layer:

1. ingests provider facts;
2. creates `ProviderAwareLabelClassifier`;
3. calls the existing dry-run report for each thread;
4. combines candidate entries deterministically by thread/message identifier.

Detection, inference and recommendation decisions therefore remain owned by
the original foundation modules.

## Outcomes

The existing three result families are preserved unchanged:

- `ELIGIBLE_FOR_ADDITIVE_REPAIR`
- `REVIEW_REQUIRED`
- `NO_ACTION`

An eligible M1 proposal is still not authorized or executed in dry-run mode.

Ambiguous or conflicting evidence remains review/no-action according to the
existing inference and reporting policy.

## Stable proposal correlation identifiers

Issue #10 already established:

    correlation_id_for_dry_run(candidate)

and:

    DryRunProposalReference

Issue #29 reuses that exact contract.

The original `DryRunCandidateReport.to_dict()` representation is not modified,
because that representation is an input to the canonical correlation hash.

Machine output therefore keeps the existing foundation entries unchanged and
adds a separate:

    proposal_references

array.

Each reference contains the canonical correlation identifier plus the stable
proposal metadata required by later apply/journal work.

The same correlation IDs are surfaced in human output.

## Machine output

Machine output retains the existing dry-run fields:

    schema_version
    mode
    entries

and adds provider-orchestration context:

    complete
    proposal_references
    provider_limitations

Each entry itself retains the existing foundation shape.

JSON serialization is deterministic.

## Privacy

The existing dry-run report omits:

- message bodies;
- attachment contents;
- credentials;
- OAuth tokens;
- raw provider response bodies.

Issue #29 does not add those fields.

Correlation identifiers are deterministic hashes of the existing safe
candidate record; they are not credentials or provider mutation tokens.

## Provider limitations

Read-side provider limitations remain visible in the CLI result rather than
being silently discarded.

This includes limitations surfaced by Gmail ingestion and bounded selection.

## Testing

End-to-end tests cover:

- HIGH / eligible additive repair;
- MEDIUM / human review;
- conflicting evidence / no action;
- stable correlation identifiers;
- deterministic JSON;
- provider read-only surface only;
- full-mailbox output gating;
- `repair --apply` remaining disabled;
- real `GmailReadAdapter` snapshots through a synthetic Gmail transport.

No Gmail credentials, network access or real mailbox data are required.
