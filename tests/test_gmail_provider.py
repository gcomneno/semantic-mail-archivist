from pathlib import Path
import unittest

from semantic_mail_archivist import (
    GMAIL_MESSAGE_STRUCTURE_FIELDS,
    GmailAuthSession,
    GmailAuthorizationMode,
    GmailReadAdapter,
    GmailReadRetryPolicy,
    GoogleGmailReadTransport,
    ProviderErrorCode,
    ProviderLabelKind,
    ProviderOperationError,
    ProviderReadAdapter,
    ProviderWriteCapability,
)


class FakeCredentials:
    pass


class FakeGmailTransport:
    def __init__(self):
        self.profile = {
            "emailAddress": "user@example.test",
        }

        self.labels = {
            "labels": [
                {
                    "id": "INBOX",
                    "name": "INBOX",
                    "type": "system",
                },
                {
                    "id": "Label_1",
                    "name": "Projects/Alpha",
                    "type": "user",
                    "labelListVisibility": "labelShow",
                },
            ]
        }

        self.thread_pages = {
            None: {
                "threads": [{"id": "t-1"}],
                "nextPageToken": "next",
            },
            "next": {
                "threads": [{"id": "t-2"}],
            },
        }

        self.threads = {
            "t-1": {
                "id": "t-1",
                "messages": [
                    {
                        "id": "m-1",
                        "threadId": "t-1",
                        "labelIds": [
                            "INBOX",
                            "Label_1",
                        ],
                        "historyId": "101",
                        "payload": {
                            "headers": [
                                {
                                    "name": "Subject",
                                    "value": "Project Alpha",
                                },
                                {
                                    "name": "From",
                                    "value": "Alice <alice@example.test>",
                                },
                                {
                                    "name": "To",
                                    "value": "Bob <bob@example.test>",
                                },
                            ]
                        },
                    }
                ],
            },
            "t-2": {
                "id": "t-2",
                "messages": [],
            },
        }

        self.structures = {
            "m-1": {
                "id": "m-1",
                "threadId": "t-1",
                "payload": {
                    "partId": "",
                    "mimeType": "multipart/mixed",
                    "body": {"size": 0},
                    "parts": [
                        {
                            "partId": "0",
                            "mimeType": "text/plain",
                            "body": {"size": 20},
                        },
                        {
                            "partId": "1",
                            "mimeType": "application/pdf",
                            "filename": "contract.pdf",
                            "body": {
                                "attachmentId": "att-1",
                                "size": 1234,
                            },
                        },
                    ],
                },
            }
        }

        self.states = {
            "m-1": {
                "id": "m-1",
                "labelIds": [
                    "INBOX",
                    "Label_1",
                ],
                "historyId": "102",
            }
        }

    def get_profile(self):
        return self.profile

    def list_labels(self):
        return self.labels

    def list_threads(
        self,
        *,
        page_token=None,
        page_size=None,
    ):
        return self.thread_pages[page_token]

    def get_thread_metadata(self, thread_id):
        return self.threads[thread_id]

    def get_message_structure(self, message_id):
        return self.structures[message_id]

    def get_message_state(self, message_id):
        return self.states[message_id]


def read_session():
    return GmailAuthSession(
        mode=GmailAuthorizationMode.READ_ONLY,
        token_path=Path("/synthetic/read.json"),
        credentials=FakeCredentials(),
    )


class FakeAuthManager:
    def __init__(self):
        self.identifiers = []

    def account_safe_id(
        self,
        identifier,
    ):
        self.identifiers.append(
            identifier
        )
        return "gmail:derived-safe-id"


class FakeResponse:
    def __init__(
        self,
        status_code,
        payload,
    ):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class SyntheticNetworkError(Exception):
    pass


class FakeAuthorizedSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(
        self,
        url,
        *,
        params,
        timeout,
    ):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "timeout": timeout,
            }
        )

        outcome = self.outcomes.pop(0)

        if isinstance(outcome, BaseException):
            raise outcome

        return outcome


