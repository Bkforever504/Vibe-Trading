# New Chat Handoff - Revenue Leak Score Next Steps

Date: 2026-07-18 CT

Primary handoff:

```text
C:\Users\kenne\Desktop\LeakLens_AI\NEW_CHAT_HANDOFF_2026-07-18_REVENUE_LEAK_SCORE_NEXT_STEPS.md
```

Project root:

```text
C:\Users\kenne\Desktop\LeakLens_AI
```

Website repo/static deploy folder:

```text
C:\Users\kenne\Desktop\LeakLens_AI\site
```

Live site:

```text
https://revenue-leak-score.onrender.com
```

## User Goal

Kenny loves the Revenue Leak Score site and wants the next chat to finish the steps that turn it into a real sales machine:

1. deploy latest local site improvement
2. finish Zapier/Stripe revenue routing
3. run a full fake-client acceptance test
4. create the two missing email templates
5. start outreach with confidence

This is the highest-priority non-trading cash-flow project right now.

## Current Website State

Site repo status at handoff time:

```powershell
git -C 'C:\Users\kenne\Desktop\LeakLens_AI\site' status --short
```

Expected:

```text
 M index.html
```

Latest commit:

```text
68c2b2e Send form leads to Zapier
```

Local `site\index.html` has one intentional, browser-tested improvement not yet committed/deployed:

- Added Monitoring Plus (`$299/mo`) to schema, pricing card, and FAQ.
- Added a hero hot-buyer link straight to the `$299` Full Audit Stripe checkout.
- Reframed the Google Business Profile copy so "last Google review was 94 days ago" is clearly an example, not fake-specific copy.

## Browser QA Already Completed

Local Chromium QA passed:

- responsive layout at `360x740`, `390x844`, `768x1024`, `1280x720`, `1440x900`
- no horizontal overflow
- no visible mojibake
- hero CTA visible
- new `$299` hot-buyer link visible
- Monitoring Plus link visible
- mocked Formspree/Zapier success path passed without sending a duplicate live lead
- Stripe links open in new tabs with `rel="noopener"`
- no console errors from the browser smoke test

Screenshots:

```text
C:\Users\kenne\Desktop\LeakLens_AI\output\playwright\rls-1280.png
C:\Users\kenne\Desktop\LeakLens_AI\output\playwright\rls-1440.png
C:\Users\kenne\Desktop\LeakLens_AI\output\playwright\rls-360.png
C:\Users\kenne\Desktop\LeakLens_AI\output\playwright\rls-390.png
```

## Current Money Links

```text
Full Revenue Leak Audit ($299):
https://buy.stripe.com/28E4gBfFJ1ekaQx6NEdIA0o

Monthly Monitoring ($199/mo):
https://buy.stripe.com/4gM6oJctxcX26Ah2xodIA0p

Monitoring Plus ($299/mo):
https://buy.stripe.com/5kQ6oJ3X17CI3o5goedIA0q
```

## Current Automation State

Read:

```text
C:\Users\kenne\Desktop\LeakLens_AI\ZAPIER_LIVE_SETUP_STATUS.md
C:\Users\kenne\Desktop\LeakLens_AI\REVENUE_OPS_COMPLETION_CHECKLIST.md
```

Known live endpoints:

```text
Formspree endpoint:
https://formspree.io/f/xdarnzna

Zapier lead hook:
https://hooks.zapier.com/hooks/catch/28010576/42ocirc/

Zapier Stripe checkout hook:
https://hooks.zapier.com/hooks/catch/28010576/42oc7u6/

Zapier Tables CRM:
Table title: REVENUE_LEAK_SCORE_CRM_TEMPLATE
Table ID: 01KVMCJVC4C7M2NV3WB25NTQE2
```

Already completed:

- Free scan lead intake Zap is live/tested.
- Site sends lead data to Zapier after Formspree success.
- Stripe checkout completed hook is live/tested.
- Stripe event: `checkout.session.completed`.

Still open:

- Stripe/Zapier offer-specific routing.
- Failed payment/cancellation handling is only documented for now.

## P0 Next Work Queue

1. Commit and deploy latest site change.

Suggested commit message:

```text
Expose Monitoring Plus and hot audit checkout
```

2. Build Zapier Paths in the Zapier UI.

Path A - Full Audit:

```text
Filter: mode = payment AND amount_total = 29900
Find/update CRM row by email.
Set status = Paid Audit Purchased.
Create task/notification: Deliver Full Audit - due 48h.
```

Path B - Monitoring:

```text
Filter: mode = subscription AND amount_total = 19900
Find/update CRM row by email.
Set status = Monitoring Active.
Create onboarding task due 48h.
Create recurring monthly monitoring task.
```

Path C - Monitoring Plus:

```text
Filter: mode = subscription AND amount_total = 29900
Find/update CRM row by email.
Set status = Monitoring Active Plus.
Create onboarding task due 48h.
Create recurring monthly monitoring task.
```

Important: Path A and Path C both use `amount_total = 29900`; disambiguate with `mode = payment` vs `mode = subscription`. Always dedupe by email.

3. Write two missing email templates:

```text
C:\Users\kenne\Desktop\LeakLens_AI\PAID_AUDIT_CONFIRMATION_EMAIL.md
C:\Users\kenne\Desktop\LeakLens_AI\MONITORING_ONBOARDING_EMAIL.md
```

4. Run full fake-client acceptance test:

```powershell
python tools\scan_leaklens.py --business "Test HVAC Co" --city "Dallas, TX" --url "https://example.com" --category "HVAC" --output-dir reports\clients\test-hvac-co --html
```

Then confirm CRM row, report outputs, Stripe test payment/subscription routing, and task creation.

## Scan Tool State

Tool:

```text
C:\Users\kenne\Desktop\LeakLens_AI\tools\scan_leaklens.py
```

Tests:

```text
C:\Users\kenne\Desktop\LeakLens_AI\tools\test_scan_leaklens.py
```

Latest completed upgrades:

- `--output-dir`
- `--payment-link`
- default real `$299` Stripe checkout link
- `--avg-ticket`
- `--close-rate`
- `--html`
- HTML template `$299` CTA fixed
- 7 offline tests passed

Use this for real client scans:

```powershell
python tools\scan_leaklens.py --business "Name" --city "City, ST" --url "site.com" --category "HVAC" --output-dir reports\clients\<business-slug> --html
```

Never write real client scans to `reports\samples`.

## Guardrails

- No fake testimonials.
- No fake customer logos.
- No unsupported revenue guarantees.
- Keep "public data only".
- Keep "no sales call".
- Keep manual QA before sending.
- Use estimated ranges only.
- Do not build a full SaaS yet.
- Do not publish root project docs to the static website repo.
- Do not break Formspree, Zapier, Stripe, Plausible, or email fallback.

## Recommended Opening Prompt

```text
Read C:\Users\kenne\Desktop\LeakLens_AI\NEW_CHAT_HANDOFF_2026-07-18_REVENUE_LEAK_SCORE_NEXT_STEPS.md and continue from that exact state. First deploy the latest site index.html change if not deployed, then finish the Zapier/Stripe routing plan, write the two missing email templates, and run the full fake-client acceptance test. Do not redesign the site unless a QA failure requires it.
```
