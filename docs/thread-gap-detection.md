# Message-level label gap detection

Status: **Initial detector contract**  
Issue: **#2 — Detect message-level label gaps inside classified threads**

This document defines the boundary of the first executable detector in Semantic Mail Archivist.

The detector answers only:

> Does this message lack a semantic user label while other messages in the same thread provide semantic classification evidence?

It does **not** answer which label should be applied and it never mutates provider state.

## Inputs

The core consumes provider-independent snapshots:

```text
ThreadSnapshot
  thread_id
  messages[]

MessageSnapshot
  message_id
  labels[]
  has_attachment
```

Provider-specific label semantics are supplied through a `LabelClassifier` adapter.

The initial Gmail adapter recognizes well-known Gmail system labels separately from user labels and accepts explicit operational user labels. Its system-label set is configurable so a future Gmail API integration can supply provider metadata rather than treating the built-in list as permanent truth.

## Detection rule

A message becomes a gap candidate when:

1. the message itself has no `USER_SEMANTIC` label; and
2. at least one other message in the same thread has a `USER_SEMANTIC` label.

The detector then returns the surrounding semantic evidence rather than resolving it.

If exactly one distinct semantic label appears in the surrounding evidence, the context is reported as:

```text
STABLE
```

If more than one distinct semantic label appears, the context is reported as:

```text
CONFLICTING
```

`STABLE` is a description of observed context, **not an inference decision or confidence score**. Issue #3 owns inference and confidence scoring.

## What is deliberately excluded

A thread containing only provider/system labels does not provide semantic evidence and therefore produces no gap candidate.

Operational labels do not satisfy semantic classification. A message carrying only `@Waiting`, for example, can still be a semantic gap.

Messages that already carry at least one semantic user label are not reported as gaps.

## Attachments

The detector preserves the message-level `has_attachment` fact on a candidate but performs no document classification.

This distinction is intentional:

```text
message has attachment != attachment is a significant document
```

Document significance belongs to #5.

## Output

Each `LabelGapCandidate` contains:

```text
thread_id
message_id
has_attachment
context_status
surrounding_evidence[]
```

Each evidence item contains:

```text
label
supporting_message_ids
support_count
```

No proposed label is present in the output model.

## Synthetic acceptance scenarios

The automated tests cover:

1. a clean thread with the same semantic label before and after an unlabelled reply;
2. an unlabelled message surrounded by competing semantic labels;
3. a thread containing only Gmail/system labels, including `CHAT`;
4. provider-supplied system-label metadata;
5. an unlabelled message with an attachment;
6. a message that is already semantically labelled;
7. an operational-only label that must not hide a semantic gap.

All scenarios are synthetic and contain no mailbox-derived content.

## Safety boundary

This detector is mutation class **M0 — Read-only** under the classification and safety model.

It does not:

- calculate confidence;
- infer a missing label;
- create labels;
- add or remove labels;
- archive messages;
- move messages to Trash;
- inspect attachment contents;
- call Gmail or any other provider API.

Those boundaries are intentional acceptance properties, not temporary omissions.
