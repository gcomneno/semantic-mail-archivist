from io import StringIO
from pathlib import Path
import tempfile
import unittest

from semantic_mail_archivist.cli import (
    CliCommandResult,
    CliDependencies,
    CliExitCode,
    CliOperatingMode,
    ShellOnlyRuntime,
    main,
)
from semantic_mail_archivist.provider import (
    ProviderDescriptor,
    ProviderIdentity,
    ProviderReadCapabilities,
)


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def audit(
        self,
        invocation,
        dependencies,
    ):
        self.calls.append(
            (
                "audit",
                invocation,
                dependencies,
            )
        )
        return CliCommandResult(
            CliExitCode.OK,
            "ok",
            "Synthetic audit shell completed.",
        )

    def repair_dry_run(
        self,
        invocation,
        dependencies,
    ):
        self.calls.append(
            (
                "repair_dry_run",
                invocation,
                dependencies,
            )
        )
        return CliCommandResult(
            CliExitCode.OK,
            "ok",
            "Synthetic repair dry-run shell completed.",
        )

    def repair_apply(
        self,
        invocation,
        dependencies,
    ):
        self.calls.append(
            (
                "repair_apply",
                invocation,
                dependencies,
            )
        )
        return CliCommandResult(
            CliExitCode.OK,
            "ok",
            "Synthetic apply handler reached.",
        )


