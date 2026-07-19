from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import agent_trade_debate_report as debate
from scripts import hmm_regime_scanner as hmm
from scripts import prediction_market_slow_news_watch as slow_news
from scripts import strategy_leak_audit as leak


def test_strategy_leak_audit_rejects_future_shift() -> None:
    report = leak.scan_text("df['future'] = df.close.shift(-1)\nsignal = df.future > df.close\n")

    assert report["verdict"] == "reject_until_fixed"
    assert report["critical_count"] == 1
    assert any(item["rule_id"] == "future_shift" for item in report["findings"])


def test_strategy_leak_audit_flags_centered_rolling() -> None:
    report = leak.scan_text("mid = close.rolling(20, center=True).mean()\n")

    assert report["verdict"] == "needs_review"
    assert report["warning_count"] == 1


def test_hmm_classifies_panic_observation() -> None:
    assert hmm.classify_observation(ret_z=-1.2, vol_z=1.5) == "panic"


def test_hmm_aggregate_prefers_panic_when_probability_elevated() -> None:
    report = hmm.aggregate([
        {"status": "ok", "probabilities": {"trend": 0.2, "chop": 0.2, "panic": 0.6}},
        {"status": "ok", "probabilities": {"trend": 0.3, "chop": 0.2, "panic": 0.5}},
    ])

    assert report["state"] == "panic"
    assert report["action_context"] == "risk_down_context"


def test_pca_power_iteration_extracts_dominant_component() -> None:
    from scripts import pca_market_forces as pca

    eigenvalue, vector = pca._power_iteration([[1.0, 0.9], [0.9, 1.0]])

    assert eigenvalue > 1.8
    assert abs(abs(vector[0]) - abs(vector[1])) < 0.01


def test_pca_build_report_handles_fetch_error(monkeypatch) -> None:
    from scripts import pca_market_forces as pca

    monkeypatch.setattr(pca, "fetch_returns", lambda symbols, lookback_days: (_ for _ in ()).throw(RuntimeError("no data")))

    report = pca.build_report(day="2026-07-04", symbols=["SPY", "QQQ"])

    assert report["execution_enabled"] is False
    assert report["status"] == "error"
    assert report["force_regime"] == "unavailable"


def test_slow_news_classifies_macro_titles() -> None:
    themes = slow_news.classify_title("Will the Fed cut rates after CPI?")

    assert "fed_rates" in themes
    assert "inflation_cpi" in themes


def test_slow_news_build_report_from_mocked_markets(monkeypatch) -> None:
    monkeypatch.setattr(slow_news, "fetch_active_markets", lambda pages, page_limit: [
        {"slug": "fed-cut", "title": "Will the Fed cut interest rates?", "volume": "2500", "prices": [0.6, 0.4]},
        {"slug": "random", "title": "Will a random meme trend?", "volume": "100", "prices": [0.5, 0.5]},
    ])

    report = slow_news.build_report(top=2)

    assert report["execution_enabled"] is False
    assert report["candidate_count"] >= 1
    assert report["top_candidates"][0]["slug"] == "fed-cut"


def test_debate_risk_manager_veto_from_market_force() -> None:
    risk = debate.risk_manager_case({"risk_veto": {"active": True}}, None)

    assert risk["veto"] is True
    assert risk["score"] >= 10


def test_debate_final_verdict_observe_only() -> None:
    verdict = debate.final_verdict(
        {"score": 3.0},
        {"score": 0.0},
        {"veto": False},
    )

    assert verdict == "bull_case_leads_observe_only"


def test_manual_fable5_orchestrator_runs_read_only_stack() -> None:
    runner = ROOT / "scripts" / "run_fable5_intelligence_stack.ps1"

    text = runner.read_text(encoding="utf-8")

    assert "strategy_leak_audit.py" in text
    assert "hmm_regime_scanner.py" in text
    assert "pca_market_forces.py" in text
    assert "prediction_market_slow_news_watch.py" in text
    assert "agent_trade_debate_report.py" in text
    assert "execution_gate_audit.py" in text
    assert "--fail-on-issues" in text
    assert "/v2/orders" not in text


def test_numpy_dependent_runners_use_system_python() -> None:
    # HMM and PCA must not use uv --with numpy/pandas — AppLocker blocks
    # numpy DLLs from uv temp cache. These runners must use system Python.
    for name in ["run_hmm_regime_scanner.ps1", "run_pca_market_forces.ps1"]:
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "--with numpy" not in text, f"{name} must not use uv --with numpy"
    # Orchestrator may use --with yfinance for missed_banger_review.
    # yfinance has no AppLocker-blocked DLLs unlike numpy.
    orch = (ROOT / "scripts" / "run_fable5_intelligence_stack.ps1").read_text(encoding="utf-8")
    assert "--with numpy" not in orch, "orchestrator must not use uv --with numpy"
