from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from enum import IntEnum
import io
import json
from pathlib import Path
import sys
from typing import Callable, Mapping, Protocol, Sequence, TextIO

from .cli_config import (
    CliConfig,
    CliConfigError,
    CliMailboxConfig,
    CliOutputFormat,
    default_cli_config_path,
    load_cli_config,
)
from .provider import ProviderReadAdapter


class CliExitCode(IntEnum):
    OK = 0
    USAGE = 2
    CONFIGURATION_ERROR = 3
    COMMAND_NOT_IMPLEMENTED = 4
    WRITE_DISABLED = 5
    PROVIDER_UNAVAILABLE = 6
    INTERNAL_ERROR = 70


class CliOperatingMode(str):
    READ_ONLY = "read_only"
    WRITE_REQUESTED = "write_requested"


@dataclass(frozen=True)
class CliInvocation:
    command: str
    operating_mode: str
    output_format: CliOutputFormat
    output_destination: Path | None
    mailbox: CliMailboxConfig

    @property
    def read_only(self) -> bool:
        return (
            self.operating_mode
            == CliOperatingMode.READ_ONLY
        )

    @property
    def write_requested(self) -> bool:
        return (
            self.operating_mode
            == CliOperatingMode.WRITE_REQUESTED
        )


ProviderFactory = Callable[
    [CliMailboxConfig],
    ProviderReadAdapter,
]


@dataclass(frozen=True)
class CliDependencies:
    """Dependency-injection seam for future command orchestration."""

    provider_factories: Mapping[
        str,
        ProviderFactory,
    ]

    @classmethod
    def empty(cls) -> "CliDependencies":
        return cls(provider_factories={})

    def provider_for(
        self,
        mailbox: CliMailboxConfig,
    ) -> ProviderReadAdapter:
        factory = self.provider_factories.get(
            mailbox.provider
        )

        if factory is None:
            raise CliExecutionError(
                CliExitCode.PROVIDER_UNAVAILABLE,
                "Configured provider is not available in this CLI runtime.",
            )

        return factory(mailbox)


@dataclass(frozen=True)
class CliCommandResult:
    exit_code: CliExitCode
    status: str
    human_message: str

    def __post_init__(self) -> None:
        if not self.status.strip():
            raise ValueError(
                "status cannot be empty"
            )

        if not self.human_message.strip():
            raise ValueError(
                "human_message cannot be empty"
            )


class CliExecutionError(RuntimeError):
    def __init__(
        self,
        exit_code: CliExitCode,
        safe_detail: str,
    ) -> None:
        if not safe_detail.strip():
            raise ValueError(
                "safe_detail cannot be empty"
            )

        self.exit_code = exit_code
        self.safe_detail = safe_detail

        super().__init__(
            f"{int(exit_code)}: {safe_detail}"
        )


class CliCommandRuntime(Protocol):
    def audit(
        self,
        invocation: CliInvocation,
        dependencies: CliDependencies,
    ) -> CliCommandResult:
        ...

    def repair_dry_run(
        self,
        invocation: CliInvocation,
        dependencies: CliDependencies,
    ) -> CliCommandResult:
        ...

    def repair_apply(
        self,
        invocation: CliInvocation,
        dependencies: CliDependencies,
    ) -> CliCommandResult:
        ...


class ShellOnlyRuntime:
    """Issue #27 shell: command contracts exist, orchestration does not."""

    def audit(
        self,
        invocation: CliInvocation,
        dependencies: CliDependencies,
    ) -> CliCommandResult:
        return CliCommandResult(
            exit_code=CliExitCode.COMMAND_NOT_IMPLEMENTED,
            status="not_implemented",
            human_message=(
                "Audit command shell is available; real mailbox "
                "audit orchestration is not wired yet."
            ),
        )

    def repair_dry_run(
        self,
        invocation: CliInvocation,
        dependencies: CliDependencies,
    ) -> CliCommandResult:
        return CliCommandResult(
            exit_code=CliExitCode.COMMAND_NOT_IMPLEMENTED,
            status="not_implemented",
            human_message=(
                "Repair dry-run command shell is available; real "
                "mailbox dry-run orchestration is not wired yet."
            ),
        )

    def repair_apply(
        self,
        invocation: CliInvocation,
        dependencies: CliDependencies,
    ) -> CliCommandResult:
        return CliCommandResult(
            exit_code=CliExitCode.WRITE_DISABLED,
            status="write_disabled",
            human_message=(
                "Write execution is disabled in this CLI shell."
            ),
        )


