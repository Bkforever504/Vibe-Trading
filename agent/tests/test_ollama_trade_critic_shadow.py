from scripts import ollama_trade_critic_shadow as runner


def _decision(key: str, score: int = 80):
    return {
        "candidate_key": key,
        "candidate": {"symbol": key, "direction": "LONG", "score": score},
        "evidence_cards": [{"role": "technical", "claim": "confirmed", "evidence_hash": f"hash-{key}"}],
    }


def test_cpu_budget_defers_honestly_without_calling_model(monkeypatch):
    monkeypatch.setattr(runner.governed, "build_report", lambda: {"decisions": [_decision("SPY"), _decision("QQQ", 90)]})
    monkeypatch.setattr(runner, "evaluate", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not call")))
    report = runner.build_report(
        model="qwen3:4b-instruct", base_url="http://127.0.0.1:11434",
        timeout_seconds=30, max_new_evaluations=0,
    )
    assert report["summary"]["deferred_capacity"] == 2
    assert all(row["status"] == "deferred_capacity" for row in report["cards"])
    assert all(row["execution_enabled"] is False and row["can_submit_orders"] is False for row in report["cards"])


def test_matching_valid_card_is_reused_without_inference(monkeypatch):
    decision = _decision("SPY")
    monkeypatch.setattr(runner.governed, "build_report", lambda: {"decisions": [decision]})
    monkeypatch.setattr(runner, "evaluate", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not call")))
    prior = {
        "cards": [{
            "candidate_key": "SPY", "status": "ok", "model": "qwen3:4b-instruct",
            "input_hash": runner.input_digest(decision["candidate"], decision["evidence_cards"]),
            "execution_enabled": False, "can_submit_orders": False,
        }]
    }
    report = runner.build_report(
        model="qwen3:4b-instruct", base_url="http://127.0.0.1:11434",
        timeout_seconds=30, previous=prior,
    )
    assert report["cards"][0]["cache_hit"] is True
    assert report["summary"]["new_evaluations"] == 0

