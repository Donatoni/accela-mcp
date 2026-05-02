# Installing accela-mcp

There are four supported ways to get this MCP server running, in order of
friendliest to most flexible. Pick one.

| Path | Best for | Terminal needed? |
|---|---|---|
| [A. Claude Desktop drag-drop](#a-claude-desktop-drag-drop) | Non-technical users, fastest install | No |
| [B. `accela-mcp setup` (CLI)](#b-accela-mcp-setup-cli) | Most users — auto-configures Claude Desktop and Codex | Yes (one command) |
| [C. Codex (manual)](#c-codex-manual) | Codex CLI users who prefer manual config | Yes |
| [D. Cursor / generic stdio](#d-cursor--generic-stdio) | Cursor users and any MCP host that takes a stdio command | Yes |

All paths talk to the same Accela API and use the same code; they differ only
in how the MCP server gets configured into your host.

## Before you start

You need an Accela Construct app. Create one at the
[Accela Developer Portal](https://developer.accela.com) and copy three things:

1. **App ID** (public)
2. **App Secret** (private — treat like a password)
3. **Redirect URI** registered on the app. Use `http://localhost:8765/oauth/callback`
   unless you have a reason to pick a different port.

You also need a recent Python (3.11+) and your tenant's **agency** and
**environment** strings (e.g. `MYCITY` / `TEST`).

## A. Claude Desktop drag-drop

Use this if you'd rather not touch the command line.

1. **Download** the latest `accela-mcp-<version>.mcpb` from the
   [Releases page](https://github.com/Donatoni/accela-mcp/releases).
2. **Drag** it into Claude Desktop's Settings → Extensions panel (the area
   labeled *Drag .MCPB or .DXT files here to install*).
3. **Configure** in the extension's settings tab that opens after install:
   - *Accela App ID* — paste from the Developer Portal
   - *Accela App Secret* — paste from the Developer Portal
   - *OAuth Redirect URI* — leave the default unless you registered a
     different one
   - *Encryption Key* — leave blank; the server will generate one for you
4. **Log in from chat.** Start a new conversation and ask: *“Log me into
   Accela.”* Claude will call the `accela_login` tool, which opens your
   browser to Accela's authorize page. After you sign in, the tab will
   say *Authentication successful* and tokens are saved.
5. **Restart Claude Desktop.** This is required so the rest of the Accela
   tools (records, inspections, fees, etc.) become visible to Claude.

**Verifying it works:** ask *“Am I logged into Accela?”* — Claude should
call `accela_auth_status` and report your agency, environment, and token
expiries.

## B. `accela-mcp setup` (CLI)

Use this if you're comfortable in a terminal — it's the fastest path that
also configures Codex automatically.

```bash
pip install accela-mcp     # or: uv tool install accela-mcp
accela-mcp setup
```

`setup` walks you through:

- Entering your App ID, App Secret, agency, environment, and redirect URI
- Creating a private user-level env file (mode 0600 on Unix)
- Auto-generating an encryption key
- Writing a default `capabilities.yaml`
- Running the OAuth Authorization Code flow
- Installing the MCP entry into Claude Desktop's `claude_desktop_config.json`
  and/or Codex's `~/.codex/config.toml`, picking the right path for your
  platform

After it finishes, restart Claude Desktop / Codex.

You can re-check the install at any time:

```bash
accela-mcp doctor             # local checks
accela-mcp doctor --online    # also pings Accela's tokeninfo
accela-mcp status             # token + agency + environment summary
```

## C. Codex (manual)

If you'd rather hand-edit Codex's TOML, install the package:

```bash
pip install accela-mcp     # or: uv tool install accela-mcp
```

Then add to `~/.codex/config.toml`:

```toml
[mcp_servers.accela]
command = "accela-mcp"
args = ["serve"]

[mcp_servers.accela.env]
ACCELA_APP_ID = "your-app-id"
ACCELA_APP_SECRET = "your-app-secret"
ACCELA_REDIRECT_URI = "http://localhost:8765/oauth/callback"
# Leave ACCELA_MCP_KEY unset — the server generates one on first run.
```

Then run the OAuth flow once:

```bash
accela-mcp auth --agency YOUR_AGENCY --environment YOUR_ENV
```

This persists tokens to the path that `accela-mcp status` reports.

## D. Cursor / generic stdio

For Cursor or any other MCP host that accepts a stdio command, install
the package and configure your host to run `accela-mcp serve`. The minimal
JSON config most hosts accept:

```json
{
  "mcpServers": {
    "accela": {
      "command": "accela-mcp",
      "args": ["serve"],
      "env": {
        "ACCELA_APP_ID": "your-app-id",
        "ACCELA_APP_SECRET": "your-app-secret",
        "ACCELA_REDIRECT_URI": "http://localhost:8765/oauth/callback"
      }
    }
  }
}
```

Then run `accela-mcp auth --agency YOUR_AGENCY --environment YOUR_ENV`
once to persist tokens.

## Troubleshooting

### "Refresh token expired"

Accela's refresh tokens have a 7-day window. If you see this, ask Claude
to *log me into Accela* (path A) or run `accela-mcp auth ...` (paths B–D).

### "Port 8765 is already in use"

Some other process is bound to your redirect URI's port. Stop it and
retry, or register a different port on the Accela Developer Portal and
update `ACCELA_REDIRECT_URI` everywhere.

### "Failed to decrypt token file"

`ACCELA_MCP_KEY` changed since the tokens were saved. Run `accela_login`
(or `accela-mcp auth`) to mint fresh tokens against the current key.

### Tools other than `accela_login` aren't showing up

You're in **bootstrap mode** — the server started without valid tokens
and is exposing only the auth tools. Run `accela_login`, then **restart
the host app** so it re-queries the tool list.

### `accela_login` says "config_missing"

The host's settings panel hasn't been filled in yet — set App ID and
App Secret in the extension's Configuration tab and try again.

## Where things live

| File | Default location (macOS) | Set via |
|---|---|---|
| Encrypted tokens | `~/Library/Application Support/accela-mcp/tokens.json` | `ACCELA_MCP_TOKEN_PATH` |
| `capabilities.yaml` | `~/Library/Application Support/accela-mcp/capabilities.yaml` | `ACCELA_MCP_CONFIG_PATH` |
| Setup env file | `~/Library/Application Support/accela-mcp/.env` | `ACCELA_MCP_ENV_PATH` |

Linux and Windows use the platform's standard user-config directory
(see `platformdirs`).
