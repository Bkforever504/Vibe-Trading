from pathlib import Path

from scripts.agent_bridge import (
    BridgePaths,
    claim_task,
    inbox_for,
    init_bridge,
    post_message,
    release_task,
)


def test_post_message_creates_inbox_and_markdown_handoff(tmp_path: Path) -> None:
    paths = BridgePaths(tmp_path / "BRIDGE")

    message = post_message(
        paths,
        sender="codex",
        recipient="claude",
        topic="Execution guard",
        body="Paper execution is guarded. Live remains blocked.",
    )

    inbox = inbox_for(paths, "claude")
    assert len(inbox) == 1
    assert inbox[0]["id"] == message["id"]
    assert inbox[0]["from"] == "codex"
    assert inbox[0]["to"] == "claude"
    assert "Paper execution" in inbox[0]["body"]
    handoff = paths.messages_dir / f"{message['id']}.md"
    assert handoff.exists()
    assert "Execution guard" in handoff.read_text(encoding="utf-8")


def test_claim_task_prevents_two_agents_working_same_task(tmp_path: Path) -> None:
    paths = BridgePaths(tmp_path / "BRIDGE")

    first = claim_task(paths, agent="codex", task="wire dashboard guard blocks")
    second = claim_task(paths, agent="claude", task="different task")

    assert first["claimed"] is True
    assert first["agent"] == "codex"
    assert second["claimed"] is False
    assert second["active_claim"]["task"] == "wire dashboard guard blocks"

    released = release_task(paths, agent="codex")
    assert released["released"] is True

    third = claim_task(paths, agent="claude", task="different task")
    assert third["claimed"] is True
    assert third["agent"] == "claude"


def test_init_bridge_writes_readme_with_usage(tmp_path: Path) -> None:
    paths = BridgePaths(tmp_path / "BRIDGE")

    init_bridge(paths)

    assert paths.root.exists()
    readme = paths.readme.read_text(encoding="utf-8")
    assert "agent_bridge.py post" in readme
    assert "agent_bridge.py claim" in readme
