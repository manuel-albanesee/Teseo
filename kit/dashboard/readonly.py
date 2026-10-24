"""Attach readonly; persistenza opzionale nel solo file scelto dal launcher."""
import os
from pathlib import Path
import threading
from uuid import UUID, NAMESPACE_URL, uuid5

from .contracts import ContractError, inspect_vault, VaultCompatibility, parse_manifest, parse_json


class VaultRegistry:
    def __init__(self, store_path=None):
        self._roots = {}
        self._lock = threading.RLock()
        self._store = None
        self.restore_issues = []
        if store_path is not None:
            from .registry_store import RegistryStore
            store = RegistryStore(store_path)
            try:
                for entry in store.read():
                    try:
                        result = self.attach(entry["path"])
                        if result["vault_id"] != entry["vault_id"]:
                            self._roots.pop(result["vault_id"], None)
                            raise ContractError("vault_identity_changed", "Identità salvata non corrispondente")
                    except ContractError as error:
                        self.restore_issues.append({"code": error.code,
                            "message": "Un vault salvato non è più disponibile; collegarlo nuovamente"})
                self._store = store
            except BaseException:
                store.close()
                raise

    @staticmethod
    def _root(value):
        if (not isinstance(value, str) or not value or len(value) > 4096
                or value.startswith(("\\", "//")) or "://" in value
                or "\0" in value or not Path(value).is_absolute()):
            raise ContractError("invalid_vault_path", "Indicare una cartella locale con percorso assoluto")
        try:
            return Path(value).resolve(strict=True)
        except (OSError, ValueError):
            raise ContractError("vault_unreadable", "Cartella vault non accessibile") from None

    @staticmethod
    def _description(root):
        compatibility = inspect_vault(root)
        if compatibility.mode == 'incompatible' and not (root / 'Wiki reference.md').exists():
            # Recovery-only attach: compatible identity plus a durable interrupted ontology record.
            from .storage import _compatible_root, _no_link
            import sqlite3
            try:
                _, identifier = _compatible_root(root, allow_missing_schema=True)
                for relative in ('.teseo/local', '.teseo/local/operations.sqlite'):
                    _no_link(root / relative)
                db = sqlite3.connect((root / '.teseo/local/operations.sqlite').as_uri() + '?mode=ro', uri=True)
                try:
                    records = [parse_json(row[0]) for row in db.execute('SELECT record FROM operations WHERE length(record)<=5242880 ORDER BY rowid DESC LIMIT 128')]
                finally:
                    db.close()
                if any(item.get('vault_id') == identifier and item.get('kind') in ('ontology_apply','ingest_lint','lint','fill_gaps')
                       and item.get('state') in ('prepared', 'applying', 'recovery_required') for item in records):
                    with (root / '.teseo/project.json').open('rb') as stream:
                        manifest = parse_manifest(stream.read(65537))
                    compatibility = VaultCompatibility('recovery_required', manifest,
                        ({'code':'recovery_required','message':'Schema assente dopo un’operazione interrotta: usare recovery esplicito'},))
            except (ContractError, OSError, sqlite3.Error):
                pass
        if compatibility.mode == "incompatible":
            message = compatibility.issues[0]["message"] if compatibility.issues else "Formato non supportato"
            raise ContractError("incompatible_vault", message)
        vault_id = (str(UUID(compatibility.manifest["vault_id"])) if compatibility.manifest else
                    str(uuid5(NAMESPACE_URL, "teseo-local:" + os.path.normcase(str(root)))))
        return {"vault_id": vault_id, "path": str(root), "mode": "readonly",
                "compatibility": compatibility.mode, "issues": list(compatibility.issues),
                "schema_version": compatibility.manifest["schema_version"] if compatibility.manifest else None,
                "capabilities": {"attach_readonly": True, "graph": False, "rebuild": False,
                                 "ontology_preview": compatibility.mode == 'compatible',
                                 "shared_state": compatibility.mode == 'compatible',
                                 "ontology_apply": compatibility.mode == 'compatible' and os.name == 'nt',
                                 "ontology_apply_automatic": False, "external_writer_exclusion": False,
                                 "write_notes": False, "sync": compatibility.mode == 'compatible',
                                 "sync_automatic": False},
                "content_revision": None, "graph_generation": None}

    def attach(self, value):
        root = self._root(value)
        result = self._description(root)
        with self._lock:
            existing = self._roots.get(result["vault_id"])
            if existing is not None and existing != root:
                raise ContractError("vault_id_conflict", "Questo UUID è già collegato a un altro clone")
            replaced = [identifier for identifier, path in self._roots.items()
                        if path == root and identifier != result["vault_id"]]
            if len(self._roots) - len(replaced) >= 32 and existing is None:
                raise ContractError("vault_limit", "Massimo 32 vault per sessione")
            previous = dict(self._roots)
            for identifier in replaced:
                del self._roots[identifier]
            self._roots[result["vault_id"]] = root
            try:
                if self._store is not None:
                    self._store.write([{"vault_id": identifier, "path": str(path)}
                                       for identifier, path in self._roots.items()])
            except (ContractError, OSError):
                self._roots = previous
                raise ContractError("registry_unavailable", "Registro non salvato; collegamento non aggiunto") from None
        return result

    def close(self):
        if self._store is not None:
            self._store.close()

    def status(self, vault_id):
        with self._lock:
            root = self._roots.get(vault_id)
        if root is None:
            raise ContractError("vault_missing", "Vault non collegato in questa sessione")
        if self._root(str(root)) != root:
            raise ContractError("vault_path_changed", "La cartella collegata è stata sostituita")
        result = self._description(root)
        if result["vault_id"] != vault_id:
            raise ContractError("vault_identity_changed", "Identità vault cambiata; collegare nuovamente")
        return result

    def list(self):
        with self._lock:
            identifiers = list(self._roots)
        return [self.status(identifier) for identifier in identifiers]

    def root(self, vault_id):
        self.status(vault_id)
        with self._lock:
            return self._roots[vault_id]

    def operation_root(self, vault_id):
        """Polling/recovery restano leggibili durante un replace interrotto dello schema."""
        from .storage import _compatible_root
        with self._lock:
            root = self._roots.get(vault_id)
        if root is None:
            raise ContractError('vault_missing', 'Vault non collegato')
        if self._root(str(root)) != root:
            raise ContractError('vault_path_changed', 'Percorso vault cambiato')
        if _compatible_root(root, allow_missing_schema=True)[1] != vault_id:
            raise ContractError('vault_identity_changed', 'Identità vault cambiata')
        return root
