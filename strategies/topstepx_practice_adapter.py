#!/usr/bin/env python3
"""Fail-closed ProjectX/TopstepX adapter for a Topstep Practice account.

The adapter is read-only by default. Order methods require all of these:

* an explicit practice account ID allowlist;
* an API-returned account name containing ``PRACTICE``;
* a practice-only execution confirmation;
* a personal-device confirmation;
* one MES contract or less;
* a passing deterministic prop-rule decision;
* no existing position/order and no prior entry that session.

There is intentionally no funded/Combine override.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from strategies.prop_rule_gate import AccountState, ProposedTrade, evaluate_prop_trade


API_BASE_URL = "https://api.topstepx.com"
PRACTICE_NAME_PATTERN = re.compile(r"(?:^|[^A-Z])PRACTICE(?:[^A-Z]|$)")
EXECUTION_CONFIRMATION = "PRACTICE_ONLY_CONFIRMED"
LOCAL_DEVICE_CONFIRMATION = "PERSONAL_DEVICE_CONFIRMED"
DEFAULT_JOURNAL = Path.home() / ".vibe-trading" / "topstepx-practice-orders.jsonl"
DEFAULT_BLOCK_FILE = Path.home() / ".vibe-trading" / "MANUAL_RESET_REQUIRED.json"


def to_eastern(value: datetime) -> datetime:
    """Convert an aware timestamp to US Eastern without an external tz database."""
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    current = value.astimezone(timezone.utc)
    year = current.year

    march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
    first_sunday_march = 1 + ((6 - march_first.weekday()) % 7)
    second_sunday_march = first_sunday_march + 7
    dst_start_utc = datetime(year, 3, second_sunday_march, 7, tzinfo=timezone.utc)

    november_first = datetime(year, 11, 1, tzinfo=timezone.utc)
    first_sunday_november = 1 + ((6 - november_first.weekday()) % 7)
    dst_end_utc = datetime(year, 11, first_sunday_november, 6, tzinfo=timezone.utc)

    offset = -4 if dst_start_utc <= current < dst_end_utc else -5
    name = "EDT" if offset == -4 else "EST"
    return current.astimezone(timezone(timedelta(hours=offset), name))


class ProjectXError(RuntimeError):
    """Base adapter error."""


class ProjectXAPIError(ProjectXError):
    """Gateway request failed or returned an unsuccessful payload."""


class PracticeSafetyError(ProjectXError):
    """A practice-only safety invariant failed."""


class JsonTransport(Protocol):
    def post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]: ...


class UrllibJsonTransport:
    """Small dependency-free JSON transport with no order retry behavior."""

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    def post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Accept": "text/plain", "Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ProjectXAPIError(f"ProjectX HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProjectXAPIError(f"ProjectX network error: {exc.reason}") from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProjectXAPIError("ProjectX returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ProjectXAPIError("ProjectX returned a non-object payload")
        return result


@dataclass(frozen=True)
class PracticeExecutionConfig:
    allowed_account_id: int | None = None
    max_contracts: int = 1
    max_stop_ticks: int = 40
    max_target_ticks: int = 80
    entry_start_et: time = time(9, 45)
    entry_cutoff_et: time = time(11, 30)
    execution_confirmation: str = ""
    local_device_confirmation: str = ""
    journal_path: Path = DEFAULT_JOURNAL
    block_file: Path = DEFAULT_BLOCK_FILE

    @classmethod
    def from_env(
        cls,
        *,
        journal_path: Path = DEFAULT_JOURNAL,
        block_file: Path = DEFAULT_BLOCK_FILE,
    ) -> "PracticeExecutionConfig":
        raw_account = os.environ.get("TOPSTEPX_PRACTICE_ACCOUNT_ID", "").strip()
        account_id = int(raw_account) if raw_account.isdigit() else None
        return cls(
            allowed_account_id=account_id,
            execution_confirmation=os.environ.get("TOPSTEPX_PRACTICE_EXECUTION", "").strip(),
            local_device_confirmation=os.environ.get("TOPSTEPX_LOCAL_DEVICE", "").strip(),
            journal_path=journal_path,
            block_file=block_file,
        )


@dataclass(frozen=True)
class PracticeAccount:
    id: int
    name: str
    balance: float
    can_trade: bool
    is_visible: bool


@dataclass(frozen=True)
class ProjectXContract:
    id: str
    name: str
    description: str
    tick_size: float
    tick_value: float
    active_contract: bool
    symbol_id: str


def _require_success(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    if payload.get("success") is not True:
        raise ProjectXAPIError(
            f"{operation} failed: errorCode={payload.get('errorCode')} "
            f"errorMessage={payload.get('errorMessage')!r}"
        )
    return payload


def _finite(value: Any, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ProjectXAPIError(f"Invalid {field}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise ProjectXAPIError(f"Non-finite {field}: {value!r}")
    return parsed


def parse_accounts(payload: dict[str, Any]) -> list[PracticeAccount]:
    _require_success(payload, "account search")
    accounts: list[PracticeAccount] = []
    for row in payload.get("accounts") or []:
        if not isinstance(row, dict):
            continue
        accounts.append(
            PracticeAccount(
                id=int(row["id"]),
                name=str(row.get("name") or ""),
                balance=_finite(row.get("balance", 0.0), field="account balance"),
                can_trade=bool(row.get("canTrade")),
                is_visible=bool(row.get("isVisible")),
            )
        )
    return accounts


def select_allowed_practice_account(
    accounts: list[PracticeAccount],
    allowed_account_id: int | None,
) -> PracticeAccount:
    if allowed_account_id is None:
        raise PracticeSafetyError("TOPSTEPX_PRACTICE_ACCOUNT_ID is required")
    matches = [account for account in accounts if account.id == allowed_account_id]
    if len(matches) != 1:
        raise PracticeSafetyError("Configured practice account ID was not returned exactly once")
    account = matches[0]
    if PRACTICE_NAME_PATTERN.search(account.name.upper()) is None:
        raise PracticeSafetyError("Allowed account name does not contain the standalone PRACTICE marker")
    if not account.can_trade or not account.is_visible:
        raise PracticeSafetyError("Practice account is not active, visible, and tradeable")
    return account


def parse_contracts(payload: dict[str, Any]) -> list[ProjectXContract]:
    _require_success(payload, "contract search")
    contracts: list[ProjectXContract] = []
    for row in payload.get("contracts") or []:
        if not isinstance(row, dict):
            continue
        contracts.append(
            ProjectXContract(
                id=str(row.get("id") or ""),
                name=str(row.get("name") or ""),
                description=str(row.get("description") or ""),
                tick_size=_finite(row.get("tickSize"), field="tick size"),
                tick_value=_finite(row.get("tickValue"), field="tick value"),
                active_contract=bool(row.get("activeContract")),
                symbol_id=str(row.get("symbolId") or ""),
            )
        )
    return contracts


def select_active_mes_contract(contracts: list[ProjectXContract]) -> ProjectXContract:
    matches = [
        contract
        for contract in contracts
        if contract.active_contract
        and contract.symbol_id.upper() == "F.US.MES"
        and contract.id.upper().startswith("CON.F.US.MES.")
        and contract.name.upper().startswith("MES")
    ]
    if len(matches) != 1:
        raise PracticeSafetyError(f"Expected exactly one active MES contract, found {len(matches)}")
    contract = matches[0]
    if abs(contract.tick_size - 0.25) > 1e-9 or abs(contract.tick_value - 1.25) > 1e-9:
        raise PracticeSafetyError("MES tick specification does not match 0.25 points / $1.25")
    return contract


def _journal_has_entry(path: Path, session_date: str) -> bool:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return False
    latest_status: dict[str, str] = {}
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("session_date") != session_date:
            continue
        tag = str(row.get("custom_tag") or row.get("request", {}).get("customTag") or f"legacy-{index}")
        latest_status[tag] = str(row.get("status") or "")
    return any(status in {"submitting", "unknown", "accepted"} for status in latest_status.values())


def _append_journal(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


class TopstepXPracticeAdapter:
    def __init__(
        self,
        *,
        username: str,
        api_key: str,
        config: PracticeExecutionConfig | None = None,
        transport: JsonTransport | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.username = username.strip()
        self.api_key = api_key.strip()
        self.config = config or PracticeExecutionConfig.from_env()
        self.transport = transport or UrllibJsonTransport()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._token: str | None = None

    def _post(self, path: str, payload: dict[str, Any], *, authenticated: bool = True) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if authenticated:
            if not self._token:
                raise ProjectXAPIError("ProjectX session is not authenticated")
            headers["Authorization"] = f"Bearer {self._token}"
        return self.transport.post(f"{API_BASE_URL}{path}", payload, headers)

    def login(self) -> None:
        if not self.username or not self.api_key:
            raise ProjectXAPIError("TOPSTEPX_USERNAME and TOPSTEPX_API_KEY are required")
        response = _require_success(
            self._post(
                "/api/Auth/loginKey",
                {"userName": self.username, "apiKey": self.api_key},
                authenticated=False,
            ),
            "API-key login",
        )
        token = str(response.get("token") or "").strip()
        if not token:
            raise ProjectXAPIError("API-key login returned no session token")
        self._token = token

    def search_accounts(self) -> list[PracticeAccount]:
        return parse_accounts(
            self._post("/api/Account/search", {"onlyActiveAccounts": True})
        )

    def allowed_practice_account(self) -> PracticeAccount:
        return select_allowed_practice_account(
            self.search_accounts(),
            self.config.allowed_account_id,
        )

    def available_contracts(self) -> list[ProjectXContract]:
        return parse_contracts(self._post("/api/Contract/available", {"live": False}))

    def active_mes_contract(self) -> ProjectXContract:
        return select_active_mes_contract(self.available_contracts())

    def retrieve_bars(
        self,
        contract: ProjectXContract,
        *,
        start: datetime,
        end: datetime,
        minutes: int = 1,
        limit: int = 20_000,
    ) -> list[dict[str, Any]]:
        if contract.symbol_id.upper() != "F.US.MES":
            raise PracticeSafetyError("Historical data is restricted to MES")
        if minutes not in (1, 5, 15):
            raise ValueError("Only 1, 5, or 15 minute bars are allowed")
        if limit < 1 or limit > 20_000:
            raise ValueError("ProjectX bar limit must be between 1 and 20,000")
        response = _require_success(
            self._post(
                "/api/History/retrieveBars",
                {
                    "contractId": contract.id,
                    "live": False,
                    "startTime": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "endTime": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "unit": 2,
                    "unitNumber": minutes,
                    "limit": limit,
                    "includePartialBar": False,
                },
            ),
            "retrieve bars",
        )
        rows = response.get("bars") or []
        return [row for row in rows if isinstance(row, dict)]

    def search_open_orders(self, account: PracticeAccount) -> list[dict[str, Any]]:
        response = _require_success(
            self._post("/api/Order/searchOpen", {"accountId": account.id}),
            "open-order search",
        )
        return [row for row in response.get("orders") or [] if isinstance(row, dict)]

    def search_open_positions(self, account: PracticeAccount) -> list[dict[str, Any]]:
        response = _require_success(
            self._post("/api/Position/searchOpen", {"accountId": account.id}),
            "open-position search",
        )
        return [row for row in response.get("positions") or [] if isinstance(row, dict)]

    def _assert_execution_enabled(self, *, risk_reducing: bool = False) -> None:
        if self.config.execution_confirmation != EXECUTION_CONFIRMATION:
            raise PracticeSafetyError("Practice execution confirmation is missing")
        if self.config.local_device_confirmation != LOCAL_DEVICE_CONFIRMATION:
            raise PracticeSafetyError("Personal-device confirmation is missing")
        if self.config.block_file.exists() and not risk_reducing:
            raise PracticeSafetyError("Global manual-reset kill switch is active")

    def place_practice_bracket_order(
        self,
        *,
        side: str,
        size: int,
        stop_ticks: int,
        target_ticks: int,
        account_state: AccountState,
        rule_profile: dict[str, Any],
        custom_tag: str | None = None,
    ) -> dict[str, Any]:
        self._assert_execution_enabled()
        now = to_eastern(self.now_fn())
        if not self.config.entry_start_et <= now.time().replace(tzinfo=None) <= self.config.entry_cutoff_et:
            raise PracticeSafetyError("Entry is outside the 09:45-11:30 ET practice window")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if size < 1 or size > self.config.max_contracts:
            raise PracticeSafetyError("Practice order exceeds the one-MES size cap")
        if stop_ticks < 1 or stop_ticks > self.config.max_stop_ticks:
            raise PracticeSafetyError("Stop ticks exceed the practice risk cap")
        if target_ticks < 1 or target_ticks > self.config.max_target_ticks:
            raise PracticeSafetyError("Target ticks exceed the practice cap")
        session_date = now.date().isoformat()
        if _journal_has_entry(self.config.journal_path, session_date):
            raise PracticeSafetyError("One accepted practice entry already exists for this session")

        account = self.allowed_practice_account()
        contract = self.active_mes_contract()
        risk_dollars = stop_ticks * contract.tick_value * size
        decision = evaluate_prop_trade(
            rule_profile,
            ProposedTrade(
                symbol="MES",
                side=side,
                contracts=size,
                risk_dollars=risk_dollars,
                automated=True,
                running_on_vps=False,
            ),
            account_state,
        )
        if not decision.allowed:
            raise PracticeSafetyError(f"Prop rule gate blocked order: {','.join(decision.reasons)}")

        open_positions = self.search_open_positions(account)
        open_orders = self.search_open_orders(account)
        if open_positions or open_orders:
            raise PracticeSafetyError("Practice account must have no open position or order before entry")

        tag = custom_tag or f"mes-practice-{session_date}-{uuid4().hex[:12]}"
        payload = {
            "accountId": account.id,
            "contractId": contract.id,
            "type": 2,
            "side": 0 if side == "buy" else 1,
            "size": size,
            "customTag": tag,
            "stopLossBracket": {"ticks": stop_ticks, "type": 4},
            "takeProfitBracket": {"ticks": target_ticks, "type": 1},
        }
        attempt = {
            "recorded_at": now.isoformat(),
            "session_date": session_date,
            "custom_tag": tag,
            "status": "submitting",
            "mode": "topstep_practice_only",
            "request": payload,
        }
        _append_journal(self.config.journal_path, attempt)
        try:
            raw_response = self._post("/api/Order/place", payload)
        except ProjectXError:
            _append_journal(self.config.journal_path, {**attempt, "status": "unknown"})
            raise
        if raw_response.get("success") is not True:
            _append_journal(
                self.config.journal_path,
                {**attempt, "status": "rejected", "response": raw_response},
            )
        response = _require_success(raw_response, "place order")
        record = {
            "recorded_at": now.isoformat(),
            "session_date": session_date,
            "custom_tag": tag,
            "status": "accepted",
            "mode": "topstep_practice_only",
            "account": asdict(account),
            "contract": asdict(contract),
            "request": payload,
            "response": response,
            "risk_dollars": risk_dollars,
            "rule_gate": asdict(decision),
        }
        _append_journal(self.config.journal_path, record)
        return record

    def emergency_flatten_practice_mes(self) -> dict[str, Any]:
        """Cancel managed MES orders and close the managed MES position."""
        self._assert_execution_enabled(risk_reducing=True)
        account = self.allowed_practice_account()
        contract = self.active_mes_contract()
        open_orders = self.search_open_orders(account)
        open_positions = self.search_open_positions(account)
        mes_orders = [row for row in open_orders if str(row.get("contractId") or "") == contract.id]
        mes_positions = [row for row in open_positions if str(row.get("contractId") or "") == contract.id]
        canceled: list[int] = []
        for row in mes_orders:
            order_id = int(row["id"])
            _require_success(
                self._post("/api/Order/cancel", {"accountId": account.id, "orderId": order_id}),
                "cancel order",
            )
            canceled.append(order_id)
        closed = False
        if mes_positions:
            _require_success(
                self._post(
                    "/api/Position/closeContract",
                    {"accountId": account.id, "contractId": contract.id},
                ),
                "close MES position",
            )
            closed = True
        return {
            "mode": "topstep_practice_only",
            "account_id": account.id,
            "contract_id": contract.id,
            "canceled_order_ids": canceled,
            "position_close_requested": closed,
            "unmanaged_open_order_count": len(open_orders) - len(mes_orders),
            "unmanaged_open_position_count": len(open_positions) - len(mes_positions),
        }
