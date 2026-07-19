# Codex Handoff — X MCP Setup

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Date: 2026-06-30

## What Was Configured

Official X MCP docs used:

- `https://docs.x.com/tools/mcp`
- Markdown source: `https://docs.x.com/tools/mcp.md`

Added both official X MCP servers to Claude config:

1. `x-docs`
   - URL: `https://docs.x.com/mcp`
   - Purpose: search/read X API documentation.
   - No credentials required.

2. `xapi`
   - Command: `npx`
   - Args:
     ```json
     ["-y", "@xdevplatform/xurl", "mcp", "https://api.x.com/mcp"]
     ```
   - Purpose: X API MCP via X's `xurl` OAuth bridge.
   - Requires X Developer app OAuth credentials or a cached `~/.xurl` login.

Files updated:

- `C:\Users\kenne\.claude\mcp.json`
- `C:\Users\kenne\.claude\.mcp.json`

Backups created:

- `C:\Users\kenne\.claude\mcp.json.bak-20260630-115158`
- `C:\Users\kenne\.claude\.mcp.json.bak-20260630-115158`

## Verification

Confirmed npm package exists:

```powershell
npm view @xdevplatform/xurl name version bin
```

Result:

```text
name = '@xdevplatform/xurl'
version = '1.2.2'
bin = { xurl: 'cli.js' }
```

`npx` probe exited nonzero with no useful output, but the MCP command matches X's official docs exactly.

## What Is Still Needed

The docs MCP should work after restarting Claude Code/Claude Desktop.

The X API MCP will not search posts until OAuth is configured:

1. Go to [X Developer Portal](https://developer.x.com).
2. Create or open an app.
3. Enable OAuth 2.0.
4. Add redirect URI:
   ```text
   http://localhost:8080/callback
   ```
5. Copy:
   - `CLIENT_ID`
   - `CLIENT_SECRET`
6. Either:
   - add them to the MCP config env block, or
   - set them as user environment variables before launching Claude, or
   - register/authenticate with `xurl` so it uses `~/.xurl`.

Official first-run/auth command:

```powershell
npx -y @xdevplatform/xurl mcp https://api.x.com/mcp
```

When credentials are available, first use should open a browser for one-time X login and cache the token in `~/.xurl`.

## Security Notes

- Do not paste X tokens into chats or committed files.
- Prefer a dedicated X Developer app with the minimum scopes needed.
- Treat `~/.xurl` as secret because it stores refreshed auth state.

## Trading Workflow Use

Once authenticated, use X search as an idea/context source only:

- track posts from MoonDev, Axel, Tom Dörr, quant/trading bot builders
- collect strategy claims into `research/social_strategy_intake/`
- never route X claims directly to execution
- every claim still goes through:
  1. rules extraction
  2. Pine/Python translation
  3. repaint/lookahead scan
  4. backtest/OOS/PBO
  5. shadow forward test
  6. 30-day / 10-signal gate

