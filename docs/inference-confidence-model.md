# Label inference and confidence model

Status: **Initial inference contract**  
Issue: **#3 — Infer labels from thread context with confidence scoring**

This document defines the first explainable inference model used by Semantic Mail Archivist after issue #2 has detected a message-level semantic label gap.

The inference layer answers:

> Given a detected gap and the observable context around it, is there enough coherent evidence to propose one existing semantic label?

It does **not** apply labels or otherwise mutate provider state.

## Relationship to the safety contract

The confidence bands are the bands defined by `docs/classification-safety-model.md`:

| Band | Score |
|---|---:|
| `HIGH` | `>= 0.90` |
| `MEDIUM` | `>= 0.60` and `< 0.90` |
| `LOW` | `< 0.60` |

The numeric value is an **explainable policy score**, not a statistically calibrated probability.

A score of `0.93` means that the initial policy weights produce strong coherent evidence. It does not claim that the label is correct with a measured 93% empirical probability.

Future empirical calibration may revise weights or thresholds only through an explicit policy change. Application code must not silently reinterpret the bands.

## Classification remains separate from mutation

Issue #3 produces semantic inference only.

Even this result:

```text
proposed label: Personal/Housing
confidence: HIGH 0.93
```

does not authorize a mailbox write.

Mutation authorization remains a separate decision under the safety contract.

## Input boundary

Inference consumes:

```text
ThreadSnapshot
LabelGapCandidate
```

`LabelGapCandidate` comes from the read-only detector introduced by issue #2. The inference layer does not rediscover gaps or treat raw provider state as authoritative by itself.

`MessageSnapshot` gains optional provider-independent evidence fields:

```text
normalized_subject
participants[]
semantic_label_hints[]
```

All are optional. Missing metadata is treated as unknown rather than negative evidence.

### `normalized_subject`

A provider adapter or upstream normalization step may supply a subject with reply/forward syntax normalized where practical.

The inference layer compares the supplied values; it does not implement provider-specific subject parsing.

### `participants`

A normalized collection of participants associated with the message.

The initial scorer checks continuity by set overlap. It does not publish, log, or persist participant values by itself.

### `semantic_label_hints`

Optional upstream evidence that the target message is semantically compatible with one or more existing user labels.

This field deliberately does not prescribe how the hints are produced. A future implementation may derive them from deterministic rules, local models, remote models, user rules, or another analyzer, provided the safety contract is respected.

Issue #3 itself selects no LLM or external classification provider.

## Hard refusal conditions

Some conflicts are stronger than additive scoring.

### Competing thread semantic labels

If the issue #2 candidate reports `CONFLICTING`, inference returns:

```text
proposed_label: null
confidence_score: 0.0
confidence_band: LOW
conflict: competing_thread_semantic_labels
```

No thread label is guessed.

### Direct semantic incompatibility

If `semantic_label_hints` are present but do not include the single stable thread label, direct semantic evidence vetoes inheritance:

```text
proposed_label: null
confidence_score: 0.0
confidence_band: LOW
conflict: direct_semantic_hint_conflicts_with_thread
```

This follows the issue #1 rule that message-level semantic evidence may override weaker thread context.

## Initial scoring policy

When exactly one stable surrounding semantic label remains and no hard veto applies, scoring begins with thread-consensus evidence.

| Signal | Contribution | Meaning |
|---|---:|---|
| stable thread semantic consensus | `+0.55` | all semantic evidence around the gap supports one label |
| at least two supporting messages | `+0.15` | label has repeated surrounding support |
| exactly one supporting message | `+0.05` | minimal support; deliberately weaker |
| supporting messages on both sides of target | `+0.10` | gap is structurally enclosed by matching classification |
| normalized subject matches supporters | `+0.08` | topic continuity signal |
| normalized subject differs from all supporters | `-0.10` | topic discontinuity signal |
| participant overlap with every supporter | `+0.05` | relationship/conversation continuity |
| no participant overlap with any supporter | `-0.10` | relationship discontinuity signal |
| target semantic hint includes proposed label | `+0.12` | direct semantic compatibility |
| attachment present | `0.00` | recorded but neutral until document significance exists |

