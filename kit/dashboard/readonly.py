"""Registro temporaneo dei vault collegati; nessuna scrittura nel filesystem."""
import os
from pathlib import Path
import threading
from uuid import UUID, NAMESPACE_URL, uuid5

from .contracts import ContractError, inspect_vault


class VaultRegistry:
    def __init__(self):
        self._roots = {}
        self._lock = threading.RLock()

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
        if compatibility.mode == "incompatible":
            message = compatibility.issues[0]["message"] if compatibility.issues else "Formato non supportato"
            raise ContractError("incompatible_vault", message)
        vault_id = (str(UUID(compatibility.manifest["vault_id"])) if compatibility.manifest else
                    str(uuid5(NAMESPACE_URL, "teseo-local:" + os.path.normcase(str(root)))))
        return {"vault_id": vault_id, "path": str(root), "mode": "readonly",
                "compatibility": compatibility.mode, "issues": list(compatibility.issues),
                "capabilities": {"attach_readonly": True, "graph": False, "rebuild": False,
                                 "write_notes": False, "sync": False},
                "content_revision": None, "graph_generation": None}

    def attach(self, value):
        root = self._root(value)
        result = self._description(root)
        with self._lock:
            existing = self._roots.get(result["vault_id"])
            if existing is not None and existing != root:
                raise ContractError("vault_id_conflict", "Questo UUID è già collegato a un altro clone")
            if len(self._roots) >= 32 and existing is None:
                raise ContractError("vault_limit", "Massimo 32 vault per sessione")
            self._roots[result["vault_id"]] = root
        return result

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
