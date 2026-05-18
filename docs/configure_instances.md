# Configure instances

An **instance** is a named Splunk connection — host, credentials, and namespace — that you reference with `--instance <NAME>` on any `spc` command.

There are three ways to declare one.

## Configuration sources

When `spc` needs an instance, it looks through these sources **in order** — values from a higher source override lower ones, field by field:

1. **`~/.spc/config.toml`** — recommended; supports multiple named instances
2. **`~/.spc.env`** — single instance, dotenv format
3. **Process environment variables** (`SPC_INSTANCE__*`) — for CI/CD and one-shot runs

## Add a new instance

Use `spc instances set <NAME>` — it writes to `~/.spc/config.toml`. Run it interactively or pass everything as flags.

### Interactive

```sh
spc instances set prod
```

You'll be prompted for host, port, authentication, and namespace. Add `-d` (or `--default`) to make this the default instance.

### With arguments

Skip the prompts by passing flags. Username + password:

```sh
spc instances set prod \
  --host splunk.lab --port 443 \
  --username admin --password toto123 \
  --app search --owner nobody --sharing app \
  --ssl-verify \
  -d
```

Token-based auth (replaces `--username` / `--password`):

```sh
spc instances set dev \
  --host localhost --port 8089 \
  --token eyJraWQ…
```

| Flag | Maps to |
|---|---|
| `--host` | hostname or IP |
| `--port` | management port |
| `--username` / `--password` | basic auth |
| `--token` | API token (alternative to user/pass) |
| `--ssl-verify` | verify the TLS certificate |
| `--app` / `--owner` / `--sharing` | namespace |
| `-d`, `--default` | mark this instance as the default |

## Manage instances

| Command | What it does |
|---|---|
| `spc instances ls` | List all instances (default marked with `*`) |
| `spc instances rm <NAME>` | Delete an instance |

## `.env` file

For a **single** instance, drop a `~/.spc.env`:

```env
SPC_INSTANCE__HOST=splunk.lab
SPC_INSTANCE__PORT=443
SPC_INSTANCE__USERNAME=admin
SPC_INSTANCE__PASSWORD=toto123
SPC_INSTANCE__NAMESPACE__APP=search
```

## Environment variables

The same variables work from the shell — handy in CI/CD pipelines:

```sh
SPC_INSTANCE__HOST=splunk.lab SPC_INSTANCE__TOKEN=eyJraWQ… spc info
```

**Naming convention**

- Prefix: `SPC_`
- Object delimiter: `__` (double underscore)
- Field names: uppercase

So `namespace.app` becomes `SPC_INSTANCE__NAMESPACE__APP`.

## Field reference

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | string | `localhost` | Splunk hostname or IP |
| `port` | int | `8089` | Splunk management port |
| `username` | string | — | Basic-auth username |
| `password` | string | — | Basic-auth password |
| `token` | string | — | API token (alternative to username/password) |
| `ssl_verify` | bool | `true` | Disable for self-signed certs |
| `namespace.app` | string | `search` | Splunk app context |
| `namespace.owner` | string | `nobody` | User context |
| `namespace.sharing` | enum | `app` | One of `user`, `app`, `global`, `system` |

/// warning | Credentials are stored in clear text
`config.toml` and `.spc.env` keep passwords and tokens unencrypted. Keep these files at mode `600` and never commit them. For CI/CD, inject `SPC_INSTANCE__*` from a secret store at runtime rather than checking in a config file.
///
