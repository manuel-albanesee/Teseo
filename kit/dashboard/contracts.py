"""Contratti v1 puri: parsing e classificazione non modificano il vault.

Questo modulo è l'autorità runtime dei formati di base. Non adotta vault legacy,
non valida ancora lo schema dei singoli eventi e non autorizza scritture.
"""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from uuid import UUID

KIT_VERSION = "1.0.0"
SUPPORTED_VERSIONS = {"format_version": 1, "schema_version": 1, "event_version": 1}
MAX_INTEGER = 2**53 - 1
MAX_MANIFEST_BYTES = 64 * 1024
DEFAULT_SHARED_PATHS = (
    "wiki/", "raw/", "Wiki reference.md", "index.md", "log.md", ".teseo/shared/",
)


class ContractError(ValueError):
    """Errore serializzabile senza traceback o contenuto privato."""

    def __init__(self, code, message, path=None):
        super().__init__(message)
        self.code, self.path = code, path

    def as_dict(self):
        return {"code": self.code, "message": str(self), "path": self.path}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate_key", "Chiave JSON duplicata")
        result[key] = value
    return result


def _validate_json(value):
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise ContractError("non_nfc", "Stringa JSON non NFC")
        if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ContractError("invalid_unicode", "Surrogate Unicode isolato")
    elif value is None or type(value) is bool:
        return
    elif type(value) is int:
        if not -MAX_INTEGER <= value <= MAX_INTEGER:
            raise ContractError("integer_range", "Intero fuori intervallo JSON v1")
    elif isinstance(value, list):
        for item in value:
            _validate_json(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("invalid_key", "Le chiavi JSON devono essere stringhe")
            _validate_json(key)
            _validate_json(item)
    else:
        raise ContractError("invalid_value", "Valore non ammesso nel JSON v1")


def parse_json(data):
    """JSON UTF-8 senza BOM, chiavi duplicate, float o normalizzazioni implicite."""
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
        if not isinstance(value, dict):
            raise ContractError("invalid_root", "Il JSON deve contenere un oggetto")
        _validate_json(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError("invalid_json", "JSON UTF-8 non valido") from error


def canonical_json(value):
    """Byte canonici, LF incluso; conserva i campi opzionali sconosciuti."""
    if not isinstance(value, dict):
        raise ContractError("invalid_root", "Il JSON deve contenere un oggetto")
    _validate_json(value)
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def content_hash(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


def portable_path(path):
    """Valida una stringa relativa portabile, senza accedere al filesystem."""
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise ContractError("unsafe_path", "Percorso relativo non valido", path)
    parts = path.removesuffix("/").split("/")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((".", " "))
                or _RESERVED.match(part) or any(c in '<>:"|?*' or ord(c) < 32 for c in part)
                or any(0xD800 <= ord(c) <= 0xDFFF for c in part)
                or unicodedata.normalize("NFC", part) != part):
            raise ContractError("unsafe_path", "Nome non portabile", path)
    return path


def resolve_path(root, path):
    """Controlla anche symlink e junction; non garantisce esclusione da race."""
    portable_path(path)
    root = Path(root).resolve(strict=True)
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ContractError("path_escape", "Il percorso esce dal vault", path)
    return target


def validate_paths(paths):
    """Rifiuta collisioni anche su filesystem sensibili alle maiuscole."""
    seen = {}
    for path in paths:
        portable_path(path)
        # Controllare ogni prefisso rileva anche wiki/A e Wiki/B.
        parts = path.removesuffix("/").split("/")
        for end in range(1, len(parts) + 1):
            prefix = "/".join(parts[:end])
            key = prefix.casefold()
            if key in seen and seen[key] != prefix:
                raise ContractError("path_collision", "Collisione tra percorsi", path)
            seen[key] = prefix


class PathKind(str, Enum):
    MANIFEST = "manifest"
    MARKDOWN = "markdown"
    RAW = "immutable_raw"
    EVENT = "shared_event"
    GRAPH = "derived_graph"
    PERSONAL = "personal_legacy"
    LOCAL = "local"
    EXECUTABLE = "executable_or_client_config"
    UNKNOWN = "unknown"


def classify_path(path):
    """Classificazione conservativa: unknown non è un permesso di condivisione."""
    portable_path(path)
    if path == ".teseo/project.json":
        return PathKind.MANIFEST
    if path in (".graph/memoria.sqlite", ".graph/domande.sqlite") or any(
            path.startswith(f".graph/{name}.sqlite-") for name in ("memoria", "domande")):
        return PathKind.PERSONAL
    if path == ".graph/graph.sqlite" or path.startswith(".teseo/local/graphs/"):
        return PathKind.GRAPH
    if path.startswith((".teseo/local/", ".git/", ".graph_backup/")):
        return PathKind.LOCAL
    if path in ("AGENTS.md", "CLAUDE.md") or path.startswith((".agents/", ".claude/", ".codex/", ".github/", ".graph/")):
        return PathKind.EXECUTABLE
    if path.startswith("raw/"):
        return PathKind.RAW
    if path in ("Wiki reference.md", "index.md", "log.md") or (path.startswith("wiki/") and path.endswith(".md")):
        return PathKind.MARKDOWN
    if path.startswith(".teseo/shared/events/") and path.endswith(".json"):
        return PathKind.EVENT
    return PathKind.UNKNOWN


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ContractError("invalid_version", "Versione kit attesa: major.minor.patch")
    return tuple(map(int, value.split(".")))


def parse_manifest(data):
    manifest = parse_json(data)
    required = {*SUPPORTED_VERSIONS, "vault_id", "minimum_kit_version", "shared_paths"}
    if not required <= manifest.keys():
        raise ContractError("missing_field", "Manifest incompleto", ".teseo/project.json")
    for field, supported in SUPPORTED_VERSIONS.items():
        if type(manifest[field]) is not int or manifest[field] != supported:
            raise ContractError("unsupported_version", f"Versione non supportata: {field}")
    try:
        UUID(manifest["vault_id"])
    except (ValueError, TypeError, AttributeError) as error:
        raise ContractError("invalid_vault_id", "vault_id deve essere un UUID") from error
    if _version(manifest["minimum_kit_version"]) > _version(KIT_VERSION):
        raise ContractError("kit_too_old", "Il vault richiede un kit più recente")
    paths = manifest["shared_paths"]
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise ContractError("invalid_shared_paths", "shared_paths deve essere una lista di percorsi")
    validate_paths(paths)
    if len(paths) != len(set(paths)) or any(p not in DEFAULT_SHARED_PATHS for p in paths):
        raise ContractError("invalid_shared_paths", "Selezione dati fuori allowlist o duplicata")
    return manifest


@dataclass(frozen=True)
class VaultCompatibility:
    mode: str
    manifest: dict | None = None
    issues: tuple = ()


def inspect_vault(root):
    """Legacy resta readonly; un manifest incompatibile non innesca migrazioni."""
    try:
        root = Path(root).resolve(strict=True)
        if not root.is_dir() or not (root / "wiki").is_dir() or not (root / "Wiki reference.md").is_file():
            raise ContractError("invalid_vault", "Attesi wiki/ e Wiki reference.md")
        resolve_path(root, "wiki/")
        resolve_path(root, "Wiki reference.md")
        path = resolve_path(root, ".teseo/project.json")
        if not path.exists():
            return VaultCompatibility("legacy_readonly")
        with path.open("rb") as stream:
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise ContractError("manifest_too_large", "Manifest oltre 64 KiB")
        return VaultCompatibility("compatible", parse_manifest(data))
    except ContractError as error:
        return VaultCompatibility("incompatible", issues=(error.as_dict(),))
    except OSError:
        error = ContractError("vault_unreadable", "Vault o manifest non accessibile")
        return VaultCompatibility("incompatible", issues=(error.as_dict(),))
