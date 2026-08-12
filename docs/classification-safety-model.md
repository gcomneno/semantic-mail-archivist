# Classification and Safety Model

Status: **Foundation contract**  
Version: **0.1**  
Issue: **#1 — Define the mail classification and safety model**

This document defines the decision contract that every classifier, repair workflow, cleanup workflow, and provider adapter in Semantic Mail Archivist must obey.

It is intentionally implementation-independent. Application code must implement this policy; application code must not silently invent a different policy.

Normative terms such as **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are used deliberately.

## 1. Constitutional rule

> **Learn the user's taxonomy. Do not impose one.**

The user's existing mailbox organization is first-class evidence. Semantic Mail Archivist may identify gaps, conflicts, redundancy, or opportunities for improvement, but it must not treat an existing taxonomy as noise merely because another taxonomy would be simpler for the software.

## 2. Classification and mutation are separate decisions

A classification answers a semantic question such as:

```text
What is this message?
What existing user label is most compatible with it?
Does it appear to contain a significant document?
Does it belong to a protected semantic domain?
```

A mutation answers a different question:

```text
Is the system allowed to change the mailbox because of that classification?
```

High classification confidence does **not** automatically grant mutation permission.

Every proposed write therefore requires two independent outputs:

```text
semantic decision
mutation authorization
```

A valid result is:

```text
semantic decision: HIGH confidence
mutation authorization: DENIED
```

## 3. Label classes

Provider-visible labels must be classified before they are used as evidence.

### 3.1 User semantic labels

Labels created or intentionally used by the mailbox owner to express what a message is, for example:

```text
Personal/Housing
Personal/Health
Work/Training
Work/Projects
```

These are strong taxonomy evidence.

### 3.2 User operational labels

Labels expressing what the user needs to do, for example:

```text
@Action
@Waiting
@Deadline
@Document
@Reference
```

These are not semantic inheritance evidence by default. Operational state can change from one message to the next inside the same thread.

### 3.3 Provider/system labels

Provider-managed state such as inbox, unread, important, promotions, updates, sent, spam, or trash.

These labels MUST NOT be interpreted as user semantic classification.

### 3.4 Unknown user labels

When the system cannot safely determine whether a user label is semantic, operational, or another kind of marker, it MUST retain that uncertainty. Unknown labels MUST NOT silently become inheritance evidence.

## 4. Evidence model

Every decision must record the evidence that produced it. Evidence is grouped by strength and role rather than treated as interchangeable signals.

### E1 — Direct message evidence

Examples:

- user semantic labels already present on the message;
- message sender and recipients;
- subject and normalized thread subject;
- message text when analysis of content is enabled;
- direct attachment metadata;
- explicit provider metadata attached to that message.

Direct message evidence has priority over weaker contextual inference when they conflict.

### E2 — Thread-consistency evidence

Examples:

- the same semantic label appears consistently on surrounding messages;
- participants and subject remain stable;
- no competing semantic classification appears in the thread;
- the unlabelled message is structurally positioned as a reply inside the same conversation.

Thread context is evidence, **not proof**.

The mere presence of label `X` somewhere in a thread MUST NOT imply that every unlabelled message should receive `X`.

### E3 — Mailbox-taxonomy evidence

Examples:

- the user already has a label that matches the inferred topic;
- similar messages from the same relationship are consistently classified under one existing label;
- hierarchical position in the existing taxonomy supports the interpretation.

The system SHOULD prefer an existing compatible label over inventing a new one.

### E4 — Heuristic or model-derived semantic evidence

Examples:

- semantic classification of subject/body;
- sender-domain heuristics;
- document-type inference;
- learned similarity with other messages.

E4 may strengthen a decision but MUST NOT override clear contradictory E1 evidence on its own.

## 5. Confidence model

Confidence is expressed as a score from `0.00` to `1.00` and a corresponding band.

| Band | Score | Meaning |
|---|---:|---|
| **HIGH** | `>= 0.90` | Evidence is coherent enough for an explainable proposal. Some non-destructive writes may become eligible if all safety gates also pass. |
| **MEDIUM** | `>= 0.60` and `< 0.90` | Plausible but not safe for automatic mutation. Human review is required. |
| **LOW** | `< 0.60` | Evidence is weak, contradictory, or incomplete. The system must make no mailbox change. |

A numeric score is never sufficient by itself. Confidence MUST be accompanied by:

```text
proposed classification
evidence used
conflicting evidence
confidence score
confidence band
safety gates
recommended action
```

### 5.1 Confidence is not permission

A HIGH-confidence classification may still fail mutation authorization because of:

- conflicting user labels;
- protected-domain constraints;
- significant-document evidence;
- an unsupported provider operation;
- missing audit capability;
- lack of explicit write mode;
- a mutation class requiring a stricter threshold.

### 5.2 Refusal is a successful result

The system MUST be able to conclude:

```text
NO INFERENCE
NO ACTION
REVIEW REQUIRED
```

without treating those outcomes as errors.

## 6. Conflict and ambiguity rules

