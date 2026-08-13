# Local CLI shell

Issue #27 turns the Python package into an executable local application shell.

It deliberately does **not** orchestrate a real Gmail audit, repair dry-run or
write execution yet.

## Console entry point

After installation:

    semantic-mail-archivist --help

The equivalent module invocation is:

    python -m semantic_mail_archivist --help

## Configuration

The default path is:

    ~/.config/semantic-mail-archivist/config.toml

`XDG_CONFIG_HOME` is respected.

A minimal configuration is:

    [mailbox]
    provider = "gmail"
    account = "personal"

`account` is a local profile/alias. It is not an email address or credential.

Optional output configuration:

    [output]
    format = "human"
    destination = "-"

Supported formats are:

- `human`;
- `json`.

`destination = "-"` means stdout.

Relative output destinations are resolved relative to the configuration file.

The CLI configuration schema deliberately has no credential, password, OAuth
token, refresh token or client-secret fields. Secret-like keys are rejected.

Gmail OAuth client configuration and OAuth tokens remain in the private paths
defined by the authentication layer from issue #25.

## Commands

Read-only audit shell:

    semantic-mail-archivist --config ./config.toml audit

Read-only repair planning shell:

    semantic-mail-archivist --config ./config.toml repair

or explicitly:

    semantic-mail-archivist --config ./config.toml repair --dry-run

`repair` without a mode defaults to dry-run.

Explicit write intent is command-specific:

    semantic-mail-archivist --config ./config.toml repair --apply

Issue #27 does not execute writes. The default shell returns a stable
`WRITE_DISABLED` exit status for `repair --apply`.

There is no global `--apply` switch.

## Exit semantics

The CLI reserves stable exit codes:

- `0` — success;
- `2` — usage / argument parsing error;
- `3` — configuration or output-destination error;
- `4` — command shell exists but orchestration is not implemented yet;
- `5` — explicit write request rejected because writes are disabled;
- `6` — configured provider unavailable to an injected runtime;
- `70` — unexpected local CLI failure.

## Output contracts

Human output is the default.

Machine-readable output is selected explicitly:

    semantic-mail-archivist \
        --config ./config.toml \
        --format json \
        audit

The shell machine record contains only stable operational facts:

- command;
- exit code;
- operating mode;
- read-only boolean;
- status.

It does not echo:

- account alias;
- provider credentials;
- OAuth state;
- message subject/body;
- attachment content.

Output can remain on stdout or be directed to a local file with `--output`.

## Read-only default

Observable command modes are:

- `audit` -> `read_only`;
- `repair` -> `read_only`;
- `repair --dry-run` -> `read_only`;
- `repair --apply` -> `write_requested`, then rejected by the #27 default
  runtime.

No provider is instantiated by the default issue #27 runtime.

## Dependency injection

`CliDependencies` contains a provider-factory registry keyed by provider name.

Future orchestration can resolve a provider through that registry. Tests can
supply entirely synthetic provider factories without Gmail credentials or
network operations.

The default shell does not resolve a provider at all.

This keeps argument parsing, configuration loading and output rendering
separate from provider I/O and from domain/safety policy.
