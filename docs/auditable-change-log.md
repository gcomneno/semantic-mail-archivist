# Auditable Change Log

Status: **Initial mutation-audit contract**

Version: **1.0**

Issue: **#10 — Create an auditable change log**

## Purpose

Every future mailbox mutation, successful or attempted, must be attributable.

This contract defines the audit record that write-capable workflows must
produce before such workflows can be considered complete.

It does **not** implement mailbox writes.

## Safety-model alignment

The canonical mutation classes remain:

- M0 — read-only;
- M1 — additive reversible;
- M2 — corrective reversible;
- M3 — placement/state change;
- M4 — Trash-style destructive but recoverable;
- M5 — permanent destructive and prohibited by the initial contract.

The shared `MutationClass` enum now exposes the complete M0-M5 taxonomy.

The change-log action taxonomy deliberately contains no permanent-delete
action.

## Record schema

Every `ChangeAuditRecord` contains:

- schema version;
- record identifier;
- timezone-aware timestamp;
- provider;
- account-safe identifier;
- message identifier;
- action and mutation class;
- optional target label;
- previous state;
- requested new state;
- actual resulting state;
- summarized reasoning evidence;
- confidence score and band;
- safety-gate records;
- initiator and explicit execution mode;
- result;
- provider result metadata;
- optional dry-run correlation;
- rollback metadata.

`requested_new_state` and `resulting_state` are deliberately separate.

The schema validates that the requested state actually represents the declared
action. For example:

- `ADD_LABEL` must add exactly the target label and preserve placement;
- `REMOVE_LABEL` must remove exactly the target label and preserve placement;
- `ARCHIVE` must move a known Inbox message out of Inbox without modifying
  user labels;
- `MOVE_TO_TRASH` must move a known non-Trash message to Trash and out of
  Inbox.

This prevents an audit record from naming one action while describing a
different requested mutation.

This makes these outcomes distinguishable:

- success — resulting state equals the requested state;
- failure — provider state is unchanged or unknown;
- partial failure — provider state changed but did not reach the requested
  state;
- denied — provider state remains the previous state.

## Provider-neutral state

`MailboxStateSnapshot` records only the provider-neutral state currently needed
for the initial safety model:

- user labels;
- inbox placement when known;
- Trash placement when known.

No message body or attachment content is part of this type.

## Dry-run correlation

`DryRunProposalReference.from_candidate()` derives a deterministic SHA-256
correlation identifier from the complete existing dry-run candidate record and
the dry-run schema version.

The current dry-run schema (#4) represents only additive `ADD_LABEL`
repair proposals. Consequently that correlation type is accepted only on
M1 `ADD_LABEL` change records; M2/M3/M4 records cannot falsely claim
correlation with it.

Therefore:

- the same dry-run candidate produces the same correlation identifier;
- a materially changed proposal produces a different identifier;
- an applied M1 label addition can retain a direct reference to the proposal
  that preceded it.

The dry-run itself still grants no write authorization.

## Minimum evidence and write mode

A change record must contain at least one summarized reasoning-evidence record
and at least one safety-gate record. Empty placeholders are not accepted.

Safety-gate decisions and mutation results are semantically linked:

- `DENIED` requires at least one `BLOCKED` safety gate;
- any `BLOCKED` safety gate requires the overall result to be `DENIED`;
- `FAILED` and `PARTIAL_FAILURE` represent execution/provider failures after
  safety authorization, not safety-policy refusals.

M4 `MOVE_TO_TRASH` records require `DEDICATED_CLEANUP_WRITE`, matching the
canonical safety model. That execution mode is reserved for Trash-style
actions.

## Results and failures

`MutationResultStatus` distinguishes:

- `SUCCEEDED`;
- `FAILED`;
- `PARTIAL_FAILURE`;
- `DENIED`.

A successful record must expose the requested final state.

A partial-failure record must expose an actual resulting state that differs
from both the previous state and the fully requested state.

A denied record must show that the previous state was preserved.

## Rollback

A reversible operation must declare:

- rollback action;
- state to restore;
- optional provider capability required for restoration.

The restore state must reconstruct the recorded previous state.

The rollback action must also be the semantic inverse of the forward action:
label add/remove, archive/restore-to-Inbox, and Trash/restore-from-Trash are
paired explicitly by the schema.

Synthetic examples include:

- M1 label addition -> rollback by label removal;
- M2 label removal -> rollback by label addition;
- M3 archive -> rollback by restore-to-inbox;
- M4 move-to-Trash -> rollback by restore-from-Trash where the provider
  supports it.

This metadata defines a future rollback contract; it does not execute rollback.

## Provider-result redaction

The default provider result stores only:

- safe provider status;
- safe failure code;
- safe request identifier.

The schema intentionally has no field for raw HTTP responses, raw exception
messages, provider credentials, access tokens, message bodies, or attachment
contents.

Raw provider errors must be reduced to safe codes before entering an audit
record.

## Evidence privacy

Evidence must be summarized.

Evidence details must not contain complete bodies, credentials, authentication
codes, or attachment contents.

The record API exposes no dedicated fields for any of those values.

## Local-first persistence

`append_change_record_jsonl()` appends one deterministic JSON record to a local
JSONL file and flushes it to disk.

A hosted telemetry service is not required.

`render_change_record_json()` and `render_change_log_jsonl()` allow callers to
manage their own local storage when preferred.

## Out of scope

This contract does not implement:

- Gmail or other provider mutation APIs;
- automatic label addition or removal;
- archive;
- Trash;
- rollback execution;
- permanent deletion;
- hosted telemetry;
- compliance certification.
