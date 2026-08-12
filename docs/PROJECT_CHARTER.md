# Project Charter

Semantic Mail Archivist repairs, classifies, and preserves the semantic structure of long-lived email archives without replacing the organization their owners already built.

## Constitution

> **Learn the user's taxonomy. Do not impose one.**

## Product contract

The project must prefer explainable, reversible, auditable behavior over aggressive automation.

Classification and mutation are separate concerns. A system may be confident that a message belongs to a category without being authorized to change the mailbox. Destructive actions require a materially higher confidence standard than non-destructive classification.

The canonical foundation policy for these decisions is [`classification-safety-model.md`](classification-safety-model.md). Implementations must conform to that contract rather than inventing safety policy inside provider adapters, classifiers, or write workflows.

## Safety invariants

1. Existing user taxonomy is evidence, not noise to normalize away.
2. Thread-level context must not be treated as proof that every message shares the same semantic category.
3. Ambiguity must be surfaced rather than hidden behind a guessed classification.
4. Protected semantic domains must never be subjected to casual automatic deletion.
5. Development and tests must use synthetic or explicitly sanitized fixtures.
6. Dry-run behavior must be available before write behavior.
7. Every mutation must be explainable and auditable.
8. Provider credentials, tokens, message bodies, and sensitive attachment content must not leak into default logs.
9. Local-first analysis must remain a supported architectural path.
10. A refusal to modify a message is a valid successful outcome when evidence is insufficient.

## Initial implementation boundary

The first implementation target is a local CLI with Gmail as the initial provider integration. Provider-specific behavior should be isolated behind adapters where practical.

The foundation phase ends when the safety model, inference contract, synthetic acceptance fixtures, dry-run format, and audit contract are specified well enough to implement without inventing policy inside application code.
