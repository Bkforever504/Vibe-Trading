from __future__ import annotations

from scripts.remote_dashboard_gateway import _is_allowed_api_path


def test_dashboard_supervisor_rejects_stale_published_tunnel_hostname() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "run_remote_trading_dashboard_supervisor.ps1").read_text(encoding="utf-8")

    assert "function Test-PublishedUrl" in script
    assert "[System.Net.Dns]::GetHostAddresses" in script
    assert "(Test-RemoteTunnel) -and (Test-PublishedUrl)" in script


def test_remote_dashboard_gateway_allows_only_read_only_cockpit_get_paths() -> None:
    assert _is_allowed_api_path("/trading/dashboard")
    assert _is_allowed_api_path("/trading/dashboard/sources/catalysts")
    assert _is_allowed_api_path("/trading/quotes")
    assert _is_allowed_api_path("/trading/bars")
    assert _is_allowed_api_path("/trading/opportunities")
    assert _is_allowed_api_path("/trading/feed-status")
    assert _is_allowed_api_path("/trading/opportunities/stream")
    assert not _is_allowed_api_path("/trading/quotes/extra")
    assert not _is_allowed_api_path("/trading/opportunities/delete")
    assert not _is_allowed_api_path("/live/status")
