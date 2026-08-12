# Optional Operational State Layer

Status: **Initial contract**
Version: **0.1**
Issue: **#8 — Add an optional operational state layer**

The operational layer answers a different question from semantic
classification.

Semantic labels answer:

    What is this message about?

Operational labels answer:

    What does the user need to do with this message?

The two axes remain independent.

A message may therefore carry both a semantic category and one or more
operational states, for example:

    Work/Training + @Document

The operational layer does not rename, replace, or restructure the user's
semantic taxonomy.

## Initial states

The initial state vocabulary is:

- `ACTION`
- `WAITING`
- `DEADLINE`
- `DOCUMENT`
- `REFERENCE`

The default display labels are:

- `@Action`
- `@Waiting`
- `@Deadline`
- `@Document`
- `@Reference`

These names are defaults, not a universal naming convention.

`OperationalLayerConfig` allows each state to use a different preferred
label and a set of explicitly configured equivalent labels.

## Existing-label reuse

The system may reuse an existing mailbox label instead of proposing a new
display label when both conditions are true:

1. the configured operational catalog maps that label to the state;
2. the provider/user `LabelClassifier` classifies that label as
   `USER_OPERATIONAL`.

This double gate is deliberate.

A label that merely resembles an operational alias but is currently
classified as semantic is not silently reinterpreted or stolen from the
user's taxonomy.

Provider system labels are never reused as operational labels.

## Current state discovery

Operational labels already attached to the message are inspected separately
from semantic labels.

Known configured labels become `current_states`.

A label classified as `USER_OPERATIONAL` but not mapped by the operational
catalog is preserved as an unmapped operational label and causes review
rather than silently guessing its meaning.

## Proposals

The initial classifier uses explainable metadata-level evidence.

Direct subject semantics can support:

- action required;
- waiting or pending response;
- deadline or due-date context;
- document handling;
- reference-only material.

Issue #5 `DocumentCandidate` output can independently support the
`DOCUMENT` state when a significant durable document is present.

Generic attachments do not imply `DOCUMENT`.

Document candidates must belong to the same message being assessed.

## Multiple operational states

Operational states are not forced into a single winner.

Compatible states may coexist.

For example:

    ACTION + DEADLINE

is valid: the user may need to perform an action by a deadline.

The initial hard incompatibility is:

    ACTION + WAITING

because one says the user needs to act while the other says the current
workflow is waiting on someone or something else.

The configuration owns the incompatibility matrix so future workflows can
adapt it deliberately.

The classifier detects conflicts among:

- states already attached to the message;
- newly proposed states;
- current and proposed states.

Conflicts produce `REVIEW_REQUIRED`.

## Disabled mode

The complete operational layer can be disabled with:

    OperationalLayerConfig(enabled=False)

Disabled mode performs no operational inference and does not consume
document or mailbox-label inputs.

Semantic classification remains unaffected.

## Recommendations

An assessment can return:

- `DISABLED`
- `NO_PROPOSAL`
- `ALREADY_SATISFIED`
- `PROPOSE_OPERATIONAL_STATE`
- `REVIEW_REQUIRED`

A proposal contains:

- operational state;
- resolved display label;
- confidence score and band;
- explainable evidence;
- whether an existing mailbox label can be reused;
- whether a future workflow would need to create the configured label.

The phrase "requires label creation" is descriptive only.

It is not permission to create anything.

## Read-only boundary

Issue #8 is M0/read-only.

Every assessment reports:

    mutation_authorization = DENIED
    execution_status = NOT_EXECUTED

The implementation contains no provider mutation API.

It does not:

- create labels;
- apply labels;
- remove labels;
- change semantic labels;
- archive or move messages;
- create tasks;
- create reminders;
- synchronize calendars;
- call Gmail or another provider.

A future write-capable workflow must introduce a separate explicit write
mode and authorization gate.

An `OperationalStateProposal` must never itself be interpreted as mutation
authorization.

## Confidence

Operational inference uses the shared confidence bands:

    HIGH    >= 0.90
    MEDIUM  >= 0.60 and < 0.90
    LOW     < 0.60

Direct operational language is initial deterministic policy evidence rather
than a statistical probability.

Significant-document evidence reuses the confidence already produced by the
document-significance layer.

Scores are clamped to the 0.00–1.00 policy range and clamping remains
inspectable in evidence.

## Privacy

Operational evidence summarizes matched semantic cues.

It does not echo the complete message subject, message body, authentication
codes, attachment contents, or correspondent identifiers.

Synthetic fixtures use invented identifiers only.

## Out of scope

This initial layer does not implement:

- provider writes;
- task synchronization;
- calendar synchronization;
- reminder scheduling;
- universal operational label names;
- automatic restructuring of existing user workflows.
