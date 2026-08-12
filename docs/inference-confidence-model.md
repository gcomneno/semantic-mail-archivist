# Label inference and confidence model

Status: **Initial inference contract**  
Issue: **#3 — Infer labels from thread context with confidence scoring**

This document defines the first explainable inference model used after issue #2 detects a message-level semantic label gap.

The inference layer answers:

> Given a detected gap and the observable context around it, is there enough coherent evidence to propose one existing semantic label?

It does **not** apply labels or otherwise mutate provider state.

## Relationship to the safety contract

Confidence bands match `docs/classification-safety-model.md`:

| Band | Score |
|---|---:|
| `HIGH` | `>= 0.90` |
| `MEDIUM` | `>= 0.60` and `< 0.90` |
| `LOW` | `< 0.60` |

The number is an **explainable policy score**, not a statistically calibrated probability. A score of `0.93` means the policy weights produce strong coherent evidence; it does not claim a measured 93% probability of correctness.

Classification remains separate from mutation authorization. Even a `HIGH` inference does not grant permission to write to a mailbox.

## Input boundary

Inference consumes:

```text
ThreadSnapshot
LabelGapCandidate
```

`LabelGapCandidate` is produced by the read-only detector from issue #2.

`MessageSnapshot` gains optional provider-independent evidence fields:

```text
normalized_subject
correspondents[]
semantic_label_hints[]
```

Missing metadata is treated as unknown rather than negative evidence.

### `normalized_subject`

An upstream normalizer may remove provider-specific reply/forward syntax. The inference layer only compares the supplied normalized value.

### `correspondents`

A normalized collection of **non-owner correspondents** associated with the message.

The mailbox owner's own identities must be removed before this signal is supplied. Otherwise every ordinary conversation would trivially overlap on the owner address and create a false continuity signal.

The initial scorer checks correspondent continuity by set overlap. It does not log or persist these values by itself.

### `semantic_label_hints`

Optional upstream evidence that the target message is semantically compatible with one or more existing user labels.

Issue #3 deliberately does not prescribe how hints are produced. Future analyzers may use deterministic rules, local models, remote models, user rules, or another mechanism, provided the project safety contract is respected.

Issue #3 itself selects no LLM or external classification provider.

## Hard refusal and ambiguity rules

### Competing thread semantic labels

If issue #2 reports `CONFLICTING`:

```text
proposed_label: null
confidence_score: 0.0
confidence_band: LOW
conflict: competing_thread_semantic_labels
```

No thread label is guessed.

### Direct semantic incompatibility

If semantic hints are present but do not include the single stable thread label:

```text
proposed_label: null
confidence_score: 0.0
confidence_band: LOW
conflict: direct_semantic_hint_conflicts_with_thread
```

This follows the issue #1 rule that message-level semantic evidence may override weaker thread context.

### Ambiguous direct semantic hints

If the target hints include the stable thread label **and** one or more competing alternatives, the thread label does not receive the direct-semantic bonus.

Instead:

```text
contribution: -0.15
conflict: ambiguous_direct_semantic_hints
```

This normally downgrades an otherwise strong thread proposal into `MEDIUM`, preserving it for review without presenting direct ambiguity as HIGH-confidence agreement.

## Initial scoring policy

When exactly one stable surrounding semantic label remains and no hard veto applies, scoring begins with thread-consensus evidence.

| Signal | Contribution | Meaning |
|---|---:|---|
| stable thread semantic consensus | `+0.55` | all surrounding semantic evidence supports one label |
| at least two supporting messages | `+0.15` | repeated surrounding support |
| exactly one supporting message | `+0.05` | minimal support; deliberately weaker |
| supporting messages on both sides | `+0.10` | target gap is structurally enclosed |
| normalized subject matches supporters | `+0.08` | topic continuity |
| normalized subject differs from all supporters | `-0.10` | topic discontinuity |
| non-owner correspondent overlap with every supporter | `+0.05` | relationship continuity |
| no non-owner correspondent overlap with any supporter | `-0.10` | relationship discontinuity |
| unique target semantic hint matches proposed label | `+0.12` | unambiguous direct semantic compatibility |
| target hints include proposed label plus alternatives | `-0.15` | direct semantic ambiguity |
| attachment present | `0.00` | neutral until document significance exists |

The score is normalized into `[0.00, 1.00]` and rounded to three decimal places.

If clamping changes the raw score, an explicit `score_clamp` evidence item records the normalization contribution. Therefore the final score remains reconstructable by summing the returned evidence contributions and rounding to three decimals.

## Why attachment presence is neutral

Attachment presence alone does not mean that an attachment is a significant document or that it supports a semantic label.

Issue #3 records attachment presence with contribution `0.00` until issue #5 introduces document-significance evidence.

This prevents unsupported reasoning such as:

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

A LOW result deliberately becomes `proposed_label: null`. This is a successful refusal, not an inference error.

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

This is intentionally ready for issue #4 dry-run reporting without requiring the report layer to reverse-engineer the scorer.

## Synthetic acceptance scenarios

### A — Strong enclosed thread context

```text
Message 1: Personal/Housing
Message 2: no semantic label
Message 3: Personal/Housing
normalized subject: same
non-owner correspondent: same
```

Expected: `Personal/Housing`, `HIGH`, at least `0.93`.

### B — Competing classifications

```text
Message 1: Work/Project-A
Message 2: no semantic label
Message 3: Work/Finance
```

Expected: no proposed label, LOW confidence, `competing_thread_semantic_labels`.

### C — Stable thread but contradictory target semantics

```text
Thread evidence: Work/Project
Target semantic hint: Work/Finance
```

Expected: no proposed label, LOW confidence, `direct_semantic_hint_conflicts_with_thread`.

### D — Ambiguous target semantics

```text
Thread evidence: Work/Project
Target semantic hints: Work/Project, Work/Finance
```

Expected: proposal may remain `Work/Project`, but confidence is downgraded to MEDIUM and `ambiguous_direct_semantic_hints` is reported.

### E — One supporting message only

```text
Message 1: Work/Vendor
Message 2: no semantic label
no additional continuity metadata
```

Expected: `Work/Vendor`, score `0.60`, MEDIUM.

### F — Weak and discontinuous context

```text
supporting label: Work/Vendor
supporting subject: invoice
target subject: holiday
supporting correspondent: vendor
target correspondent: friend
```

Expected: no proposed label, LOW confidence, with subject and correspondent discontinuity conflicts.

### G — Positive direct semantic compatibility

```text
Thread evidence: Personal/Insurance
Target semantic hint: Personal/Insurance
Target has attachment: yes
```

Expected: HIGH proposal; attachment contribution remains `0.00`.

### H — Score normalization remains explainable

A case that activates enough positive signals to exceed `1.00` must return:

```text
confidence_score: 1.00
evidence includes: score_clamp
sum(evidence contributions): 1.00
```

The clamping step is visible rather than hidden.

## Read-only safety boundary

The inference engine is mutation class **M0 — Read-only**.

It does not call Gmail or another provider, create/apply/remove labels, archive messages, change operational state, inspect document contents, move messages to Trash, or permanently delete anything.

Its output is evidence for later review and dry-run workflows only.

## Change control

The initial weights are policy values chosen to make the decision mechanics explicit during the foundation phase.

Any later change that lowers a confidence threshold, converts a hard refusal into a soft penalty, adds a new evidence source, materially changes a scoring contribution, or allows LOW-confidence proposals should be reviewed as an inference-policy change rather than hidden inside unrelated implementation work.
