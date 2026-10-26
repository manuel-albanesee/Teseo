"""Contratti readonly: formati, confini e byte canonici senza servizi esterni."""
import _shortpath  # noqa: F401
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from kit.dashboard.contracts import (
    ContractError, DEFAULT_SHARED_PATHS, MAX_INTEGER, PathKind, canonical_json, check_path_budget,
    is_junction, classify_path, content_hash, inspect_vault, parse_json, parse_manifest,
    portable_path, resolve_path, validate_paths,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dashboard"


class Contracts(unittest.TestCase):
    def manifest(self, **changes):
        value = json.loads((FIXTURES / "project-v1.json").read_text(encoding="utf-8"))
        return canonical_json({**value, **changes})

    def assert_code(self, code, function, *args):
        with self.assertRaises(ContractError) as raised:
            function(*args)
        self.assertEqual(raised.exception.code, code)
        self.assertIn("message", raised.exception.as_dict())

    def test_manifest_fixture_and_unknown_optional_fields_preserved(self):
        parsed = parse_manifest(self.manifest(extension={"description": "caffè"}))
        self.assertEqual(parsed["extension"], {"description": "caffè"})
        self.assertEqual(parsed["shared_paths"], list(DEFAULT_SHARED_PATHS))

    def test_unsupported_versions(self):
        for field in ("format_version", "schema_version", "event_version"):
            for value in (2, 0, True, "1"):
                with self.subTest(field=field, value=value):
                    self.assert_code("unsupported_version", parse_manifest, self.manifest(**{field: value}))
        self.assert_code("kit_too_old", parse_manifest, self.manifest(minimum_kit_version="2.0.0"))

    def test_required_fields_and_uuid(self):
        self.assert_code("missing_field", parse_manifest, b'{}')
        for value in ("not-uuid", None, 12, {}):
            self.assert_code("invalid_vault_id", parse_manifest, self.manifest(vault_id=value))

    def test_version_syntax(self):
        for value in (None, "DA_DEFINIRE", "1.0", "01.0.0", "1.0.0;command"):
            self.assert_code("invalid_version", parse_manifest, self.manifest(minimum_kit_version=value))

    def test_sharing_allowlist(self):
        for paths in ([], "wiki/", [12], [".graph/"], ["wiki/", "wiki/"], ["https://host/"], ["C:/vault"]):
            with self.subTest(paths=paths), self.assertRaises(ContractError):
                parse_manifest(self.manifest(shared_paths=paths))

    def test_canonical_bytes_fixture(self):
        data = (FIXTURES / "canonical-v1.json").read_bytes()
        parsed = parse_json(data)
        self.assertEqual(canonical_json(parsed), data)
        self.assertEqual(content_hash(parsed), hashlib.sha256(data).hexdigest())
        self.assertEqual(canonical_json({"z": 1, "a": {"é": 2, "b": 3}}),
                         '{"a":{"b":3,"é":2},"z":1}\n'.encode("utf-8"))
        self.assertEqual(canonical_json({"array": [3, 1, 2]}), b'{"array":[3,1,2]}\n')

    def test_json_rejects_ambiguous_or_unsupported_values(self):
        for data, code in (
            (b'{"a":1,"a":2}', "duplicate_key"),
            (b'{"a":{"b":1,"b":2}}', "duplicate_key"),
            (b'\xef\xbb\xbf{}', "invalid_json"),
            (b'[]', "invalid_root"), (b'{"n":1.0}', "invalid_value"),
            (b'{"n":NaN}', "invalid_value"), (b'{"n":Infinity}', "invalid_value"),
            (b'{"s":"e\\u0301"}', "non_nfc"),
            (b'{"s":"\\ud800"}', "invalid_unicode"), (b'\xff', "invalid_json"),
            (b'{"n":9007199254740992}', "integer_range"),
        ):
            with self.subTest(data=data):
                self.assert_code(code, parse_json, data)
        self.assert_code("invalid_key", canonical_json, {1: "a"})
        self.assert_code("invalid_value", canonical_json, {"a": (1, 2)})
        self.assertEqual(parse_json(canonical_json({"lo": -MAX_INTEGER, "hi": MAX_INTEGER})),
                         {"lo": -MAX_INTEGER, "hi": MAX_INTEGER})

    def test_nonportable_paths(self):
        for path in ("", "/root", "../secret", "wiki/../secret", "C:/vault", "a\\b",
                     "a//b", "a/./b", "wiki/NUL.md", "wiki/COM1", "wiki/LPT¹.txt",
                     "wiki/a.", "wiki/a ", "a\x00b", "wiki/e\u0301.md", "wiki/\ud800"):
            with self.subTest(path=repr(path)):
                self.assert_code("unsafe_path", portable_path, path)

    def test_collisions_include_directories(self):
        for paths in (["wiki/A.md", "wiki/a.md"], ["wiki/A.md", "Wiki/B.md"]):
            self.assert_code("path_collision", validate_paths, paths)
        validate_paths(["wiki/Anna.md", "wiki/Bruno.md"])

    def test_classification(self):
        cases = {
            ".teseo/project.json": PathKind.MANIFEST, "wiki/Anna.md": PathKind.MARKDOWN,
            "Wiki reference.md": PathKind.MARKDOWN, "index.md": PathKind.MARKDOWN,
            "log.md": PathKind.MARKDOWN, "raw/source.py": PathKind.RAW,
            ".teseo/shared/events/a.json": PathKind.EVENT,
            ".graph/graph.sqlite": PathKind.GRAPH,
            ".teseo/local/graphs/a.sqlite": PathKind.GRAPH,
            ".graph/memoria.sqlite": PathKind.PERSONAL,
            ".graph/domande.sqlite-wal": PathKind.PERSONAL,
            ".graph_backup/backup/memoria.sqlite": PathKind.LOCAL,
            ".teseo/local/journal.json": PathKind.LOCAL, ".git/config": PathKind.LOCAL,
            ".graph/build_graph.py": PathKind.EXECUTABLE, "AGENTS.md": PathKind.EXECUTABLE,
            ".github/hooks/a.json": PathKind.EXECUTABLE, "custom.txt": PathKind.UNKNOWN,
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(classify_path(path), expected)

    def test_inspection_never_adopts_or_modifies_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki").mkdir()
            (root / "Wiki reference.md").write_text("schema", encoding="utf-8")
            before = sorted(p.relative_to(root) for p in root.rglob("*"))
            self.assertEqual(inspect_vault(root).mode, "legacy_readonly")
            self.assertEqual(before, sorted(p.relative_to(root) for p in root.rglob("*")))
            (root / ".teseo").mkdir()
            manifest = root / ".teseo/project.json"
            data = self.manifest(vault_id=str(uuid4()))
            manifest.write_bytes(data)
            self.assertEqual(inspect_vault(root).mode, "compatible")
            self.assertEqual(manifest.read_bytes(), data)
            manifest.write_bytes(self.manifest(format_version=2))
            result = inspect_vault(root)
            self.assertEqual(result.mode, "incompatible")
            self.assertEqual(result.issues[0]["code"], "unsupported_version")
            manifest.write_bytes(b" " * 65537)
            self.assertEqual(inspect_vault(root).issues[0]["code"], "manifest_too_large")

    def test_invalid_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(inspect_vault(tmp).issues[0]["code"], "invalid_vault")
            self.assertEqual(inspect_vault(Path(tmp) / "missing").issues[0]["code"], "vault_unreadable")

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vault"
            root.mkdir()
            try:
                (root / "outside").symlink_to(Path(tmp), target_is_directory=True)
            except OSError:
                self.skipTest("La piattaforma non consente la creazione di symlink")
            self.assert_code("path_escape", resolve_path, root, "outside/secret")


class PathBudget(unittest.TestCase):
    def test_long_root_is_refused_before_any_write_on_limited_windows(self):
        with tempfile.TemporaryDirectory() as temp,                 mock.patch("kit.dashboard.contracts.os.name", "nt"),                 mock.patch("kit.dashboard.contracts._long_paths_enabled", return_value=False):
            with self.assertRaises(ContractError) as caught:
                check_path_budget(Path(temp) / ("x" * 120))
            self.assertEqual(caught.exception.code, "path_too_long")
            self.assertNotIn(temp, str(caught.exception))

    def test_short_root_and_long_path_support_are_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            deep = Path(temp) / ("x" * 120)
            deep.mkdir()
            with mock.patch("kit.dashboard.contracts.os.name", "nt"),                     mock.patch("kit.dashboard.contracts._long_paths_enabled", return_value=True):
                check_path_budget(deep)
            with mock.patch("kit.dashboard.contracts.os.name", "posix"):
                check_path_budget(deep)


@unittest.skipUnless(os.name == "nt", "le junction NTFS esistono solo su Windows")
class Junctions(unittest.TestCase):
    def test_junction_is_detected_with_and_without_native_path_is_junction(self):
        with tempfile.TemporaryDirectory() as temp:
            target, link = Path(temp) / "target", Path(temp) / "link"
            target.mkdir()
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            if result.returncode:
                self.skipTest("mklink /J non disponibile")
            try:
                self.assertTrue(is_junction(link))
                self.assertFalse(is_junction(target))
                self.assertFalse(is_junction(Path(temp) / "missing"))
                with mock.patch.object(Path, "is_junction", None):  # Python < 3.12
                    self.assertTrue(is_junction(link))
                    self.assertFalse(is_junction(target))
            finally:
                os.rmdir(link)


if __name__ == "__main__":
    unittest.main()
