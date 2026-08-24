# Mailbox Audit Report

Status: **Initial contract**

Version: **1.0**

Issue: **#9 — Produce a complete mailbox audit report**

## Purpose

The mailbox audit composes the existing read-only analyzers into one coherent
mailbox-level view.

It does not introduce a new semantic classifier.

The audit answers questions such as:

- how many messages were analysed;
- what semantic taxonomy is currently visible;
- where message-level semantic label gaps exist;
- which gaps have HIGH-confidence additive repair proposals;
- which repair cases require review;
- which gaps contain explicit ambiguity/conflict, including cases where no
  proposal is safe;
- which gaps remain unresolved;
- which attachments are significant documents;
- which protected-domain hints exist;
- which messages appear obsolete or low-value;
- which operational-state opportunities exist when the operational layer is
  enabled;
- which provider facts were missing, partial, or unsupported.

## Architecture

The contract is deliberately:

    explicit facts in -> read-only audit out

The audit reuses:

- message-level gap detection and repair reporting;
- document-significance assessment;
- protected-domain inference;
- obsolescence assessment;
- optional operational-state assessment.

It does not duplicate their policy rules.

Each message produces one `AuditMessageRecord` containing the outputs of all
applicable dimensions. This allows, for example, a message to be both
semantically obsolete and protected while still retaining the conservative
`RETAIN` recommendation produced by the obsolescence layer.

## Missing provider facts

The audit never invents absent provider facts.

If attachment metadata is missing while a message says that attachments exist,
the report records `missing_attachment_metadata`.

If complete protected-domain coverage was requested for that same message, the
audit downgrades effective coverage to `PARTIAL` and records
`protection_coverage_downgraded`. Missing attachment evidence can therefore
never coexist with an audit claim of complete protection coverage.

Conversely, attachment metadata supplied for a message whose
`has_attachment` flag is false is rejected as contradictory provider input.

If no obsolescence context is supplied, an empty/unknown context is used and
the report records `missing_obsolescence_context`.

If complete protected-domain coverage is not explicitly supplied, coverage is
`PARTIAL` and the report records `partial_protection_coverage`.

Absence of a protected-domain hint under partial coverage is therefore never
reported as proof that a message is safe for destructive action.

Provider-specific limitations can be supplied explicitly as
`ProviderLimitation` records.

## Read-only boundary

The mailbox audit is M0/read-only.

The report always exposes:

    mutation_authorization = DENIED
    execution_status = NOT_EXECUTED

The audit performs no provider mutation.

It does not:

- add or remove labels;
- create operational labels;
- archive or move messages;
- Trash messages;
- permanently delete messages;
- create tasks, reminders, or calendar events.

A future write-capable workflow must remain a separate authorization layer.

## Stable machine-readable output

`MailboxAuditReport.to_dict()` defines the machine-readable schema.

`render_mailbox_audit_json()` emits deterministic compact JSON with sorted
keys.

The top-level schema contains:

- schema version;
- read-only mode and execution boundary;
- summary counts;
- user taxonomy summary;
- per-message records;
- warnings;
- provider limitations.

Summary counts are derived from the same per-message records included in the
report, so they can be independently traced and recomputed.

## Human-readable output

`render_mailbox_audit_text()` presents the same audit dimensions without
dumping message contents.

The human report includes:

- summary counts;
- taxonomy overview;
- one compact line group per message;
- warnings;
- provider limitations.

## Privacy

The default audit does not include:

- message bodies;
- credentials or tokens;
- authentication codes;
- attachment contents;
- correspondent identifiers;
- attachment filenames in the machine or human audit representation.

Existing analyzer evidence remains metadata-level and cue-oriented rather than
echoing complete private subjects or attachment contents.

## Operational state

The operational layer remains independently configurable.

When disabled, the per-message operational assessment reports `DISABLED` and
creates no operational opportunities.

When enabled, existing `USER_OPERATIONAL` labels can be reused according to
the operational-layer contract.

## CLI integration

The local CLI exposes the audit entrypoint:

    semantic-mail-archivist audit

The original issue #9 contract remains the provider-independent audit API and
renderer boundary.

The current repository now also implements the Gmail-backed path:

    CLI
      -> Gmail READ_ONLY authorization
      -> GmailReadAdapter
      -> provider-neutral ingestion
      -> existing mailbox audit engine
      -> human / JSON audit renderer

The provider integration supplies facts only and does not introduce a second
analysis path or move semantic/safety policy into Gmail-specific code.

See `gmail-audit-cli.md` and `gmail-read-only-ingestion.md` for the provider and
CLI details.