class FakeProvider:
    def descriptor(self):
        return ProviderDescriptor(
            identity=ProviderIdentity(
                provider="synthetic",
                account_safe_id="safe-test",
            ),
            read_capabilities=ProviderReadCapabilities(),
        )


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "config.toml"
        self.config.write_text(
            """
[mailbox]
provider = "synthetic"
account = "fixture-account"
""",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(
        self,
        args,
        *,
        runtime=None,
        dependencies=None,
    ):
        stdout = StringIO()
        stderr = StringIO()

        code = main(
            args,
            runtime=runtime,
            dependencies=dependencies,
            stdout=stdout,
            stderr=stderr,
        )

        return (
            code,
            stdout.getvalue(),
            stderr.getvalue(),
        )

    def test_help_does_not_require_configuration(self):
        code, stdout, stderr = self.run_cli(
            ["--help"]
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertIn(
            "semantic-mail-archivist",
            stdout,
        )
        self.assertIn(
            "audit",
            stdout,
        )
        self.assertIn(
            "repair",
            stdout,
        )
        self.assertEqual(
            stderr,
            "",
        )

    def test_unknown_command_returns_usage_without_runtime(self):
        runtime = FakeRuntime()

        code, _, stderr = self.run_cli(
            ["unknown"],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.USAGE,
        )
        self.assertEqual(
            runtime.calls,
            [],
        )
        self.assertIn(
            "invalid choice",
            stderr,
        )

    def test_missing_config_fails_before_runtime(self):
        runtime = FakeRuntime()

        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.root / "missing.toml"),
                "audit",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.CONFIGURATION_ERROR,
        )
        self.assertEqual(
            stdout,
            "",
        )
        self.assertEqual(
            runtime.calls,
            [],
        )
        self.assertIn(
            "configuration error",
            stderr,
        )

    def test_audit_is_observably_read_only(self):
        runtime = FakeRuntime()

        code, _, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "audit",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )

        _, invocation, _ = runtime.calls[0]

        self.assertTrue(
            invocation.read_only
        )
        self.assertFalse(
            invocation.write_requested
        )
        self.assertEqual(
            invocation.operating_mode,
            CliOperatingMode.READ_ONLY,
        )

    def test_repair_without_flag_defaults_to_dry_run(self):
        runtime = FakeRuntime()

        code, _, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "repair",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            runtime.calls[0][0],
            "repair_dry_run",
        )
        self.assertTrue(
            runtime.calls[0][1].read_only
        )

    def test_explicit_dry_run_is_read_only(self):
        runtime = FakeRuntime()

        code, _, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "repair",
                "--dry-run",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            runtime.calls[0][0],
            "repair_dry_run",
        )
        self.assertTrue(
            runtime.calls[0][1].read_only
        )

    def test_apply_is_command_specific_and_explicit(self):
        runtime = FakeRuntime()

        code, _, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "repair",
                "--apply",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            runtime.calls[0][0],
            "repair_apply",
        )
        self.assertTrue(
            runtime.calls[0][1].write_requested
        )

        code, _, _ = self.run_cli(
            [
                "--apply",
                "--config",
                str(self.config),
                "audit",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.USAGE,
        )

    def test_default_runtime_blocks_apply(self):
        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "repair",
                "--apply",
            ]
        )

        self.assertEqual(
            code,
            CliExitCode.WRITE_DISABLED,
        )
        self.assertIn(
            "write_disabled",
            stdout,
        )
        self.assertIn(
            "write_requested",
            stdout,
        )
        self.assertEqual(
            stderr,
            "",
        )

    def test_shell_only_runtime_never_resolves_provider(self):
        calls = []

        def provider_factory(mailbox):
            calls.append(mailbox)
            raise AssertionError(
                "provider must not be resolved by issue #27 shell"
            )

        dependencies = CliDependencies(
            provider_factories={
                "synthetic": provider_factory,
            }
        )

        code, _, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "audit",
            ],
            runtime=ShellOnlyRuntime(),
            dependencies=dependencies,
        )

        self.assertEqual(
            code,
            CliExitCode.COMMAND_NOT_IMPLEMENTED,
        )
        self.assertEqual(
            calls,
            [],
        )

    def test_provider_factory_seam_accepts_fake_provider(self):
        fake = FakeProvider()
        calls = []

        def provider_factory(mailbox):
            calls.append(mailbox)
            return fake

        dependencies = CliDependencies(
            provider_factories={
                "synthetic": provider_factory,
            }
        )

        provider = dependencies.provider_for(
            type(
                "Mailbox",
                (),
                {
                    "provider": "synthetic",
                    "account": "fixture-account",
                },
            )()
        )

        self.assertIs(
            provider,
            fake,
        )
        self.assertEqual(
            len(calls),
            1,
        )

    def test_human_output_is_default_and_omits_account_alias(self):
        runtime = FakeRuntime()

        code, stdout, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "audit",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertIn(
            "mode: read_only",
            stdout,
        )
        self.assertIn(
            "status: ok",
            stdout,
        )
        self.assertNotIn(
            "fixture-account",
            stdout,
        )

    def test_json_output_contract_is_stable_and_privacy_safe(self):
        runtime = FakeRuntime()

        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "--format",
                "json",
                "audit",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stdout,
            (
                '{"command":"audit","exit_code":0,'
                '"mode":"read_only","read_only":true,'
                '"status":"ok"}\n'
            ),
        )
        self.assertEqual(
            stderr,
            "",
        )
        self.assertNotIn(
            "fixture-account",
            stdout,
        )

    def test_output_destination_override_writes_result(self):
        runtime = FakeRuntime()
        destination = (
            self.root / "result.json"
        )

        code, stdout, stderr = self.run_cli(
            [
                "--config",
                str(self.config),
                "--format",
                "json",
                "--output",
                str(destination),
                "audit",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertEqual(
            stdout,
            "",
        )
        self.assertEqual(
            stderr,
            "",
        )
        self.assertIn(
            '"read_only":true',
            destination.read_text(
                encoding="utf-8"
            ),
        )

    def test_config_format_can_be_overridden_by_cli(self):
        self.config.write_text(
            """
[mailbox]
provider = "synthetic"
account = "fixture-account"

[output]
format = "json"
""",
            encoding="utf-8",
        )

        runtime = FakeRuntime()

        code, stdout, _ = self.run_cli(
            [
                "--config",
                str(self.config),
                "--format",
                "human",
                "audit",
            ],
            runtime=runtime,
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )
        self.assertIn(
            "mode: read_only",
            stdout,
        )
        self.assertFalse(
            stdout.startswith("{")
        )

    def test_no_credential_or_token_arguments_exist(self):
        code, stdout, _ = self.run_cli(
            ["--help"]
        )

        self.assertEqual(
            code,
            CliExitCode.OK,
        )

        lowered = stdout.casefold()

        for forbidden in (
            "--token",
            "--password",
            "--client-secret",
            "--refresh-token",
            "--credentials",
        ):
            self.assertNotIn(
                forbidden,
                lowered,
            )


if __name__ == "__main__":
    unittest.main()
