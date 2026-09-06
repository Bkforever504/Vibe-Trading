from agent.observability.discord_backfill import recover_rows


def test_missing_message_id_is_permanently_unrecoverable_without_guess():
    result = recover_rows([{"event_id": "old", "delivered": True, "attempted_at": "2026-09-04T15:00:00Z"}],
                          source="governed_shadow", fetcher=None)[0]
    assert result["status"] == "unrecoverable"
    assert result["recoverable"] is False
    assert result["discord_delivered_ts"] is None


def test_stored_message_id_recovers_only_returned_discord_timestamp():
    result = recover_rows([{"event_id": "old", "discord_message_id": "123456789"}],
                          source="governed_shadow",
                          fetcher=lambda message_id: {"id": message_id, "timestamp": "2026-09-04T15:00:04Z", "content": "not persisted"})[0]
    assert result["status"] == "recovered"
    assert result["discord_delivered_ts"] == "2026-09-04T15:00:04Z"
    assert len(result["response_hash"]) == 64
    assert "content" not in result
