# Contributing to Splunk Power Client

Thanks for your interest! This project uses an automated release pipeline based on [Conventional Commits](https://www.conventionalcommits.org/), so a small amount of discipline on commits and PRs goes a long way.

## Local setup

```sh
uv sync --all-extras --dev
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

This installs both the formatting/linting hook and the commit-message validator.

Useful commands:

```sh
uv run ruff check .              # lint
uv run ruff format --check .     # format check (no write)
uv run ruff format .             # apply formatting
uv run pytest                    # tests
uv run mkdocs serve              # docs preview
uv build                         # build wheel + sdist
```

## PR and commit conventions

All changes to `main` must go through a **Pull Request**, **squash-merged**, with a **Conventional Commit-formatted PR title**:

```
<type>(<scope>): <subject>
```

The PR title becomes the squashed commit on `main`. That commit is what `python-semantic-release` parses to decide the next version bump.

### Types

| Type | Use when | Effect on release |
|---|---|---|
| `feat` | Adding a feature | MINOR bump |
| `fix` | Fixing a bug | PATCH bump |
| `perf` | Performance improvement | PATCH bump |
| `docs` | Documentation only | listed in CHANGELOG, no bump |
| `refactor` | Internal refactor, no behaviour change | listed in CHANGELOG, no bump |
| `style` | Formatting only | hidden, no bump |
| `test` | Tests only | hidden, no bump |
| `build` | Build system / deps | hidden, no bump |
| `ci` | CI configuration | hidden, no bump |
| `chore` | Maintenance | hidden, no bump |
| `revert` | Revert a previous commit | hidden, no bump |

A breaking change is signalled by `!` after the type (e.g. `feat(cli)!: rename --instance to --profile`) or by a `BREAKING CHANGE:` footer in the PR body. Either forces a MAJOR bump.

### Examples

```
feat(ingest): add streaming events to Splunk
fix(secrets): handle Ctrl+C during token prompt
docs: update lookups guide
feat(cli)!: rename --instance flag to --profile
```

## Releases

Releases are fully automated. **Do not** tag manually or edit the version in `pyproject.toml`. When a PR is merged to `main`:

1. Tests run.
2. `python-semantic-release` decides the next version from the conventional-commit type(s) since the last tag.
3. If a bump is warranted: it updates `pyproject.toml` + `CHANGELOG.md`, creates a `chore(release): vX.Y.Z [skip ci]` commit, tags `vX.Y.Z`, pushes.
4. The package is built with `uv build` and published to PyPI via OIDC trusted publishing.
5. A GitHub Release is created with the changelog section + a *Contributors* section listing unique GitHub authors of PRs/commits in this release range.

If no conventional-commit type since the last tag warrants a bump, the workflow silently does nothing.

## Reporting issues

Issues are tracked on GitHub. To have an issue auto-closed by a PR, reference it in the PR body with `Closes #N` or `Fixes #N` — GitHub will close the issue when the PR is merged.
