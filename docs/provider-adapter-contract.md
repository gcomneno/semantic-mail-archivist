# Provider Adapter Contract

Status: **Phase 2 provider boundary**

Issue: **#24 — Define the provider adapter contract for real mailbox access**

## Purpose

The provider adapter boundary connects real mailbox state to the existing
provider-independent Semantic Mail Archivist core.

Provider code supplies facts.

Provider code does not decide:

- what a message means;
- whether a user label is semantic or operational;
- confidence;
- mutation class;
- mutation authorization;
- safety thresholds;
- whether a write should occur.

Those decisions remain in the existing core contracts.

## Existing core types remain canonical

The provider boundary deliberately reuses:

- `AttachmentSnapshot`;
- `ProviderLimitation`.

Message transport is intentionally separate. `ProviderMessageSnapshot`
contains only provider facts and has no `semantic_label_hints` field.

The Phase 2 ingestion layer (#26) is responsible for translating raw provider
message facts and label identifiers into the existing core `MessageSnapshot`
and `ThreadSnapshot` types.

This separation prevents a provider adapter from silently supplying semantic
inference hints while still avoiding a parallel semantic domain model.

## Account identity

`ProviderIdentity` exposes:

- provider identity;
- an `account_safe_id`.

`account_safe_id` must be safe for local reports and audit records. A provider
implementation must not assume that the user's raw email address is an
appropriate logging identifier.

## Provider label facts

`ProviderLabelSnapshot` contains:

- provider label identifier;
- display name;
- provider-level ownership kind;
- user-visible status.

`ProviderLabelKind` distinguishes only:

- `PROVIDER_SYSTEM`;
- `USER`;
- `UNKNOWN`.

This is intentionally weaker than the core `LabelClass`.

In particular, the provider adapter must not classify a user-owned label as
`USER_SEMANTIC` or `USER_OPERATIONAL`. That remains application/core policy.

## Read surface

`ProviderReadAdapter` exposes only read operations:

- descriptor/capability discovery;
- label listing;
- paged thread references;
- paged message snapshots within a thread;
- attachment metadata;
- fresh message state.

The contract contains no mutation method.

A provider may report a capability as unsupported and surface a redacted
`ProviderOperationError` or `ProviderLimitation`.

## Pagination

`ProviderPage` contains:

- a tuple of items;
- an opaque optional continuation token.

Tokens are provider implementation details. Core policy must not inspect or
derive semantics from them.

Both threads and messages are independently pageable so the contract does not
assume that every provider exposes mailbox hierarchy in the same way.

`list_messages()` returns `ProviderMessageSnapshot`, not the semantic core
`MessageSnapshot`. The provider therefore supplies raw IDs and metadata;
translation into user-visible label names and core semantic inputs belongs to
the ingestion layer.

## Attachment privacy

`list_attachments()` returns `AttachmentSnapshot` metadata.

The provider read contract has no attachment-byte download method.

Issue #24 therefore cannot accidentally make attachment contents a dependency
of ordinary analysis.

## Fresh state

`ProviderMessageState` is intentionally small and provider-neutral:

- message identifier;
- current stable provider label identifiers;
- Inbox state when known;
- Trash state when known;
- optional opaque provider revision.

Fresh state uses provider label IDs rather than display names because names may
be renamed while provider identity remains stable. Human/core semantic label
names are resolved separately from the provider label catalog.

This is the read primitive intended for later mutation preflight.

It grants no write permission.

## Capabilities

Read and write capability metadata are represented by separate types:

- `ProviderReadCapabilities`;
- `ProviderWriteCapabilities`.

Write capability discovery is not mutation authorization.

A provider reporting `ADD_LABEL` support does not mean Semantic Mail Archivist
may call it. Classification policy, explicit write mode, safety gates,
preflight, journaling, and auditability remain separate requirements.

Issue #24 defines no write operation even when write capability metadata is
present.

## Provider limitations

`ProviderDescriptor.limitations` uses the existing `ProviderLimitation` audit
type.

Callers can therefore pass those limitations directly to
`build_mailbox_audit(..., provider_limitations=...)` without translation or
loss.

Missing provider facts must remain visible rather than being fabricated.

## Error contract

`ProviderOperationError` exposes only:

- a stable `ProviderErrorCode`;
- a caller-supplied safe detail;
- whether retry may be appropriate.

It intentionally has no field for:

- raw HTTP responses;
- OAuth tokens;
- credentials;
- message bodies;
- attachment contents.

Provider implementations must reduce raw provider failures to safe categories
before exposing them through this boundary.

## Cross-provider rule

This module contains no Gmail-specific types, scopes, endpoints, IDs, or
mutation semantics.

Gmail is the first Phase 2 implementation, not the definition of the core
provider contract.

## Out of scope

Issue #24 does not implement:

- Gmail OAuth;
- Gmail API calls;
- mailbox ingestion orchestration;
- CLI commands;
- provider writes;
- mutation authorization;
- attachment-body download;
- semantic label policy.
