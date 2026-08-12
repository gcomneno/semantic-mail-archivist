# Document Significance

Status: **Initial contract**
Version: **0.1**
Issue: **#5 — Detect significant documents versus generic attachments**

This module distinguishes attachment presence from document significance using
metadata and message context only.

The issue #2/#3 `has_attachment` fact remains neutral. The document-significance
classifier is a separate read-only decision layer.

## Input boundary

`AttachmentSnapshot` contains only metadata needed by the first classifier:

    attachment_id
    filename
    mime_type
    disposition
    is_repeated_template
    exact_duplicate_count
    near_duplicate_count

The classifier does not accept attachment bytes, extracted document text, OCR
output, provider credentials, or mutation handles.

Message context comes from the existing `MessageSnapshot` fields. Correspondent,
subject, and semantic-hint data may contribute directly. Raw provider-visible
labels contribute only when a `LabelClassifier` is supplied, and only labels
classified as `USER_SEMANTIC` are accepted as taxonomy evidence. System,
operational, and unknown labels are not silently promoted to semantic evidence.

Evidence descriptions summarize matched cues instead of echoing full personal
context.

## Output

`DocumentCandidate` exposes:

    message_id
    attachment_id
    filename
    document_class
    significance
    confidence_score
    confidence_band
    evidence
    protection_hints

Significance has three first-class outcomes:

    significant_document
    generic_attachment
    unknown

The classifier can therefore refuse to force a document type.

## Initial document classes

The first deterministic model recognizes:

    contract
    tax
    insurance
    receipt
    invoice
    administrative
    medical

It also exposes:

    generic_attachment
    unknown

These are classifier outputs, not mailbox labels. In particular, issue #5 never
applies `@Document`.

## Evidence model

The first version uses explainable metadata/context signals:

- filename semantics;
- normalized subject semantics;
- classified user semantic taxonomy / semantic hints;
- correspondent context;
- document-compatible MIME type;
- provider attachment versus inline disposition;
- repeated/template metadata;
- exact and near-duplicate occurrence metadata.

Filename/context matches are summarized as matched cue names. Full subjects,
addresses, attachment contents, and message bodies are not copied into evidence.

A regular document MIME type strengthens an already-supported document class but
does not invent one by itself. A PDF named only `scan-001.pdf`, for example,
remains `unknown` until stronger semantics exist.

## Inline and generic assets

Inline placement alone does not prove that an image is decorative. An inline
image with no decorative or document semantics remains `unknown`.

Image files with obvious decorative names such as logo, icon, banner, spacer,
signature, pixel, or avatar are generic attachments; inline placement strengthens
that conclusion.

A non-inline image without document semantics is classified as a generic
attachment rather than being forced into a document class.

## Repeated templates and duplicates

Repeated/template metadata is negative evidence for a distinct significant
record, but it is not an absolute veto. A strongly supported contract or
administrative document may remain significant at reduced confidence.

Exact duplicate occurrences do not reduce semantic document significance. They
are reported through `duplicate_occurrence` so a future indexing layer can avoid
redundant storage or indexing without pretending the document became worthless.

Near-duplicate occurrences are not collapsed automatically. They receive
`near_duplicate_review`, because small differences may be semantically important.

Issue #5 does not calculate fingerprints or near-duplicate similarity itself;
those counts are normalized metadata supplied by an upstream collector.

## Protection hints

A significant candidate carries `significant_document` plus a conservative hint
when the class maps to a protected domain from the foundation safety contract.

Examples include:

    protected_domain:tax_fiscal
    protected_domain:insurance
    protected_domain:payments_receipts_invoices
    protected_domain:health_medical
    protected_domain:contracts_employment

Administrative records receive a retention-review hint rather than an automatic
claim that every administrative attachment belongs to public administration.

Protection hints are safety evidence only. They do not decide legal retention,
indexing, mailbox mutation, Trash eligibility, or deletion.

## Read-only boundary

The classifier is M0/read-only.

It does not:

- call Gmail or another provider;
- create, add, remove, or inherit `@Document`;
- archive or trash messages;
- download attachment bodies;
- perform OCR;
- extract full document content;
- calculate retention/deletion policy.

A later workflow may consume document-significance evidence, but classification
confidence is not mutation authorization.
