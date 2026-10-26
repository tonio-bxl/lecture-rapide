#!/usr/bin/env python3
"""Serve Lecture rapide statically and proxy Gutendex / Gutenberg / Gallica (CORS).

Usage:
  python3 server.py            # http://127.0.0.1:8765/
  python3 server.py 9000
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8765"))

ALLOWED_HOSTS = (
    "gutendex.com",
    "www.gutenberg.org",
    "gutenberg.org",
    "gallica.bnf.fr",
    "www.gallica.bnf.fr",
)

UA = (
    "Mozilla/5.0 (compatible; LectureRapide/1.0; +https://localhost) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

mimetypes.add_type("application/epub+zip", ".epub")
mimetypes.add_type("text/javascript", ".mjs")


def host_allowed(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.send_header("Cache-Control", "no-store")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/api/health":
            body = json.dumps({"ok": True, "proxy": True}).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/proxy":
            self._proxy(parsed.query)
            return

        # Static files
        if path in ("", "/"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        # Prevent path traversal
        target = (ROOT / rel).resolve()
        if not str(target).startswith(str(ROOT)) or not target.is_file():
            self.send_error(404, "Not found")
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif target.suffix in (".js", ".mjs"):
            ctype = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, query: str) -> None:
        qs = urllib.parse.parse_qs(query)
        url = (qs.get("url") or [None])[0]
        if not url:
            self._json_error(400, "Paramètre url manquant.")
            return
        if not host_allowed(url):
            self._json_error(403, "Hôte non autorisé pour le proxy.")
            return

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type") or "application/octet-stream"
                status = getattr(resp, "status", 200) or 200
                # Cloudflare challenge HTML
                if b"Just a moment" in data[:800] or b"cf-error-details" in data[:2000]:
                    self._json_error(
                        502,
                        "La source a bloqué la requête (Cloudflare). "
                        "Réessayez plus tard ou utilisez Gutenberg.",
                    )
                    return
                self.send_response(status)
                self._cors()
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Proxied-Url", url)
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = e.read() if e.fp else b""
            msg = "Erreur HTTP %s de la source." % e.code
            if e.code == 403:
                msg = "Accès refusé par la source (403). Essayez Gutenberg ou un autre titre."
            # Return JSON error for textish responses so the UI can show it;
            # for binary we still surface status.
            if "json" in (e.headers.get("Content-Type") or "") or not body:
                self._json_error(e.code if e.code >= 400 else 502, msg)
            else:
                # Might be Cloudflare HTML
                if b"Just a moment" in body[:800] or b"Attention Required" in body[:800]:
                    self._json_error(
                        502,
                        "La source a bloqué la requête (Cloudflare). "
                        "Réessayez plus tard ou utilisez Gutenberg.",
                    )
                    return
                self.send_response(e.code)
                self._cors()
                self.send_header("Content-Type", e.headers.get("Content-Type") or "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except Exception as exc:
            self._json_error(502, "Échec réseau du proxy : %s" % exc)

    def _json_error(self, code: int, message: str) -> None:
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    os.chdir(ROOT)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Lecture rapide — http://%s:%s/" % (HOST, PORT), flush=True)
    print("Proxy : /api/proxy?url=…  (Gutendex, Gutenberg, Gallica)", flush=True)
    print("Ctrl+C pour arrêter.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.", flush=True)


if __name__ == "__main__":
    main()