class _Parser(argparse.ArgumentParser):
    """Argparse parser with deterministic error returns through main()."""


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="semantic-mail-archivist",
        description=(
            "Local, read-first shell for Semantic Mail Archivist."
        ),
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Local TOML configuration path. "
            "Credentials and tokens are not accepted here."
        ),
    )
    parser.add_argument(
        "--format",
        choices=tuple(
            value.value
            for value in CliOutputFormat
        ),
        default=None,
        dest="output_format",
        help=(
            "Output format override: human or json. "
            "Default comes from configuration, then human."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        dest="output_destination",
        help=(
            "Output destination override. "
            "Omit for configuration/default stdout."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    audit = subparsers.add_parser(
        "audit",
        help=(
            "Read-only audit command shell "
            "(real orchestration added later)."
        ),
    )
    audit.set_defaults(
        command_mode=CliOperatingMode.READ_ONLY,
    )

    repair = subparsers.add_parser(
        "repair",
        help=(
            "Repair command shell; defaults to dry-run."
        ),
    )

    repair_mode = repair.add_mutually_exclusive_group()

    repair_mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Read-only repair planning. This is the default."
        ),
    )
    repair_mode.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Explicit write intent. Write execution is not "
            "implemented by issue #27."
        ),
    )

    return parser


def _config_path(
    parsed: argparse.Namespace,
) -> Path:
    if parsed.config is not None:
        return parsed.config

    return default_cli_config_path()


def _invocation_from(
    parsed: argparse.Namespace,
    config: CliConfig,
) -> CliInvocation:
    if parsed.command == "audit":
        mode = CliOperatingMode.READ_ONLY

    elif parsed.command == "repair":
        mode = (
            CliOperatingMode.WRITE_REQUESTED
            if parsed.apply
            else CliOperatingMode.READ_ONLY
        )

    else:
        raise CliExecutionError(
            CliExitCode.USAGE,
            "Unknown command.",
        )

    output_format = (
        CliOutputFormat(parsed.output_format)
        if parsed.output_format is not None
        else config.output.format
    )

    output_destination = (
        parsed.output_destination
        if parsed.output_destination is not None
        else config.output.destination
    )

    return CliInvocation(
        command=parsed.command,
        operating_mode=mode,
        output_format=output_format,
        output_destination=output_destination,
        mailbox=config.mailbox,
    )


def _dispatch(
    runtime: CliCommandRuntime,
    invocation: CliInvocation,
    dependencies: CliDependencies,
) -> CliCommandResult:
    if invocation.command == "audit":
        return runtime.audit(
            invocation,
            dependencies,
        )

    if invocation.command == "repair":
        if invocation.write_requested:
            return runtime.repair_apply(
                invocation,
                dependencies,
            )

        return runtime.repair_dry_run(
            invocation,
            dependencies,
        )

    raise CliExecutionError(
        CliExitCode.USAGE,
        "Unknown command.",
    )


def _machine_payload(
    invocation: CliInvocation,
    result: CliCommandResult,
) -> dict[str, object]:
    return {
        "command": invocation.command,
        "exit_code": int(result.exit_code),
        "mode": invocation.operating_mode,
        "read_only": invocation.read_only,
        "status": result.status,
    }


def _render(
    invocation: CliInvocation,
    result: CliCommandResult,
) -> str:
    if (
        invocation.output_format
        is CliOutputFormat.JSON
    ):
        return json.dumps(
            _machine_payload(
                invocation,
                result,
            ),
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"

    return (
        f"semantic-mail-archivist: {result.human_message}\n"
        f"mode: {invocation.operating_mode}\n"
        f"status: {result.status}\n"
    )


def _write_output(
    invocation: CliInvocation,
    rendered: str,
    stdout: TextIO,
) -> None:
    destination = invocation.output_destination

    if destination is None:
        stdout.write(rendered)
        return

    try:
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination.write_text(
            rendered,
            encoding="utf-8",
        )
    except OSError:
        raise CliExecutionError(
            CliExitCode.CONFIGURATION_ERROR,
            "Configured output destination could not be written.",
        ) from None


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime: CliCommandRuntime | None = None,
    dependencies: CliDependencies | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    args = (
        list(sys.argv[1:])
        if argv is None
        else list(argv)
    )

    out = (
        sys.stdout
        if stdout is None
        else stdout
    )
    err = (
        sys.stderr
        if stderr is None
        else stderr
    )

    parser = build_parser()

    try:
        with (
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            parsed = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code)

    try:
        config = load_cli_config(
            _config_path(parsed)
        )

        invocation = _invocation_from(
            parsed,
            config,
        )

        active_runtime = (
            runtime
            if runtime is not None
            else ShellOnlyRuntime()
        )
        active_dependencies = (
            dependencies
            if dependencies is not None
            else CliDependencies.empty()
        )

        result = _dispatch(
            active_runtime,
            invocation,
            active_dependencies,
        )

        rendered = _render(
            invocation,
            result,
        )

        _write_output(
            invocation,
            rendered,
            out,
        )

        return int(result.exit_code)

    except CliConfigError as exc:
        err.write(
            "semantic-mail-archivist: configuration error: "
            + exc.safe_detail
            + "\n"
        )
        return int(
            CliExitCode.CONFIGURATION_ERROR
        )

    except CliExecutionError as exc:
        err.write(
            "semantic-mail-archivist: "
            + exc.safe_detail
            + "\n"
        )
        return int(exc.exit_code)

    except Exception:
        err.write(
            "semantic-mail-archivist: unexpected local CLI failure.\n"
        )
        return int(
            CliExitCode.INTERNAL_ERROR
        )
