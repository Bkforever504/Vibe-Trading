# Trading Scanner Gap Audit — 2026-08-24

Status: operational safety review, not an edge claim. All scanner output remains manual-review only with `execution_enabled=false` and `can_submit_orders=false`.

## Closed in this pass

| Control | Implemented behavior | Provenance |
|---|---|---|
| Event / macro posture | Fresh `market-catalyst-calendar.json` is required in production. Explicit `stand_aside`, an active high-impact caution window, a stale report, a wrong-session report, or a missing required report cannot become a ready candidate. The same active-window flag now reaches the canonical pattern penalty. | Local read-only catalyst calendar with source and age exposed |
| Session boundaries | New entries fail closed outside RTH, during 09:30–09:35 ET, and during the last ten minutes. The official 2026 NYSE holidays and 1:00 p.m. early closes are frozen in the scanner; unsupported years fail closed. | [NYSE Holidays & Trading Hours](https://www.nyse.com/trade/hours-calendars) |
| Quote integrity | Non-positive, missing, or crossed quotes block. Locked quotes warn. Quote age, bid/ask size, and an advisory depth imbalance are exposed. IEX is explicitly labeled single-venue and not NBBO. | Alpaca IEX/SIP source label in payload |
| Completed-bar integrity | Malformed OHLC, future bars, duplicate/out-of-order timestamps, and stale primary bars block. Intraday gaps degrade the source. | Completed 5-minute Alpaca bars |
| UI / operations | Mobile dashboard shows event posture, session phase, and data integrity before setup details. The service supervisor now waits for the API and gateway ports before proceeding. | Local health checks |

## Required next data integrations

These must not be inferred from ordinary OHLC bars or an IEX quote. Until a named source is wired, they remain manual preflight checks rather than hidden assumptions.

| Gap | Why it matters | Safe policy now | Required source / next implementation |
|---|---|---|---|
| Symbol halt and LULD state | An apparently perfect level can be untradeable or reopen through the invalidation. LULD bands use a five-minute reference and operate during RTH. | A missing/stale quote blocks, but that is not proof of a halt. Verify symbol status before manual entry. | Poll the [Nasdaq current-halts/RSS feed](https://nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS) or an entitled consolidated status feed; expose halt reason and resumption time. NYSE explains [LULD and market-wide breakers](https://www.nyse.com/trade/trading-information). |
| Consolidated NBBO | IEX bid/ask is not the national best market and cannot prove executable spread or size. | Dashboard says `single_venue_iex_not_nbbo` and degrades data quality. Revalidate in the broker ticket. | Use an entitled Alpaca SIP stream and verify the entitlement at connection time. |
| SSR and stock borrow | A short setup may be subject to the alternative uptick rule or unavailable/expensive to borrow. Rule 201 is triggered after a listing-market determination of a 10% decline and persists for the rest of that day and the next. | Never describe a short equity candidate as immediately executable without broker locate/status. | Add listing-market SSR status plus Alpaca asset `borrow_status`; broker remains authoritative. [SEC Regulation SHO FAQ](https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions-8), [Alpaca borrow-status change](https://docs.alpaca.markets/us/changelog/2026-06-05-borrow-status-6b96a5a). |
| Corporate actions / symbol changes | Splits, mergers, spin-offs, and symbol changes can corrupt historical levels and returns if adjustment lineage is incomplete. | Treat suspicious discontinuities as data-quality failures; do not auto-adjust from price alone. | Add Alpaca's read-only [corporate-actions endpoint](https://docs.alpaca.markets/us/reference/corporateactions-1), cache by effective date, and version adjusted/raw series separately. |
| Complete earnings and issuer-news status | A general catalyst headline is not a complete earnings calendar or proof that news is fully disseminated. | Unknown event status cannot add grade points. Current catalyst is veto/context only. | Add point-in-time earnings dates plus SEC/issuer event timestamps; preserve revisions and first-seen time. |
| True order flow / absorption | OHLCV curvature and quote-size imbalance are not footprint, delta, queue position, or MBO absorption. | Labels already say proxy/advisory and contribute no validated probability. | Databento or another entitled trades/MBP/MBO feed, with venue and timestamp qualification. |
| Options contract execution and expiration | Underlying-chart quality does not establish contract NBBO, liquidity, Greeks, assignment style, or broker liquidation timing. 0DTE positions are highly time-sensitive and firms may liquidate positions before the close. | Equity scanner does not manufacture an options contract. Any options plan requires current contract quote and broker rules. | Contract-level NBBO, open interest/volume, Greeks timestamp, exercise style, expiration/settlement type, and explicit exit deadline. See [FINRA 0DTE risks](https://www.finra.org/investors/insights/zeroing-in-options-trading-strategy), [FINRA assignment](https://www.finra.org/investors/insights/trading-options-understanding-assignment), and the [OCC options disclosure document](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document). |
| Point-in-time universe / delistings | Changing the universe after observing outcomes creates survivorship and selection bias. | Frozen universe hashes remain mandatory for promotion evidence. | Store membership, additions/removals, and delisted names by effective date. |

## Evidence and learning gaps

1. A dashboard grade is not a win probability until the existing promotion gate has at least 100 resolved outcomes, 30 independent dates, regime minima, positive Brier skill, and multiple-testing control.
2. Review misses by taxonomy: discovery miss, ranking miss, latency miss, false positive, safety-blocked winner, and source failure. Do not change rules from one anecdote.
3. Every promoted rule needs rolling calibration and decay alerts. A failed rolling gate demotes to shadow; it does not silently loosen entry filters.
4. Compare candidates only within a versioned universe, source tier, setup family, regime, and cost model.
5. Repaired data must trigger a bounded backfill and re-grade, with the original record retained for audit.

## Priority

1. Halt/LULD + consolidated SIP/NBBO qualification.
2. Broker asset metadata for SSR/borrow/tradability.
3. Corporate-actions and point-in-time earnings ingestion.
4. Contract-level options preflight and expiration/assignment policy.
5. True order-flow ingestion only after data entitlement and timestamp-quality tests pass.

No item above authorizes orders or guarantees a winning trade. The goal is to prevent a visually strong setup from being promoted when its market, data, instrument, or evidence state is not actually tradeable.
