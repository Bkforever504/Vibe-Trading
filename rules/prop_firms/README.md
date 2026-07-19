# Prop Firm Rule Profiles

These JSON profiles are used by `strategies/prop_rule_gate.py`.

The rule gate is conservative by design:

- If automation is prohibited, automated trades are blocked.
- If a required rule is missing and `unknown_rules_block` is true, trades are blocked.
- If a trade would break max daily loss, trailing drawdown, max contracts, VPS/local-device, or consistency constraints, it is blocked.
- A high confidence score means the gate has enough rule data to make a conservative allow/block decision. It does not mean the trading strategy has proven edge.

## Profiles

- `topstep_topstepx_api.json`
  - Allows automation with conditions.
  - Blocks VPS/remote-server execution.
  - Uses conservative placeholder loss/contract/consistency caps until the exact selected account is confirmed.

- `apex_conservative.json`
  - Blocks automated trading until current official rules are verified.

- `tradeify_conservative.json`
  - Blocks automated trading until current official rules are verified.

## Before Prop/Live Use

1. Choose the exact firm and account type.
2. Verify the current official rules.
3. Replace placeholder caps with exact account numbers.
4. Run `agent/tests/test_strategy_safety_layers.py`.
5. Keep the bot in shadow mode until the strategy has enough trade evidence.

