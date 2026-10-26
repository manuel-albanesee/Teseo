"""Storage su vault sacrificabili: concorrenza reale, crash e fault injection."""
import _shortpath  # noqa: F401
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.dashboard import contracts, storage
from kit.dashboard.contracts import ContractError
from kit.dashboard.storage import (
    Journal, Snapshot, SnapshotFile, VaultLock, capture_snapshot, validate_raw_unchanged,
)


class Storage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="teseo storage ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "wiki").mkdir()
        (self.root / "raw").mkdir()
        (self.root / ".teseo").mkdir()
        (self.root / ".teseo/project.json").write_bytes(
            (ROOT / "tests/fixtures/dashboard/project-v1.json").read_bytes())
        (self.root / "Wiki reference.md").write_text("Schema originale", encoding="utf-8")
        (self.root / "wiki/Anna.md").write_text("Nota originale", encoding="utf-8")
        (self.root / "raw/fonte.txt").write_text("Fonte originale", encoding="utf-8")

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(ContractError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def candidate(self, base):
        return Snapshot(tuple(replace(entry, data=b"Nota candidata") if entry.path == "wiki/Anna.md"
                              else entry for entry in base.files))

    def validating(self, journal, base):
        record = journal.create("rebuild", {"scope": "all"}, "test", base)
        for state in ("waiting_lock", "running", "validating"):
            record = journal.transition(record["operation_id"], state)
        return record

    def child(self, mode):
        process = subprocess.Popen([sys.executable, str(Path(__file__)), mode, str(self.root)],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop_child, process)
        return process

    @staticmethod
    def stop_child(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def wait_ready(self, process):
        deadline = time.monotonic() + 10
        while not (self.root / ".teseo/local/ready").exists():
            if process.poll() is not None:
                self.fail(process.communicate()[1].decode("utf-8", "replace"))
            if time.monotonic() >= deadline:
                self.fail("Processo figlio non pronto")
            time.sleep(0.02)

    def test_create_refuses_initial_fields_that_would_override_identity_or_base(self):
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            base = capture_snapshot(self.root)
            for field in ("vault_id", "before", "operation_id", "kind", "base_content_digest"):
                with self.subTest(field=field):
                    self.assert_code("invalid_operation", journal.create, "rebuild", {"n": field}, "key-" + field,
                                     base, initial={field: "x"})

    def test_local_database_is_versioned_and_newer_versions_are_refused(self):
        import sqlite3
        from contextlib import closing
        with VaultLock(self.root) as lock, Journal(lock):
            pass
        path = self.root / ".teseo/local/operations.sqlite"
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            db.execute("PRAGMA user_version=99")
            db.commit()
        with VaultLock(self.root) as lock:
            self.assert_code("storage_version", Journal, lock)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_legacy_has_no_implicit_storage(self):
        (self.root / ".teseo/project.json").unlink()
        self.assert_code("vault_readonly", VaultLock, self.root)
        self.assertFalse((self.root / ".teseo/local").exists())

    def test_lock_rejects_invalid_timeout_without_creating_storage(self):
        for timeout in (-1, float("nan"), float("inf"), "5", None, True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                VaultLock(self.root, timeout=timeout)
        self.assertFalse((self.root / ".teseo/local").exists())

    def test_lock_required_for_every_journal_access(self):
        lock = VaultLock(self.root)
        self.assert_code("lock_required", Journal, lock)
        with lock:
            journal = Journal(lock)
        try:
            self.assert_code("lock_required", journal.get, "missing")
        finally:
            journal.__exit__()

    def test_two_processes_are_serialized_and_lock_survives_as_file(self):
        first = self.child("--hold")
        self.wait_ready(first)
        self.assert_code("vault_busy", VaultLock(self.root, timeout=0.05).__enter__)
        (self.root / ".teseo/local/release").touch()
        self.assertEqual(first.wait(timeout=10), 0)
        with VaultLock(self.root):
            self.assertTrue((self.root / ".teseo/local/vault.lock").exists())
        self.assertEqual((self.root / ".teseo/local/.gitignore").read_text(), "*\n")

    def test_waiting_writer_acquires_after_owner_exits(self):
        first = self.child("--hold")
        self.wait_ready(first)
        # La richiesta successiva può attendere il proprietario senza rimuoverne il lock.
        (self.root / ".teseo/local/release").touch()
        with VaultLock(self.root, timeout=5) as lock:
            self.assertTrue(lock.held)
        self.assertEqual(first.wait(timeout=10), 0)

    def test_process_crash_releases_kernel_lock(self):
        first = self.child("--hold")
        self.wait_ready(first)
        first.kill()
        first.wait(timeout=10)
        with VaultLock(self.root, timeout=2):
            pass

    def test_content_digest_ignores_mtime_and_detects_same_size_schema_change(self):
        before = capture_snapshot(self.root)
        self.assertEqual(before.digest, capture_snapshot(self.root).digest)
        schema = self.root / "Wiki reference.md"
        stamp = schema.stat()
        schema.write_text("Schema modificato", encoding="utf-8")
        os.utime(schema, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assert_code("blocked_external_change", before.assert_unchanged, self.root)
        self.assertNotEqual(before.schema_digest, capture_snapshot(self.root).schema_digest)

    def test_new_deleted_and_renamed_notes_invalidate_snapshot(self):
        base = capture_snapshot(self.root)
        page = self.root / "wiki/Anna.md"
        data = page.read_bytes()
        page.unlink()
        self.assert_code("blocked_external_change", base.assert_unchanged, self.root)
        page.write_bytes(data)
        page.rename(self.root / "wiki/Bruno.md")
        self.assert_code("blocked_external_change", base.assert_unchanged, self.root)
        (self.root / "wiki/Bruno.md").rename(page)
        (self.root / "wiki/Nuova.md").write_text("nuova", encoding="utf-8")
        self.assert_code("blocked_external_change", base.assert_unchanged, self.root)

    def test_snapshot_excludes_personal_and_local_state(self):
        base = capture_snapshot(self.root)
        (self.root / ".graph").mkdir()
        (self.root / ".graph/memoria.sqlite").write_bytes(b"private")
        with VaultLock(self.root):
            (self.root / ".teseo/local/session.json").write_bytes(b"private")
        self.assertEqual(base.digest, capture_snapshot(self.root).digest)
        self.assertFalse(any("private".encode() == entry.data for entry in base.files))

    def test_byte_limit_and_unknown_shared_file(self):
        self.assert_code("snapshot_too_large", capture_snapshot, self.root, max_bytes=1)
        (self.root / "wiki/run.py").write_text("never run", encoding="utf-8")
        self.assert_code("unexpected_data_path", capture_snapshot, self.root)

    def test_change_during_scan_is_rejected(self):
        real = storage._scan
        def scan(root, max_bytes):
            snapshot = real(root, max_bytes)
            (self.root / "wiki/Anna.md").write_bytes(b"changed during scan")
            return snapshot
        with mock.patch.object(storage, "_scan", side_effect=scan):
            self.assert_code("blocked_external_change", capture_snapshot, self.root)

    def test_raw_additions_allowed_old_sources_immutable(self):
        base = capture_snapshot(self.root)
        extra = SnapshotFile("raw/nuova.txt", b"new")
        validate_raw_unchanged(base, Snapshot(base.files + (extra,)))
        for replacement in (None, SnapshotFile("raw/fonte.txt", b"changed"), SnapshotFile("raw/rename.txt", b"Fonte originale")):
            files = tuple(entry for entry in base.files if entry.path != "raw/fonte.txt")
            if replacement:
                files += (replacement,)
            self.assert_code("immutable_raw_changed", validate_raw_unchanged, base, Snapshot(files))

    def test_snapshot_rejects_traversal_and_duplicates(self):
        self.assert_code("unsafe_path", Snapshot, (SnapshotFile("../outside", b"x"),))
        entry = SnapshotFile("wiki/a.md", b"x")
        self.assert_code("duplicate_path", Snapshot, (entry, entry))
        self.assert_code("invalid_snapshot", Snapshot, (SnapshotFile(".graph/private", b"x"),))

    def test_journal_persists_fields_and_idempotency_across_reopen(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock:
            with Journal(lock) as journal:
                first = journal.create("rebuild", {"scope": "all"}, "same", base)
            with Journal(lock) as journal:
                repeated = journal.create("rebuild", {"scope": "all"}, "same", base)
                self.assertEqual(first, repeated)
                self.assertEqual(first["base_content_digest"], base.digest)
                self.assertIsNone(first["base_git_revision"])
                self.assertEqual(first["before"], base.hashes)
                copy = capture_snapshot(self.root / first["snapshot_path"])
                self.assertEqual(copy.digest, base.digest)
                self.assert_code("idempotency_conflict", journal.create, "rebuild", {"scope": "other"}, "same", base)

    def test_invalid_transitions_and_apply_are_blocked(self):
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = journal.create("rebuild", {}, "state", capture_snapshot(self.root))
            operation = record["operation_id"]
            self.assert_code("invalid_transition", journal.transition, operation, "validating")
            self.assert_code("prepare_required", journal.transition, operation, "prepared")
            self.assert_code("apply_unavailable", journal.transition, operation, "applying")
            journal.transition(operation, "cancelled")
            self.assert_code("invalid_transition", journal.transition, operation, "running")
            base = capture_snapshot(self.root)
            note = journal.create("ontology", {}, "note-apply", base)
            journal.transition(note["operation_id"], "waiting_lock")
            journal.transition(note["operation_id"], "running")
            self.assert_code("invalid_transition", journal.complete_rebuild, note["operation_id"],
                             SimpleNamespace(content_revision=base.digest, generation="a" * 64))

    def test_prepare_persists_candidate_without_changing_live_notes(self):
        base = capture_snapshot(self.root)
        candidate = self.candidate(base)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = self.validating(journal, base)
            prepared = journal.prepare(record["operation_id"], candidate)
            self.assertEqual(prepared["state"], "prepared")
            self.assertEqual(prepared["after"], candidate.hashes)
            path = self.root / prepared["checkpoint"]["candidate_path"]
            self.assertEqual(capture_snapshot(path).digest, candidate.digest)
            recovered = journal.require_recovery()[0]
            self.assertEqual(recovered["checkpoint"], prepared["checkpoint"])
            self.assertEqual(recovered["after"], prepared["after"])
            self.assertEqual(journal.orphan_snapshots(), [])
        self.assertEqual(capture_snapshot(self.root).digest, base.digest)

    def test_snapshot_directories_use_short_tokens_while_ids_stay_uuids(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = self.validating(journal, base)
            operation, token = record["operation_id"], record["operation_id"].replace("-", "")[:16]
            self.assertEqual(uuid.UUID(operation).version, 4)
            self.assertEqual(record["snapshot_path"], f".teseo/local/snapshots/{token}/base")
            prepared = journal.prepare(operation, self.candidate(base))
            checkpoint = prepared["checkpoint"]["checkpoint_id"]
            self.assertEqual(uuid.UUID(checkpoint).version, 4)
            self.assertEqual(prepared["checkpoint"]["candidate_path"],
                             f".teseo/local/snapshots/{token}/candidates/{checkpoint.replace('-', '')[:16]}")

    def test_path_budget_equals_longest_real_path_of_a_nested_rebuild(self):
        from kit.dashboard.graph_service import rebuild
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            prepared = journal.prepare(self.validating(journal, base)["operation_id"], self.candidate(base))
        rebuild(self.root / prepared["checkpoint"]["candidate_path"])
        graphs = [path for path in (self.root / ".teseo/local/snapshots").rglob("*.sqlite")]
        self.assertEqual(len(graphs), 1)
        measured = len(graphs[0].relative_to(self.root).as_posix()) + 1 + len("-journal")
        self.assertEqual(measured, contracts._LONGEST_INTERNAL_PATH)

    def test_vault_root_limit_leaves_room_on_limited_windows(self):
        with mock.patch("kit.dashboard.contracts.os.name", "nt"), \
                mock.patch("kit.dashboard.contracts._long_paths_enabled", return_value=False):
            self.assertGreaterEqual(contracts.max_vault_path_length(), 90)

    def test_create_retries_when_directory_token_collides(self):
        base = capture_snapshot(self.root)
        first, clash, fresh = (uuid.UUID(value) for value in (
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "aaaaaaaa-aaaa-aaaa-bbbb-bbbbbbbbbbbb",
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc"))
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            with mock.patch.object(storage, "uuid4", side_effect=[first]):
                one = journal.create("rebuild", {"n": 1}, "one", base)
            marker = self.root / one["snapshot_path"] / "wiki/Anna.md"
            before = marker.read_bytes()
            with mock.patch.object(storage, "uuid4", side_effect=[clash, fresh]):
                two = journal.create("rebuild", {"n": 2}, "two", base)
            self.assertEqual(two["operation_id"], str(fresh))
            self.assertNotEqual(one["snapshot_path"], two["snapshot_path"])
            self.assertEqual(marker.read_bytes(), before)

    def test_prepare_never_reuses_a_colliding_checkpoint_directory(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = self.validating(journal, base)
            operation = record["operation_id"]
            token = operation.replace("-", "")[:16]
            taken = self.root / f".teseo/local/snapshots/{token}/candidates/{'d' * 16}"
            taken.mkdir(parents=True)
            (taken / "keep.txt").write_bytes(b"gia presente")
            supplied = "dddddddd-dddd-dddd-dddd-dddddddddddd"
            self.assert_code("snapshot_exists", journal.prepare, operation, self.candidate(base),
                             checkpoint_id=supplied)
            self.assertEqual((taken / "keep.txt").read_bytes(), b"gia presente")
            self.assertEqual(journal.get(operation)["state"], "validating")
            generated = [uuid.UUID(supplied), uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")]
            with mock.patch.object(storage, "uuid4", side_effect=generated):
                prepared = journal.prepare(operation, self.candidate(base))
            self.assertEqual(prepared["checkpoint"]["checkpoint_id"], str(generated[1]))
            self.assertEqual((taken / "keep.txt").read_bytes(), b"gia presente")

    def test_orphans_follow_recorded_paths_for_token_legacy_and_mixed_layouts(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            modern = self.validating(journal, base)
            self.assertEqual(journal.orphan_snapshots(), [])
            legacy = journal.create("rebuild", {"legacy": True}, "legacy", base)
            old = f".teseo/local/snapshots/{legacy['operation_id']}/base"
            (self.root / old).parent.mkdir()
            os.rename(self.root / legacy["snapshot_path"], self.root / old)
            os.rmdir((self.root / legacy["snapshot_path"]).parent)
            legacy["snapshot_path"] = old
            journal._save(legacy)
            self.assertEqual(journal.orphan_snapshots(), [])
            stray = self.root / ".teseo/local/snapshots" / ("f" * 16)
            stray.mkdir()
            self.assertEqual(journal.orphan_snapshots(), [stray.relative_to(self.root).as_posix()])
            stray.rmdir()
            for step in ("waiting_lock", "running", "validating"):
                journal.transition(legacy["operation_id"], step)
            prepared = journal.prepare(legacy["operation_id"], self.candidate(base))
            self.assertEqual(journal.orphan_snapshots(), [])
            extra = self.root / prepared["checkpoint"]["candidate_path"]
            extra.with_name("stale").mkdir()
            self.assertEqual(journal.orphan_snapshots(),
                             [extra.with_name("stale").relative_to(self.root).as_posix()])
            self.assertEqual(modern["state"], "validating")

    def test_prepare_records_external_change(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = self.validating(journal, base)
            (self.root / "wiki/Anna.md").write_bytes(b"external edit")
            self.assert_code("blocked_external_change", journal.prepare, record["operation_id"], self.candidate(base))
            self.assertEqual(journal.get(record["operation_id"])["state"], "blocked_external_change")
        self.assertEqual((self.root / "wiki/Anna.md").read_bytes(), b"external edit")

    def test_prepare_checks_again_after_copy(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = self.validating(journal, base)
            persist = journal._persist_snapshot
            def injected(relative, snapshot):
                persist(relative, snapshot)
                (self.root / "wiki/Anna.md").write_bytes(b"external during copy")
            with mock.patch.object(journal, "_persist_snapshot", side_effect=injected):
                self.assert_code("blocked_external_change", journal.prepare, record["operation_id"], self.candidate(base))
            self.assertEqual(journal.get(record["operation_id"])["state"], "blocked_external_change")

    def test_prepare_rejects_raw_mutation_and_corrupt_backup(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = self.validating(journal, base)
            bad = Snapshot(tuple(replace(entry, data=b"bad") if entry.path.startswith("raw/") else entry
                                 for entry in base.files))
            self.assert_code("immutable_raw_changed", journal.prepare, record["operation_id"], bad)
            (self.root / record["snapshot_path"] / "wiki/Anna.md").write_bytes(b"corrupted")
            self.assert_code("snapshot_corrupt", journal.prepare, record["operation_id"], self.candidate(base))

    def test_failed_checkpoint_write_keeps_validating_and_live_data(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = self.validating(journal, base)
            with mock.patch.object(journal, "_save", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    journal.prepare(record["operation_id"], self.candidate(base))
            self.assertEqual(journal.get(record["operation_id"])["state"], "validating")
            self.assertEqual(len(journal.orphan_snapshots()), 1)
            self.assertEqual(len(journal.require_recovery()), 1)
        self.assertEqual(capture_snapshot(self.root).digest, base.digest)

    def test_failed_create_reports_orphan_without_inserting_partial_record(self):
        base = capture_snapshot(self.root)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            with mock.patch.object(storage, "canonical_json", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    journal.create("test", {}, "failed", base)
            self.assertEqual(journal.db.execute("SELECT count(*) FROM operations").fetchone(), (0,))
            self.assertEqual(len(journal.orphan_snapshots()), 1)
        self.assertEqual(capture_snapshot(self.root).digest, base.digest)

    def test_ignore_reinclusion_is_rejected_and_lock_is_released(self):
        with VaultLock(self.root):
            pass
        ignore = self.root / ".teseo/local/.gitignore"
        ignore.write_text("*\n!operations.sqlite\n", encoding="utf-8")
        self.assert_code("local_not_ignored", VaultLock(self.root).__enter__)
        ignore.write_text("*\n", encoding="utf-8")
        with VaultLock(self.root):
            pass

    @unittest.skipUnless(os.name == "nt", "Gate junction Windows")
    def test_junction_outside_data_root_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="teseo outside ") as outside:
            junction = self.root / "raw/outside"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), outside],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            try:
                self.assert_code("linked_path", capture_snapshot, self.root)
            finally:
                junction.rmdir()

    def test_crashed_operation_is_flagged_on_each_restart(self):
        process = self.child("--crash")
        self.assertEqual(process.wait(timeout=15), 19)
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            recovered = journal.require_recovery()
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["state"], "recovery_required")
            self.assertEqual(journal.require_recovery(), recovered)
            self.assertTrue((self.root / recovered[0]["snapshot_path"]).is_dir())


def child_mode(mode, root):
    with VaultLock(root, timeout=5) as lock:
        if mode == "--crash":
            with Journal(lock) as journal:
                record = journal.create("test", {}, "crash", capture_snapshot(root))
                journal.transition(record["operation_id"], "waiting_lock")
                journal.transition(record["operation_id"], "running")
                os._exit(19)
        local = root / ".teseo/local"
        (local / "ready").touch()
        deadline = time.monotonic() + 15
        while not (local / "release").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("timeout test lock")
            time.sleep(0.02)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("--hold", "--crash"):
        child_mode(sys.argv[1], Path(sys.argv[2]))
    else:
        unittest.main()
