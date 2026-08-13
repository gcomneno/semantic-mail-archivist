# Gmail-backed read-only audit CLI

Issue #28 connects the local CLI shell to the existing provider-neutral mailbox
audit engine.

The audit path is:

    CLI configuration
        -> READ_ONLY Gmail authorization
        -> GmailReadAdapter
        -> provider-neutral mailbox ingestion
        -> ProviderAwareLabelClassifier
        -> existing build_mailbox_audit()
        -> existing human / JSON audit renderers

No second audit engine is introduced.

## Read-only invariant

The command:

    semantic-mail-archivist audit

uses only the provider read adapter.

The Gmail provider factory requests:

    GmailAuthorizationMode.READ_ONLY

`GmailReadAdapter` independently rejects any non-read-only auth session.

The audit path does not request:

- M1 write authorization;
- mutation capabilities;
- fresh mutation-preflight state;
- add/remove label operations;
- archive;
- Trash;
- permanent deletion.

## Local configuration

A minimal configuration remains:

    [mailbox]
    provider = "gmail"
    account = "personal"

`account` remains a local descriptive alias. It is not passed to Gmail as an
email address and is never a token or credential.

Issue #28 continues to use the single private Gmail authorization store
established by issue #25. Multiple named auth stores are not introduced here.

The OAuth client configuration and tokens remain outside this TOML file.

## Full-mailbox audit

A full-mailbox report can be large in either human or JSON form because the
existing audit renderers include per-message records.

Unbounded audit therefore requires an explicit local output destination.

Human-readable full audit:

    semantic-mail-archivist         --output ~/.local/state/semantic-mail-archivist/reports/audit.txt         audit

Human output remains privacy-safe according to the existing mailbox audit
renderer. It omits full message bodies, attachment contents and the sensitive
fields already excluded by the audit schema.

A bounded road-test may still render directly to stdout.

## Bounded road test

A development/road-test run can inspect a small mailbox slice:

    semantic-mail-archivist audit --max-threads 10

An optional provider page-size hint is available:

    semantic-mail-archivist audit \
        --max-threads 10 \
        --thread-page-size 25

Both values must be positive integers.

A bounded run is not presented as complete. Existing ingestion records:

    bounded_mailbox_selection

and the limitation flows unchanged into the existing mailbox audit report.

No real mailbox content belongs in repository fixtures or commits.

## Machine-readable audit

Machine output uses the existing mailbox audit JSON schema directly:

    semantic-mail-archivist \
        --format json \
        audit \
        --max-threads 10

The CLI does not wrap that report in a second command schema.

The existing audit fields therefore retain their semantics, including:

- schema version;
- read-only mode;
- summary;
- taxonomy;
- per-message audit records;
- warnings;
- provider limitations.

## Large full-mailbox reports

Full-mailbox reports can be large and may contain provider-safe message and
thread identifiers.

For that reason every unbounded audit requires an explicit local output
destination. JSON is selected explicitly:

    semantic-mail-archivist \
        --format json \
        --output ~/.local/state/semantic-mail-archivist/reports/audit.json \
        audit

The CLI writes explicit output destinations through a private temporary file,
flushes and fsyncs it, atomically replaces the destination and sets the final
file mode to `0600` on POSIX systems.

Bounded JSON road-test output may still be printed to stdout explicitly.

## Provider limitations

Provider limitations are not swallowed by the CLI.

Limitations discovered by the Gmail adapter and ingestion layer flow into the
existing `MailboxAuditReport.provider_limitations` field and are rendered by
both existing audit renderers.

Examples include:

- intentionally bounded mailbox selection;
- incomplete provider label catalog;
- incomplete attachment metadata;
- Gmail metadata limitations already surfaced by the provider adapter.

## User label semantics

Provider ownership and semantic classification remain separate.

`ProviderAwareLabelClassifier` treats provider-managed Gmail labels as system
labels authoritatively.

For Gmail user-owned labels the runtime delegates to the existing
`GmailLabelClassifier`.

The provider adapter itself still does not make semantic decisions.

## Authentication failures

Authentication failures use the redacted safe details established by issue #25.

Provider transport failures use the redacted `ProviderOperationError` details
established by issue #24/#26.

Raw OAuth responses, credentials, tokens and provider response bodies are not
printed by the CLI error path.

## Testing

End-to-end CLI audit tests use a synthetic `ProviderReadAdapter` and an injected
synthetic label classifier.

They require:

- no Gmail credentials;
- no OAuth flow;
- no network access;
- no real mailbox data;
- no provider mutation implementation.
