# Mailbox Semantic Health Audit — Commercial Acceptance v1

- Acceptance artifact version: `1`
- Related epic: #41
- Commercial gate: #44
- Gate 1 evidence: #43
- Product: Mailbox Semantic Health Audit
- Assessment boundary: read-only commercial service
- Evidence baseline: repository `main` after PR #47

## Purpose

This artifact determines which behaviors and commercial claims of the Mailbox Semantic Health Audit are supported by current implementation, synthetic contract coverage, and the controlled real Gmail mailbox road test.

It does not introduce new analysis behavior, provider capability, mutation authority, pricing, customer workflow, hosted processing, or legal/compliance guarantees.

Every evaluated behavior is classified using exactly one of:

- **VERIFIED**
- **KNOWN LIMITATION**
- **REVIEW REQUIRED**
- **NOT YET SUPPORTED**

A commercial claim must not depend on behavior classified as **NOT YET SUPPORTED**.

## Product truth boundary

The accepted product sequence for this commercial gate is:

    Observe
      -> Understand
        -> Audit
          -> Protect
            -> Propose
              -> Review

Repair is outside this commercial acceptance boundary.

The Gmail ingestion path is metadata-first.

It may consume selected headers, label facts, MIME structure, and attachment metadata according to the provider contract.

It does not make complete content-level understanding of all messages or documents part of the accepted product claim.

The interpretation boundary is therefore:

- document significance = **signal/candidate**;
- protected semantic domain = **hint**;
- obsolescence = conservative **assessment**;
- incomplete evidence remains explicit;
- unknown, ambiguity, abstention, refusal, and review-required outcomes are valid product behavior.

## Approved commercial claim

The following claim is supported by this acceptance artifact:

> Identify messages and attachments that present signals of possible documentary value or sensitivity and surface where review is warranted.

The following stronger interpretations are not implied:

- complete understanding of all message or document contents;
- proof that a message is unprotected because no protection hint was found;
- legal, regulatory, tax, fiscal, employment, insurance, health, or retention advice;
- authority to delete, archive, Trash, relabel, or otherwise mutate Gmail;
- guaranteed false-positive or false-negative rates;
- guaranteed runtime for arbitrary mailboxes.

## Acceptance matrix

