# CatDesk Integration Evaluation

Date: 2026-08-27
Repository reviewed: `Xeift/CatDesk` at release `v0.4.0` / commit `00717ff84a9b23c962c74d7021ccc450c92c5356`
Decision: **do not integrate CatDesk into the Vibe-Trading production stack.**

## Executive assessment

CatDesk is a general-purpose bridge that gives ChatGPT Web local file, shell, background-process, and optional browser-control tools. Its own description calls it a stripped-down Codex and explicitly says it lacks cron and other active utilities. It is not a market-data feed, scanner, ranking engine, alert router, trading dashboard, or durable automation service. [README: purpose and architecture](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#how-does-this-work)

Accordingly, CatDesk would not close the current gaps in mover coverage, signal ranking, outcome grading, scanner health, or execution readiness. It would duplicate development capabilities already available through Codex while introducing a public remote-control boundary around the Windows trading host.

## Fit with Vibe-Trading

| Area | Material benefit | Assessment |
| --- | --- | --- |
| Market data | None | No feed adapter, exchange schema, historical data store, or market-data entitlement support is present. The declared stack is a coding-agent/MCP stack. [README: stack](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#stack) |
| Ranking | None | CatDesk supplies file and command tools, not candidate features, regime logic, cross-sectional ranking, or trade-outcome evaluation. [README: tools](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#tools) |
| Alerting | None | There is no trading alert dispatcher, escalation policy, deduplication contract, or delivery integration. |
| Observability | Low, concept-only | Bounded command output, job state, polling/cancellation, request logs, and a tool-call widget could inspire developer telemetry, but they do not measure feed freshness, missed intervals, signal coverage, grading latency, or scheduler truth. [background-job implementation](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/src/command_jobs.rs) |
| Desktop UI | Low | The Ratatui interface and HTML/JavaScript widget show MCP activity and estimated token usage, not prices, ranked opportunities, health gates, or resolved outcomes. The README also warns of severe lag after 50+ tool calls. [README: performance note](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#quickstart) |
| Automation | None for production | Background commands are interactive job helpers. CatDesk describes itself as lacking cron and active utilities, so it cannot replace Task Scheduler, heartbeat, watchdog, or recovery logic. [README](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#how-does-this-work) |
| Browser research | Limited | Optional Chromium control could assist isolated manual research, but provides no deterministic market-data or scoring advantage and expands access to authenticated browser sessions. |

## Security and operational risks

1. **Critical remote-access exposure.** Setup specifies connector authentication as `None`; a persistent random URL path is the effective bearer secret. The maintainer states that anyone with the MCP URL can access the computer. [README: connector setup](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#quickstart), [README: safety](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#safety)

2. **Critical Windows confinement gap.** Native file-tool targets are canonicalized and rejected outside the workspace, which is a useful safeguard. [path resolution](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/src/command.rs#L71-L123) However, on Windows the shell runner discards `workspace_root` and passes the requested command directly to `powershell.exe` with `-ExecutionPolicy Bypass`; setting the current directory does not restrict absolute filesystem or network access. This means shell tools can escape the workspace even though native file tools cannot. [Windows process runner](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/src/process_runner.rs#L335-L351), [command dispatch](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/src/mcp.rs#L1406-L1459)

3. **Platform security is uneven.** Version 0.4.0 added Linux Landlock confinement and requires it to be fully enforced, but the equivalent Windows path uses process-management controls rather than a filesystem/network sandbox. [Linux sandbox](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/src/linux_sandbox.rs#L155-L201), [v0.4.0 release](https://github.com/Xeift/CatDesk/releases/tag/v0.4.0)

4. **Browser-session blast radius.** Enabling browser mode launches a DevTools bridge capable of controlling Chromium. On a trading workstation this can expose logged-in data, broker, email, and other browser sessions if the connector or agent is compromised. [README: browser control](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#who-needs-this)

5. **Credentials and endpoint persist locally.** The ngrok authtoken, static domain, and secret path are stored in `~/.catdesk/config.toml`; explicit directory/file permission hardening is compiled only on Unix, not Windows. [config persistence](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/src/state.rs#L293-L322), [saved ngrok token](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/src/state.rs#L610-L640)

6. **High-authority defaults increase impact.** The README recommends `Allow all actions` for smoother use and warns that the tool can wipe a disk; it strongly recommends VM/container isolation. That operating model is incompatible with a host carrying live trading credentials and autonomous tasks. [README: caution and permissions](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#quickstart)

7. **Supply-chain controls are helpful but incomplete.** The npm postinstall downloads a native executable and verifies it against `SHA256SUMS`; release CI builds with a locked Cargo graph and publishes checksums. This catches transfer corruption, but the binary and checksum share the same GitHub release trust domain, and GitHub Actions are referenced by mutable major-version tags rather than commit hashes. [npm installer](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/npm/postinstall.js#L36-L95), [release workflow](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/.github/workflows/release.yml)

## Maintenance and licensing

CatDesk is active but young and pre-1.0: public releases moved from `v0.2.0` on August 22 to `v0.3.0` on August 23 and `v0.4.0` on August 27, 2026. Rapid iteration is encouraging for a developer utility but represents high interface and operational churn for a production dependency. The maintainer also explicitly describes some features as buggy and recommends isolation. [release history](https://github.com/Xeift/CatDesk/releases), [README disclaimer](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/README.md#disclaimer)

The project is MIT-licensed, so concepts or code could be reused with the required copyright/license notice; the license also disclaims warranty. [LICENSE](https://github.com/Xeift/CatDesk/blob/00717ff84a9b23c962c74d7021ccc450c92c5356/LICENSE)

## Recommendation

- **Production/live stack:** reject. Do not connect CatDesk to the scanner workspace, Task Scheduler, market-data credentials, Discord secrets, broker environment, dashboard host, or execution host.
- **Architecture reuse:** do not add the dependency. If useful, independently borrow only generic ideas such as bounded background-job output and explicit poll/cancel state; Vibe-Trading's trading-specific heartbeat and scorecard remain the correct control plane.
- **Optional experiment:** only if a separate need arises after Codex quota exhaustion, evaluate CatDesk as a non-production coding convenience inside a disposable VM with a copy of non-secret source, no authenticated browser profile, read-only or tightly restricted permissions, and no route to trading services. This would improve developer access, not trading performance.

No installation was performed and no Vibe-Trading application code was changed.
