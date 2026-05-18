# Project context for AI agents

This file is auto-loaded by Claude Code (and similar tools) when working in this repo. It captures non-obvious decisions so agents do not re-litigate them.

For human contributors, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Release pipeline

The release flow is fully automated through GitHub Actions:

| File | Trigger | Role |
|---|---|---|
| [.github/workflows/test.yml](.github/workflows/test.yml) | push (non-main), PR to main, `workflow_call` | `uv sync`, `ruff check`, `ruff format --check`, `pytest --cov` |
| [.github/workflows/release.yml](.github/workflows/release.yml) | push to main | reuses test.yml → `python-semantic-release` → `uv build` → `uv publish --trusted-publishing always` → `gh release create` (with Contributors section) |
| [.github/workflows/docs.yml](.github/workflows/docs.yml) | push to main (docs paths), workflow_dispatch | `mkdocs build --strict` → `actions/deploy-pages@v4` |

Single source of truth for version: `[project].version` in [pyproject.toml](pyproject.toml). Never edit it by hand — `python-semantic-release` writes it.

## Toolchain decisions

These are deliberate. Do not propose alternatives unless asked:

- **python-semantic-release (v10)** — version bump + CHANGELOG + tag + push. Config in `[tool.semantic_release]`. Changelog mode = `update` with insertion flag `<!-- version list -->` in [CHANGELOG.md](CHANGELOG.md).
- **`uv publish --trusted-publishing always`** — NOT `pypa/gh-action-pypi-publish`. Tool consistency with `uv build`. OIDC only; no `PYPI_API_TOKEN` secret. PyPI side requires a pre-configured trusted publisher (project + owner + repo + workflow filename `release.yml`).
- **commitizen** — `commit-msg` validation only (via pre-commit hook `cz_conventional_commits`). It does NOT manage versions here; semantic-release owns that.
- **ruff** — lint + format, both in pre-commit and in test.yml. Config in `[tool.ruff]`.
- **mkdocs-material** — strict build, deployed via `actions/deploy-pages@v4`. Source set to "GitHub Actions" in repo Settings → Pages.
- **uv** for everything else (`uv sync`, `uv build`, `uv publish`). Python 3.13 (locked in [.python-version](.python-version)).

## Release commits

Release commits use `chore(release): vX.Y.Z [skip ci]`. The `[skip ci]` prevents the release workflow from re-triggering on its own commit. Tag pushes do not trigger workflows (the workflow filters on `branches: [main]`, not tags).

## Workflows and pre-commit are linked

If you change `ruff`/`commitizen`/Python version, update **both** [.pre-commit-config.yaml](.pre-commit-config.yaml) and the corresponding workflow file. Versions should match across the two to avoid "passes locally, fails in CI" surprises.

## Things to NOT propose

- Long-lived `PYPI_API_TOKEN` or `TWINE_*` credentials — OIDC is configured.
- A custom Python script for the release flow (parsing commits, rendering changelog) — `python-semantic-release` covers this.
- Per-line PR enrichment in the changelog (PR #N + author + linked issues) — explicitly scoped out; only the bottom *Contributors* section is enriched, via `gh api compare`.
- Versioned docs via `mike` — not in scope.
- `mkdocs gh-deploy` — we use `actions/deploy-pages` (modern Pages flow), not the gh-pages branch.
- Direct pushes to `main` — see [CONTRIBUTING.md](CONTRIBUTING.md).
