# Semantic Mail Archivist

> **Preserve the meaning of your mailbox, not just the messages.**

Semantic Mail Archivist is a privacy-first, local-first project for understanding, repairing, classifying, and preserving the semantic structure of long-lived email archives.

Its first commercially evaluated product boundary is the **Mailbox Semantic Health Audit**: a read-only Gmail audit that helps reveal the mailbox's observed taxonomy, organization gaps, and review-worthy document, protection, and obsolescence signals without modifying Gmail.

Email is more than an inbox. Over years it becomes a personal and professional knowledge base containing documents, decisions, relationships, contracts, receipts, administrative records, technical history, and other context that may be difficult or impossible to reconstruct elsewhere.

The problem is that this structure silently degrades. A conversation can look correctly organized to a user while individual messages inside the thread no longer carry the expected user labels. Important documents become buried among generic attachments. Old notifications and obsolete services accumulate beside records that must never be removed casually.

Semantic Mail Archivist aims to make that archive trustworthy again without replacing the organization its owner has already built.

## Core principle

> **Learn the user's taxonomy. Do not impose one.**

The existing mailbox organization is evidence. Semantic Mail Archivist should first understand it, then repair gaps, propose classifications, identify valuable documents, and surface obsolete material conservatively.

The non-negotiable project invariants are recorded in the [Project Charter](docs/PROJECT_CHARTER.md).

## Mailbox Semantic Health Audit

The first commercial product boundary is deliberately read-only:

```text
Observe
  -> Understand
    -> Audit
      -> Protect
        -> Propose
          -> Review
```

`Repair` is outside this first paid Audit boundary.

The Gmail audit is metadata-first. The current read path may consume:

- Gmail label facts;
- selected message headers: Subject, From, To, Cc, and Reply-To;
- MIME structure;
- attachment metadata such as MIME type, filename, attachment identifier, size, and part structure.

Ordinary ingestion deliberately does not request or download:

- ordinary message body content;
- raw messages;
- snippets;
- attachment bytes;
- OCR or extracted attachment contents.

The Gmail integration uses exactly `https://www.googleapis.com/auth/gmail.readonly` for this read-only path. That scope is broader than the application's ordinary data surface because Gmail requires it to expose MIME structure; the adapter still minimizes the fields actually requested.

Within this boundary:

- document significance is a **signal/candidate**, not complete document understanding;
- protected-domain output is a **hint/safety signal**, not proof of complete coverage;
- obsolescence is a conservative **assessment**, not deletion authority;
- unknown, ambiguous, incomplete, review-required, and refusal outcomes are valid results;
- absence of a finding is not proof that no relevant signal exists;
- the audit makes no legal, statutory-retention, compliance, or certification guarantee.

The accepted public claim is:

> Identify messages and attachments that present signals of possible documentary value or sensitivity and surface where review is warranted.

See [Commercial Acceptance v1](docs/mailbox-semantic-health-audit-acceptance-v1.md) for the verified claim and limitation matrix.

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

## Current local product surface

The current implementation is a local, read-first CLI rather than a GUI.

Gmail-backed read-only Audit and repair dry-run orchestration are implemented. Explicit mailbox writes remain disabled.

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

### Future explicit apply

```text
semantic-mail-archivist repair --apply
```

This command surface represents explicit write intent, but write execution is currently disabled.

The broader Phase 2 roadmap keeps mutation work separate from read-only Audit readiness:

- **M1 — additive reversible:** explicit apply remains separate Phase 2 work; fresh-state preflight, journaling, auditability, and rollback must be satisfied before it can become trustworthy;
- **M2 — corrective reversible:** disabled unless explicitly implemented later;
- **M3 — placement/state change:** disabled unless explicitly implemented later;
- **M4 — Trash-style destructive but recoverable:** disabled unless explicitly implemented later and subject to stricter safety gates;
- **M5 — permanent destructive:** prohibited by the initial safety contract.

A successful Audit or dry-run never grants deferred mutation authority.

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

The foundation contracts are implemented through a local CLI, Gmail read-only provider integration, mailbox Audit, and Gmail-backed repair dry-run.

The **Mailbox Semantic Health Audit** has completed its controlled real-mailbox road test and its dedicated commercial acceptance report. Public documentation now reflects that verified read-only product boundary.

This does **not** by itself declare the service commercially ready. The final commercial-readiness checkpoint remains separate work under issue #46, including unresolved external production OAuth delivery requirements.

The broader Phase 2 roadmap also remains incomplete: explicit M1 apply and rollback are separate work, and later M2/M3/M4 mutation paths remain disabled unless explicitly implemented. M5 permanent deletion remains prohibited by the initial safety contract.