A decision MUST be downgraded or refused when material evidence conflicts.

### 6.1 Competing semantic labels

If surrounding messages carry multiple competing semantic labels and the current message provides no decisive direct evidence, automatic inheritance is forbidden.

### 6.2 Direct evidence versus thread evidence

When message-level semantics materially conflict with thread-level consensus, direct message evidence wins and automatic thread inheritance is forbidden.

### 6.3 Semantic versus operational state

A stable semantic label in a thread MAY be inheritable when all gates pass. A volatile operational label MUST NOT be inherited merely because neighbouring messages carry it.

### 6.4 Unknown meaning

Unknown classification is preferable to a guessed classification. Unknown or ambiguous meaning MUST become conservative behavior when any destructive action is considered.

## 7. Protected semantic domains

The following domains are protected by default:

- health and medical administration;
- tax and fiscal records;
- banking and financial records;
- insurance;
- contracts and employment records;
- pensions, benefits, and public administration;
- identity and authentication records;
- education records;
- legal correspondence;
- payments, receipts, and invoices.

Protected status is a **safety constraint**, not a permanent-retention claim.

A message may belong to more than one protected domain. Domain inference may itself have uncertainty.

When a message is definitely or plausibly protected:

- semantic classification may still proceed;
- additive non-destructive labeling may still be proposed;
- archival/document indexing may still be proposed;
- destructive recommendations MUST be suppressed or escalated to explicit human review;
- uncertainty MUST bias toward retention, not deletion.

The project MUST NOT make claims about legal retention periods unless a separate, jurisdiction-specific policy is explicitly introduced and maintained.

## 8. Mutation classes

Mutation safety is stricter than classification safety.

| Class | Examples | Default minimum | Additional gates |
|---|---|---:|---|
| **M0 — Read-only** | audit, classify, report | none | Must not change provider state |
| **M1 — Additive reversible** | add an existing semantic label | HIGH `>= 0.90` | explicit write mode; no unresolved material conflict; audit record available |
| **M2 — Corrective reversible** | remove/replace a user label | HIGH `>= 0.97` | explicit write mode; stronger evidence than for addition; previous state recorded |
| **M3 — Placement/state change** | archive, mark operational state | HIGH `>= 0.95` | explicit write mode; provider semantics understood; previous state recorded |
| **M4 — Trash-style destructive but recoverable** | move message to provider Trash | HIGH `>= 0.995` | dedicated cleanup write mode; no protected-domain signal; no significant-document signal; no unresolved ambiguity; evidence must include positive obsolescence signals |
| **M5 — Permanent destructive** | permanent deletion | **PROHIBITED in the initial contract** | no implementation permitted by this version |

Thresholds are policy defaults, not promises of statistical calibration. Later empirical calibration MAY adjust them, but lowering a threshold requires an explicit contract revision rather than an implementation-only change.

### 8.1 Additions are safer than removals

Adding a compatible existing label generally preserves information. Removing or replacing a user's classification can erase intent. Therefore M2 requires a higher threshold and stronger evidence than M1.

### 8.2 Age is never deletion evidence by itself

Message age MAY contribute context, but age alone MUST NOT make a message eligible for M4.

M4 requires positive low-value/obsolescence evidence and successful passage of every protection gate.

### 8.3 Trash and permanent deletion are different operations

A provider Trash action and permanent deletion MUST be represented as distinct mutation classes. An implementation MUST NOT describe a Trash action as permanent deletion or vice versa.

## 9. Write-mode contract

The default mode is read-only.

A write workflow MUST have an explicit write mode. A previous analysis or dry-run does not silently authorize later mutation.

Before any mutation-capable workflow is considered trustworthy, the project MUST support a dry-run representation containing at least:

```text
message-safe identifier
current state
proposed state
evidence
conflicts
confidence
mutation class
safety-gate result
planned action
```

Dry-run MUST NOT mutate provider state.

## 10. Auditability contract

Every successful or attempted mutation MUST be attributable.

The audit model must eventually record at least:

```text
timestamp
provider
account-safe identifier
message-safe identifier
action / mutation class
previous state
requested new state
evidence summary
confidence score and band
safety-gate result
initiator / execution mode
provider result
```

Failed and partially failed operations MUST be distinguishable from successful operations.

A mutation MUST NOT be enabled if the implementation cannot produce the minimum audit record required for its class.

## 11. Privacy and logging defaults

Default logs and reports MUST NOT contain:

- provider access tokens or credentials;
- complete message bodies;
- complete attachment contents;
- secrets or one-time authentication codes;
- unnecessary personal identifiers.

Reports SHOULD use safe/stable identifiers and summarized evidence.

Development fixtures MUST be synthetic or explicitly sanitized. Real mailbox contents MUST NOT be committed merely because they were useful when discovering a failure mode.

Local-first analysis MUST remain a supported architectural path.

## 12. Synthetic decision examples

These examples define expected policy behavior; they are not tied to a real mailbox.

### Example A — Clean semantic inheritance

