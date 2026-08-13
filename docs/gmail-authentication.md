# Gmail Local Authentication

Status: **Phase 2 authentication bootstrap**

Issue: **#25 — Add local Gmail authentication and least-privilege scope handling**

## Purpose

Semantic Mail Archivist authenticates locally to Gmail without embedding
credentials or tokens in repository files, reports, or default logs.

Authentication and semantic policy remain separate concerns.

This module authorizes access. It does not classify mail and it does not mutate
mail.

## Scope policy

Phase 2 uses two explicit authorization modes.

### Read-only mailbox access

`READ_ONLY` requests exactly:

    https://www.googleapis.com/auth/gmail.readonly

The narrower `gmail.metadata` scope was evaluated and deliberately rejected for
the complete Phase 2 read path.

`gmail.metadata` permits labels and message headers, but Gmail's `METADATA`
message format does not expose the parsed MIME payload. Phase 2 issue #26 needs
MIME structure and attachment metadata such as filename and MIME type without
downloading attachment bytes.

`gmail.readonly` is therefore the minimum Gmail scope that supports the complete
planned read-only ingestion contract.

This authorization permits more data than the application intends to consume.
Consequently authorization scope and data-minimization policy remain separate
controls.

Issue #26 must:

- use Gmail read APIs only;
- request only the fields required by the provider adapter;
- use partial responses via the Gmail `fields` parameter;
- omit body data and snippets from ordinary ingestion;
- avoid `users.messages.attachments.get` by default;
- expose missing provider facts conservatively rather than widening retrieval
  silently.

The provider adapter contract still exposes attachment metadata only.

### M1 write

`M1_WRITE` requests exactly:

    https://www.googleapis.com/auth/gmail.modify

This authorization is stored separately so the later #31 M1 implementation can
perform the one explicitly authorized label-addition write path.

Issue #25 itself performs no mailbox write.

The project deliberately never requests:

    https://mail.google.com/

which includes immediate permanent deletion capability that Semantic Mail
Archivist does not need.

## Separate authorization state

Google installed applications do not support incremental authorization as a
safe mechanism for growing one existing desktop authorization in place.

Semantic Mail Archivist therefore stores independent local authorization state
for:

- read-only mailbox access;
- future M1 write access.

A read-only workflow never falls back to or reuses the write-capable token.

If a stored token does not match the exact scope policy for its mode,
authentication fails closed and requires explicit reset/re-authorization.

## Desktop OAuth flow

The production backend uses Google's installed-application OAuth flow and a
local loopback callback on an ephemeral port.

The first authorization is interactive in the user's browser.

Subsequent runs reuse the local token when valid or refresh it when a refresh
token is available.

Refresh failure is surfaced as a redacted local error; raw OAuth responses and
token material are never copied into safe errors.

## Local paths

Defaults follow XDG-style locations.

Client configuration:

    ~/.config/semantic-mail-archivist/gmail-oauth-client.json

Authorization state:

    ~/.local/state/semantic-mail-archivist/auth/gmail/read-only-token.json
    ~/.local/state/semantic-mail-archivist/auth/gmail/m1-write-token.json
    ~/.local/state/semantic-mail-archivist/auth/gmail/account-id.key

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected when set.

Authentication state directories are forced to mode `0700` and token/key files
to mode `0600` on POSIX systems.

Before an existing OAuth client configuration is used, its file mode is also
restricted to `0600` on POSIX systems.

The OAuth client configuration is never copied into the token directory.

## Account-safe identity

The Gmail API exposes the authenticated mailbox address through profile
metadata.

The raw address must not become the default audit/log account identifier.

`GmailAccountSafeId` derives a stable local pseudonym using HMAC-SHA256 with a
random private local key.

Example shape:

    gmail:0123456789abcdef01234567

The key is local-only and protected with the same private-file policy as token
state.

The raw address is not persisted by this helper.

## Reset and re-authorization

`GmailAuthManager.reset(mode)` removes only the token for the selected
authorization mode.

Resetting read-only authorization does not delete M1-write authorization, and
vice versa.

The OAuth client configuration and account-ID key are preserved.

## Error contract

`GmailAuthError` exposes stable privacy-safe error codes for:

- missing local OAuth client configuration;
- authorization required in non-interactive mode;
- unreadable token state;
- scope mismatch;
- refresh failure;
- invalid authorization;
- failed interactive OAuth flow;
- local storage failure;
- invalid account-safe-ID key.

Raw provider/library exceptions are deliberately not copied into the safe error
detail.

## Dependencies

The core package remains provider-neutral.

Gmail OAuth support is provided as the optional package extra:

    pip install '.[gmail]'

Issue #26 can extend this Gmail extra with the Gmail API client dependency when
real provider ingestion is implemented.

## Repository safety

The repository ignores common local OAuth filenames and the project-local
emergency auth directory pattern as defense in depth.

Normal authentication state lives outside the repository.

Tests use synthetic credential objects and a fake OAuth backend. They contain no
real Google credentials.

## Provider-policy boundary

Having a `gmail.readonly` token means only that Google has authorized the
application to make read requests.

It does not authorize:

- message classification decisions;
- Semantic Mail Archivist mutation classes;
- M1 application;
- archive/Trash actions;
- permanent deletion.

Likewise, possessing a separate `gmail.modify` token is not sufficient to
authorize an M1 write. The later write workflow must still satisfy the canonical
safety gates, fresh-state preflight, mutation journal, explicit apply mode, and
audit requirements.

## Out of scope

Issue #25 does not implement:

- Gmail mailbox ingestion;
- Gmail message or label mutation calls;
- CLI audit/repair orchestration;
- M1 mutation authorization;
- hosted authentication;
- service-account/domain-wide delegation.
