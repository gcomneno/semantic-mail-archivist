# Protected Semantic Categories

Status: **Initial contract**
Version: **0.1**
Issue: **#6 — Introduce protected semantic categories**

Protected semantic categories are safety hints used to make later destructive
decisions conservative. They are independent of provider folders and of any
particular user label spelling.

Protection is not a permanent-retention rule, a statutory-retention claim, or a
deletion authorization.

## Initial taxonomy

| Domain | Rationale | Synthetic positive example | Synthetic negative example |
|---|---|---|---|
| `health_medical` | Health and medical administration can contain sensitive and irreplaceable records. | `Medical appointment report` | `Wealth planning notes` |
| `tax_fiscal` | Fiscal records can be important for reporting, audit, and personal administration. | `Tax return notice` | `Syntax workshop notes` |
| `banking_financial` | Banking and financial records may document balances, credit, loans, or account activity. | `Bank account statement` | `Project planning update` |
| `insurance` | Policies, claims, premiums, and related records may remain relevant after a conversation ends. | `Insurance policy renewal` | `Quality assurance review` |
| `contracts_employment` | Contracts and employment records can encode durable rights and obligations. | `Employment contract` | `Contractor schedule` |
| `pensions_benefits_public_admin` | Pension, benefit, social-security, and public-administration records can affect entitlements or official procedures. | `Pension benefit notice` | `Pensive writing notes` |
| `identity_authentication` | Identity and authentication records can be sensitive and difficult to replace safely. | `Passport identity card renewal` | `Matrix identity exercise` |
| `education` | Education records may document qualifications, enrolment, and academic history. | `University academic transcript` | `Educational design discussion` |
| `legal` | Legal correspondence may contain notices, claims, rights, deadlines, or procedural history. | `Legal court notice` | `Legalization workflow` |
| `payments_receipts_invoices` | Payments, receipts, and invoices can prove transactions and obligations. | `Invoice payment receipt` | `Repayment strategy` |

These examples are synthetic and deliberately minimal. They test the classifier
without exposing real mailbox or attachment content.

## Domain hints

A `ProtectedDomainHint` contains:

    domain
    confidence_score
    confidence_band
    evidence

An assessment may contain zero, one, or several hints. Multiple domains are
preserved rather than forced into a single winner. For example, a medical
insurance claim may legitimately produce both `health_medical` and `insurance`.

Confidence uses the foundation thresholds:

    HIGH    >= 0.90
    MEDIUM  >= 0.60 and < 0.90
    LOW     < 0.60

A LOW or MEDIUM domain hint is still relevant to destructive safety. Uncertainty
is not converted into permission.

## Evidence sources

The initial deterministic inference layer can consume:

- normalized subject semantics;
- semantic label hints;
- provider-visible labels only after `LabelClassifier` classifies them as
  `USER_SEMANTIC`;
- correspondent context;
- document-significance outputs from issue #5.

System, operational, and unknown labels are not silently promoted to protected
semantic evidence.

Document candidates are consumed through explicit `protected_domain:*` hints.
When duplicate candidates map to the same domain, only the strongest candidate
contributes to the score, preventing duplicate occurrences from manufacturing
higher confidence.

Evidence descriptions summarize the matched cue and domain. They do not echo full
subjects, correspondent identifiers, message bodies, or attachment contents.

## Coverage and unknown state

Protection coverage is explicit:

    PARTIAL
    COMPLETE

`PARTIAL` is the default. If no protected hint is found under partial coverage,
the assessment is `UNKNOWN`, not `NOT_PROTECTED`.

`COMPLETE` is an explicit caller assertion that all protection-relevant evidence
required by the active analysis contract was available and evaluated. The
classifier never upgrades itself to COMPLETE merely because no keyword matched.

With COMPLETE coverage and no domain hints, the result may be `NOT_PROTECTED`.
This is still only a semantic safety result, not authorization for deletion.

## Assessment states

An assessment has one of four states:

    PROTECTED
    POSSIBLY_PROTECTED
    NOT_PROTECTED
    UNKNOWN

`PROTECTED` means at least one HIGH-confidence protected-domain hint exists.

`POSSIBLY_PROTECTED` means one or more protected-domain hints exist, but none is
HIGH confidence.

`NOT_PROTECTED` requires COMPLETE coverage and zero protected-domain hints.

`UNKNOWN` means zero hints under PARTIAL coverage.

## Destructive-action protection gate

`evaluate_destructive_protection_gate()` consumes the assessment and returns one
of:

    BLOCKED_PROTECTED_DOMAIN
    BLOCKED_POSSIBLE_DOMAIN
    BLOCKED_UNKNOWN
    PASSED_NO_PROTECTED_SIGNAL

The first three outcomes block a destructive action.

`PASSED_NO_PROTECTED_SIGNAL` means only that the protected-domain gate did not
find a reason to block. It does not authorize Trash, deletion, or any other
mutation. A future M4 workflow must still satisfy all other safety gates,
confidence thresholds, write-mode requirements, significant-document checks,
positive obsolescence evidence, and auditability requirements.

This distinction preserves the foundation rule:

    classification confidence != mutation permission

## Relationship to document significance

Issue #5 and issue #6 answer different questions.

Document significance asks whether an attachment appears to be a semantically
valuable document.

Protected-domain inference asks whether a message or document plausibly belongs
to a safety-sensitive semantic domain.

A significant document can be outside the protected taxonomy. A protected
message may have no attachment at all. The two signals may reinforce each other
but remain separate.

## Read-only boundary

Issue #6 is M0/read-only.

It does not:

- call Gmail or another provider;
- add, remove, or invent mailbox labels;
- move messages;
- archive or Trash messages;
- permanently delete anything;
- claim statutory retention periods;
- make country-specific compliance guarantees;
- expose real sensitive fixture content.

Its destructive-action policy is a gate only. Actual deletion implementation
remains out of scope.
