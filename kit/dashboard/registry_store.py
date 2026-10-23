"""Registro opzionale, locale al servizio: nessun token né codice dei vault."""
import os
from pathlib import Path
import tempfile
from uuid import UUID

from .contracts import ContractError, canonical_json, parse_json
from .storage import _no_link


class RegistryStore:
    def __init__(self, value):
        path = Path(value)
        if not path.is_absolute() or str(path).startswith(("\\", "//")):
            raise ContractError("invalid_registry", "Il registro richiede un file locale assoluto")
        for parent in (*reversed(path.parents), path):
            _no_link(parent)
        self.path = path.resolve()
        if not self.path.parent.is_dir():
            raise ContractError("invalid_registry", "La directory del registro deve già esistere")
        lock = self.path.with_name(self.path.name + ".lock")
        _no_link(lock)
        self._stream = lock.open("a+b")
        try:
            if lock.stat().st_size == 0:
                self._stream.write(b"\0")
                self._stream.flush()
            self._stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._stream.close()
            raise ContractError("registry_busy", "Registro già utilizzato da un altro servizio") from None

    def read(self):
        _no_link(self.path)
        if not self.path.exists():
            return []
        with self.path.open("rb") as stream:
            data = stream.read(64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise ContractError("invalid_registry", "Registro oltre 64 KiB")
        record = parse_json(data)
        paths = record.get("vaults")
        if (record.get("format_version") != 1 or type(record.get("format_version")) is not int
                or set(record) != {"format_version", "vaults"} or not isinstance(paths, list)
                or len(paths) > 32 or any(not isinstance(entry, dict)
                    or set(entry) != {"path", "vault_id"}
                    or not isinstance(entry["path"], str) or not isinstance(entry["vault_id"], str)
                    for entry in paths)):
            raise ContractError("invalid_registry", "Formato registro non supportato")
        try:
            if (len({entry["path"] for entry in paths}) != len(paths)
                    or len({entry["vault_id"] for entry in paths}) != len(paths)
                    or any(str(UUID(entry["vault_id"])) != entry["vault_id"] for entry in paths)):
                raise ValueError
        except ValueError:
            raise ContractError("invalid_registry", "Registro con identità duplicate o non valide") from None
        return paths

    def write(self, paths):
        for parent in (*reversed(self.path.parents), self.path):
            _no_link(parent)
        _no_link(self.path)
        data = canonical_json({"format_version": 1, "vaults": paths})
        if len(data) > 64 * 1024:
            raise ContractError("invalid_registry", "Registro oltre 64 KiB")
        fd, name = tempfile.mkstemp(prefix=".vaults-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def close(self):
        self._stream.close()