class GmailProviderTests(unittest.TestCase):
    def adapter(self, transport=None):
        return GmailReadAdapter(
            read_session(),
            account_safe_id="gmail:safe-account",
            transport=(
                transport
                if transport is not None
                else FakeGmailTransport()
            ),
        )

    def test_from_auth_manager_derives_provider_safe_identity(self):
        manager = FakeAuthManager()
        transport = FakeGmailTransport()

        adapter = GmailReadAdapter.from_auth_manager(
            manager,
            read_session(),
            transport=transport,
        )

        descriptor = adapter.descriptor()

        self.assertEqual(
            manager.identifiers,
            ["user@example.test"],
        )
        self.assertEqual(
            descriptor.identity.provider,
            "gmail",
        )
        self.assertEqual(
            descriptor.identity.account_safe_id,
            "gmail:derived-safe-id",
        )
        self.assertNotIn(
            "user@example.test",
            repr(descriptor),
        )
        self.assertNotIn(
            "user@example.test",
            repr(adapter),
        )

    def test_from_auth_manager_rejects_missing_profile_identity(self):
        manager = FakeAuthManager()
        transport = FakeGmailTransport()
        transport.profile = {}

        with self.assertRaises(
            ProviderOperationError
        ) as context:
            GmailReadAdapter.from_auth_manager(
                manager,
                read_session(),
                transport=transport,
            )

        self.assertEqual(
            context.exception.code,
            ProviderErrorCode.INVALID_PROVIDER_RESPONSE,
        )
        self.assertEqual(
            manager.identifiers,
            [],
        )

    def test_transport_profile_requests_only_email_address(self):
        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    200,
                    {
                        "emailAddress": (
                            "user@example.test"
                        )
                    },
                )
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        result = transport.get_profile()

        self.assertEqual(
            result["emailAddress"],
            "user@example.test",
        )
        self.assertEqual(
            session.calls[0]["url"],
            (
                "https://gmail.googleapis.com/"
                "gmail/v1/users/me/profile"
            ),
        )
        self.assertEqual(
            session.calls[0]["params"],
            {
                "fields": "emailAddress",
            },
        )

    def test_adapter_satisfies_provider_read_protocol(self):
        self.assertIsInstance(
            self.adapter(),
            ProviderReadAdapter,
        )

    def test_write_authorization_session_is_rejected(self):
        session = GmailAuthSession(
            mode=GmailAuthorizationMode.M1_WRITE,
            token_path=Path("/synthetic/write.json"),
            credentials=FakeCredentials(),
        )

        with self.assertRaises(ValueError):
            GmailReadAdapter(
                session,
                account_safe_id="gmail:safe",
                transport=FakeGmailTransport(),
            )

    def test_descriptor_has_no_write_capabilities(self):
        descriptor = self.adapter().descriptor()

        for capability in ProviderWriteCapability:
            self.assertFalse(
                descriptor.write_capabilities.supports(
                    capability
                )
            )

    def test_label_ownership_maps_from_gmail_type(self):
        labels = self.adapter().list_labels()

        self.assertEqual(
            labels[0].kind,
            ProviderLabelKind.PROVIDER_SYSTEM,
        )
        self.assertEqual(
            labels[1].kind,
            ProviderLabelKind.USER,
        )

    def test_thread_pages_preserve_provider_identity(self):
        adapter = self.adapter()

        first = adapter.list_threads(
            page_size=100
        )
        second = adapter.list_threads(
            page_token=first.next_page_token,
            page_size=100,
        )

        self.assertEqual(
            first.items[0].thread_id,
            "t-1",
        )
        self.assertEqual(
            second.items[0].thread_id,
            "t-2",
        )

    def test_thread_page_size_is_bounded_by_gmail_limit(self):
        adapter = self.adapter()

        with self.assertRaises(ValueError):
            adapter.list_threads(
                page_size=501
            )

    def test_message_metadata_and_attachment_structure_are_combined(self):
        message = (
            self.adapter()
            .list_messages("t-1")
            .items[0]
        )

        self.assertEqual(
            message.message_id,
            "m-1",
        )
        self.assertEqual(
            message.label_ids,
            ("INBOX", "Label_1"),
        )
        self.assertEqual(
            message.subject,
            "Project Alpha",
        )
        self.assertEqual(
            message.correspondents,
            (
                "alice@example.test",
                "bob@example.test",
            ),
        )
        self.assertTrue(
            message.has_attachment
        )

    def test_attachment_metadata_has_no_content_surface(self):
        adapter = self.adapter()

        adapter.list_messages("t-1")

        attachments = adapter.list_attachments(
            "m-1"
        )

        self.assertEqual(
            len(attachments),
            1,
        )
        self.assertEqual(
            attachments[0].attachment_id,
            "att-1",
        )
        self.assertEqual(
            attachments[0].filename,
            "contract.pdf",
        )
        self.assertEqual(
            attachments[0].mime_type,
            "application/pdf",
        )
        self.assertFalse(
            hasattr(attachments[0], "data")
        )
        self.assertFalse(
            hasattr(attachments[0], "content")
        )

    def test_fresh_state_uses_labels_and_history_revision(self):
        state = self.adapter().get_message_state(
            "m-1"
        )

        self.assertTrue(state.in_inbox)
        self.assertFalse(state.in_trash)
        self.assertEqual(
            state.provider_revision,
            "gmail-history:102",
        )

    def test_message_pagination_is_explicitly_unsupported(self):
        with self.assertRaises(
            ProviderOperationError
        ) as context:
            self.adapter().list_messages(
                "t-1",
                page_token="not-supported",
            )

        self.assertEqual(
            context.exception.code,
            ProviderErrorCode.UNSUPPORTED_CAPABILITY,
        )

    def test_missing_requested_headers_surface_limitation(self):
        transport = FakeGmailTransport()

        transport.threads["t-1"]["messages"][0][
            "payload"
        ] = {}

        adapter = self.adapter(transport)

        message = adapter.list_messages(
            "t-1"
        ).items[0]

        self.assertIsNone(
            message.subject
        )

        self.assertTrue(
            any(
                item.code
                == "gmail_message_headers_incomplete"
                for item in adapter.descriptor().limitations
            )
        )

    def test_unknown_label_type_surfaces_limitation(self):
        transport = FakeGmailTransport()

        transport.labels["labels"].append(
            {
                "id": "future",
                "name": "Future",
                "type": "future-type",
            }
        )

        adapter = self.adapter(transport)
        labels = adapter.list_labels()

        future = next(
            item
            for item in labels
            if item.label_id == "future"
        )

        self.assertIs(
            future.kind,
            ProviderLabelKind.UNKNOWN,
        )

        self.assertTrue(
            any(
                item.code
                == "gmail_label_ownership_unknown"
                for item in adapter.descriptor().limitations
            )
        )

    def test_missing_history_id_surfaces_limitation(self):
        transport = FakeGmailTransport()
        del transport.states["m-1"][
            "historyId"
        ]

        adapter = self.adapter(transport)
        state = adapter.get_message_state(
            "m-1"
        )

        self.assertIsNone(
            state.provider_revision
        )

        self.assertTrue(
            any(
                item.code
                == "gmail_message_revision_unavailable"
                for item in adapter.descriptor().limitations
            )
        )

    def test_transport_thread_list_is_complete_mailbox_read(self):
        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    200,
                    {"threads": []},
                )
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        transport.list_threads(
            page_token="page-2",
            page_size=500,
        )

        params = session.calls[0][
            "params"
        ]

        self.assertIs(
            params["includeSpamTrash"],
            True,
        )
        self.assertEqual(
            params["pageToken"],
            "page-2",
        )
        self.assertEqual(
            params["maxResults"],
            500,
        )
        self.assertEqual(
            params["fields"],
            "threads(id),nextPageToken",
        )

    def test_transport_metadata_read_requests_only_selected_headers(self):
        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    200,
                    {"id": "t-1"},
                )
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        transport.get_thread_metadata(
            "t-1"
        )

        params = session.calls[0][
            "params"
        ]

        self.assertEqual(
            params["format"],
            "metadata",
        )
        self.assertEqual(
            params["metadataHeaders"],
            [
                "Subject",
                "From",
                "To",
                "Cc",
                "Reply-To",
            ],
        )
        self.assertNotIn(
            "snippet",
            params["fields"],
        )
        self.assertNotIn(
            "raw",
            params["fields"],
        )

    def test_transport_fresh_state_uses_partial_full_without_payload(self):
        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    200,
                    {
                        "id": "m-1",
                        "labelIds": ["INBOX"],
                        "historyId": "123",
                    },
                )
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        transport.get_message_state(
            "m-1"
        )

        params = session.calls[0][
            "params"
        ]

        self.assertEqual(
            params["format"],
            "full",
        )
        self.assertEqual(
            params["fields"],
            "id,labelIds,historyId",
        )

        for forbidden in (
            "payload",
            "body",
            "data",
            "raw",
            "snippet",
        ):
            self.assertNotIn(
                forbidden,
                params["fields"],
            )

    def test_structure_partial_response_never_requests_body_data(self):
        self.assertIn(
            "attachmentId",
            GMAIL_MESSAGE_STRUCTURE_FIELDS,
        )
        self.assertIn(
            "size",
            GMAIL_MESSAGE_STRUCTURE_FIELDS,
        )
        self.assertNotIn(
            "data",
            GMAIL_MESSAGE_STRUCTURE_FIELDS,
        )
        self.assertNotIn(
            "raw",
            GMAIL_MESSAGE_STRUCTURE_FIELDS,
        )
        self.assertNotIn(
            "snippet",
            GMAIL_MESSAGE_STRUCTURE_FIELDS,
        )

    def test_transport_structure_uses_full_with_partial_fields(self):
        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    200,
                    {
                        "id": "m-1",
                        "threadId": "t-1",
                    },
                )
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        transport.get_message_structure(
            "m-1"
        )

        params = session.calls[0][
            "params"
        ]

        self.assertEqual(
            params["format"],
            "full",
        )
        self.assertEqual(
            params["fields"],
            GMAIL_MESSAGE_STRUCTURE_FIELDS,
        )
        self.assertNotIn(
            "data",
            params["fields"],
        )

    def test_429_is_retried_with_bounded_backoff(self):
        sleeps = []

        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    429,
                    {"error": {"errors": []}},
                ),
                FakeResponse(
                    200,
                    {"labels": []},
                ),
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            retry_policy=GmailReadRetryPolicy(
                max_attempts=2,
                base_delay_seconds=0.5,
            ),
            sleep=sleeps.append,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        result = transport.list_labels()

        self.assertEqual(
            result,
            {"labels": []},
        )
        self.assertEqual(
            len(session.calls),
            2,
        )
        self.assertEqual(
            sleeps,
            [0.5],
        )

    def test_403_rate_limit_reason_is_retryable(self):
        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    403,
                    {
                        "error": {
                            "errors": [
                                {
                                    "reason": (
                                        "userRateLimitExceeded"
                                    )
                                }
                            ]
                        }
                    },
                ),
                FakeResponse(
                    200,
                    {"labels": []},
                ),
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            retry_policy=GmailReadRetryPolicy(
                max_attempts=2,
                base_delay_seconds=0,
            ),
            sleep=lambda _: None,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        self.assertEqual(
            transport.list_labels(),
            {"labels": []},
        )

    def test_permission_403_fails_closed_without_raw_error(self):
        token = "DO-NOT-LEAK"

        session = FakeAuthorizedSession(
            [
                FakeResponse(
                    403,
                    {
                        "error": {
                            "message": token,
                            "errors": [
                                {
                                    "reason": "forbidden",
                                    "message": token,
                                }
                            ],
                        }
                    },
                )
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        with self.assertRaises(
            ProviderOperationError
        ) as context:
            transport.list_labels()

        self.assertEqual(
            context.exception.code,
            ProviderErrorCode.AUTHORIZATION_INSUFFICIENT,
        )
        self.assertFalse(
            context.exception.retryable
        )
        self.assertNotIn(
            token,
            str(context.exception),
        )

    def test_401_and_404_map_to_stable_provider_errors(self):
        for status, expected in (
            (
                401,
                ProviderErrorCode.AUTHENTICATION_REQUIRED,
            ),
            (
                404,
                ProviderErrorCode.NOT_FOUND,
            ),
        ):
            with self.subTest(status=status):
                session = FakeAuthorizedSession(
                    [
                        FakeResponse(
                            status,
                            {"error": {}},
                        )
                    ]
                )

                transport = GoogleGmailReadTransport(
                    authorized_session=session,
                    request_error_types=(
                        SyntheticNetworkError,
                    ),
                )

                with self.assertRaises(
                    ProviderOperationError
                ) as context:
                    transport.list_labels()

                self.assertEqual(
                    context.exception.code,
                    expected,
                )

    def test_network_failure_is_bounded_and_retryable(self):
        session = FakeAuthorizedSession(
            [
                SyntheticNetworkError(),
                SyntheticNetworkError(),
            ]
        )

        transport = GoogleGmailReadTransport(
            authorized_session=session,
            retry_policy=GmailReadRetryPolicy(
                max_attempts=2,
                base_delay_seconds=0,
            ),
            sleep=lambda _: None,
            request_error_types=(
                SyntheticNetworkError,
            ),
        )

        with self.assertRaises(
            ProviderOperationError
        ) as context:
            transport.list_labels()

        self.assertEqual(
            context.exception.code,
            ProviderErrorCode.RETRYABLE_PROVIDER_FAILURE,
        )
        self.assertTrue(
            context.exception.retryable
        )
        self.assertEqual(
            len(session.calls),
            2,
        )

    def test_public_adapter_exposes_no_mutation_methods(self):
        forbidden = {
            "add_label",
            "remove_label",
            "modify",
            "archive",
            "trash",
            "untrash",
            "delete",
            "send",
        }

        public_names = {
            name
            for name in dir(
                GmailReadAdapter
            )
            if not name.startswith("_")
        }

        self.assertFalse(
            public_names & forbidden
        )


if __name__ == "__main__":
    unittest.main()
