# Crash-aware local mutation journal

Status: **Pre-write durability contract**

Issue: **#30 — Add a crash-aware local mutation journal before enabling writes**

## Purpose

The mutation journal closes the uncertainty window between future mutation
authorization and final change-log recording.

It does not enable provider writes.

The durable sequence for a future write workflow is:

    safety / authorization
        -> fresh provider preflight
        -> append + fsync INTENT
        -> future provider mutation call
        -> inspect fresh provider/result state
        -> write final ChangeAuditRecord
        -> append + fsync FINALIZATION

If the process stops after INTENT and before FINALIZATION, the attempt is
interrupted/unfinalized.

An interrupted attempt is never success by implication.

## Separate responsibilities

The existing `ChangeAuditRecord` remains the canonical finalized audit record.

The mutation journal records temporal execution state that the final change log
cannot safely represent before the outcome is known.

The journal therefore does not replace or duplicate:

- semantic classification;
- confidence inference;
- mutation authorization;
- safety gates;
- provider result classification;
- rollback metadata;
- the final change-log record.

## Shared attempt identity

`MutationAttemptIntent.attempt_id` is the future
`ChangeAuditRecord.record_id`.

`MutationAttemptFinalization.audit_record_id` must equal that same attempt ID.

This keeps the existing change-log schema usable without adding a second
cross-system identity.

## Event model

Journal schema version:

    1.0

The append-only event types are:

    intent
    finalization

An `intent` contains only the minimum safe facts needed to identify and
reconcile a future attempt:

- attempt ID;
- timezone-aware timestamp;
- provider;
- account-safe ID;
- message ID;
- action and canonical mutation class;
- target label when applicable;
- provider state observed immediately before the future call;
- provider state requested by the future call;
- initiator;
- execution mode;
- originating dry-run correlation ID when applicable.

A `finalization` contains:

- the same attempt ID;
- timezone-aware timestamp;
- final result class;
- audit-record ID, equal to the attempt ID.

Final results reuse the canonical change-log result taxonomy:

- `succeeded`;
- `failed`;
- `partial_failure`;
- `denied`.

## Crash semantics

### Crash before provider call

If INTENT is durable and the process stops before the provider call, the next
load discovers the attempt as interrupted.

Fresh provider state equal to the recorded pre-call state is reported only as:

    previous_state_observed

### Crash after provider call but before finalization

If fresh provider state matches the recorded requested state, reconciliation
reports only:

    requested_state_observed

This is not automatically converted to success.

The same provider state may have arisen through another actor or process.
Finalization still requires the later write workflow to establish the canonical
change-log result.

### Divergent state

Any fresh state matching neither the pre-call nor requested state is:

    divergent_state_observed

The journal does not guess which actor or operation caused it.

## Recovery and replay

`reconcile_interrupted_attempt()` is pure and idempotent.

It consumes an interrupted journal attempt plus fresh
`ProviderMessageState`.

It never:

- calls a provider;
- writes provider state;
- mutates the journal;
- finalizes an attempt;
- replays an operation;
- grants mutation authorization.

Automatic replay is explicitly outside issue #30.

A later workflow may use the observation as one input to a deliberate
reconciliation decision.

## Durable append semantics

Journal persistence is local JSONL.

Each event append:

1. opens the file in append mode;
2. keeps POSIX file mode at `0600`;
3. writes one deterministic JSON record;
4. fsyncs the file;
5. fsyncs the containing directory when creating the journal/path.

Journal directories use `0700` on POSIX.

This makes the INTENT persistence primitive suitable to run before a future
provider mutation call.

## Torn final record

A crash can interrupt a filesystem write.

If the final JSONL record is malformed, the loader reports:

    trailing_corruption = true

and does not treat that partial record as a valid finalization.

Any previously complete INTENT therefore remains discoverable as interrupted.

Corruption before the last record fails closed with
`MutationJournalCorruptionError`.

Appending or finalizing is refused while trailing corruption is present.

No repair/truncation policy is invented by issue #30.

## Privacy

Journal records deliberately exclude:

- message bodies;
- attachment contents;
- credentials;
- OAuth/access/refresh tokens;
- raw provider errors;
- arbitrary provider response bodies.

Provider state uses the existing safe provider facts:

- message ID;
- label IDs;
- placement flags;
- optional provider revision.

The account identity is the existing `account_safe_id`.

Dry-run linkage stores only the canonical correlation identifier.

## Change-log compatibility

Issue #30 does not change `CHANGE_LOG_SCHEMA_VERSION`.

The existing `ChangeAuditRecord` remains the finalized record for:

- reasoning evidence;
- safety gates;
- previous/requested/resulting semantic state;
- provider outcome;
- rollback metadata;
- dry-run proposal reference.

A future workflow must persist that record with:

    record_id == attempt_id

before appending the journal FINALIZATION marker.

## Provider boundary

Issue #30 adds no provider write adapter and calls no mutation method.

`ProviderReadAdapter` remains read-only.

`ProviderMessageState` is used only as a fresh fact format for future preflight
and reconciliation.

Provider capabilities remain metadata, not authorization.

## Synthetic acceptance coverage

Tests cover:

- crash before provider call;
- crash after provider call / before finalization;
- provider failure;
- successful finalization;
- denied and partial-failure terminal states;
- divergent provider state;
- idempotent reconciliation;
- torn trailing finalization;
- fail-closed historical corruption;
- duplicate attempt/finalization rejection;
- shared journal/change-log attempt identity;
- canonical action/mutation-class ownership;
- deterministic privacy-safe JSON;
- POSIX private file/directory modes.

No mailbox mutation is invoked.
