from __future__ import annotations

from scripts.remote_dashboard_gateway import DashboardHTTPServer, _is_allowed_api_path, _trusted_tailscale_identity


def test_dashboard_supervisor_rejects_stale_published_tunnel_hostname() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "run_remote_trading_dashboard_supervisor.ps1").read_text(encoding="utf-8")

    assert "function Test-PublishedUrl" in script
    assert "Resolve-DnsName" in script
    assert '-Server $resolver' in script
    assert "(Test-RemoteTunnel) -and (Test-PublishedUrl)" in script


def test_dashboard_backend_is_bound_to_loopback_behind_authenticated_gateway() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts" / "run_live_trading_dashboard_backend.ps1").read_text(encoding="utf-8")

    assert "'127.0.0.1'" in runner
    assert "'0.0.0.0'" not in runner


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


def test_remote_dashboard_gateway_accept_queue_handles_parallel_module_bursts() -> None:
    assert DashboardHTTPServer.request_queue_size >= 64


def test_tailscale_identity_auth_requires_enabled_loopback_proxy_and_tsnet_host() -> None:
    headers = {"Host": "vibe-dashboard.example.ts.net", "Tailscale-User-Login": "owner@example.com"}

    assert _trusted_tailscale_identity(headers, ("127.0.0.1", 50123), enabled=True)
    assert not _trusted_tailscale_identity(headers, ("100.64.0.10", 50123), enabled=True)
    assert not _trusted_tailscale_identity({**headers, "Host": "example.com"}, ("127.0.0.1", 50123), enabled=True)
    assert not _trusted_tailscale_identity({"Host": headers["Host"]}, ("127.0.0.1", 50123), enabled=True)
    assert not _trusted_tailscale_identity(headers, ("127.0.0.1", 50123), enabled=False)


def test_dashboard_supervisor_enables_tailscale_identity_only_on_loopback_gateway() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "run_remote_trading_dashboard_supervisor.ps1").read_text(encoding="utf-8")

    assert '"--host", "127.0.0.1"' in script
    assert '"--trust-tailscale-identity"' in script


def test_remote_dashboard_build_inlines_dynamic_imports_for_mobile_reliability() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    config = (root / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

    assert "inlineDynamicImports: true" in config
    assert "manualChunks" not in config
