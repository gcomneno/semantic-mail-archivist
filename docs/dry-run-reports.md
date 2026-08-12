# Dry-run Repair Reports

Status: **Initial contract**
Version: **1.0**
Issue: **#4 — Add dry-run repair reports**

This layer turns message-level gap detection and explainable inference into an
inspectable repair report. It remains entirely read-only.

## Boundary

The reporting layer consumes the existing issue #2 detector and issue #3
inference engine. It does not change either decision model and it does not call
a provider mutation API.

The conceptual future interface remains:

```text
semantic-mail-archivist repair --dry-run
```

Issue #4 intentionally does not choose a CLI framework. The report contract is
kept independent so a later CLI can render the same domain result without
becoming the canonical data format.

## Machine-readable schema

The stable representation starts with:

```json
{
  "schema_version": "1.0",
  "mode": "dry_run",
  "entries": []
}
```

Each candidate entry contains:

```text
thread_id
message_id
current_user_labels
proposed_label
confidence_score
confidence_band
evidence
conflicts
recommendation
planned_action
mutation_class
mutation_authorization
safety_gate_result
authorization_reasons
execution_status
```

`current_user_labels` excludes provider/system labels. User semantic,
operational, and unknown labels are retained so uncertainty is not erased from
the report.

The JSON renderer is deterministic and uses only JSON-safe primitives.

## Three separate decisions

A report keeps these concepts independent:

1. **Semantic recommendation** — what the evidence supports.
2. **Mutation authorization** — whether a provider write is permitted.
3. **Execution status** — whether anything was executed.

Dry-run always has:

```text
mutation_authorization: DENIED
safety_gate_result: NOT_EVALUATED_FOR_WRITE
execution_status: NOT_EXECUTED
```

`NOT_EVALUATED_FOR_WRITE` is deliberate: issue #4 does not pretend that
future protected-domain, document-significance, cleanup, or audit gates have
already been evaluated.

A HIGH proposal therefore does not silently become permission to write.

## Outcomes

### HIGH — additive repair proposal

A HIGH inference with a proposed label and no unresolved conflict is represented
as:

```text
recommendation: ELIGIBLE_FOR_ADDITIVE_REPAIR
planned_action: ADD_LABEL
mutation_class: M1
mutation_authorization: DENIED
safety_gate_result: NOT_EVALUATED_FOR_WRITE
authorization_reasons:
  dry_run_mode
  explicit_write_mode_absent
execution_status: NOT_EXECUTED
```

`M1` describes the class of the proposed future action. It does not mean the
action is currently authorized.

### REVIEW REQUIRED

A proposal below the M1 HIGH threshold remains inspectable but cannot be planned
as a write:

```text
recommendation: REVIEW_REQUIRED
planned_action: NO_ACTION
mutation_class: M0
mutation_authorization: DENIED
safety_gate_result: NOT_EVALUATED_FOR_WRITE
execution_status: NOT_EXECUTED
```

The authorization reasons explain the confidence/review gate and preserve any
reported conflicts.

### NO ACTION

When inference refuses to propose a safe label:

```text
proposed_label: null
recommendation: NO_ACTION
planned_action: NO_ACTION
mutation_class: M0
mutation_authorization: DENIED
safety_gate_result: NOT_EVALUATED_FOR_WRITE
authorization_reasons:
  dry_run_mode
  no_safe_inference
execution_status: NOT_EXECUTED
```

Refusal is a successful domain result, not a reporting error.

## Privacy boundary

The report model does not include message bodies, snippets, attachment contents,
credentials, tokens, or other unnecessary personal content.

Evidence is reused from the structured, summarized issue #3 inference evidence.
Attachments remain represented only through the neutral inference signal already
defined there; issue #4 does not attempt to classify document significance.

Development examples and tests remain synthetic.

## Future write-mode boundary

This report must not be treated as authorization for a later write. A future
mutation-capable workflow will require explicit write mode and the safety/audit
gates defined by the classification and safety contract.

In particular, issue #4 does not claim that future protected-domain,
significant-document, obsolescence, or audit gates have already been evaluated.
