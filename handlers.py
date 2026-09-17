"""HTTP request handler: serves the UI, static assets and the JSON/scan API."""

import http.server
import json
import threading
import urllib.parse
from datetime import datetime
from pathlib import Path

from config import CONFIG
from export import export_txt
from log import log
from scanner import PRINTERS, SCAN_STATUS, STATE_LOCK, run_scan
from snmp import SNMPGET, SNMPWALK

TEMPLATES_DIR = Path(__file__).parent / 'templates'
STATIC_DIR    = Path(__file__).parent / 'static'

INDEX_HTML = (TEMPLATES_DIR / 'index.html').read_text(encoding='utf-8')

STATIC_CONTENT_TYPES = {
    '.css': 'text/css; charset=utf-8',
    '.js':  'application/javascript; charset=utf-8',
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log(f'{self.address_string()} — {fmt % args}')

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, filename="export.txt"):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, url_path):
        rel = url_path[len('/static/'):]
        static_root = STATIC_DIR.resolve()
        file_path   = (STATIC_DIR / rel).resolve()

        if static_root not in file_path.parents or not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            return

        content_type = STATIC_CONTENT_TYPES.get(file_path.suffix, 'application/octet-stream')
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path.startswith("/static/"):
            self._serve_static(path)
            return

        if path == "/" or path == "/index.html":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/status":
            with STATE_LOCK:
                self.send_json(dict(SCAN_STATUS))

        elif path == "/api/printers":
            with STATE_LOCK:
                printers = list(PRINTERS)
            ts = printers[0]["scanned_at"] if printers else None
            self.send_json({"printers": printers, "scanned_at": ts})

        elif path == "/api/export/txt":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.send_text(export_txt(), f"ink_levels_{ts}.txt")

        elif path == "/api/export/json":
            with STATE_LOCK:
                printers = list(PRINTERS)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            body = json.dumps(printers, indent=2, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="ink_levels_{ts}.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/scan":
            length = int(self.headers.get("Content-Length", 0))
            raw    = self.rfile.read(length).decode("utf-8", errors="replace")
            params = urllib.parse.parse_qs(raw)

            subnet    = (params.get("subnet", [None])[0] or "").strip() or CONFIG.get("subnet")
            community = (params.get("community", [None])[0] or "").strip() or CONFIG.get("community", "public")
            hosts_raw = (params.get("hosts", [None])[0] or "").strip()
            hosts     = [h.strip() for h in hosts_raw.split(",") if h.strip()] if hosts_raw else None

            if not SNMPWALK or not SNMPGET:
                self.send_json({"ok": False, "error": "snmpwalk/snmpget non trovati. Installa: sudo apt install snmp"})
                return

            if SCAN_STATUS["running"]:
                self.send_json({"ok": False, "error": "Scansione già in corso"})
                return

            thread = threading.Thread(target=run_scan, args=(subnet, community, hosts), daemon=True)
            thread.start()
            self.send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()
