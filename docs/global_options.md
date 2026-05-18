# Global options

A few flags work the same way across `spc` regardless of which subcommand you run. There are two categories:

- **Root-level globals** — go *before* the subcommand
- **Per-command globals** — accepted on every command (e.g. `--instance`)

## Root-level globals

These are accepted by `spc` itself, so they must appear **before** the subcommand:

| Flag | Description |
|---|---|
| `--namespace-app` | Override the namespace `app` for this invocation |
| `--namespace-owner` | Override the namespace `owner` for this invocation |
| `--version` | Print the version and exit |

Example — list lookups in the `search` app owned by `nobody`, overriding whatever the instance's default namespace is:

```sh
spc --namespace-app search --namespace-owner nobody lookups ls --instance prod
```

/// note
Placement matters: `spc --namespace-app … lookups ls` works; `spc lookups ls --namespace-app …` does not.
///

## `--instance`

`--instance <NAME>` is available on **every** command that talks to Splunk. It selects which instance the command runs against:

```sh
spc info --instance prod
spc lookups ls --instance dev
spc searches ls --instance staging --search 'name="*alert*"'
```

If omitted, `spc` falls back to the instance marked as `default` in your config — see [Configure instances](configure_instances.md).

## Splunk API filters (per-command)

Several `ls` commands accept Splunk's REST filter parameters as flags. These are **not** global — they only exist on commands that list collections, and the exact set varies per command.

| Flag | Description |
|---|---|
| `--search` | Splunk search expression filtering the response (Splunk's `search` query parameter) |
| `--sort-key` | Field name to sort by |
| `--sort-dir` | `asc` (ascending) or `desc` (descending) |
| `--limit` | Max number of entries (`0` or `-1` means *all*) |

Where each flag is available:

| Command | `--search` | `--sort-key` | `--sort-dir` | `--limit` |
|---|:---:|:---:|:---:|:---:|
| `spc jobs ls` | ✓ | ✓ | ✓ | ✓ |
| `spc secrets ls` | ✓ | ✓ | ✓ | ✓ |
| `spc lookups ls` | ✓ | — | — | ✓ |
| `spc searches ls` | ✓ | — | — | — |

Example — the 50 most recent search jobs in the `search` app:

```sh
spc jobs ls --instance prod \
  --search 'eai:acl.app="search"' \
  --sort-key dispatch_time \
  --sort-dir desc \
  --limit 50
```

These flags map directly to Splunk's REST API filter parameters. For the exact semantics — especially the expression syntax accepted by `--search` — see the official [Splunk REST API reference: Parameters](https://help.splunk.com/en/splunk-enterprise/leverage-rest-apis/rest-api-reference/9.4/introduction/using-the-rest-api-reference#ariaid-title5).
