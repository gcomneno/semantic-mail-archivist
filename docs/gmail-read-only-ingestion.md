# Gmail read-only mailbox ingestion

Issue #26 implements the first real provider path for Semantic Mail Archivist.

The boundary is:

    Gmail REST facts
      -> GmailReadAdapter
      -> ProviderReadAdapter facts
      -> provider-neutral ingestion
      -> existing core snapshots

No semantic classification policy is implemented in the Gmail adapter.

## Authorization invariant

`GmailReadAdapter` accepts only a `GmailAuthSession` whose mode is
`READ_ONLY`.

A token created for `M1_WRITE` is deliberately rejected even though Gmail may
permit read calls with that scope.

The issue exposes no mailbox mutation methods.

## Account-safe identity

The real adapter can be constructed with
`GmailReadAdapter.from_auth_manager(...)`.

That path performs one read-only Gmail profile request and requests only:

    emailAddress

The raw Gmail address exists only long enough to be passed to
`GmailAuthManager.account_safe_id(...)`, which derives the HMAC-based local
pseudonym introduced by issue #25.

The resulting `ProviderIdentity` stores only:

- provider `gmail`;
- the derived account-safe identifier.

The Gmail address is not retained by `GmailReadAdapter` and is not emitted in
the provider descriptor.

## Gmail reads

The transport implements only:

- current-user profile get for account-safe identity;
- labels list;
- threads list;
- thread metadata get;
- message MIME-structure get;
- fresh minimal message-state get.

No calls exist for:

- modify;
- batchModify;
- trash/untrash;
- delete/batchDelete;
- send;
- attachment-content download.

## Complete mailbox traversal

Thread enumeration uses Gmail `users.threads.list`.

Spam and Trash are included so an unbounded traversal represents the complete
mailbox visible to the selected account.

The provider pagination token remains opaque to the core.

Gmail permits at most 500 thread results per page; the adapter validates this
bound.

`threads.get` returns all messages belonging to one thread, so the Gmail
implementation does not invent a second provider pagination protocol for
messages.

## Data minimization

Two complementary reads are used.

### Header metadata

`threads.get` uses `format=metadata` and requests only:

- Subject;
- From;
- To;
- Cc;
- Reply-To.

No snippet or body is requested.

### MIME structure

Attachment discovery requires parsed MIME structure, which is unavailable from
Gmail `format=metadata`.

The adapter therefore performs `messages.get` with `format=full`, but applies a
partial-response `fields` selector containing only:

- message/thread identifiers;
- MIME part identifiers;
- MIME type;
- filename;
- attachment ID;
- body size;
- recursively nested MIME-part structure.

The selector deliberately omits:

- `body.data`;
- `raw`;
- `snippet`.

Attachment contents are not downloaded.

The MIME metadata selector is recursively bounded. If a container appears at
the deepest requested level, the adapter treats attachment presence
conservatively and records an explicit provider limitation rather than silently
assuming the structure is complete.

## Attachment identity

When Gmail exposes `attachmentId`, that provider ID is retained.

For attachment-like MIME parts whose bytes are inline rather than externally
addressable, a deterministic message-part identifier is used instead.

The adapter never reads the bytes to derive attachment identity.

## Label ownership

Gmail exposes label ownership as `system` or `user`.

The adapter maps those values to provider ownership only:

- Gmail `system` -> `PROVIDER_SYSTEM`;
- Gmail `user` -> `USER`;
- unknown future values -> `UNKNOWN` plus an explicit limitation.

This does not decide whether a user label is semantic or operational.

The provider-neutral `ProviderAwareLabelClassifier` makes provider system
ownership authoritative while delegating user-label taxonomy to the caller.

## Retry and failure policy

Retry is bounded.

Temporary network failures, HTTP 429, Gmail rate-limit responses and server
errors 500/502/503/504 are retryable.

Authentication, ordinary authorization and not-found failures fail closed.

Raw Gmail error messages and response bodies are never copied into
`ProviderOperationError`.

## Fresh state

`get_message_state` uses Gmail `format=full` together with the strict partial
response:

    id,labelIds,historyId

`format=minimal` is deliberately not used because Gmail documents that format
as returning only message ID and labels, while the future mutation preflight
also needs `historyId` when Gmail makes it available.

The partial response excludes payload, body data, raw content and snippets.

The fresh-state read returns:

- stable message ID;
- current label IDs;
- Inbox/Trash state derived from Gmail system label IDs;
- Gmail `historyId` as provider revision metadata when available.

It never mutates the message.

## Testing

All tests use synthetic transport/session responses.

No mailbox content, OAuth token, refresh token or attachment bytes are stored
in repository fixtures.
