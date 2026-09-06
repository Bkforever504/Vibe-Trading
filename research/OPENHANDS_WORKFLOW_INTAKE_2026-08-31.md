# OpenHands workflow intake — 2026-08-31

## Decision

**Verdict: sandbox-only pilot.** Do not adopt OpenHands as a runtime, scheduler, or credential-bearing component of Vibe-Trading. It is potentially useful as a separately operated engineering/research workbench for bounded, human-reviewed tasks. Its value is agent orchestration and a browser control plane, not a trading safety boundary.

The repository supplied for review is now primarily **Agent Canvas**: a browser control center that can launch OpenHands, Codex, Claude Code, Gemini, and other ACP-compatible agents. Agent execution, tools, workspaces, and conversation state reside in the separate Software Agent SDK/Agent Server; automation scheduling is another component. The actual privilege boundary is therefore the selected workspace/sandbox and its mounts, credentials, and network policy—not Canvas itself. [OpenHands README](https://github.com/OpenHands/OpenHands#architecture) [Architecture guide](https://docs.openhands.dev/openhands/usage/agent-canvas/architecture)

## Practical fit for Vibe-Trading

Appropriate pilot work:

- Static analysis and test-generation against a **sanitized, disposable clone**.
- Independent code review of proposed scanner/backtest changes.
- Reproducible research note drafting from non-sensitive public inputs already placed in the sandbox.
- Dependency or documentation audits which produce a patch/report for a human to review outside the sandbox.

Potential benefits are real: Canvas centralizes multiple agent backends, supports conversations and scheduled/event-based workflows, and may run locally, in containers, VMs, or managed infrastructure. The SDK also exposes per-call tokens, cost, latency, and aggregate conversation statistics—useful for a measured experiment rather than an open-ended agent spend. [OpenHands README](https://github.com/OpenHands/OpenHands#agent-canvas) [Metrics tracking](https://docs.openhands.dev/sdk/guides/metrics)

It is *not* appropriate for signal generation, market-data collection with paid credentials, paper/live execution, broker administration, account reconciliation, or unattended trading research. Those jobs combine external instructions, code execution, market/broker access, and valuable credentials; adding an agent control plane increases the blast radius without providing a necessary trading control.

## Permission and sandbox assessment

| Deployment choice | Assessment | Vibe-Trading policy |
| --- | --- | --- |
| Host/process mode | The agent runs as a normal host process with the user account's file and command privileges; OpenHands says it has no container isolation. | **Prohibited.** |
| Docker sandbox | Recommended by OpenHands locally; improves isolation/reproducibility, but every read-write mount can still be changed by the agent. | **Required for pilot**, with one dedicated, disposable workspace mount only. |
| Remote VM / cloud | Adds always-on operation and management/security burden. The VM host can read/write its filesystem, execute commands, use the network, and store secrets. | **Out of scope for pilot.** Reconsider only after a formal design review. |
| Canvas connected to another agent (ACP) | Canvas is only a client; the remote agent/server and workspace set privileges. | Do not assume Canvas changes Codex/Claude Code permissions; approve the backend separately. |

The official Docker guide explicitly says that anything mounted read-write into `/workspace` can be modified. The process guide explicitly says the agent may read/write all files accessible to the user and run host commands. [Docker sandbox guide](https://docs.openhands.dev/openhands/usage/sandboxes/docker) [Process sandbox guide](https://docs.openhands.dev/openhands/usage/sandboxes/process)

### Required pilot controls

1. Create a fresh Docker sandbox from a pinned image digest with a non-root, unprivileged user. Mount only a scrubbed clone under one purpose-specific workspace path; no Docker socket, host SSH agent, home directory, cloud metadata endpoint, or parent workspace mount.
2. Make the clone read-only for report-only tasks. If testing an edit task, use a short-lived copy and collect a patch/diff; never let it write to the actual working tree.
3. Apply egress deny-by-default. If a model API is required, permit only the specific provider hostname through an authenticated proxy; do not permit broker, exchange, data-vendor, email, cloud-control-plane, GitHub write, or general internet access.
4. Start with `AlwaysConfirm` for **every** action. OpenHands has risk-based and deterministic analyzers, but its own guidance notes that model-based analysis can be manipulated and encoding can hide dangerous commands; analyzer output is not a substitute for a restrictive runtime. [Security and action confirmation](https://docs.openhands.dev/sdk/guides/security)
5. No MCP servers, plugins, browser automation, webhooks, scheduled automations, or remote backend during the first pilot. Each introduces an additional tool/identity/data path and must be separately allowlisted and threat-modeled.
6. Delete the container, workspace copy, conversations, and cached credentials after each trial; retain only reviewed findings/patches in the normal repository process.

## Credentials and broker safety

**Do not give OpenHands any brokerage, exchange, payment, market-data, database, GitHub-write, cloud-admin, SSH, Windows credential-manager, or user-session credentials.** Do not mount `.env` files, `.git` credentials, browser profiles, credential-broker sockets, AWS/GCP/Azure configuration, or the existing Vibe-Trading secrets locations.

OpenHands has useful protections but they do not make a secret safe from the process that receives it. Its Secret Registry can inject values as environment variables and mask values in command output; the Canvas secret manager likewise automatically exports custom secrets into the agent runtime. An agent that can execute a process with a secret can often send it over an allowed network path or use it for an action. Treat secret masking as an accidental-disclosure control, not a capability boundary. [Secret Registry](https://docs.openhands.dev/sdk/guides/secrets) [Canvas secrets management](https://docs.openhands.dev/openhands/usage/settings/secrets-settings)

ChatGPT subscription authentication has a separate concern: the SDK can launch OAuth, cache credentials locally in `~/.openhands/auth/`, and refresh them automatically. Do not use subscription login in the pilot. Use a newly created, spend-capped API key scoped to the pilot environment, or a provider proxy with an enforced budget, then revoke it after the experiment. [LLM subscriptions](https://docs.openhands.dev/sdk/guides/llm-subscriptions)

## Model providers, cost, and data handling

OpenHands uses LiteLLM and therefore accepts many model providers; it recommends using a powerful model for strong performance but warns that it issues many prompts and most models cost money. Local/open-weight models can reduce external data transmission but may have weaker/reliability-variable tool use. [LLM overview](https://docs.openhands.dev/openhands/usage/llms/llms)

For the pilot, use exactly one provider chosen by the owner, with a fresh API key, provider-side hard spend cap, low per-run token cap, low time cap, and a daily budget that is intentionally small. Record per-run input/output tokens, tool calls, runtime, cost, failure mode, and whether the output was accepted. The SDK exposes these metrics, but it is still necessary to set an external provider cap because metrics are reporting, not a spend-control guarantee. [Metrics tracking](https://docs.openhands.dev/sdk/guides/metrics)

Never send proprietary strategy logic, historical private research, account identifiers, execution logs containing broker order IDs, or raw credential-bearing configuration to a third-party model endpoint during the pilot. A local model is only eligible after its host, weights, telemetry, and sandbox are reviewed; it is not automatically safer merely because it is local.

## Deployment view

Do **not** deploy an always-on public Canvas/Agent Server for Vibe-Trading. OpenHands' VM guidance says such a host is trusted infrastructure because it can store secrets and execute/network on the host; it recommends a strong backend key, network access control, and HTTPS before exposure. It also recommends limiting SSH and protecting the VM filesystem because it contains settings, secrets, conversations, and working copies. [VM/self-hosting guide](https://docs.openhands.dev/openhands/usage/agent-canvas/backend-setup/vm)

The smallest pilot is local-only Docker, accessed only on loopback, with no scheduled workload. A later internal service could be considered only after the pilot passes, with a dedicated VM, VPN/identity-aware access, TLS, firewall, patching, distinct service account, central logs, rotation procedure, and a documented incident/revocation playbook. Public URLs, ngrok, shared backends, and Kubernetes are not justified by the first use case.

## Smallest safe pilot

**Objective:** compare one OpenHands-assisted, read-only code/research review with the current workflow; it must not modify a real repository or access an external operational system.

**Input:** a fresh scrubbed copy of one non-production module plus a deliberately non-sensitive fixture/test data set. Remove secrets, private endpoints, account identifiers, and `.git` auth material.

**Agent configuration:** Docker-only; one workspace; no shell privilege escalation; no browser; no MCP; no automations; no ingress beyond localhost; explicit `AlwaysConfirm`; deterministic policy rails enabled; fresh capped provider credential; explicit time/token ceiling.

**Task:** “Review these supplied files for reproducibility/test gaps and write `REVIEW.md`; do not modify source, access the network, or execute commands other than the listed test command after approval.” A human pre-approves only file reads and a fixed test command, then manually exports the report. No patch application in the pilot.

**Success gate (three runs maximum):** outputs are useful, reproducible, cost is within a pre-set budget, and no unexpected action/network/secret exposure occurs. Any unexpected privilege request, attempted network access, secret discovery, policy bypass, or unbounded spend is an immediate stop and remediation event—not a prompt-tuning issue.

## Hard no-go boundaries

- Host/process runtime, `--mount-cwd` against the actual Vibe-Trading repository, or any mount of the user profile/home.
- Broker/exchange/trading API credentials, live market-data credentials, API session cookies, private keys, OAuth refresh tokens, credential-manager access, SSH agent/socket, or Docker socket.
- Automated trade decisions, execution, account changes, withdrawals, order cancellation/replacement, or recurring market/broker jobs.
- General egress, browser-based login to sensitive services, arbitrary MCP servers/plugins, writable GitHub credentials, or event/webhook automation.
- Public/remote Canvas before a separate infrastructure/security design is approved.

## Bottom line

OpenHands is worth a **contained experiment** as a multi-agent engineering control surface, especially if the team wants an independently operated review/research lane. It should not be interposed into the existing live or shadow trading pipeline. Keep it disposable, offline from operational systems, manually confirmed, and evaluated on measurable quality/cost before expanding scope.

