"""Bootstrap HTTP locale: sessione effimera e attach readonly, nessun rebuild."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import re
import secrets
import threading
import time
from urllib.parse import urlsplit, parse_qs, unquote
import webbrowser

from .bootstrap_ui import PAGE
from .contracts import ContractError, parse_json
from .readonly import VaultRegistry
from .read_api import ReadAPI

MAX_BODY_BYTES = 16 * 1024


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0, registry=None, rate_limit=120):
        self.registry = registry or VaultRegistry()
        self.read_api = ReadAPI(self.registry)
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.rate_limit, self._requests = rate_limit, deque()
        self._rate_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    @property
    def launch_url(self):
        return f"{self.origin}/#session={self.session_token}"

    def allow_request(self):
        with self._rate_lock:
            now = time.monotonic()
            while self._requests and self._requests[0] <= now - 60:
                self._requests.popleft()
            if len(self._requests) >= self.rate_limit:
                return False
            self._requests.append(now)
            return True

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # Nessun traceback o percorso sensibile nei log del servizio.
        pass


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TeseoLocal/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        # Non registrare URL, header di sessione o contenuto del vault.
        pass

    def _reply(self, status, body, content_type="application/json; charset=utf-8", nonce=None, etag=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if status != 304:
            self.send_header("Content-Length", str(len(data)))
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        script = f"'nonce-{nonce}'" if nonce else "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'none'; script-src {script}; "
                         f"style-src {script}; connect-src 'self'; base-uri 'none'; "
                         "form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def _data_reply(self, body):
        data = json.dumps(body, ensure_ascii=True).encode("utf-8")
        etag = '"' + hashlib.sha256(data).hexdigest() + '"'
        if self._header("If-None-Match") in (etag, "*"):
            self._reply(304, b"", etag=etag)
        else:
            self._reply(200, data, etag=etag)

    def _error(self, status, code, message):
        self._reply(status, {"error": {"code": code, "message": message, "retryable": status in (429, 503)},
                             "content_revision": None, "graph_generation": None})

    def send_error(self, code, message=None, explain=None):
        self._error(code, "http_error", self.responses.get(code, ("Errore HTTP",))[0])

    def _header(self, name):
        values = self.headers.get_all(name, [])
        return values[0] if len(values) == 1 else None

    def _guard(self):
        if self._header("Host") != self.server.origin.removeprefix("http://"):
            self._error(403, "invalid_host", "Host non autorizzato")
            return False
        origins = self.headers.get_all("Origin", [])
        if (origins and origins != [self.server.origin]) or (self.command == "POST" and not origins):
            self._error(403, "invalid_origin", "Origine non autorizzata")
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._error(403, "cross_site", "Richiesta da un altro sito rifiutata")
            return False
        if not self.server.allow_request():
            self._error(429, "rate_limited", "Troppe richieste; riprovare tra un minuto")
            return False
        return True

    def _authenticated(self):
        token = self._header("X-Teseo-Session") or ""
        if not token.isascii() or not secrets.compare_digest(token, self.server.session_token):
            self._error(403, "invalid_session", "Sessione locale assente o scaduta")
            return False
        return True

    def _body(self):
        if self.headers.get_all("Transfer-Encoding") or self._header("Content-Type") != "application/json":
            raise ContractError("invalid_request", "Richiesto JSON senza Transfer-Encoding")
        length = self._header("Content-Length")
        if (not length or len(length) > 5 or not length.isascii() or not length.isdecimal()
                or not 0 < int(length) <= MAX_BODY_BYTES):
            raise ContractError("invalid_body_size", "Corpo JSON assente o oltre 16 KiB")
        data = self.rfile.read(int(length))
        if len(data) != int(length):
            raise ContractError("invalid_request", "Corpo richiesta incompleto")
        return parse_json(data)

    def _dispatch(self):
        if not self._guard():
            return
        target = urlsplit(self.path)
        if (target.scheme or target.netloc or target.fragment or len(target.query) > 4096
                or re.search(r"%(?![0-9a-fA-F]{2})", self.path)
                or (target.query and (self.command != "GET" or not target.path.startswith("/api/v1/vaults/")))):
            self._error(400, "invalid_target", "Percorso richiesta non valido")
            return
        if self.command == "GET" and target.path == "/":
            nonce = secrets.token_urlsafe(18)
            self._reply(200, PAGE.replace("__NONCE__", nonce).encode("utf-8"), "text/html; charset=utf-8", nonce)
            return
        if not self._authenticated():
            return
        if self.command == "POST":
            if target.path != "/api/v1/session":
                token = self._header("X-Teseo-CSRF") or ""
                if not token.isascii() or not secrets.compare_digest(token, self.server.csrf_token):
                    self._error(403, "invalid_csrf", "Token CSRF non valido")
                    return
            body = self._body()
            if target.path == "/api/v1/session" and body == {}:
                self._reply(200, {"csrf_token": self.server.csrf_token, "content_revision": None,
                                  "graph_generation": None})
                return
            if target.path == "/api/v1/vaults/attach":
                if set(body) != {"path"}:
                    raise ContractError("invalid_payload", "Richiesto il solo campo path")
                self._reply(200, self.server.registry.attach(body["path"]))
                return
        elif self.command == "GET":
            if target.path == "/api/v1/vaults":
                self._reply(200, {"vaults": self.server.registry.list(), "content_revision": None,
                                  "graph_generation": None})
                return
            parts = target.path.split("/")
            try:
                raw = parse_qs(target.query, keep_blank_values=True, strict_parsing=True,
                               encoding="utf-8", errors="strict", max_num_fields=8)
                if any(len(values) != 1 for values in raw.values()):
                    raise ValueError
                parameters = {key: values[0] for key, values in raw.items()}
                if parts[1:4] == ["api", "v1", "vaults"]:
                    if len(parts) == 6:
                        reader = {"status": self.server.read_api.status, "graph": self.server.read_api.graph,
                                  "ontology": self.server.read_api.ontology,
                                  "diagnostics": self.server.read_api.diagnostics}.get(parts[5])
                        if reader:
                            self._data_reply(reader(parts[4], parameters))
                            return
                    if len(parts) == 7 and parts[5] == "nodes":
                        node_id = unquote(parts[6], encoding="utf-8", errors="strict")
                        self._data_reply(self.server.read_api.node(parts[4], node_id, parameters))
                        return
            except ContractError:
                raise
            except (ValueError, UnicodeError):
                raise ContractError("invalid_query", "Parametri URL non validi") from None
        self._error(404, "route_missing", "Endpoint non disponibile in questo incremento")

    def _handle(self):
        try:
            self._dispatch()
        except ContractError as error:
            status = {"vault_missing": 404, "vault_id_conflict": 409, "vault_identity_changed": 409,
                      "vault_path_changed": 409, "incompatible_vault": 422, "vault_unreadable": 422,
                      "vault_limit": 409, "revision_changed": 409, "node_missing": 404,
                      "graph_unavailable": 503, "graph_upgrade_required": 503, "graph_unreadable": 503,
                      "graph_corrupt": 503, "graph_too_large": 503, "document_unavailable": 503,
                      "document_too_large": 422, "invalid_node_data": 422, "invalid_node": 403,
                      "unsafe_path": 403, "linked_path": 403, "path_escape": 403}.get(error.code, 400)
            self._error(status, error.code, str(error))
        except (ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception:
            self._error(503, "service_unavailable", "Servizio temporaneamente non disponibile")

    do_GET = _handle
    do_POST = _handle

    def do_OPTIONS(self):
        self._error(403, "cors_disabled", "Accesso cross-origin disabilitato")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", action="append", default=[], help="Cartella locale da collegare, ripetibile")
    parser.add_argument("--port", type=int, default=0, help="Porta loopback; 0 sceglie una porta libera")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("porta attesa fra 0 e 65535")
    registry = VaultRegistry()
    try:
        for path in args.vault:
            registry.attach(path)
    except ContractError as error:
        parser.error(str(error))
    with DashboardServer(args.port, registry) as server:
        print(f"Teseo locale: {server.launch_url}", flush=True)
        print("Arresto: Ctrl+C nel terminale.", flush=True)
        if not args.no_browser:
            webbrowser.open(server.launch_url)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
