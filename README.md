# Splunk Power Client

> A modern, scriptable command-line client for Splunk power users and administrators.

[![PyPI](https://img.shields.io/pypi/v/splunk-power-client.svg)](https://pypi.org/project/splunk-power-client/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://github.com/nicolas-rdgs/Splunk-Power-Client/actions/workflows/test.yml/badge.svg)](https://github.com/nicolas-rdgs/Splunk-Power-Client/actions/workflows/test.yml)
[![Docs](https://github.com/nicolas-rdgs/Splunk-Power-Client/actions/workflows/docs.yml/badge.svg)](https://nicolas-rdgs.github.io/Splunk-Power-Client/)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg)](https://www.conventionalcommits.org)
[![semantic-release](https://img.shields.io/badge/semantic--release-python-e10079?logo=semantic-release)](https://github.com/python-semantic-release/python-semantic-release)

`spc` is a Python CLI that streamlines day-to-day Splunk operations — uploading lookups, managing saved searches, dispatching jobs, editing configurations — through a fast, scriptable, multi-instance command line.

📚 **[Documentation](https://nicolas-rdgs.github.io/Splunk-Power-Client/)** &middot; 📝 **[Changelog](CHANGELOG.md)** &middot; 🤝 **[Contributing](CONTRIBUTING.md)**

> [!WARNING]
> **🚧 Work in progress** — `spc` is still under active development. Expect breaking changes, rough edges, and bugs. Use it with caution in production environments — and please [open an issue](https://github.com/nicolas-rdgs/Splunk-Power-Client/issues) if you hit one.

---

## Features

- **Lookups** — Upload from CSV, JSON, or Excel into Lookup CSV or KVStore. Synchronise a lookup from one Splunk instance to another in a single command.
- **Saved searches** — Reschedule in bulk, dispatch in the past with trigger actions (replay), or backfill over an arbitrary time window.
- **Jobs** — List, inspect, and manage search jobs.
- **Configurations** — Update Splunk configuration files quickly.
- **Users** — Create multiple local users from a definition file.
- **Secrets** — Manage Splunk secrets safely.
- **Ingest** — Stream events into Splunk programmatically.
- **Multi-instance** — Switch seamlessly between Splunk environments (dev / staging / prod) from a single profile-aware configuration.

## Installation

```sh
# As a standalone tool
uv tool install splunk-power-client

# Or with pip
pip install splunk-power-client
```

Requires **Python 3.13+**.

## Quickstart

```sh
# Discover commands
spc --help

# Manage instances (add / list / update / remove)
spc instances --help

# Show the active Splunk instance and its details
spc info
```

For the full command reference, examples, and recipes, see the **[documentation](https://nicolas-rdgs.github.io/Splunk-Power-Client/)**.

## Commands

| Command | Status | What it does |
|---|:---:|---|
| `instances` | ✅ | Add, list, and switch between Splunk instances |
| `info` | ✅ | Show details of the active Splunk instance |
| `lookups` | ✅ | Upload, synchronise, list, delete CSV / KVStore lookups |
| `secrets` | ✅ | Manage Splunk secrets |
| `jobs` | ✅ | List and inspect search jobs |
| `debug/refresh` | ✅ | Refresh Splunk configuration without restart |
| `searches` | 🚧 | Reschedule, dispatch, replay saved searches |
| `configs` | 🚧 | Bulk-update Splunk configuration files |
| `users` | 🚧 | Create multiple local users |
| `ingest` | 🚧 | Stream events into Splunk |

Legend: ✅ available · 🚧 work in progress

## Development

This project uses [uv](https://docs.astral.sh/uv/) for everything — dependency management, building, publishing.

```sh
git clone https://github.com/nicolas-rdgs/Splunk-Power-Client.git
cd Splunk-Power-Client

uv sync --all-extras --dev
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

Common commands:

```sh
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run pytest                    # tests
uv run mkdocs serve              # preview docs locally
uv build                         # build wheel + sdist
```

The full contribution flow — Conventional Commits, PR conventions, and the automated release pipeline — is documented in **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Development methodology

The core architecture, feature design, and the bulk of `spc` are written by hand. AI assistance (Claude, by Anthropic) is used **deliberately and under human review** to accelerate well-defined, lower-creativity work and to drastically improve quality and reduce development time. Concretely, AI helps with:

- Refactoring and naming consistency
- Scaffolding repetitive code (model definitions, command boilerplate)
- Improving test coverage and edge-case handling
- Writing and polishing documentation
- Setting up and maintaining the CI/CD pipeline

Every change goes through a Pull Request and a human review before reaching `main`. Nothing is committed unreviewed.

## Release process

Releases are fully automated. Merging a Pull Request with a [Conventional Commits](https://www.conventionalcommits.org/)-formatted title to `main` triggers:

1. **Test** — `ruff check`, `ruff format --check`, `pytest --cov`
2. **Version** — [python-semantic-release](https://python-semantic-release.readthedocs.io/) decides the next SemVer, updates `pyproject.toml` and `CHANGELOG.md`, tags `vX.Y.Z`
3. **Build & publish** — `uv build`, then `uv publish --trusted-publishing always` (OIDC, no long-lived tokens)
4. **GitHub Release** — with the changelog section and a *Contributors* list

See [CONTRIBUTING.md](CONTRIBUTING.md) for the human side of this flow.

## Acknowledgements

Built on [Splunk Enterprise SDK for Python](https://dev.splunk.com/enterprise/docs/devtools/python/sdk-python), [Typer](https://typer.tiangolo.com/), [Pydantic](https://docs.pydantic.dev/), [Rich](https://rich.readthedocs.io/), and [uv](https://docs.astral.sh/uv/).

## License

Released under the [MIT License](LICENSE) — © 2025 Nicolas Rodrigues.
