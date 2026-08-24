# Gmail Production OAuth Readiness

- Issue: #50
- Commercial epic: #41
- Readiness checkpoint: #46
- Product: Mailbox Semantic Health Audit
- Scope under review: `https://www.googleapis.com/auth/gmail.readonly`

## Purpose

This document records the production OAuth delivery requirements that must be
resolved before an external customer can truthfully authorize the paid
read-only Mailbox Semantic Health Audit.

It does not widen Gmail access, introduce mailbox writes, add hosted mailbox
processing, or change semantic/safety policy.

## Existing implementation boundary

The current Audit authorization path is local and read-only.

It uses exactly:

    https://www.googleapis.com/auth/gmail.readonly

The current provider path:

- uses Google's installed-application/Desktop OAuth flow;
- performs the first authorization interactively in the user's browser;
- stores authorization state locally;
- keeps token/key files private;
- uses `GmailAuthorizationMode.READ_ONLY`;
- accepts only READ_ONLY sessions in `GmailReadAdapter`;
- exposes no Gmail mutation method through the Audit provider path.

The Mailbox Semantic Health Audit remains metadata-first.

Ordinary ingestion deliberately does not request or download:

- ordinary message body content;
- raw messages;
- snippets;
- attachment bytes;
- OCR or extracted attachment contents.

## Why `gmail.readonly` is required

Google classifies `gmail.readonly` as a restricted scope.

Semantic Mail Archivist has already evaluated the narrower
`gmail.metadata` scope.

That scope is insufficient for the current accepted Audit contract because the
Audit needs parsed MIME structure and attachment metadata while continuing to
avoid attachment-content download.

The Gmail provider therefore uses `messages.get` with `format=full` only with a
strict partial-response field selector that omits body data, raw content and
snippets.

`gmail.readonly` is consequently the minimum scope currently known to satisfy
the accepted metadata-first Audit feature set.

Any production verification request must explain this least-privilege rationale
rather than implying that Semantic Mail Archivist consumes every kind of data
the scope could technically expose.

## Proposed external-customer authorization model

The preferred production model preserves the existing local-first architecture:

    customer machine
        -> Google installed-application OAuth
        -> Gmail API
        -> local Semantic Mail Archivist processing
        -> private local Audit report

Under this model:

- the customer grants Google authorization directly to the installed/local app;
- OAuth tokens remain on the customer/operator machine;
- Gmail restricted-scope data is processed locally;
- Gmail mailbox data is not intentionally relayed through GiadaWare servers;
- no hosted mailbox-processing backend is introduced merely to satisfy OAuth;
- the Audit remains read-only and metadata-first.

This is the production model to validate unless Google verification requirements
force an explicit architectural decision to the contrary.

## Google production-verification requirements

Authoritative Google documentation currently establishes that:

1. `gmail.readonly` is a restricted Gmail API scope.
2. Production applications requesting restricted user data normally require
   OAuth app verification unless an applicable exception exists.
3. The application must request the narrowest scope necessary and justify why a
   narrower scope cannot provide the required feature.
4. Branding and consent-screen information must accurately represent the
   application.
5. The application homepage must be publicly accessible.
6. The relevant application domains must be verified where required by the
   verification process.
7. A public privacy policy must describe how Google user data is accessed, used,
   stored and shared.
8. Restricted-scope use must comply with the Google API Services User Data
   Policy and Limited Use requirements.
9. Verification material may require a demonstration showing how the user
   initiates authorization, grants the requested scope, and how that scope is
   used by the application.
10. Production OAuth configuration must declare the scopes actually used.

These requirements must be checked again against Google's authoritative
documentation at submission time because verification policy is externally
controlled and may change independently of this repository.

## Security-assessment boundary

Google's restricted-scope verification documentation states that applications
which can access restricted Google user data from or through a third-party
server must undergo the applicable security assessment.

Semantic Mail Archivist's preferred Audit architecture deliberately avoids that
data path: OAuth, Gmail access, analysis and report persistence are local.

However, this repository does not treat that architecture alone as proof of an
assessment exemption.

The applicable assessment requirement for the concrete submitted OAuth project
must be confirmed through the Google verification process or other authoritative
Google guidance before #50 can be closed.

Until then:

    security assessment applicability = UNRESOLVED

The product must not advertise that it is exempt.

## Privacy-policy requirements

The production privacy policy must accurately reflect the actual local-first
behavior.

At minimum it must state, consistently with implementation, that:

- the Audit requests Gmail read-only authorization;
- authorization does not grant Semantic Mail Archivist mutation authority;
- processing is metadata-first;
- ordinary message bodies and attachment contents are not part of ordinary
  ingestion;
- OAuth credentials/tokens are not included in reports;
- local authorization state is stored privately;
- full-mailbox Audit reports are written to an explicit private local
  destination;
- Google user data is used only for the user-facing Audit functionality
  described to the user;
- data handling follows the applicable Google API Services User Data Policy,
  including Limited Use requirements.

The final legal/privacy-policy wording is a publication requirement, not a
license to invent broader data collection.

## Human-access boundary

The automated local Audit path and human access to Google user data are separate
questions.

The existing product architecture does not require a GiadaWare operator to read
raw mailbox contents.

Any future service procedure that gives a human operator access to Google user
data or private reports must be evaluated explicitly against:

- the user's affirmative authorization/consent;
- the published privacy policy;
- Google API Services User Data Policy;
- Limited Use requirements;
- the existing Semantic Mail Archivist privacy boundary.

Issue #50 does not silently authorize human mailbox inspection.

## Production submission inputs still required

Before submission, the project needs an explicit production checklist covering:

- OAuth application identity and branding;
- verified public domain;
- public application homepage;
- public privacy policy;
- support/developer contact information;
- exact declared `gmail.readonly` scope;
- least-privilege scope justification;
- authorization/use demonstration video where required;
- external/production publishing configuration;
- confirmation of security-assessment applicability;
- any additional evidence requested by Google's verification team.

## Controlled production validation

After the required Google production configuration and verification steps permit
it, #50 requires a controlled customer-style authorization path using an
external account that is not merely the original testing-mode test account.

That validation must confirm:

- authorization completes through the approved production configuration;
- exactly `gmail.readonly` is granted for the Audit path;
- the token remains local/private;
- the existing Gmail read adapter is used unchanged;
- bounded Audit execution succeeds first;
- no provider mutation capability is requested or invoked;
- no ordinary body or attachment-byte ingestion is introduced;
- private output behavior remains intact.

No raw mailbox evidence, OAuth secrets, account address or private report should
be committed to the repository.

## Current decision

The preferred production delivery model is:

**LOCAL DESKTOP / INSTALLED-APPLICATION OAUTH**

with:

**NO INTENTIONAL GMAIL RESTRICTED-DATA TRANSIT THROUGH GIADAWARE SERVERS**

This model is architecturally compatible with the currently accepted read-only
Mailbox Semantic Health Audit.

Production readiness is not yet established.

Outstanding external work remains:

- prepare the public verification surface;
- configure the OAuth application for production submission;
- submit/complete the applicable Google verification process;
- resolve security-assessment applicability for the concrete local-only model;
- perform the controlled production customer-style authorization validation.

Until those steps are complete, #50 remains open and #46 remains:

**BLOCKED BY KNOWN LIMITATION**