| Area | Classification | Acceptance decision |
| --- | --- | --- |
| Local Gmail READ_ONLY authorization | **VERIFIED** | The controlled road test authenticated successfully using Gmail read-only authority only. |
| External commercial OAuth distribution | **NOT YET SUPPORTED** | Gate 1 used a local Desktop OAuth client with the Google application in testing mode and an explicitly authorized test account. External production distribution and any required Google verification/restricted-scope review are not established. |
| Read-only provider boundary | **VERIFIED** | The audit CLI requests READ_ONLY authorization, the Gmail read adapter independently requires read-only authorization, and the road test completed without provider mutation. |
| Bounded audit semantics | **VERIFIED** | A bounded real-mailbox audit completed before full traversal and explicitly reported bounded selection. |
| Bounded audit completeness | **KNOWN LIMITATION** | A bounded audit intentionally analyzes only the selected thread subset and must not be presented as a complete mailbox assessment. |
| Full-mailbox audit semantics | **VERIFIED** | A real full-mailbox traversal completed successfully and produced a private human-readable report. |
| Taxonomy summary availability | **VERIFIED** | Taxonomy summary data is part of the audit report and was observed in bounded and full road-test output. |
| Taxonomy semantic correctness for every label | **REVIEW REQUIRED** | Structural availability and plausibility do not prove perfect semantic interpretation of every user label. |
| Message-level label-gap detection | **VERIFIED** | Gap findings are first-class report records, summary counts are computed from records, and real full-mailbox findings were observed. |
| Gap precision and recall on arbitrary real mailboxes | **REVIEW REQUIRED** | No manually established ground-truth corpus currently supports a measured precision/recall claim. |
| Document-significance candidates | **VERIFIED** | The classifier surfaces document-significance candidates from metadata-first evidence and preserves `unknown` when semantics are insufficient. |
| Complete content-level document understanding | **NOT YET SUPPORTED** | Attachment bytes, OCR, and complete document contents are outside the ordinary read surface and current classifier contract. |
| Protected-domain hints | **VERIFIED** | Protected-domain hints are explicit safety evidence and preserve partial-coverage semantics. |
| Absence of a protected hint proves absence of sensitivity | **NOT YET SUPPORTED** | Under partial coverage, zero hints result in uncertainty rather than proof that a message is unprotected. |
| Obsolescence assessment | **VERIFIED** | Obsolescence is evaluated conservatively; incomplete safety context, unknown document significance, and protected-domain uncertainty bias toward retention. |
| Deletion or retention authority | **NOT YET SUPPORTED** | An audit assessment is not mutation authority and is not a legal or permanent-retention decision. |
| Provider limitations | **VERIFIED** | Provider limitations are stable first-class report records and bounded-selection limitations were observed in the real road test. |
| Incomplete and ambiguous evidence | **VERIFIED** | Unknown, ambiguity, abstention, refusal, warning, and review-required behavior are explicit rather than silently guessed through. |
| Human-readable report | **VERIFIED** | Human output exists, is privacy-bounded by contract, and was produced for both bounded and full real-mailbox runs. |
| Machine-readable JSON report | **VERIFIED** | JSON uses the existing audit schema; a bounded real-mailbox JSON report was produced and full-mailbox JSON private-file behavior has synthetic CLI coverage. |
| Summary-to-record traceability | **VERIFIED** | Audit summary counts are derived from per-message records and explicit regression coverage verifies traceability. |
| Deterministic machine representation | **VERIFIED** | Regression coverage verifies deterministic machine output across thread ordering. |
| Privacy-safe report schema | **VERIFIED** | Report serialization deliberately excludes ordinary bodies, attachment contents, and sensitive provider fields; sanitized real-report scans found no tested credential/address/header patterns. |
| Local report persistence | **VERIFIED** | Real reports were stored locally outside the repository. |
| Private report permissions | **VERIFIED** | Real bounded, JSON, and full human reports were observed with mode `0600`. |
| Explicit destination for full-mailbox output | **VERIFIED** | Full-mailbox human and JSON audit paths require an explicit local destination. |
| Runtime on the Gate 1 mailbox | **VERIFIED** | The full road test completed in approximately 60 minutes on the tested mailbox. |
| Runtime generalization | **KNOWN LIMITATION** | One real mailbox observation is an operational measurement, not a benchmark or service-level guarantee for arbitrary mailboxes. |
| False-positive behavior | **REVIEW REQUIRED** | Synthetic tests cover conservative and ambiguous cases, but no real-mailbox ground truth currently supports a quantified or comprehensive false-positive claim. |
| False-negative behavior | **REVIEW REQUIRED** | Metadata-first analysis and partial evidence make comprehensive false-negative validation impossible without additional ground truth and/or broader evidence access. |
| Failure and refusal behavior | **VERIFIED** | Provider/network failures, unknown provider facts, ambiguous document classes, incomplete evidence, bounded limitations, and read-only refusal boundaries have explicit synthetic coverage; local OAuth setup also failed closed before remediation. |
| Gmail provider retry behavior | **VERIFIED** | Bounded retry behavior for rate limiting and network failure has regression coverage. |
| No-mutation commercial boundary | **VERIFIED** | Audit is M0/read-only; mutation authorization remains denied and execution not performed in the audit report contract and Gate 1 road test. |
| Legal/compliance/retention guarantees | **NOT YET SUPPORTED** | The product surfaces safety signals; it does not provide legal certification, statutory retention advice, or compliance guarantees. |

## Report completeness and consistency

### Structural completeness — VERIFIED

The audit report contains:

- summary;
- taxonomy summary;
- per-message records;
- warnings;
- provider limitations;
- explicit read-only mode;
- mutation authorization;
- execution status.

Summary-to-record traceability has dedicated regression coverage.

The bounded real-mailbox JSON report additionally provided machine-readable evidence that:

