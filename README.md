# Semantic Mail Archivist

> **Repair, classify and preserve an existing email knowledge base.**

Semantic Mail Archivist is a privacy-first project for repairing and preserving the semantic structure of long-lived email archives.

Email is more than an inbox. Over years it becomes a personal and professional knowledge base containing documents, decisions, relationships, contracts, receipts, administrative records, technical history, and other context that may be difficult or impossible to reconstruct elsewhere.

The problem is that this structure silently degrades. A conversation can look correctly organized to a user while individual messages inside the thread no longer carry the expected user labels. Important documents become buried among generic attachments. Old notifications and obsolete services accumulate beside records that must never be removed casually.

Semantic Mail Archivist aims to make that archive trustworthy again without replacing the organization its owner has already built.

## Core principle

> **Learn the user's taxonomy. Do not impose one.**

The existing mailbox organization is evidence. Semantic Mail Archivist should first understand it, then repair gaps, propose classifications, identify valuable documents, and surface obsolete material conservatively.

The non-negotiable project invariants are recorded in the [Project Charter](docs/PROJECT_CHARTER.md).

## The founding problem

A thread may be semantically classified while some individual messages are not:

```text
Thread: Personal/Housing

Message 1: Personal/Housing
Message 2: [no user label]
Message 3: [no user label]
Message 4: Personal/Housing
```

From the user's point of view, the conversation is organized.

From the message-level data model, its classification is incomplete.

Both statements are true.

This gap is the first problem the project intends to solve.

## Product pillars

### 1. Thread inheritance repair

Detect message-level label gaps inside classified conversations and infer missing labels only when the surrounding evidence is sufficiently strong.

A label must never be copied through a thread merely because it occurs somewhere in that thread. Sender, subject, message context, label consistency, conflicting classifications, and other signals must contribute to a confidence decision.

### 2. Semantic classification

Understand what a message represents and prefer compatible labels that already exist in the mailbox.

Examples include contracts, insurance records, tax documents, health administration, receipts, training, job correspondence, utilities, account records, and personal correspondence.

### 3. Document discovery

Distinguish between:

```text
message with an attachment
```

and:

```text
message containing a document worth indexing
```

A brochure, tracking pixel, generic attachment, signed contract, tax certificate, and insurance receipt do not have the same archival value.

### 4. Safe obsolescence detection

Identify material that is probably no longer useful, such as expired one-time codes, old marketing, transient notifications, or obsolete service messages, while protecting records whose deletion could be harmful.

## Safety model

Every proposed action should have an explicit confidence level:

```text
HIGH confidence   -> eligible for automation
MEDIUM confidence -> user review required
LOW confidence    -> no modification
```

Destructive operations require a higher standard than classification operations.

The system should favor reversible actions and maintain an audit trail containing at least:

```text
message identifier
action
previous state
new state
reasoning evidence
confidence
timestamp
```

The goal is not "AI cleaned your mailbox".

The goal is:

> This message was changed for these observable reasons, at this confidence level, and the change can be audited.

## Protected semantic domains

The initial safety model should treat at least the following domains conservatively:

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

Protection does not imply permanent retention. It means the system must not make casual automated deletion decisions in these domains.

## Two-axis organization

Semantic Mail Archivist distinguishes between **what a message is** and **what the user needs to do with it**.

A mailbox may already contain semantic labels such as:

```text
Personal/Health
Personal/Housing
Work/Training
Work/Projects
```

An optional operational layer can coexist with them:

```text
@Action
@Waiting
@Deadline
@Document
@Reference
```

This allows classifications such as:

```text
Work/Training + @Document
```

without forcing a replacement taxonomy on the user.

## MVP 0.1

The first implementation is a local, read-first CLI rather than a GUI. Gmail-backed read-only audit and repair dry-run orchestration are now available; explicit mailbox writes remain disabled until later Phase 2 issues.

### Audit

```text
semantic-mail-archivist audit
```

Expected output conceptually includes:

```text
messages analysed
message-level label gaps
repairable gaps
ambiguous gaps
significant documents discovered
protected messages
potential obsolete material
```

### Dry-run repair

```text
semantic-mail-archivist repair --dry-run
```

A proposal should explain itself:

```text
Current labels: none
Proposed label: Personal/Housing
Evidence: surrounding thread classification is consistent
Confidence: 0.97
Action: NONE (dry-run)
```

### Explicit apply

```text
semantic-mail-archivist repair --apply
```

Write operations come only after the audit and dry-run behavior is trustworthy.

## Privacy principles

- Local-first analysis should be possible.
- Mail content must not become a public dataset.
- Development fixtures must be synthetic or explicitly sanitized.
- Logs must avoid leaking message bodies or sensitive attachment contents by default.
- Provider credentials and tokens must never be written to reports or fixtures.
- Every mutation should be attributable and auditable.

## Provider scope

The first real-world investigation uses Gmail semantics, but the conceptual core should avoid unnecessary provider lock-in. Provider-specific behavior belongs behind adapters where practical.

## Initial roadmap

1. [#1 — Define the mail classification and safety model](https://github.com/gcomneno/semantic-mail-archivist/issues/1)
2. [#2 — Detect message-level label gaps inside classified threads](https://github.com/gcomneno/semantic-mail-archivist/issues/2)
3. [#3 — Infer labels from thread context with confidence scoring](https://github.com/gcomneno/semantic-mail-archivist/issues/3)
4. [#4 — Add dry-run repair reports](https://github.com/gcomneno/semantic-mail-archivist/issues/4)
5. [#5 — Detect significant documents versus generic attachments](https://github.com/gcomneno/semantic-mail-archivist/issues/5)
6. [#6 — Introduce protected semantic categories](https://github.com/gcomneno/semantic-mail-archivist/issues/6)
7. [#7 — Detect obsolete low-value messages safely](https://github.com/gcomneno/semantic-mail-archivist/issues/7)
8. [#8 — Add an optional operational state layer](https://github.com/gcomneno/semantic-mail-archivist/issues/8)
9. [#9 — Produce a complete mailbox audit report](https://github.com/gcomneno/semantic-mail-archivist/issues/9)
10. [#10 — Create an auditable change log](https://github.com/gcomneno/semantic-mail-archivist/issues/10)

The roadmap is intentionally contract-first: safety and detection precede inference, and inference precedes mailbox mutation.

## Development approach

The project starts from observed real-world failure modes, but public development must use synthetic fixtures reproducing the relevant structures rather than private mailbox content.

A representative fixture might model:

```text
classified thread
  -> labelled message
  -> unlabelled reply
  -> unlabelled reply with significant document
  -> labelled message
```

Tests should verify both successful repair and deliberate refusal when evidence is ambiguous.

## Non-goals for the first release

- replacing Gmail or another mail client;
- inventing a universal folder taxonomy;
- bulk-deleting historical mail based on opaque model judgments;
- training on a user's private mailbox by default;
- building a hosted dashboard before the local audit and repair model is trustworthy.

## Project status

**Design / foundation phase. No application implementation yet.**

The immediate goal is to formalize the safety contract, inference model, synthetic acceptance fixtures, dry-run format, and audit contract before writing the repair engine.
