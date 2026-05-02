# Accela MCP

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server
that wraps the Accela Construct API as a curated, capability-grouped tool
set. Designed for production deployment by government IT staff and
implementation partners running [Accela Civic Platform](https://www.accela.com/).

The server is **safe by default** — every install ships read-only.
Destructive and financial capability groups must be explicitly enabled in
configuration. Tokens are stored encrypted at rest, refreshed
automatically, and never logged.

> Status: **v0.2.0** — full v1 read catalog plus the v2 write groups
> (records, inspections, documents, workflow, payments) and the GIS /
> reports groups. Every write tool is dry-run by default; an explicit
> `confirm: true` is required to mutate Accela data, and a YAML-level
> kill-switch (`writes.enabled`) guards every confirmed call.

---

## Prerequisites

- **Python 3.11+**.
- An **Accela Developer Portal** account at <https://developer.accela.com>.
- An app registered there (My Apps → Add New App):
    - Targeted Users: **Agency**
    - Stage: **Under Development** (move to **Published** when ready)
    - Authorized Redirect URIs must include the value you'll set in
      `ACCELA_REDIRECT_URI` (e.g., `http://localhost:8765/oauth/callback`).
- An agency to authenticate against. For sandbox use **NULLISLAND** (newer)
  or **ISLANDTON** (legacy, more variety).

## Install

There are several install paths depending on which host you use. The full
walkthrough — including a drag-and-drop **Claude Desktop** install, Codex
config, Cursor config, and troubleshooting — lives in
[`docs/INSTALL.md`](docs/INSTALL.md). The summary:

- **Claude Desktop, no terminal:** download the latest `.mcpb` from
  [Releases](https://github.com/Donatoni/accela-mcp/releases), drag it
  into Settings → Extensions, fill in App ID + Secret in the config tab,
  then ask Claude *“log me into Accela.”*
- **CLI for Claude Desktop and/or Codex:** `uv tool install accela-mcp`
  then `accela-mcp setup` — auto-configures both apps in one command.
- **Cursor / generic stdio:** point the host at `accela-mcp serve`; see
  [`docs/INSTALL.md`](docs/INSTALL.md#d-cursor--generic-stdio).

The rest of this section covers the CLI install — see the doc above for
the drag-drop path.

For normal use, install the published CLI from
[PyPI](https://pypi.org/project/accela-mcp/) with `uv`:

```bash
uv tool install accela-mcp
```

`uv tool install` creates an isolated Python environment for the tool and
puts the `accela-mcp` command on your PATH. To update later:

```bash
uv tool upgrade accela-mcp
```

If you prefer `pip`, this also works:

```bash
python -m pip install accela-mcp
```

For release testing only, the package is also published on
[TestPyPI](https://test.pypi.org/project/accela-mcp/):

```bash
uv tool install \
  --index https://test.pypi.org/simple/ \
  --default-index https://pypi.org/simple/ \
  accela-mcp
```

## Easy Setup

After installing, run the guided setup wizard:

```bash
accela-mcp setup
```

It asks for:

- Accela App ID
- Accela App Secret
- Agency, such as `NULLISLAND`
- Environment, usually `TEST`
- Redirect URI, usually `http://localhost:8765/oauth/callback`
- Where to install the MCP entry: Claude Desktop, Codex, both, or neither

Then it:

- Generates the local encryption key automatically.
- Creates a private user-level env file.
- Creates a safe read-only `capabilities.yaml`.
- Opens the browser so you can sign in to Accela.
- Saves encrypted OAuth tokens.
- Adds the MCP server to the selected app config without putting Accela
  secrets in Claude or Codex config files.

After setup finishes, restart the selected app(s).

To check the installation later:

```bash
accela-mcp doctor
```

`doctor` checks the private setup file, capabilities config, encrypted
token file, refresh-token expiry, and selected app config. Add `--online`
if you also want it to call Accela's token-info endpoint. Use
`--apps claude`, `--apps codex`, or `--apps both` to choose which app
configs to check.

## Manual Setup

Use this only if you are deploying for an agency, scripting setup, or need
custom paths. The wizard above writes these values for you.

### Required Environment Variables

| Var                   | Purpose                                                                                                                                                                                                               |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ACCELA_APP_ID`       | Your Developer Portal app ID.                                                                                                                                                                                         |
| `ACCELA_APP_SECRET`   | App secret used for token exchange / refresh.                                                                                                                                                                         |
| `ACCELA_REDIRECT_URI` | Must match a registered redirect URI on the Developer Portal. The CLI binds a one-shot loopback listener on its host:port during the auth flow.                                                                       |
| `ACCELA_MCP_KEY`      | Local Fernet key for token storage. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and treat like a password. If lost, you must re-run `accela-mcp auth`. |

### Optional Environment Variables

| Var                      | Default                                    | Purpose                                                      |
| ------------------------ | ------------------------------------------ | ------------------------------------------------------------ |
| `ACCELA_MCP_ENV_PATH`    | user config `.env`, then repo-local `.env` | Path to the private setup env file generated by `setup`.     |
| `ACCELA_MCP_CONFIG_PATH` | user config `capabilities.yaml`            | Path to the YAML config.                                     |
| `ACCELA_MCP_TOKEN_PATH`  | user config `tokens.json`                  | Path to the encrypted token bundle.                          |
| `ACCELA_MCP_LOG_LEVEL`   | `INFO`                                     | `DEBUG` / `INFO` / `WARNING` / `ERROR`.                      |
| `ACCELA_MCP_LOG_FORMAT`  | `json`                                     | `json` (production) or `console` (human-readable, dev only). |
| `ACCELA_AUTH_BASE_URL`   | `https://auth.accela.com`                  | Override for regional / on-prem deployments.                 |
| `ACCELA_API_BASE_URL`    | `https://apis.accela.com`                  | Same.                                                        |

The default user config directory is platform-specific:

- macOS: `~/Library/Application Support/accela-mcp/`
- Linux: `~/.config/accela-mcp/`
- Windows: `%APPDATA%\accela-mcp\`

### `capabilities.yaml`

Drop a copy of `capabilities.yaml.example` at the path
`ACCELA_MCP_CONFIG_PATH` points to and edit:

```yaml
version: 1
agency: NULLISLAND
environment: TEST

# Optional — replaces the spec defaults if present.
enabled_groups:
    - discovery
    - records_read
    - inspections_read
    - documents_read
    - property_read
    - people_read
    - workflow_read
    - fees_read
    - reference_data
    - search
```

`discovery` is always enabled. The full validation rules and every
optional knob are documented in `capabilities.yaml.example`.

### Manual Quickstart

```bash
export ACCELA_APP_ID="your_app_id"
export ACCELA_APP_SECRET="your_app_secret"
export ACCELA_REDIRECT_URI="http://localhost:8765/oauth/callback"
export ACCELA_MCP_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

accela-mcp auth --agency NULLISLAND --environment TEST
accela-mcp status
accela-mcp serve
```

`accela-mcp auth` creates a default `capabilities.yaml` if one does not
exist. Edit that file to opt into additional groups, the escape hatch, or
different rate-limit settings.

## Connecting to MCP Clients

### Claude Desktop

Choose `claude` or `both` during `accela-mcp setup` to update Claude
Desktop automatically. The generated entry looks like this:

```json
{
    "mcpServers": {
        "accela": {
            "command": "accela-mcp",
            "args": ["serve"],
            "env": {
                "ACCELA_MCP_ENV_PATH": "/path/to/private/accela-mcp/.env"
            }
        }
    }
}
```

The `ACCELA_MCP_ENV_PATH` value is not secret; it points to the private
file where the real Accela credentials live. After config changes,
restart Claude Desktop.

### Codex

Choose `codex` or `both` during `accela-mcp setup` to update Codex
automatically. The setup wizard writes or updates this block in
`~/.codex/config.toml` (or `%USERPROFILE%\.codex\config.toml` on Windows):

```toml
[mcp_servers.accela]
command = "accela-mcp"
args = ["serve"]

[mcp_servers.accela.env]
ACCELA_MCP_ENV_PATH = "/path/to/private/accela-mcp/.env"
```

The setup wizard creates a timestamped backup before changing an existing
Codex config. Restart Codex after setup.

### Claude Code

For Claude Code CLI, point it at the generated env file:

```bash
claude mcp add accela --command accela-mcp --args serve \
  -e ACCELA_MCP_ENV_PATH=/path/to/private/accela-mcp/.env
```

Or use the manual environment-variable form:

```bash
claude mcp add accela --command accela-mcp --args serve \
  -e ACCELA_APP_ID=... \
  -e ACCELA_APP_SECRET=... \
  -e ACCELA_REDIRECT_URI=http://localhost:8765/oauth/callback \
  -e ACCELA_MCP_KEY=...
```

## Capability groups

| Group                                                                        | Default   | Purpose                                                                                                                             |
| ---------------------------------------------------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `discovery`                                                                  | always on | List capabilities, agency info, record-type and custom-form metadata.                                                               |
| `records_read`                                                               | on        | Search records, get record details, get my records, read custom data.                                                               |
| `inspections_read`                                                           | on        | List inspections, get details, history, checklists.                                                                                 |
| `documents_read`                                                             | on        | List record documents, download (≤25 MB inline).                                                                                    |
| `property_read`                                                              | on        | Address, parcel, owner lookups.                                                                                                     |
| `people_read`                                                                | on        | Contacts and licensed professionals.                                                                                                |
| `workflow_read`                                                              | on        | Workflow tasks and history for a record.                                                                                            |
| `fees_read`                                                                  | on        | List fees, estimate fees, list invoices.                                                                                            |
| `reference_data`                                                             | on        | Record types, statuses, departments, fee schedules (TTL-cached).                                                                    |
| `search`                                                                     | on        | Cross-entity global search.                                                                                                         |
| `records_write` / `inspections_write` / `documents_write` / `workflow_write` | off, opt-in | Mutating tools. Every tool is dry-run by default — confirmed calls require `writes.enabled: true` in YAML.                          |
| `payments_read`                                                              | off, opt-in | Read payments on a record.                                                                                                          |
| `payments_write`                                                             | off, opt-in | Initiate / commit payments. `commit` additionally requires `payments.real_money_allowed: true`; PROD adds a friction flag.          |
| `gis`                                                                        | off, opt-in | Geocode / reverse-geocode helpers.                                                                                                  |
| `reports`                                                                    | off, opt-in | List and run agency-defined reports.                                                                                                |
| `admin_escape_hatch`                                                         | off       | `accela_raw_request` for endpoints not wrapped — gated by a regex path allowlist and an HTTP-method allowlist (default `GET` only). |

## Write tools and the safety model

Write tools mutate Accela data. To prevent the LLM from making
unintended changes, this MCP enforces three layers of friction:

1. **Every write tool is dry-run by default.** Calling without
   `confirm=true` returns a structured *preview* — method, path, body,
   summary, irreversibility flag — and does NOT call Accela. The LLM
   must surface that preview to the human user, get explicit approval,
   and then re-invoke with `confirm=true` to actually execute.
2. **Master kill-switch in `capabilities.yaml`.** Listing a `*_write`
   group in `enabled_groups` requires `writes.enabled: true`. The
   server refuses to start if those mismatch — fail-loud over fail-silent.
   Optional `agency_environment_allowed` further restricts confirmed
   writes to listed environments (e.g. `["TEST"]`).
3. **Append-only audit log.** When `writes.audit_log_path` is set,
   every confirmed write writes one JSON line containing tool, method,
   path, agency, environment, scrubbed params, response status, and
   `traceId`. Survives `logging.format=console`. Mode 0600 on Unix.

Payments add a fourth gate: even with writes enabled,
`accela_commit_payment` refuses to call `/commit` unless
`payments.real_money_allowed: true`. Against PROD-like environments
you also need `payments.i_understand_this_spends_real_money: true` —
intentional friction.

For sensitive updates, `accela_update_record` accepts an
`expected_status` precondition. The tool reads the current record before
writing and refuses the update if status changed since the LLM last
looked. Stops "I confidently updated the wrong record" outcomes.

Example dry-run preview return shape:

```json
{
  "preview": true,
  "confirmation_required": true,
  "tool": "accela_update_workflow_task",
  "method": "PUT",
  "path": "/v4/records/ISLANDTON-1-2-3/workflowTasks",
  "summary": "Update workflow task '42' on record 'ISLANDTON-1-2-3' → status 'Approved'",
  "body": [{ "id": "42", "status": { "value": "Approved" } }],
  "irreversible": false,
  "affects_money": false,
  "next_step": "Show this preview to the human user. If they approve, re-invoke 'accela_update_workflow_task' with the same arguments and `confirm=True` to actually execute."
}
```

## Operational behavior

- **Auth.** OAuth 2.0 Authorization Code flow with PKCE (always on). The
  refresh token is rotated on every refresh; the 7-day refresh window is
  honored, and `accela-mcp status` warns when within 24 hours of expiry.
- **Retries.** 429 / 5xx / transient network errors are retried with
  jittered exponential backoff (configurable via
  `rate_limit.max_retries` etc. in YAML). 401 forces a refresh and
  retries exactly once.
- **Logging.** One JSON line per API call to **stderr**, including method,
  path, status, duration, attempt number, and Accela `traceId` on errors.
  Rate-limit headers are surfaced when present.
- **Caching.** Reference-data endpoints (record types, departments, etc.)
  are cached with a 1-hour TTL by default. Every reference-data tool
  exposes `cache_bypass: bool = False` for forced refresh.
- **Document downloads.** Inline base64; refused for files >25 MB.

## Troubleshooting

Start with:

```bash
accela-mcp doctor
```

| Symptom                                                                      | Cause                                               | Fix                                                                                                   |
| ---------------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `accela-mcp setup` or `auth` errors with "Failed to bind ..."                | Port in use                                         | Pick a different port in the redirect URI and update the registered redirect on the Developer Portal. |
| `OAuth state mismatch`                                                       | Stale browser session, possible CSRF                | Close the auth tab, retry.                                                                            |
| `Refresh token expired`                                                      | More than 7 days since last successful auth/refresh | Re-run `accela-mcp setup` or `accela-mcp auth`.                                                       |
| `Failed to decrypt token file`                                               | `ACCELA_MCP_KEY` changed since tokens were saved    | Re-run `accela-mcp setup` (or restore the original key).                                              |
| `capabilities.yaml agency 'X' does not match the persisted token agency 'Y'` | YAML and tokens disagree                            | Re-run setup/auth for the right agency, or update `capabilities.yaml`.                                |
| Claude Desktop or Codex does not show Accela tools                           | App config not updated or app not restarted         | Run `accela-mcp doctor --apps both`, then restart the affected app.                                   |
| Tool returns `{ "error": "accela_api_error", ... }`                          | API returned 4xx                                    | Check `trace_id` and Accela's docs; surface to your agency admin if persistent.                       |

## Development

```bash
# Install the project and dev dependencies.
uv sync --extra dev

# Lint + format.
uv run ruff check
uv run ruff format --check

# Unit tests (mocked HTTP; no real API).
uv run pytest tests/unit -v

# Coverage.
uv run pytest tests/unit --cov=accela_mcp --cov-report=term-missing

# Integration tests (real sandbox; gated).
ACCELA_INTEGRATION_TEST=1 uv run pytest tests/integration -v
```

## Limitations (v0.2.0)

- Single-agency, single-environment per running server.
- Read-only by default. Write groups must be explicitly enabled AND
  `writes.enabled: true` set in `capabilities.yaml`. Even then, every
  write tool is dry-run unless called with `confirm=true`.
- Document upload uses the legacy single-shot
  `POST /v4/records/{id}/documents` endpoint with a 20 MB inline cap.
  The newer ACDS chunked upload service is deferred.
- No webhook support — Accela does not expose a native webhook API
  (EMSE is agency-side and not in scope).

## License

Apache 2.0 — see `LICENSE`.
