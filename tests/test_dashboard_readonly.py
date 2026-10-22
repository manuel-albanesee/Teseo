"""HTTP reale su loopback: attach readonly, sessione, CSRF e input ostili."""
import contextlib
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
from kit.dashboard.server import DashboardServer, main


class ReadonlyHTTP(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="teseo readonly ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "wiki").mkdir()
        (self.root / "raw").mkdir()
        (self.root / ".graph").mkdir()
        (self.root / "Wiki reference.md").write_text("Schema", encoding="utf-8")
        (self.root / "wiki/Anna.md").write_text('<script>throw "hostile"</script>', encoding="utf-8")
        (self.root / "raw/fonte.py").write_text("raise RuntimeError('never execute')", encoding="utf-8")
        (self.root / ".graph/memoria.sqlite").write_bytes(b"not a database: do not open")
        (self.root / ".graph/build_graph.py").write_text(
            "from pathlib import Path; Path('EXECUTED').touch()", encoding="utf-8")
        self.server = DashboardServer()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02})
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def manifest(self, **changes):
        data = json.loads((ROOT / "tests/fixtures/dashboard/project-v1.json").read_bytes())
        data.update(changes)
        (self.root / ".teseo").mkdir(exist_ok=True)
        (self.root / ".teseo/project.json").write_text(json.dumps(data), encoding="utf-8")

    def request(self, method, path, data=None, headers=None, authenticated=True, csrf=True):
        request_headers = {}
        if authenticated:
            request_headers["X-Teseo-Session"] = self.server.session_token
        if method == "POST":
            request_headers.update({"Origin": self.server.origin, "Content-Type": "application/json"})
            if csrf:
                request_headers["X-Teseo-CSRF"] = self.server.csrf_token
        request_headers.update(headers or {})
        body = json.dumps(data).encode("utf-8") if data is not None and not isinstance(data, bytes) else data
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            return response.status, dict(response.getheaders()), content
        finally:
            connection.close()

    def attach(self):
        status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(self.root)})
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def hashes(self):
        return {path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file()}

    def test_legacy_attach_and_get_do_not_create_or_change_any_file(self):
        before = self.hashes()
        with mock.patch("subprocess.run", side_effect=AssertionError("no execution")):
            record = self.attach()
            self.assertEqual(record["compatibility"], "legacy_readonly")
            self.assertEqual(record["mode"], "readonly")
            self.assertFalse(record["capabilities"]["rebuild"])
            status, _, body = self.request("GET", f'/api/v1/vaults/{record["vault_id"]}/status')
            self.assertEqual(status, 200, body)
            self.assertEqual(json.loads(body)["vault_id"], record["vault_id"])
            self.assertEqual(json.loads(body)["compatibility"], record["compatibility"])
            self.assertIsNone(json.loads(body)["graph_generation"])
            status, _, body = self.request("GET", "/api/v1/vaults")
            self.assertEqual(json.loads(body)["vaults"], [record])
        self.assertEqual(self.hashes(), before)
        self.assertFalse((self.root / ".teseo").exists())
        self.assertFalse((self.root / "EXECUTED").exists())

    def test_compatible_and_repeat_attach_preserve_hashes_and_uuid(self):
        self.manifest()
        before = self.hashes()
        first = self.attach()
        self.assertEqual(first["compatibility"], "compatible")
        self.assertEqual(self.attach(), first)
        self.assertEqual(self.hashes(), before)
        self.assertFalse((self.root / ".teseo/local").exists())

    def test_future_format_and_invalid_root_are_structured_errors(self):
        self.manifest(format_version=2)
        status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(self.root)})
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["error"]["code"], "incompatible_vault")
        self.assertIn("format_version", json.loads(body)["error"]["message"])
        status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(self.root / "missing")})
        self.assertEqual(status, 422)
        self.assertNotIn(b"Traceback", body)

    def test_same_uuid_different_clone_conflicts(self):
        self.manifest()
        self.attach()
        other = self.root / "other"
        shutil.copytree(self.root / "wiki", other / "wiki")
        shutil.copytree(self.root / ".teseo", other / ".teseo")
        shutil.copyfile(self.root / "Wiki reference.md", other / "Wiki reference.md")
        status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(other)})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"]["code"], "vault_id_conflict")

    def test_recheck_compatibility_when_status_is_requested(self):
        self.manifest()
        record = self.attach()
        self.manifest(schema_version=2)
        status, _, body = self.request("GET", f'/api/v1/vaults/{record["vault_id"]}/status')
        self.assertEqual(status, 422, body)

    def test_missing_or_wrong_session_rejected_without_data(self):
        self.attach()
        for headers, authenticated in (({}, False), ({"X-Teseo-Session": "wrong"}, True),
                                       ({"X-Teseo-Session": "é"}, True)):
            status, _, body = self.request("GET", "/api/v1/vaults", headers=headers, authenticated=authenticated)
            self.assertEqual(status, 403, body)
            self.assertNotIn(str(self.root).encode(), body)

    def test_origin_host_and_csrf_enforced(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                        {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"},
                        {"X-Teseo-CSRF": "wrong"}):
            status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(self.root)}, headers)
            self.assertEqual(status, 403, body)
        status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(self.root)}, csrf=False)
        self.assertEqual(status, 403, body)
        status, headers, body = self.request("OPTIONS", "/api/v1/vaults/attach", authenticated=False)
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_session_bootstrap_requires_token_and_returns_only_csrf(self):
        status, _, body = self.request("POST", "/api/v1/session", {}, csrf=False)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["csrf_token"], self.server.csrf_token)
        self.assertNotIn(self.server.session_token.encode(), body)
        status, _, _ = self.request("POST", "/api/v1/session", {}, authenticated=False, csrf=False)
        self.assertEqual(status, 403)

    def test_bad_payloads_sizes_duplicate_keys_and_chunked_requests(self):
        for body, headers in (({"path": str(self.root), "command": "run"}, {}),
                              (b'{"path":"a","path":"b"}', {}), (b"x" * 16385, {}),
                              ({"path": str(self.root)}, {"Transfer-Encoding": "chunked"}),
                              (b"[]", {}), ({"path": 123}, {})):
            status, _, response = self.request("POST", "/api/v1/vaults/attach", body, headers)
            self.assertEqual(status, 400, response)
        self.assertFalse((self.root / ".teseo").exists())

    def test_remote_and_relative_paths_and_unknown_routes_rejected(self):
        for path in ("https://example.com", "//server/share", "\\\\server\\share", "../vault", "file://vault"):
            status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": path})
            self.assertEqual(status, 400, body)
        for path in ("/api/v1/vaults/../../raw/secret", "/%2e%2e/private", "/api/v1/vaults/unknown/status"):
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404)
        status, _, _ = self.request("POST", "/api/v1/vaults/x/rebuild", {})
        self.assertEqual(status, 404)

    def test_html_has_no_vault_data_or_token_and_uses_strict_csp(self):
        self.attach()
        status, headers, body = self.request("GET", "/", authenticated=False)
        self.assertEqual(status, 200)
        self.assertIn("nonce-", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn(self.server.session_token.encode(), body)
        self.assertNotIn(b"hostile", body)
        self.assertNotIn(str(self.root).encode(), body)
        self.assertIn(b"textContent", body)
        self.assertNotIn(b"innerHTML", body)
        self.assertIn(b"history.replaceState", body)

    def test_rate_limit_is_bounded_and_sessions_rotate(self):
        self.server.rate_limit = 2
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/")[0], 429)
        with DashboardServer() as other:
            self.assertNotEqual(other.session_token, self.server.session_token)
            self.assertEqual(other.server_address[0], "127.0.0.1")
            self.assertNotIn(self.server.session_token, self.server.origin)
            self.assertIn("#session=", self.server.launch_url)

    @unittest.skipUnless(os.name == "nt", "Junction Windows")
    def test_link_to_outside_vault_is_rejected_without_reading_scripts(self):
        (self.root / "wiki/Anna.md").unlink()
        (self.root / "wiki").rmdir()
        with tempfile.TemporaryDirectory(prefix="teseo outside ") as outside:
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.root / "wiki"), outside],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            try:
                status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(self.root)})
                self.assertEqual(status, 422, body)
            finally:
                (self.root / "wiki").rmdir()

    def test_launcher_help_in_installed_layout(self):
        shutil.copytree(ROOT / "kit/dashboard", self.root / ".graph/dashboard",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "kit/graph/teseo_dashboard.py", self.root / ".graph/teseo_dashboard.py")
        result = subprocess.run([sys.executable, str(self.root / ".graph/teseo_dashboard.py"), "--help"],
                                cwd=self.root, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIn(b"--no-browser", result.stdout)
        self.assertFalse((self.root / ".teseo").exists())
        self.assertFalse((self.root / "EXECUTED").exists())

    def test_launcher_preattach_no_browser_and_keyboard_interrupt(self):
        before = self.hashes()
        with mock.patch.object(DashboardServer, "serve_forever", side_effect=KeyboardInterrupt), \
                mock.patch("webbrowser.open") as browser, contextlib.redirect_stdout(io.StringIO()):
            main(["--vault", str(self.root), "--no-browser"])
        browser.assert_not_called()
        self.assertEqual(self.hashes(), before)


if __name__ == "__main__":
    unittest.main()
