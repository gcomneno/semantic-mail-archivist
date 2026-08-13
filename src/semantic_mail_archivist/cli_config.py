from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import tomllib
from typing import Any, Mapping


class CliOutputFormat(str, Enum):
    HUMAN = "human"
    JSON = "json"


class CliConfigErrorCode(str, Enum):
    NOT_FOUND = "not_found"
    UNREADABLE = "unreadable"
    INVALID_TOML = "invalid_toml"
    INVALID_SCHEMA = "invalid_schema"


class CliConfigError(RuntimeError):
    """Configuration failure safe to render without raw configuration data."""

    def __init__(
        self,
        code: CliConfigErrorCode,
        safe_detail: str,
    ) -> None:
        if not safe_detail.strip():
            raise ValueError("safe_detail cannot be empty")

        self.code = code
        self.safe_detail = safe_detail

        super().__init__(
            f"{code.value}: {safe_detail}"
        )


def default_cli_config_path(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = (
        os.environ
        if environ is None
        else environ
    )

    resolved_home = (
        Path.home()
        if home is None
        else home
    )

    config_base = Path(
        env.get(
            "XDG_CONFIG_HOME",
            str(resolved_home / ".config"),
        )
    )

    return (
        config_base
        / "semantic-mail-archivist"
        / "config.toml"
    )


@dataclass(frozen=True)
class CliMailboxConfig:
    """Non-secret mailbox selection.

    `account` is a local alias/profile name. It is not an email address,
    credential, token, password or OAuth secret.
    """

    provider: str
    account: str

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError(
                "provider cannot be empty"
            )

        if not self.account.strip():
            raise ValueError(
                "account cannot be empty"
            )


@dataclass(frozen=True)
class CliOutputConfig:
    format: CliOutputFormat = CliOutputFormat.HUMAN
    destination: Path | None = None


@dataclass(frozen=True)
class CliConfig:
    mailbox: CliMailboxConfig
    output: CliOutputConfig = CliOutputConfig()
    source_path: Path | None = None


_ALLOWED_TOP_LEVEL = frozenset(
    {
        "mailbox",
        "output",
    }
)

_ALLOWED_MAILBOX = frozenset(
    {
        "provider",
        "account",
    }
)

_ALLOWED_OUTPUT = frozenset(
    {
        "format",
        "destination",
    }
)

_FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "access_token",
        "client_secret",
        "credential",
        "credentials",
        "oauth_token",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def _schema_error(detail: str) -> CliConfigError:
    return CliConfigError(
        CliConfigErrorCode.INVALID_SCHEMA,
        detail,
    )


def _table(
    root: dict[str, Any],
    name: str,
    *,
    required: bool,
) -> dict[str, Any]:
    value = root.get(name)

    if value is None:
        if required:
            raise _schema_error(
                f"Configuration requires [{name}]."
            )
        return {}

    if not isinstance(value, dict):
        raise _schema_error(
            f"Configuration [{name}] must be a table."
        )

    return value


def _reject_unknown_keys(
    table: dict[str, Any],
    allowed: frozenset[str],
    location: str,
) -> None:
    unknown = sorted(
        set(table) - allowed
    )

    if unknown:
        raise _schema_error(
            (
                f"Configuration {location} contains unsupported "
                "key(s): "
                + ", ".join(unknown)
                + "."
            )
        )


def _reject_secret_like_keys(
    value: Any,
    *,
    location: str = "root",
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()

            if normalized in _FORBIDDEN_SECRET_KEYS:
                raise _schema_error(
                    (
                        "CLI configuration must not contain "
                        "credential or token material."
                    )
                )

            _reject_secret_like_keys(
                child,
                location=f"{location}.{key}",
            )

    elif isinstance(value, list):
        for child in value:
            _reject_secret_like_keys(
                child,
                location=location,
            )


def _required_text(
    table: dict[str, Any],
    key: str,
    location: str,
) -> str:
    value = table.get(key)

    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise _schema_error(
            (
                f"Configuration {location}.{key} "
                "must be a non-empty string."
            )
        )

    return value.strip()


def _parse_output_format(
    value: Any,
) -> CliOutputFormat:
    if value is None:
        return CliOutputFormat.HUMAN

    if not isinstance(value, str):
        raise _schema_error(
            "Configuration output.format must be human or json."
        )

    try:
        return CliOutputFormat(value)
    except ValueError:
        raise _schema_error(
            "Configuration output.format must be human or json."
        ) from None


def _parse_destination(
    value: Any,
    *,
    source_path: Path,
) -> Path | None:
    if value is None or value == "-":
        return None

    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise _schema_error(
            (
                "Configuration output.destination must be "
                "a path or '-'."
            )
        )

    path = Path(value).expanduser()

    if not path.is_absolute():
        path = source_path.parent / path

    return path


def load_cli_config(
    path: Path,
) -> CliConfig:
    source_path = path.expanduser()

    try:
        raw = source_path.read_bytes()
    except FileNotFoundError:
        raise CliConfigError(
            CliConfigErrorCode.NOT_FOUND,
            "Local CLI configuration file was not found.",
        ) from None
    except OSError:
        raise CliConfigError(
            CliConfigErrorCode.UNREADABLE,
            "Local CLI configuration file could not be read.",
        ) from None

    try:
        parsed = tomllib.loads(
            raw.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
    ):
        raise CliConfigError(
            CliConfigErrorCode.INVALID_TOML,
            "Local CLI configuration is not valid UTF-8 TOML.",
        ) from None

    if not isinstance(parsed, dict):
        raise _schema_error(
            "CLI configuration root must be a table."
        )

    _reject_secret_like_keys(parsed)

    _reject_unknown_keys(
        parsed,
        _ALLOWED_TOP_LEVEL,
        "root",
    )

    mailbox = _table(
        parsed,
        "mailbox",
        required=True,
    )
    output = _table(
        parsed,
        "output",
        required=False,
    )

    _reject_unknown_keys(
        mailbox,
        _ALLOWED_MAILBOX,
        "[mailbox]",
    )
    _reject_unknown_keys(
        output,
        _ALLOWED_OUTPUT,
        "[output]",
    )

    provider = _required_text(
        mailbox,
        "provider",
        "mailbox",
    )
    account = _required_text(
        mailbox,
        "account",
        "mailbox",
    )

    output_format = _parse_output_format(
        output.get("format")
    )
    destination = _parse_destination(
        output.get("destination"),
        source_path=source_path,
    )

    return CliConfig(
        mailbox=CliMailboxConfig(
            provider=provider,
            account=account,
        ),
        output=CliOutputConfig(
            format=output_format,
            destination=destination,
        ),
        source_path=source_path,
    )
