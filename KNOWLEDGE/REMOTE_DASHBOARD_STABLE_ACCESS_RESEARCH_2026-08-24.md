# Stable Phone Access for the Trading Dashboard

Date: 2026-08-24
Scope: replace the rotating Cloudflare Quick Tunnel URL; research only, no installation or runtime changes

## Recommendation

Use **Tailscale Serve as the primary path** for Kenny's private phone access.
It is the lowest-friction secure fit for one trusted operator: it needs no
custom domain, exposes the dashboard only inside Kenny's tailnet, gives the
Windows host a stable MagicDNS name, and automatically serves HTTPS. Keep the
existing loopback-only, read-only gateway on `127.0.0.1:8898` as a second auth
boundary.

Use a **Cloudflare named tunnel plus Cloudflare Access** only if access must
work from an ordinary browser without enabling Tailscale on the phone, or if
the dashboard will be shared with additional people. This option gives a
stable public hostname, but requires a domain in Cloudflare and more one-time
security configuration.

Do not treat the current Quick Tunnel as durable. Cloudflare says Quick
Tunnels generate random `trycloudflare.com` subdomains and are intended for
testing and development; it recommends a remotely managed tunnel for
production use. [Cloudflare: Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)

## Decision table

| Question | Tailscale Serve | Cloudflare named tunnel + Access |
|---|---|---|
| Best use here | Private access for Kenny's approved devices | Clientless browser access or controlled sharing |
| Phone requirement | Tailscale app connected to the same tailnet | Safari/Chrome plus Access login; no phone agent for a public-hostname app |
| Custom domain required | **No.** Tailscale supplies `<machine>.<tailnet>.ts.net`. | **Yes.** A public self-hosted Access app requires an active domain/zone in Cloudflare. |
| Stable URL | Stable while the machine name and tailnet DNS name remain unchanged | Chosen hostname remains pointed at the persistent tunnel UUID; connector restarts do not create a new random hostname |
| Public Internet exposure | No; Serve is available only inside the tailnet | Public DNS/Cloudflare edge is reachable, but Access should deny unauthorized users before origin traffic |
| Existing dashboard token | Keep it as defense in depth | Keep it as defense in depth unless a separately reviewed change replaces it |
| Operational burden | Two client installs, one login per device, one persistent Serve rule | Domain/DNS, tunnel service/token, Access application, identity policy, and session management |

