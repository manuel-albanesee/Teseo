"""Dashboard loopback: consultazione e rebuild derivati espliciti coordinati."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import re
import os
import secrets
import socket
import sqlite3
import sys
import threading
import time
from urllib.parse import urlsplit, parse_qs, unquote
import webbrowser

from .bootstrap_ui import PAGE
from .contracts import ContractError, parse_json
from .diagnostics import log_unexpected
from .readonly import VaultRegistry
from .read_api import ReadAPI
from .jobs import RebuildCoordinator
from .ontology_preview import PreviewService
from .ontology_apply import ApplyService
from .operations import SkillCoordinator
from .adapters import default_adapters
from .shared_service import SharedService
from .sync_service import SyncService
from .receiver import Receiver
from .receiver_apply import ReceiverApplyService

MAX_BODY_BYTES = 16 * 1024


_log_unexpected = log_unexpected


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = False
    # Windows: SO_REUSEADDR lascia a un altro processo condividere la porta e ricevere i token.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, port=0, registry=None, rate_limit=120):
        self.registry = registry or VaultRegistry()
        self.operations = RebuildCoordinator(self.registry)
        self.read_api = ReadAPI(self.registry, self.operations)
        self.previews = PreviewService(self.registry)
        self.applies = ApplyService(self.registry, self.previews)
        self.skills = SkillCoordinator(self.registry, default_adapters())
        self.shared = SharedService(self.registry)
        self.sync = SyncService(self.registry)
        self.receiver = Receiver(self.registry, self.sync)
        self.receiver_apply = ReceiverApplyService(self.registry, self.sync, self.receiver)
        self.operations.note_activity = self.applies.active
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.rate_limit, self._requests = rate_limit, deque()
        self._rate_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.receiver.start()

    def server_close(self):
        self.receiver.request_stop()
        self.operations.request_stop()
        self.applies.request_stop()
        self.skills.request_stop()
        super().server_close()
        self.receiver.close()
        self.operations.close()
        self.applies.close()
        self.skills.close()

    def request_stop(self):
        self.receiver.request_stop()
        self.operations.request_stop()
        self.applies.request_stop()
        self.skills.request_stop()
        threading.Thread(target=self.shutdown, name="teseo-stop", daemon=True).start()

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
        # Nessun traceback/percorso/client nei log; disconnect e timeout del client sono normali e restano muti.
        error = sys.exc_info()[1]
        if error is not None and not isinstance(error, (ConnectionError, TimeoutError)):
            _log_unexpected(error)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TeseoLocal/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)
        self._body_read = False

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

    def _error(self, status, code, message, details=None):
        # Consume a bounded, unambiguous POST body before closing: on Windows
        # unread bytes can reset TCP and hide the structured rejection from clients.
        length = self._header("Content-Length") if hasattr(self, "headers") else None
        if (self.command == "POST" and not self._body_read and length and len(length) <= 5
                and length.isascii() and length.isdecimal() and not self.headers.get_all("Transfer-Encoding")
                and 0 < int(length) <= MAX_BODY_BYTES + 1):
            self._body_read = True
            try:
                self.rfile.read(int(length))
            except (ConnectionError, TimeoutError, OSError):
                pass
        error = {"code": code, "message": message, "retryable": status in (429, 503)}
        if details is not None:
            error['details'] = details
        self._reply(status, {"error": error,
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

    def _body(self, max_bytes=MAX_BODY_BYTES):
        if self.headers.get_all("Transfer-Encoding") or self._header("Content-Type") != "application/json":
            raise ContractError("invalid_request", "Richiesto JSON senza Transfer-Encoding")
        length = self._header("Content-Length")
        if (not length or len(length) > 6 or not length.isascii() or not length.isdecimal()
                or not 0 < int(length) <= max_bytes):
            raise ContractError("invalid_body_size", "Corpo JSON assente o oltre il limite dell'endpoint")
        self._body_read = True
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
            receipt_route = re.fullmatch(r'/api/v1/vaults/[^/]+/operations/[^/]+/complete', target.path)
            body = self._body(256*1024 if receipt_route else MAX_BODY_BYTES)
            if target.path == "/api/v1/session" and body == {}:
                self._reply(200, {"csrf_token": self.server.csrf_token, "content_revision": None,
                                  "graph_generation": None})
                return
            if target.path == "/api/v1/vaults/attach":
                if set(body) != {"path"}:
                    raise ContractError("invalid_payload", "Richiesto il solo campo path")
                self._reply(200, self.server.registry.attach(body["path"]))
                return
            if target.path == "/api/v1/shutdown" and body == {}:
                self._reply(202, {"state": "stopping", "content_revision": None, "graph_generation": None})
                self.server.request_stop()
                return
            parts = target.path.split("/")
            if len(parts)==7 and parts[1:4]==['api','v1','vaults'] and parts[5]=='sync':
                method={'preview':self.server.sync.preview,'initialize':self.server.sync.initialize,'configure':self.server.sync.configure,
                        'publish':self.server.sync.publish,'resolve':self.server.sync.resolve,
                        'check':self.server.receiver.check,'pause':self.server.receiver.pause,
                        'resume':self.server.receiver.resume,'receive':self.server.receiver_apply.apply,
                        'receive-recover':self.server.receiver_apply.recover}.get(parts[6])
                if method:
                    self._reply(200,method(parts[4],body))
                    return
            if len(parts)==6 and parts[1:4]==['api','v1','vaults'] and parts[5]=='answers':
                self._reply(201,self.server.shared.record(parts[4],body))
                return
            if len(parts)==7 and parts[1:4]==['api','v1','vaults'] and parts[5]=='shared-state':
                method={'decision':self.server.shared.decision,'export-preview':self.server.shared.preview,
                        'export':self.server.shared.export,'import':self.server.shared.import_state}.get(parts[6])
                if method:
                    self._reply(200,method(parts[4],body))
                    return
            if len(parts)==8 and parts[1:4]==['api','v1','vaults'] and parts[5]=='operations' and parts[7]=='apply':
                self._reply(202,self.server.applies.apply_skill(parts[4],parts[6],body,self._header('If-Match')))
                return
            if len(parts)==6 and parts[1:4]==['api','v1','vaults'] and parts[5]=='operations':
                self._reply(202,self.server.skills.submit(parts[4],body))
                return
            if len(parts)==6 and parts[1:4]==['api','v1','vaults'] and parts[5]=='dispatch':
                self._reply(200,self.server.skills.dispatch(parts[4],body))
                return
            if len(parts)==6 and parts[1:4]==['api','v1','vaults'] and parts[5]=='probe-adapters':
                if body!={}: raise ContractError('invalid_payload','Probe senza parametri')
                self.server.registry.root(parts[4])
                self._reply(200,{'adapters':[a.probe() for a in self.server.skills.adapters.values()]})
                return
            if len(parts)==8 and parts[1:4]==['api','v1','vaults'] and parts[5]=='operations' and parts[7] in ('complete','cancel','resume'):
                if parts[7]=='complete':
                    result=self.server.skills.complete(parts[4],parts[6],body)
                else:
                    result=self.server.skills.action(parts[4],parts[6],body,parts[7])
                self._reply(200,result)
                return
            if len(parts) == 7 and parts[1:4] == ['api', 'v1', 'vaults'] and parts[5:] == ['ontology', 'apply']:
                self._reply(202, self.server.applies.submit(parts[4], body, self._header('If-Match')))
                return
            if len(parts) == 8 and parts[1:4] == ['api', 'v1', 'vaults'] and parts[5] == 'operations' and parts[7] == 'recover':
                self._reply(202, self.server.applies.recover(parts[4], parts[6], body, self._header('If-Match')))
                return
            if len(parts) == 7 and parts[1:4] == ["api", "v1", "vaults"] and parts[5:] == ['ontology', 'preview']:
                self._reply(200, self.server.previews.preview(parts[4], body))
                return
            if len(parts) == 6 and parts[1:4] == ["api", "v1", "vaults"] and parts[5] == "rebuild":
                self._reply(202, self.server.operations.submit(parts[4], body))
                return
        elif self.command == "GET":
            if target.path == "/api/v1/vaults":
                self._reply(200, {"vaults": self.server.registry.list(), "content_revision": None,
                                  "graph_generation": None, "registry_issues": self.server.registry.restore_issues})
                return
            parts = target.path.split("/")
            try:
                raw = parse_qs(target.query, keep_blank_values=True, strict_parsing=True,
                               encoding="utf-8", errors="strict", max_num_fields=8)
                if any(len(values) != 1 for values in raw.values()):
                    raise ValueError
                parameters = {key: values[0] for key, values in raw.items()}
                if parts[1:4] == ["api", "v1", "vaults"]:
                    if len(parts)==7 and parts[5:]==['sync','status']:
                        result = self.server.sync.status(parts[4],parameters)
                        # A receiver fault must not hide publication state: report it in place.
                        for key, reader in (('receiver', self.server.receiver.status),
                                            ('receive_transaction', self.server.receiver_apply.status)):
                            try:
                                result[key] = reader(parts[4])
                            except ContractError as error:
                                result[key] = {'error': {'code': error.code, 'message': str(error)}}
                            except sqlite3.Error:
                                result[key] = {'error': {'code': 'receiver_storage', 'message': 'Stato locale del receiver non leggibile'}}
                        self._data_reply(result)
                        return
                    if len(parts) == 6:
                        reader = {"status": self.server.read_api.status, "graph": self.server.read_api.graph,
                                  "ontology": self.server.read_api.ontology,
                                  "operations": self.server.operations.list,
                                  "answers": self.server.shared.answers,
                                  "diagnostics": self.server.read_api.diagnostics}.get(parts[5])
                        if reader:
                            self._data_reply(reader(parts[4], parameters))
                            return
                    if len(parts) == 7 and parts[5] == "nodes":
                        node_id = unquote(parts[6], encoding="utf-8", errors="strict")
                        self._data_reply(self.server.read_api.node(parts[4], node_id, parameters))
                        return
                    if len(parts) == 7 and parts[5] == "operations":
                        if parameters:
                            raise ContractError("invalid_query", "Le operazioni non accettano parametri")
                        self._data_reply(self.server.operations.get(parts[4], parts[6]))
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
            status = {"operation_missing": 404, "operation_unavailable": 503, "vault_readonly": 422,
                      "vault_busy": 409, "job_limit": 409, "idempotency_conflict": 409,
                      "service_stopping": 503, "registry_unavailable": 503}.get(error.code, status)
            status = {'preview_stale': 409, 'blocked_external_change': 409, 'preview_busy': 429,
                      'preview_limit': 422, 'preview_parse_failed': 422, 'preview_encoding': 422,
                      'ontology_manual': 422, 'catalog_adoption_required': 422,
                      'invalid_schema': 422}.get(error.code, status)
            status = {'manual_confirmation_required': 422, 'apply_platform_unavailable': 422,
                      'precondition_required': 428, 'migration_manual': 422, 'migration_collision': 409,
                      'migration_invalid': 422, 'invalid_migrations': 400, 'path_too_long': 422, 'shared_mapping_unavailable': 422,
                      'recovery_required': 409, 'recovery_conflict': 409}.get(error.code, status)
            status = {'invalid_receipt':403,'receipt_conflict':409,'receipt_manifest_mismatch':409}.get(error.code,status)
            if error.code.startswith(('sync_','git_')):
                status=422 if error.code in ('sync_request','sync_config','sync_consent','sync_exclusion','git_invalid_remote','git_invalid_selection','git_repository_required') else 409
            status = {'invalid_response_ids':422,'answer_conflict':409,'answer_not_supported':422,'event_write_forbidden':422,
                'event_pending':409,'event_collision':409,'shared_heads_stale':409,'legacy_preview_stale':409,
                'shared_confirmation_required':422,'legacy_missing':404,'legacy_invalid':422,'invalid_event':422,
                'event_version':422,'event_reference':422,'event_cycle':422,'event_canonical':422,'event_filename':422,
                'event_vault':422,'entity_collision':409,'question_missing':404}.get(error.code,status)
            self._error(status, error.code, str(error), getattr(error, 'details', None))
        except (ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception as error:
            _log_unexpected(error)
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
    parser.add_argument("--registry", help="File JSON locale assoluto per ricordare i vault (directory esistente)")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("porta attesa fra 0 e 65535")
    try:
        registry = VaultRegistry(args.registry)
        for path in args.vault:
            registry.attach(path)
    except (ContractError, OSError) as error:
        if "registry" in locals():
            registry.close()
        parser.error(str(error))
    try:
        with DashboardServer(args.port, registry) as server:
            print(f"Teseo locale: {server.launch_url}", flush=True)
            print("Arresto: pulsante nella UI o Ctrl+C; attesa dei rebuild in chiusura.", flush=True)
            if not args.no_browser:
                webbrowser.open(server.launch_url)
            try:
                server.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                pass
    except OSError as error:
        # Con --port fisso il bind è esclusivo su Windows: la porta occupata va spiegata, non lasciata a un traceback.
        parser.error(f"server non avviabile (porta non disponibile?): {type(error).__name__}")
    finally:
        registry.close()


if __name__ == "__main__":
    main()
