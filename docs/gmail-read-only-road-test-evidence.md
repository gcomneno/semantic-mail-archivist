# Gmail read-only road-test evidence

This document records sanitized evidence for issue #43, the first commercial-readiness gate for the Mailbox Semantic Health Audit.

It deliberately excludes raw mailbox records, message or thread identifiers, real subjects, correspondent addresses, attachment filenames, OAuth material, account identifiers, and private report contents.

## Scope

The road test exercised the existing Gmail-backed `audit` path against a real mailbox using only the configured Gmail read-only authorization.

The test did not enable, require, or invoke provider mutation.

The ingestion boundary remained metadata-first:

- selected message headers may be read;
- MIME structure and attachment metadata may be read;
- ordinary message bodies are not normally read;
- raw messages are not read;
- snippets are not read;
- attachment bytes are not downloaded.

Document-significance output therefore remains a candidate or signal, protected-domain output remains a hint, and obsolescence remains a conservative assessment.

## Preconditions verified

Before mailbox access:

- repository `main` matched `origin/main`;
- working tree was clean;
- the canonical test suite passed with 263 tests;
- local configuration and authentication material remained outside the repository;
- OAuth client material was installed with private permissions;
- Gmail authorization completed with exactly `gmail.readonly`;
- the read-only token was persisted with mode `0600`;
- no write-authority token was present.

## Setup failure modes and remediation

The road test also exercised realistic local setup failure modes before mailbox access.

The first authorization attempt failed closed because the active Python environment did not contain the optional Gmail dependencies.

An attempted user-level installation into the distribution-managed Python environment was then rejected by the operating system under PEP 668.

The remediation was to create an isolated local virtual environment outside the repository and install the repository-declared `gmail` optional dependency set there.

After that remediation:

- the OAuth modules imported successfully;
- the repository remained unchanged and clean;
- authorization completed with exactly `gmail.readonly`;
- no mailbox access occurred during the failed setup attempts.

This confirms that Gmail runtime dependencies are operationally required and that an isolated environment is the appropriate local installation path on distribution-managed Python systems.

## OAuth delivery boundary

The successful road test used a locally configured Google OAuth Desktop client with the Google Auth Platform application in testing mode and the test account explicitly authorized.

This is sufficient evidence for the controlled Gate 1 road test.

It is not evidence that external commercial OAuth distribution, Google verification requirements, or any restricted-scope production review has been completed. Those remain delivery and product-readiness dependencies for later gates.

## Bounded road test

A bounded audit was executed first with a maximum of 10 Gmail threads.

Because Gmail threads may contain multiple messages, the bounded run analyzed 11 messages.

Both human-readable and JSON reports were produced locally with mode `0600`.

Sanitized aggregate evidence from the JSON report:

| Metric | Result |
| --- | ---: |
| Messages analyzed | 11 |
| Semantic taxonomy labels visible to the audit | 212 |
| Message-level label gaps | 0 |
| Significant document candidates | 0 |
| Unknown document candidates | 5 |
| Protected-domain candidates | 6 |
| Messages with protected-domain candidates | 4 |
| Obsolete low-value candidates | 0 |
| Future Trash review candidates | 0 |
| Warnings | 22 |
| Provider limitations | 1 |

The bounded-selection limitation was explicitly reported as:

`bounded_mailbox_selection`

Incomplete-evidence semantics were preserved:

- all 11 messages had partial protection coverage;
- protection status was `possibly_protected` for 4 messages and `unknown` for 7;
- all 11 obsolescence assessments remained `unknown`;
- all 11 obsolescence recommendations were `retain`;
- warnings consisted of missing obsolescence context and partial protection coverage;
- attachment findings remained `generic_attachment` or `unknown`.

The JSON contract also explicitly reported:

- mode `read_only_audit`;
- `read_only = true`;
- mutation authorization `DENIED`;
- execution status `NOT_EXECUTED`.

## Privacy verification

Sanitized checks against the bounded human and JSON reports found no:

- email-address-like values;
- OAuth access-token patterns;
- Google client-secret patterns;
- OAuth authorization-code patterns;
- explicit Subject, From, or To header rendering;
- likely attachment filenames.

Raw reports were never copied into the repository, issue, pull request, or public evidence.

## Full-mailbox road test

After accepting the bounded run, a full-mailbox audit was executed successfully.

Operational measurements:

| Metric | Result |
| --- | ---: |
| Messages analyzed | 13,116 |
| Elapsed time | approximately 60 minutes |
| Maximum RSS | approximately 158 MiB |
| Local human report size | approximately 9.3 MiB |
| Semantic taxonomy labels visible to the audit | 212 |
| Message-level label gaps | 3,728 |
| Significant document candidates | 438 |
| Unknown document candidates | 3,741 |
| Messages with protected-domain candidates | 3,432 |
| Obsolete low-value candidates | 122 |
| Future Trash review candidates | 0 |
| Warnings | 26,232 |
| Provider limitations | 0 |

The full report was persisted locally with mode `0600`.

Sanitized privacy checks again found no email-address-like values, OAuth material, or explicit Subject, From, or To header rendering.

The full audit completed without provider mutation.

## Operational finding

The complete mailbox traversal succeeded, but required approximately one hour for this mailbox.

This is a relevant service-delivery finding for later commercial acceptance work: full-mailbox execution is operationally viable on the tested mailbox, but runtime must be treated as a material delivery characteristic rather than assumed to be interactive.

No performance optimization is introduced by this gate.

## Gate 1 conclusion

The road test demonstrates that the current Mailbox Semantic Health Audit can:

- authenticate to Gmail with read-only authority;
- execute a bounded real-mailbox audit before full traversal;
- produce private human and machine-readable reports;
- expose taxonomy and label-gap findings;
- surface document-significance candidates without claiming content understanding;
- surface protected-domain hints while preserving partial-coverage semantics;
- keep obsolescence conservative and non-destructive;
- make bounded incompleteness and provider limitations explicit;
- complete a full-mailbox traversal;
- preserve the no-mutation boundary throughout the tested path.

The evidence remains intentionally sanitized and is suitable as an input to the Gate 2 acceptance report.