- `mode` was `read_only_audit`;
- `read_only` was true;
- mutation authorization was denied;
- execution status was not executed.

### Semantic completeness — KNOWN LIMITATION

Structural completeness is not equivalent to semantic omniscience.

The audit cannot establish complete semantic interpretation when the provider does not supply sufficient evidence.

Examples include:

- incomplete label ownership/catalog facts;
- incomplete requested headers;
- incomplete attachment metadata;
- partial protection coverage;
- absent obsolescence context;
- metadata that supports only `unknown`.

These states must remain visible in commercial delivery.

## Bounded versus full-mailbox semantics

### Bounded audit — VERIFIED

A bounded audit is suitable for:

- safe initial validation;
- operator inspection;
- confirming the report shape;
- confirming provider and privacy behavior;
- validating that incomplete selection is surfaced.

It is not a complete mailbox assessment.

### Full-mailbox audit — VERIFIED

The Gate 1 full traversal analyzed the complete mailbox selection exposed by the supported Gmail traversal and completed successfully.

No bounded-selection provider limitation remained in the full run.

This does not eliminate other metadata/provider limitations that may occur on different accounts or messages.

## Privacy acceptance

### VERIFIED

The accepted service remains local-first and privacy-bounded.

Gate 1 verified:

- reports remained outside the repository;
- private report files used mode `0600`;
- raw reports were not copied into issues or pull requests;
- sanitized scans found no tested email-address, OAuth-token, Google client-secret, authorization-code, or explicit Subject/From/To rendering patterns;
- the bounded report also exposed no likely attachment filenames in the performed scan.

The public acceptance artifact contains only sanitized aggregate/process evidence.

### KNOWN LIMITATION

Aggregate statistics may still describe characteristics of the tested mailbox.

Only aggregates judged necessary for product acceptance are retained publicly.

Raw road-test reports remain private operational evidence and are not part of this artifact.

## False-positive review

### Classification: REVIEW REQUIRED

Existing synthetic coverage demonstrates conservative handling of several obvious false-positive risks, including:

- ambiguous document classes becoming `unknown`;
- document-compatible MIME types remaining `unknown` without stronger semantics;
- generic images not being forced into significant-document classifications;
- exact duplicates not being reinterpreted as semantically worthless;
- unknown labels not being silently promoted into semantic evidence;
- partial protection evidence not being interpreted as proof of safety.

This supports conservative product behavior.

It does not establish a measured false-positive rate on real mailboxes.

A future acceptance revision may upgrade this area only if a privacy-safe reviewed ground-truth procedure is defined and executed.

## False-negative review

### Classification: REVIEW REQUIRED

The current product deliberately prefers incomplete/unknown results over invented certainty.

Known false-negative risk boundaries include:

- ordinary message body content is outside the metadata-first analysis surface;
- attachment contents are not downloaded;
- OCR is not performed;
- partial protection coverage cannot prove absence of a protected domain;
- incomplete provider facts remain explicit limitations.

This means the absence of a finding must not be sold as proof that no relevant message, document, or protected-domain signal exists.

A quantified false-negative claim is not currently supported.

## Failure and refusal behavior

### VERIFIED

The accepted product treats controlled failure, abstention, and refusal as valid safety outcomes.

Regression coverage includes:

- bounded provider retry behavior;
- network failure;
- incomplete requested headers;
- incomplete attachment metadata;
- unknown provider label types;
- unknown provider message facts;
- ambiguous semantics;
- ambiguous document classification;
- incomplete protection evidence;
- incomplete obsolescence evidence;
- full-mailbox output without an explicit private destination.

The Gate 1 setup additionally demonstrated fail-closed behavior when optional Gmail dependencies were absent.

## Operational characteristics

The Gate 1 full-mailbox run completed successfully.

Observed characteristics were approximately:

- 13,116 messages analyzed;
- 60 minutes elapsed;
- 158 MiB maximum RSS;
- 9.3 MiB human report.

These values describe one controlled mailbox road test.

They are not:

