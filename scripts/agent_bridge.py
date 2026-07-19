#!/usr/bin/env python3
"""File-based bridge for Codex <-> Claude Code coordination.

This does not make the agents chat directly. It gives both agents a shared,
auditable mailbox and a one-task lock inside CODEx_CLAUDE_COLLAB/BRIDGE.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRIDGE_ROOT = REPO_ROOT / "CODEx_CLAUDE_COLLAB" / "BRIDGE"


@dataclass(frozen=True)
class BridgePaths:
    root: Path = DEFAULT_BRIDGE_ROOT

    @property
    def mailbox(self) -> Path:
        return self.root / "mailbox.jsonl"

    @property
    def lock_file(self) -> Path:
        return self.root / "active_task.json"

    @property
    def messages_dir(self) -> Path:
        return self.root / "messages"

    @property
    def readme(self) -> Path:
        return self.root / "README.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:48] or "message"


def ensure_bridge(paths: BridgePaths) -> None:
    paths.messages_dir.mkdir(parents=True, exist_ok=True)
    if not paths.mailbox.exists():
        paths.mailbox.write_text("", encoding="utf-8")


def init_bridge(paths: BridgePaths = BridgePaths()) -> None:
    ensure_bridge(paths)
    paths.readme.write_text(
        """# Codex / Claude Bridge

Use this folder as the shared coordination channel between Codex and Claude Code.

## Commands

Post a message:

```powershell
python scripts\\agent_bridge.py post --from codex --to claude --topic "What changed" --body "Short handoff"
```

Read inbox:

```powershell
python scripts\\agent_bridge.py inbox --for claude
```

Claim the active task:

```powershell
python scripts\\agent_bridge.py claim --agent claude --task "Implement dashboard guard block panel"
```

Release the active task:

```powershell
python scripts\\agent_bridge.py release --agent claude
```

Show bridge status:

```powershell
python scripts\\agent_bridge.py status
```

## Rules

- One agent owns one coding task at a time.
- Post a bridge message after every material change.
- Do not enable live trading through this bridge.
- Use git diff and tests before handing work to the other agent.
""",
        encoding="utf-8",
    )


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def post_message(
    paths: BridgePaths = BridgePaths(),
    *,
    sender: str,
    recipient: str,
    topic: str,
    body: str,
) -> dict[str, Any]:
    ensure_bridge(paths)
    message_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{safe_slug(topic)}-{uuid4().hex[:8]}"
    message = {
        "id": message_id,
        "created_at": utc_now(),
        "from": sender,
        "to": recipient,
        "topic": topic,
        "body": body,
    }
    append_jsonl(paths.mailbox, message)
    (paths.messages_dir / f"{message_id}.md").write_text(
        f"# {topic}\n\n"
        f"- id: `{message_id}`\n"
        f"- from: `{sender}`\n"
        f"- to: `{recipient}`\n"
        f"- created_at: `{message['created_at']}`\n\n"
        f"{body.strip()}\n",
        encoding="utf-8",
    )
    return message


def inbox_for(paths: BridgePaths = BridgePaths(), agent: str = "claude", limit: int = 20) -> list[dict[str, Any]]:
    ensure_bridge(paths)
    messages = [
        msg for msg in read_jsonl(paths.mailbox)
        if msg.get("to") in (agent, "all")
    ]
    return messages[-limit:]


def _read_claim(paths: BridgePaths) -> dict[str, Any] | None:
    if not paths.lock_file.exists():
        return None
    return json.loads(paths.lock_file.read_text(encoding="utf-8"))


def claim_task(paths: BridgePaths = BridgePaths(), *, agent: str, task: str) -> dict[str, Any]:
    ensure_bridge(paths)
    active = _read_claim(paths)
    if active:
        return {"claimed": False, "active_claim": active}
    claim = {
        "claimed": True,
        "agent": agent,
        "task": task,
        "claimed_at": utc_now(),
    }
    paths.lock_file.write_text(json.dumps(claim, indent=2, sort_keys=True), encoding="utf-8")
    return claim


def release_task(paths: BridgePaths = BridgePaths(), *, agent: str) -> dict[str, Any]:
    ensure_bridge(paths)
    active = _read_claim(paths)
    if not active:
        return {"released": False, "reason": "no_active_claim"}
    if active.get("agent") != agent:
        return {"released": False, "reason": "claimed_by_other_agent", "active_claim": active}
    paths.lock_file.unlink()
    return {"released": True, "released_by": agent, "released_at": utc_now()}


def bridge_status(paths: BridgePaths = BridgePaths()) -> dict[str, Any]:
    ensure_bridge(paths)
    messages = read_jsonl(paths.mailbox)
    return {
        "bridge_root": str(paths.root),
        "messages": len(messages),
        "active_claim": _read_claim(paths),
        "latest_message": messages[-1] if messages else None,
    }


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared Codex/Claude file bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    post = sub.add_parser("post")
    post.add_argument("--from", dest="sender", required=True)
    post.add_argument("--to", dest="recipient", required=True)
    post.add_argument("--topic", required=True)
    post.add_argument("--body", required=True)

    inbox = sub.add_parser("inbox")
    inbox.add_argument("--for", dest="agent", required=True)
    inbox.add_argument("--limit", type=int, default=20)

    claim = sub.add_parser("claim")
    claim.add_argument("--agent", required=True)
    claim.add_argument("--task", required=True)

    release = sub.add_parser("release")
    release.add_argument("--agent", required=True)

    sub.add_parser("status")

    args = parser.parse_args()
    paths = BridgePaths()

    if args.cmd == "init":
        init_bridge(paths)
        print_json(bridge_status(paths))
    elif args.cmd == "post":
        print_json(post_message(paths, sender=args.sender, recipient=args.recipient, topic=args.topic, body=args.body))
    elif args.cmd == "inbox":
        print_json(inbox_for(paths, args.agent, args.limit))
    elif args.cmd == "claim":
        print_json(claim_task(paths, agent=args.agent, task=args.task))
    elif args.cmd == "release":
        print_json(release_task(paths, agent=args.agent))
    elif args.cmd == "status":
        print_json(bridge_status(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
