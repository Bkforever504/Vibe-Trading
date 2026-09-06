from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.moondev_backtest_claim_audit import audit_claims

def test_extreme_claim_without_ledger_is_unverified():
    report=audit_claims([{"strategy":"x","return_pct":100000,"sharpe":4,"max_drawdown_pct":-5}])
    assert report["verdict"]=="insufficient_evidence"
    assert "underlying_trade_ledger_unavailable" in report["findings"][0]["flags"]