- a performance guarantee;
- a throughput benchmark;
- a maximum mailbox size;
- an SLA;
- evidence that interactive completion should be expected.

For the current commercial boundary, full-mailbox execution should therefore be treated as a batch/service-delivery operation rather than an interactive request.

## OAuth delivery dependency

### NOT YET SUPPORTED

The controlled Gate 1 road test proves that the local Gmail integration works with the required read-only scope.

It does not prove that a customer can yet authorize the application through a production commercial OAuth flow.

Before external customer delivery, later commercial-readiness work must determine and satisfy the applicable Google OAuth publication, verification, restricted-scope, and operational distribution requirements.

This limitation does not invalidate the local product capability demonstrated by Gate 1.

It does prevent claiming that external customer OAuth onboarding is already commercially ready.

## Commercial claim mapping

| Commercial statement | Decision |
| --- | --- |
| "We can inspect a Gmail mailbox without modifying it." | **VERIFIED** |
| "We can expose the mailbox's observed taxonomy and message-level organization gaps." | **VERIFIED** |
| "We can identify messages and attachments presenting signals of possible documentary value." | **VERIFIED** |
| "We can surface protected-domain hints and uncertainty where review is warranted." | **VERIFIED** |
| "We can conservatively surface possible low-value/obsolete messages without granting deletion authority." | **VERIFIED** |
| "We understand every message and document completely." | **NOT YET SUPPORTED** |
| "No protection hint means the message is safe or unimportant." | **NOT YET SUPPORTED** |
| "The audit provides legal/compliance/retention advice." | **NOT YET SUPPORTED** |
| "The audit can safely delete or modify Gmail." | **NOT YET SUPPORTED** |
| "Our findings have a measured real-mailbox precision/recall guarantee." | **NOT YET SUPPORTED** |
| "Any Gmail customer can already complete production OAuth onboarding." | **NOT YET SUPPORTED** |

No accepted commercial statement depends on a **NOT YET SUPPORTED** capability.

## Reproducibility runbook

### Repository verification

From a clean source checkout:

    git status --short --branch
    git rev-parse HEAD
    PYTHONPATH=src python -m unittest discover -s tests -v

The test result must be recorded rather than assumed.

### Bounded Gmail road test

Using a privately configured Gmail Desktop OAuth client and exactly the Gmail read-only scope:

    semantic-mail-archivist \
        --format human \
        --output <PRIVATE_LOCAL_PATH> \
        audit \
        --max-threads 10

Then repeat using:

    --format json

The operator must verify:

- local private destination;
- private file permissions;
- explicit bounded-selection limitation;
- read-only mode;
- mutation authorization denied;
- execution status not executed;
- warnings/provider limitations remain visible.

Do not publish the raw report.

### Full-mailbox road test

Only after bounded output has been accepted:

    semantic-mail-archivist \
        --format human \
        --output <PRIVATE_LOCAL_PATH> \
        audit

The operator must verify:

- explicit private destination;
- report persistence;
- file permissions;
- successful completion or recorded operational failure;
- no provider mutation;
- runtime recorded as operational evidence.

A full-mailbox JSON run is not required merely to prove the report schema if the bounded real JSON run and existing full-mailbox JSON contract tests remain valid.

## Acceptance conclusion

The Mailbox Semantic Health Audit is **accepted for the current read-only commercial product boundary**, subject to the limitations classified in this artifact.

The accepted capability is:

> Understand and report the observed semantic health of a Gmail mailbox, surface organization gaps and review-worthy document/protection/obsolescence signals, and preserve uncertainty without modifying Gmail.

Commercial delivery must continue to state clearly that:

- findings are evidence-based signals rather than complete content understanding;
- incomplete evidence remains visible;
- absence of a finding is not proof of absence;
- false-positive and false-negative accuracy remains review-required rather than quantified;
- the audit grants no mutation authority;
- external production OAuth onboarding is not yet established;
- legal/compliance/retention guarantees are not provided.

This artifact is suitable as the Gate 2 input to later public product-status and service-boundary work.