The final score is clamped to `[0.00, 1.00]` and rounded to three decimal places.

Every non-zero scoring contribution is returned in the output, so the score can be reconstructed from the evidence list.

## Why attachment presence is neutral

Issue #2 preserves whether the target message has an attachment, but attachment presence alone does not mean that the attachment is a significant document or that it supports a label.

Therefore issue #3 records:

```text
attachment_presence: contribution 0.00
```

until issue #5 introduces document significance evidence.

This prevents the inference engine from smuggling an unsupported assumption such as:

```text
PDF present -> important -> thread label probably correct
```

## Proposal policy

After scoring:

```text
HIGH   -> proposed label may be returned
MEDIUM -> proposed label may be returned for review
LOW    -> proposed label is suppressed
```

A LOW result therefore deliberately becomes:

```text
proposed_label: null
```

This is a successful refusal, not an inference failure.

## Output model

`LabelInference` contains:

```text
thread_id
message_id
proposed_label | null
confidence_score
confidence_band
evidence[]
conflicts[]
```

Each `InferenceEvidence` contains:

```text
signal
detail
contribution
```

This structure is intended to feed issue #4 dry-run reports without requiring those reports to reverse-engineer the scorer.

## Synthetic acceptance scenarios

### A — Strong enclosed thread context

```text
Message 1: Personal/Housing
Message 2: no semantic label
Message 3: Personal/Housing
normalized subject: same
participants: continuous
```

Expected:

```text
proposed_label: Personal/Housing
confidence_band: HIGH
```

The initial policy produces at least `0.93` without requiring semantic body hints.

### B — Competing classifications

```text
Message 1: Work/Project-A
Message 2: no semantic label
Message 3: Work/Finance
```

Expected:

```text
proposed_label: null
confidence_band: LOW
conflict: competing_thread_semantic_labels
```

### C — Stable thread but contradictory message semantics

```text
Thread evidence: Work/Project
Target semantic hint: Work/Finance
```

Expected:

```text
proposed_label: null
confidence_band: LOW
conflict: direct_semantic_hint_conflicts_with_thread
```

### D — One supporting message only

```text
Message 1: Work/Vendor
Message 2: no semantic label
no additional continuity metadata
```

Expected:

```text
proposed_label: Work/Vendor
confidence_score: 0.60
confidence_band: MEDIUM
```

The proposal exists for review but is intentionally not HIGH.

### E — Weak and discontinuous context

```text
supporting message label: Work/Vendor
supporting subject: invoice
target subject: holiday
supporting participants: vendor
target participants: friend
```

Expected:

```text
proposed_label: null
confidence_band: LOW
conflicts:
  - subject_discontinuity
  - participant_discontinuity
```

### F — Positive direct semantic compatibility

```text
Thread evidence: Personal/Insurance
Target semantic hint: Personal/Insurance
Target has attachment: yes
```

Expected:

```text
proposed_label: Personal/Insurance
confidence_band: HIGH
attachment contribution: 0.00
```

The attachment does not inflate confidence.

## Read-only safety boundary

The inference engine is mutation class **M0 — Read-only**.

It does not:

- call Gmail or another provider;
- create labels;
- apply labels;
- remove or replace labels;
- archive messages;
- change operational state;
- inspect document contents;
- move messages to Trash;
- permanently delete anything.

Its output is evidence for later review and dry-run workflows only.

## Change control

The initial weights are policy values chosen to make the decision mechanics explicit and conservative enough for the foundation phase.

Any later change that:

- lowers a confidence threshold;
- converts a hard refusal into a soft penalty;
- adds a new evidence source;
- materially changes a scoring contribution;
- allows LOW-confidence proposals;

should be reviewed as an inference-policy change rather than hidden inside unrelated implementation work.
