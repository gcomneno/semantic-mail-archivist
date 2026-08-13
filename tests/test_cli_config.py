from pathlib import Path
import tempfile
import unittest

from semantic_mail_archivist.cli_config import (
    CliConfigError,
    CliConfigErrorCode,
    CliOutputFormat,
    default_cli_config_path,
    load_cli_config,
)


class CliConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, content):
        path = self.root / "config.toml"
        path.write_text(
            content,
            encoding="utf-8",
        )
        return path

    def test_default_path_respects_xdg_config_home(self):
        path = default_cli_config_path(
            environ={
                "XDG_CONFIG_HOME": (
                    str(self.root / "xdg")
                )
            },
            home=self.root / "home",
        )

        self.assertEqual(
            path,
            (
                self.root
                / "xdg"
                / "semantic-mail-archivist"
                / "config.toml"
            ),
        )

    def test_minimal_config_defaults_to_human_stdout(self):
        config = load_cli_config(
            self.write(
                """
[mailbox]
provider = "gmail"
account = "personal"
"""
            )
        )

        self.assertEqual(
            config.mailbox.provider,
            "gmail",
        )
        self.assertEqual(
            config.mailbox.account,
            "personal",
        )
        self.assertIs(
            config.output.format,
            CliOutputFormat.HUMAN,
        )
        self.assertIsNone(
            config.output.destination
        )

    def test_json_and_relative_destination_are_loaded(self):
        config_path = self.write(
            """
[mailbox]
provider = "synthetic"
account = "test-account"

[output]
format = "json"
destination = "reports/latest.json"
"""
        )

        config = load_cli_config(
            config_path
        )

        self.assertIs(
            config.output.format,
            CliOutputFormat.JSON,
        )
        self.assertEqual(
            config.output.destination,
            (
                config_path.parent
                / "reports"
                / "latest.json"
            ),
        )

    def test_dash_destination_means_stdout(self):
        config = load_cli_config(
            self.write(
                """
[mailbox]
provider = "gmail"
account = "default"

[output]
destination = "-"
"""
            )
        )

        self.assertIsNone(
            config.output.destination
        )

    def test_missing_file_fails_with_stable_code(self):
        with self.assertRaises(
            CliConfigError
        ) as context:
            load_cli_config(
                self.root / "missing.toml"
            )

        self.assertIs(
            context.exception.code,
            CliConfigErrorCode.NOT_FOUND,
        )

    def test_invalid_toml_does_not_echo_raw_content(self):
        secret = "DO-NOT-ECHO"

        path = self.write(
            "[mailbox\n"
            + secret
        )

        with self.assertRaises(
            CliConfigError
        ) as context:
            load_cli_config(path)

        self.assertIs(
            context.exception.code,
            CliConfigErrorCode.INVALID_TOML,
        )
        self.assertNotIn(
            secret,
            str(context.exception),
        )

    def test_missing_mailbox_is_rejected(self):
        with self.assertRaises(
            CliConfigError
        ) as context:
            load_cli_config(
                self.write(
                    """
[output]
format = "human"
"""
                )
            )

        self.assertIs(
            context.exception.code,
            CliConfigErrorCode.INVALID_SCHEMA,
        )

    def test_unknown_keys_are_rejected(self):
        with self.assertRaises(
            CliConfigError
        ):
            load_cli_config(
                self.write(
                    """
[mailbox]
provider = "gmail"
account = "default"
typo = "value"
"""
                )
            )

    def test_secret_like_keys_are_rejected_without_value_echo(self):
        secret = "SECRET-VALUE"

        with self.assertRaises(
            CliConfigError
        ) as context:
            load_cli_config(
                self.write(
                    f"""
[mailbox]
provider = "gmail"
account = "default"

token = "{secret}"
"""
                )
            )

        self.assertNotIn(
            secret,
            str(context.exception),
        )
        self.assertIn(
            "must not contain credential or token material",
            str(context.exception),
        )

    def test_output_format_is_strict(self):
        with self.assertRaises(
            CliConfigError
        ):
            load_cli_config(
                self.write(
                    """
[mailbox]
provider = "gmail"
account = "default"

[output]
format = "yaml"
"""
                )
            )


if __name__ == "__main__":
    unittest.main()