The Tailscale URL follows from MagicDNS and HTTPS: Tailscale automatically
registers machine names, assigns stable device connectivity even across network
changes, and issues HTTPS names under the tailnet's `*.ts.net` domain.
[Tailscale: connect to devices](https://tailscale.com/kb/1452/connect-to-devices),
[MagicDNS](https://tailscale.com/docs/features/magicdns), and
[HTTPS certificates](https://tailscale.com/docs/how-to/set-up-https-certificates).
Changing the machine name changes its MagicDNS URL, and switching the tailnet
DNS name may break links, so both names must be treated as configuration.
[Tailscale: machine names](https://tailscale.com/kb/1098/machine-names) and
[tailnet names](https://tailscale.com/docs/concepts/tailnet-name).

The Cloudflare stability statement is an inference from its documented model:
a named tunnel is a persistent object with a UUID, and DNS continues to point
to that UUID while connectors or replicas change. Unlike a Quick Tunnel, it
does not mint a new random hostname at each start.
[Cloudflare: Tunnel overview](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
and [useful tunnel terms](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/tunnel-useful-terms/).

## Option A — Tailscale Serve (recommended)

### One-time user actions

1. Create or sign into one Tailscale tailnet with Kenny's existing SSO
   identity.
2. Install Tailscale on the Windows dashboard host and sign in. The official
   Windows flow is installer → system-tray app → browser/SSO login.
   [Tailscale: install on Windows](https://tailscale.com/docs/install/windows)
3. Install Tailscale on the iPhone, accept the iOS VPN configuration, and sign
   into the same identity/tailnet. iOS 15 or later is supported.
   [Tailscale: install on iOS](https://tailscale.com/docs/install/ios)
4. In the admin console, enable **device approval**, approve only the Windows
   host and Kenny's phone, and remove old/unrecognized devices. An unapproved
   device cannot send or receive tailnet traffic.
   [Tailscale: device approval](https://tailscale.com/docs/features/access-control/device-management/device-approval)
5. Give the Windows host a deliberate nonsensitive machine name such as
   `vibe-dashboard` and disable automatic regeneration from the OS hostname.
   This fixes the MagicDNS portion of the URL.
6. Confirm MagicDNS is enabled, then enable HTTPS certificates. HTTPS publishes
   the machine and tailnet DNS names to public Certificate Transparency logs,
   so the chosen machine name must not contain personal or secret information.
   [Tailscale: enabling HTTPS](https://tailscale.com/docs/how-to/set-up-https-certificates)
7. On the Windows host, configure persistent Serve proxying to the existing
   gateway, conceptually:

   ```powershell
   tailscale serve --bg 8898
   ```

   Verify the displayed target is `http://127.0.0.1:8898`, not a LAN address.
   Tailscale documents that Serve reverse-proxies localhost services, uses
   automatically provisioned HTTPS, and that `--bg` configuration resumes
   after Tailscale or the machine restarts.
   [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) and
   [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve)
8. Enable Tailscale **Run unattended** on Windows if the dashboard must remain
   reachable after reboot while no Windows user is signed in. Tailscale notes
   that the normal Windows mode disconnects when the current user logs out.
   [Tailscale: run unattended](https://tailscale.com/docs/how-to/run-unattended)
9. On the connected phone, open the exact URL printed by Serve, complete the
   existing dashboard token pairing once, then bookmark the **clean URL without
   `?token=`**. Never store the token-bearing pairing link in a shared bookmark,
   screenshot, note, or message.
10. Replace the tailnet's broad default access with a least-privilege grant that
   permits only Kenny's identity/device to reach the dashboard host on HTTPS.
   Tailscale recommends grants for new policies and documents them as
   deny-by-default/least-privilege controls.
   [Tailscale: grants](https://tailscale.com/docs/features/access-control/grants)

### Security and availability tradeoffs

- Tailscale's data plane uses WireGuard end-to-end encryption; the coordination
  service manages identities, keys, and policy but does not carry plaintext
  application traffic. [Tailscale: control and data planes](https://tailscale.com/kb/1508/control-data-planes)
- Serve obeys tailnet access policy and is private; do **not** use Tailscale
  Funnel, which is the public-sharing product.
- The phone must have the Tailscale VPN connected. This is the main convenience
  cost compared with browser-only Cloudflare Access.
- The Windows host, local backend/gateway, and Tailscale service must remain
  running. `--bg` preserves Serve configuration across restart, but it does not
  make an offline PC available.
- HTTPS Certificate Transparency exposes the nonsensitive machine FQDN, not
  the private service itself. Tailnet access restrictions still apply.
- Keep `remote_dashboard_gateway.py`: Tailscale authenticates the device/user
  and network path, while the gateway preserves GET-only routing and the
  existing application token. The gateway's current 24-hour cookie may still
  require periodic re-pairing; stable transport does not change that behavior.

## Option B — Cloudflare named tunnel with Access

### One-time user actions

1. Add an owned domain to Cloudflare as an active DNS zone. Cloudflare requires
   an active domain for a public self-hosted Access application and for the
   tunnel's published application hostname.
   [Cloudflare: publish a self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
2. **Before publishing the tunnel route**, create a Cloudflare Access
   self-hosted application for a hostname such as
   `dashboard.example.com`. Configure a deny-by-default Allow policy restricted
   to Kenny's exact identity/email, select the identity provider, set a
   reasonable session duration, and enable independent MFA if available.
   Cloudflare warns that a published application without Access is available
   to anyone on the Internet.
3. For the least setup friction, either use the default Cloudflare identity
   provider or explicitly enable email OTP and allow only Kenny's exact email.
   Do not create an unrestricted OTP Include rule. OTP codes are single-use
   and expire after ten minutes.
   [Cloudflare: One-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)
   and [common Access policies](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/common-policies/)
4. In Cloudflare Zero Trust, create a **remotely managed named tunnel**, choose
   Windows, and run the dashboard-provided connector installation command on
   the host. Store the tunnel token as a secret: anyone holding it can run that
   tunnel. [Cloudflare: create a tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
   and [tunnel tokens](https://developers.cloudflare.com/tunnel/advanced/tunnel-tokens/)
5. Add the published application route
   `dashboard.example.com` → `http://localhost:8898`, enable **Protect with
   Access** so the connector validates the Access token, and verify the tunnel
   is Healthy. The hostname becomes the durable bookmark.
6. Install/run `cloudflared` as a Windows service so connector restarts and
   host reboots do not require manually launching a tunnel.
   [Cloudflare: Windows service](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/windows/)
7. On the phone, browse to the stable hostname, authenticate through Access,
   complete the existing gateway-token pairing, and bookmark the clean URL.

### Security and availability tradeoffs

- Cloudflare Tunnel uses outbound-only connections, so the host needs no public
  inbound port. Cloudflare recommends blocking ingress and permitting only the
  connector's required egress; only configured tunnel services are exposed.
  [Cloudflare: tunnel with firewall](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/)
- The browser path is easier on a phone because no VPN client is required, but
  the hostname is public and Cloudflare becomes the TLS/identity enforcement
  point. Access must exist before the route, use a narrow Allow policy, and
  validate its token.
- Tunnel connections are encrypted, but a public Access deployment trusts
  Cloudflare's edge to authenticate and proxy application traffic. Tailscale's
  private peer data plane has the smaller exposure surface for this single-user
  dashboard.
- Protect the remotely managed tunnel token. Rotation requires reinstalling
  connectors with the new token.
- A custom domain, Cloudflare account/zone health, Access configuration, DNS,
  connector service, Windows host, and local gateway all become availability
  dependencies.

## Migration boundary

The transport should change without weakening the application boundary:

- keep the gateway bound to `127.0.0.1:8898`;
- retain its GET-only route allowlist and rejection of POST/PUT/PATCH/DELETE;
- retain the backend API-key file and dashboard token file outside the repo;
- never place either secret in tunnel configuration, DNS, logs, screenshots,
  or the permanent bookmark;
- run authenticated phone probes before retiring the Quick Tunnel supervisor;
- keep the Quick Tunnel disabled after cutover so there is only one intended
  remote ingress path.

No custom domain purchase or Cloudflare migration is warranted if Kenny is the
only phone user and is willing to keep Tailscale connected. Under that stated
use case, Tailscale Serve is the recommended stable replacement.
