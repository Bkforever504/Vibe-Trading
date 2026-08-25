"""Authenticated, read-only gateway for the trading cockpit.

This service is intentionally narrower than the main API. It serves the built
frontend and proxies only trading-dashboard GET routes to the loopback API.
All mutation, agent, session, and live-control routes remain inaccessible.
"""

from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import Request, urlopen


COOKIE_NAME = "vibe_remote_dashboard"
ALLOWED_API_PREFIX = "/trading/dashboard/sources/"
OPPORTUNITY_STREAM_PATH = "/trading/opportunities/stream"
ALLOWED_API_PATHS = {
    "/trading/dashboard",
    "/trading/quotes",
    "/trading/bars",
    "/trading/opportunities",
    "/trading/feed-status",
    OPPORTUNITY_STREAM_PATH,
}


class DashboardHTTPServer(ThreadingHTTPServer):
    """Threaded gateway sized for browsers that burst-load ESM chunks."""

    request_queue_size = 128
    daemon_threads = True


def _is_allowed_api_path(path: str) -> bool:
    return path in ALLOWED_API_PATHS or path.startswith(ALLOWED_API_PREFIX)


def _trusted_tailscale_identity(
    headers: Mapping[str, str], client_address: tuple[str, int], *, enabled: bool
) -> bool:
    """Trust Serve identity only through this explicitly enabled loopback seam.

    Tailscale Serve strips spoofed identity headers before adding its own. The
    loopback and ts.net checks prevent this opt-in from becoming a general
    header-based bypass if the gateway is ever rebound to another interface.
    """
    if not enabled or client_address[0] not in {"127.0.0.1", "::1"}:
        return False
    host = str(headers.get("Host") or "").split(":", 1)[0].rstrip(".").lower()
    identity = str(headers.get("Tailscale-User-Login") or "").strip()
    return bool(identity) and host.endswith(".ts.net")


class GatewayConfig:
    def __init__(self, *, frontend: Path, backend: str, api_key_file: Path, token: str, trust_tailscale_identity: bool = False) -> None:
        self.frontend = frontend.resolve()
        self.backend = backend.rstrip("/")
        self.api_key_file = api_key_file.resolve()
        self.token = token
        self.trust_tailscale_identity = trust_tailscale_identity

    def api_key(self) -> str:
        return self.api_key_file.read_text(encoding="ascii").strip()


class ReadOnlyDashboardHandler(BaseHTTPRequestHandler):
    server_version = "VibeReadOnlyDashboard/1.0"
    config: GatewayConfig

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, payload: object) -> None:
        self._send_bytes(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _cookie_token(self) -> str:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else ""

    def _authorized(self) -> bool:
        supplied = self._cookie_token()
        cookie_authorized = bool(supplied) and hmac.compare_digest(supplied, self.config.token)
        return cookie_authorized or _trusted_tailscale_identity(
            self.headers,
            self.client_address,
            enabled=self.config.trust_tailscale_identity,
        )

    def _pair_or_reject(self, parsed) -> bool:
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        if query_token and hmac.compare_digest(query_token, self.config.token):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", parsed.path or "/")
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={self.config.token}; Path=/; Max-Age=86400; HttpOnly; Secure; SameSite=Lax",
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return True
        if self._authorized():
            return False
        self._send_json(HTTPStatus.UNAUTHORIZED, {"detail": "Remote dashboard token required"})
        return True

    def _proxy_dashboard(self, path: str) -> None:
        request = Request(
            f"{self.config.backend}{path}",
            headers={"Authorization": f"Bearer {self.config.api_key()}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "application/json")
                self._send_bytes(response.status, body, content_type)
        except HTTPError as exc:
            self._send_bytes(exc.code, exc.read(), exc.headers.get("Content-Type", "application/json"))
        except (OSError, URLError) as exc:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"detail": f"Dashboard backend unavailable: {exc}"})

    def _proxy_event_stream(self, path: str) -> None:
        request = Request(
            f"{self.config.backend}{path}",
            headers={
                "Authorization": f"Bearer {self.config.api_key()}",
                "Accept": "text/event-stream",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=90) as response:
                self.send_response(response.status)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                while True:
                    line = response.readline()
                    if not line:
                        break
                    self.wfile.write(line)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except HTTPError as exc:
            self._send_bytes(exc.code, exc.read(), exc.headers.get("Content-Type", "application/json"))
        except (OSError, URLError) as exc:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"detail": f"Dashboard stream unavailable: {exc}"})

    def _serve_frontend(self, path: str, *, spa_fallback: bool = True) -> None:
        requested = unquote(path).lstrip("/")
        candidate = (self.config.frontend / requested).resolve() if requested else self.config.frontend / "index.html"
        try:
            candidate.relative_to(self.config.frontend)
        except ValueError:
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            return
        if not candidate.is_file() and not spa_fallback:
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "Asset not found"})
            return
        if not candidate.is_file():
            candidate = self.config.frontend / "index.html"
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._send_bytes(HTTPStatus.OK, body, content_type)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        # Hashed frontend assets contain no account data and must remain
        # available when mobile in-app browsers apply strict cookie timing.
        if parsed.path.startswith("/assets/") or parsed.path in {"/favicon.svg", "/favicon.ico"}:
            self._serve_frontend(parsed.path, spa_fallback=False)
            return
        if self._pair_or_reject(parsed):
            return
        path = parsed.path
        if _is_allowed_api_path(path):
            proxy_path = path + (f"?{parsed.query}" if parsed.query else "")
            if path == OPPORTUNITY_STREAM_PATH:
                self._proxy_event_stream(proxy_path)
            else:
                self._proxy_dashboard(proxy_path)
            return
        if path == "/sessions":
            self._send_json(HTTPStatus.OK, [])
            return
        if path.startswith(("/runs", "/live", "/swarm", "/mandate", "/upload", "/system", "/alpha")):
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "Route unavailable in read-only dashboard"})
            return
        self._serve_frontend(path)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def _reject_write(self) -> None:
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"detail": "Read-only dashboard"})

    do_POST = _reject_write
    do_PUT = _reject_write
    do_PATCH = _reject_write
    do_DELETE = _reject_write


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--backend", default="http://127.0.0.1:8899")
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--token", default=os.getenv("REMOTE_DASHBOARD_TOKEN", ""))
    parser.add_argument("--token-file", type=Path)
    parser.add_argument(
        "--trust-tailscale-identity",
        action="store_true",
        help="Accept Tailscale Serve identity headers only through the loopback ts.net proxy seam.",
    )
    args = parser.parse_args()
    token = args.token
    if args.token_file:
        if not args.token_file.is_file():
            parser.error("--token-file does not exist")
        token = args.token_file.read_text(encoding="ascii").strip()
    if len(token) < 24:
        parser.error("--token, --token-file, or REMOTE_DASHBOARD_TOKEN must contain at least 24 characters")
    if not (args.frontend / "index.html").is_file():
        parser.error("frontend build is missing index.html")
    if not args.api_key_file.is_file():
        parser.error("API key file does not exist")

    config = GatewayConfig(
        frontend=args.frontend,
        backend=args.backend,
        api_key_file=args.api_key_file,
        token=token,
        trust_tailscale_identity=args.trust_tailscale_identity,
    )
    handler = type("ConfiguredReadOnlyDashboardHandler", (ReadOnlyDashboardHandler,), {"config": config})
    server = DashboardHTTPServer((args.host, args.port), handler)
    print(f"Read-only dashboard gateway listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