```text
Thread: "Apartment maintenance"

Message 1: user label Personal/Housing
Message 2: no user label
Message 3: user label Personal/Housing
Participants: stable
Subject: stable
Message 2 semantics: maintenance follow-up
Competing semantic labels: none
```

Expected result:

```text
classification: Personal/Housing
confidence: HIGH, e.g. 0.97
mutation class: M1
recommendation: eligible for additive repair in explicit write mode
```

Reason: strong E1/E2 compatibility with no material conflict.

### Example B — Conflicting thread classifications

```text
Message 1: Work/Project-A
Message 2: no user label
Message 3: Work/Finance
```

Expected result:

```text
classification: NO INFERENCE
confidence: MEDIUM or LOW
mutation authorization: DENIED
recommendation: REVIEW REQUIRED
```

Reason: thread membership does not resolve competing semantics.

### Example C — Provider labels are not user taxonomy

```text
Message 1 labels: IMPORTANT, CATEGORY_UPDATES
Message 2 labels: none
```

Expected result:

```text
semantic classification from labels: none
mutation authorization: DENIED
```

Reason: provider/system labels are not semantic user labels.

### Example D — Significant protected document

```text
Message topic: insurance renewal
Attachment: policy-renewal.pdf
Existing compatible user label: Personal/Insurance
Protected-domain evidence: insurance
```

Expected result:

```text
semantic classification: Personal/Insurance
protected domain: insurance
additive label proposal: MAY be HIGH confidence
Trash eligibility: DENIED
```

Reason: protected/document evidence does not block useful classification, but it blocks casual destructive cleanup.

### Example E — Old marketing message

```text
Age: 8 years
Sender pattern: marketing campaign
Content: expired seasonal promotion
Attachments: none
Conversation replies: none
Protected-domain evidence: none
Significant-document evidence: none
```

Expected result:

```text
obsolescence classification: likely low-value
confidence: HIGH only if positive signals are strong
Trash eligibility: possible M4 candidate only at >= 0.995 and in dedicated cleanup write mode
permanent deletion: PROHIBITED
```

Reason: age contributes context but is not sufficient by itself.

### Example F — Operational state must not inherit

```text
Message 1: Work/Vendor + @Waiting
Message 2: no user labels; contains vendor reply resolving the request
Message 3: Work/Vendor
```

Expected result:

```text
semantic proposal for Message 2: Work/Vendor may be HIGH confidence
operational proposal @Waiting: MUST NOT be inherited from Message 1
```

Reason: semantic topic is stable while operational state changed.

### Example G — Direct semantics override thread consensus

```text
Messages 1-4: Personal/Housing
Message 5: forwarded tax certificate with clearly unrelated fiscal semantics
Message 5: no user label
```

Expected result:

```text
inherit Personal/Housing: DENIED
protected-domain hint: tax/fiscal
recommendation: REVIEW REQUIRED or separate semantic classification
```

Reason: E1 direct message evidence materially conflicts with E2 thread consensus.

### Example H — Unknown but potentially important

```text
Old message
Unfamiliar sender
Attachment present
Body unavailable to current analyzer
Document significance: unknown
Protected domain: unknown
```

Expected result:

```text
classification: UNKNOWN
Trash eligibility: DENIED
recommendation: RETAIN / REVIEW
```

Reason: uncertainty becomes conservative behavior for destructive decisions.

## 13. Decision pipeline

Every future decision engine should be expressible as the following policy pipeline:

```text
1. Identify provider/system labels, user semantic labels, user operational labels, and unknown labels.
2. Collect direct message evidence.
3. Collect thread-context evidence without treating it as proof.
4. Collect mailbox-taxonomy evidence.
5. Add heuristic/model evidence where enabled.
6. Detect conflicts and protected-domain signals.
7. Produce semantic proposal + explainable confidence.
8. Determine mutation class independently.
9. Apply class-specific threshold and safety gates.
10. Require explicit write mode for any mutation.
11. Require auditable previous/new state.
12. Otherwise return NO ACTION / REVIEW REQUIRED.
```

## 14. Policy invariants

The following statements are invariant under this contract:

1. Existing user taxonomy is evidence.
2. Thread context is never proof by itself.
3. Provider/system labels are not semantic user labels.
4. Classification confidence is not mutation permission.
5. Ambiguity may legitimately produce no classification and no action.
6. Protected-domain uncertainty biases destructive decisions toward retention.
7. Age alone never authorizes cleanup.
8. Additive changes require less authority than destructive changes.
9. Dry-run precedes trustworthy write workflows.
10. Every mutation must be explainable and auditable.
11. Default logs minimize sensitive content.
12. Permanent deletion is prohibited by version 0.1 of this contract.

## 15. Change control

This document is a product-safety contract. Changes that materially weaken a safety invariant, lower mutation thresholds, add a new destructive class, or relax protected-domain behavior MUST be reviewed as explicit policy changes.

Provider adapters, classifiers, and future model integrations MUST conform to the current contract rather than quietly redefining it.