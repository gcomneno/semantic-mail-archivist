# Safe Obsolete-Message Detection

Status: **Initial contract**
Version: **0.1**
Issue: **#7 — Detect obsolete low-value messages safely**

This feature classifies historical messages that may have little remaining value.
It does not delete, Trash, archive, move, relabel, or otherwise mutate provider
state.

The classifier answers:

    Does this message look obsolete or low-value?

It does not answer:

    May the system delete this message?

Those are separate decisions under the project safety model.

## Candidate classes

The initial classifier can express:

- `expired_one_time_code`
- `old_marketing_campaign`
- `transient_service_notification`
- `obsolete_product_announcement`
- `discontinued_service_notification`
- `low_value_automated_mail`
- `unknown`

These classes describe likely obsolescence semantics. They are not retention-law
categories and do not imply a provider action.

## Separate context model

Temporal and cleanup-specific facts live in `ObsolescenceContext`, not in
`MessageSnapshot`.

This preserves the neutral message model and follows the same separation used by
document-significance and protected-domain analysis.

The context can carry:

    age_days
    automated_sender
    expiration_confirmed
    transient_event_completed
    product_superseded
    service_discontinued
    document_assessment_complete
    meaningful_correspondence
    payment_history
    account_access_record
    ambiguous_semantics

Safety-sensitive boolean fields are tri-state:

    True
    False
    None / not assessed

An unassessed safety field is not silently treated as safe.

## Positive obsolescence evidence

Age can strengthen an existing positive obsolescence signal, but never creates
one.

Examples of positive evidence include:

- direct semantics indicating a one-time code plus confirmed expiration;
- marketing semantics plus an expired campaign;
- transient-notification semantics plus a completed event;
- product-announcement semantics plus a superseded product/version;
- service-notification semantics plus a discontinued service;
- automated low-value semantics plus explicit automation and absence of
  meaningful conversation.

The initial deterministic score follows the shared confidence bands:

    HIGH    >= 0.90
    MEDIUM  >= 0.60 and < 0.90
    LOW     < 0.60

A HIGH obsolescence classification is still not mutation authorization.

## Age invariant

Age by itself contributes `0.0`.

For example:

    Age: 12 years
    Positive obsolescence semantics: none

produces:

    class: UNKNOWN
    recommendation: RETAIN

When positive obsolescence evidence already exists, age of at least 30 days may
add supporting context. This is a classifier heuristic only; it is not a
retention period and carries no legal meaning.

## Protection conflicts

The assessment records conflicts separately from obsolescence confidence.

Conflicts include:

- protected domain;
- possible protected domain;
- unknown protected-domain status;
- significant document;
- unknown document significance;
- attachment present but not assessed;
- document assessment present but not explicitly complete;
- meaningful correspondence;
- payment history;
- account-access record;
- ambiguous semantics;
- incomplete safety context.

Any of these prevents the initial classifier from recommending future Trash
review.

This allows a result such as:

    obsolescence class: OLD_MARKETING_CAMPAIGN
    confidence: HIGH
    recommendation: RETAIN
    conflict: PROTECTED_DOMAIN

The semantic conclusion remains inspectable without turning classification
confidence into mutation permission.

## Document-significance integration

Issue #5 `DocumentCandidate` values are consumed directly.

Document candidates must belong to the same message being assessed; cross-message inputs are rejected.

A `SIGNIFICANT_DOCUMENT` blocks future Trash review.

`UNKNOWN` document significance is also conservative.

If `MessageSnapshot.has_attachment` is true but the caller supplies no document
assessment, the message is retained rather than assuming the attachment is
low-value.

Supplying one or more candidates does not by itself prove that every attachment
was assessed. `document_assessment_complete=True` is therefore required before
the document gate can be considered clear for a future Trash review.

Generic attachments do not by themselves create obsolescence evidence.

## Protected-domain integration

Issue #6 `ProtectedDomainAssessment` is consumed directly.

The protection assessment must belong to the same message being assessed; cross-message inputs are rejected.

- `PROTECTED` -> retain;
- `POSSIBLY_PROTECTED` -> retain;
- `UNKNOWN` -> retain;
- `NOT_PROTECTED` removes only this protection conflict.

Omitting the protection assessment defaults to conservative retention.

`NOT_PROTECTED` does not authorize cleanup; it only means that the protected
domain gate did not find a blocking signal under an explicitly complete
assessment.

## Recommendations

The classifier can return:

    RETAIN
    REVIEW
    REVIEW_FOR_FUTURE_TRASH

`RETAIN` is used for unknown classification and for safety conflicts.

`REVIEW` means the message has some obsolescence evidence but does not meet the
foundation M4 confidence threshold.

`REVIEW_FOR_FUTURE_TRASH` requires:

- known obsolescence class;
- confidence `>= 0.995`;
- no protection conflict;
- explicitly assessed safety context.

Even this outcome is not a provider mutation and is not mutation authorization.
It means only that a future dedicated cleanup workflow may inspect the message as
an M4 candidate.

## Trash and permanent deletion remain distinct

The foundation contract defines:

    M4 = provider Trash-style destructive but recoverable
    M5 = permanent deletion

Issue #7 implements neither.

Permanent deletion remains prohibited.

A future Trash implementation must use a dedicated cleanup write mode, preserve
auditability, and re-evaluate all M4 safety gates at execution time. A historical
classification or `REVIEW_FOR_FUTURE_TRASH` result must never silently authorize
a later write.

## Privacy

The classifier uses summarized semantic cues and explicit context facts.

Evidence descriptions do not echo complete subjects, bodies, authentication
codes, attachment contents, or correspondent identifiers.

Synthetic fixtures use invented identifiers and minimal metadata only.

## Read-only boundary

Issue #7 is M0/read-only.

It does not:

- call Gmail or another provider;
- move messages to Trash;
- permanently delete messages;
- archive or relabel messages;
- unsubscribe newsletters;
- claim statutory retention periods;
- infer that old means worthless.

Its output is explainable classification plus a conservative recommendation.
