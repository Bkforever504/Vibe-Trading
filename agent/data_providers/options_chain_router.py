"""Fail-honest options-chain provider routing."""

from __future__ import annotations

from typing import Any, Mapping


class OptionsChainRouter:
    def __init__(self, providers: Mapping[str, Any], priority: list[str] | tuple[str, ...]) -> None:
        self.providers = dict(providers)
        self.priority = list(priority)

    def fetch_chain(self, symbol: str, **params: Any) -> dict[str, Any]:
        attempts: list[dict[str, str]] = []
        for name in self.priority:
            provider = self.providers.get(name)
            if provider is None:
                attempts.append({"provider": name, "status": "not_configured"})
                continue
            result = provider.fetch_chain(symbol, **params)
            status = str(result.get("status", "missing"))
            attempts.append({"provider": name, "status": status})
            if status == "ok" and result.get("contracts"):
                routed = dict(result)
                routed["route_attempts"] = attempts
                routed["execution_enabled"] = False
                routed["execution_eligible"] = False
                return routed
        return {
            "provider": None,
            "status": "missing",
            "symbol": symbol.upper(),
            "contracts": [],
            "contract_count": 0,
            "route_attempts": attempts,
            "execution_enabled": False,
            "execution_eligible": False,
        }
