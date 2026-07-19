# Codex / Claude Bridge

Use this folder as the shared coordination channel between Codex and Claude Code.

## Commands

Post a message:

```powershell
python scripts\agent_bridge.py post --from codex --to claude --topic "What changed" --body "Short handoff"
```

Read inbox:

```powershell
python scripts\agent_bridge.py inbox --for claude
```

Claim the active task:

```powershell
python scripts\agent_bridge.py claim --agent claude --task "Implement dashboard guard block panel"
```

Release the active task:

```powershell
python scripts\agent_bridge.py release --agent claude
```

Show bridge status:

```powershell
python scripts\agent_bridge.py status
```

## Rules

- One agent owns one coding task at a time.
- Post a bridge message after every material change.
- Do not enable live trading through this bridge.
- Use git diff and tests before handing work to the other agent.
