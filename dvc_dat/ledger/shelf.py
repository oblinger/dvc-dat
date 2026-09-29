"""The artifact shelf: hash-keyed, write-once bytes the ledger's references point at.

Only the box's local shelf ships. Its layout is a bucket's:
``sha256/<ab>/<rest>`` holds the payload (a file, or a folder for a ``ckpt``),
``sha256/<ab>/<rest>._art_.yaml`` its sidecar (type, size, hash, names -- what a
cloud shelf keeps as object tags), and ``_index_.json`` maps every given name
to its hash, rebuilt from the sidecars by :meth:`LocalShelf.reindex`. A cloud
shelf is another :class:`Shelf`: ``head`` a head request, ``path`` a download
into the local cache, ``region`` its region for the whereabouts table.
"""

from __future__ import annotations

import fcntl
import hashlib
import json as _json
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import yaml

from ..core import _hash_payload, _sha256_file
from .types import Source

SIDECAR = "._art_.yaml"
INDEX = "_index_.json"


@dataclass
class ShelfEntry:
    """What a shelf knows of one object without fetching it."""

    hash: str
    type: str
    size: int
    names: List[str] = field(default_factory=list)


def is_hash(rid: str) -> bool:
    hexd = rid[len("sha256:"):] if rid.startswith("sha256:") else ""
    return len(hexd) == 64 and all(c in "0123456789abcdef" for c in hexd)


class Shelf(ABC):
    """One copy of the store: identity without a fetch (``head``), bytes with one (``path``)."""

    region: str

    @abstractmethod
    def head(self, rid: str) -> Optional[ShelfEntry]:
        """The entry a name or a hash keys, or ``None``."""

    @abstractmethod
    def put(self, source: Source, type_token: str, name: Optional[str] = None) -> ShelfEntry:
        """Store ``source`` (bytes, or a file's or folder's path) under its hash, and ``name`` as a second key."""

    @abstractmethod
    def path(self, rid: str) -> Path:
        """The payload on local disk; ``FileNotFoundError`` when this shelf does not hold it."""


class LocalShelf(Shelf):
    """The box's ``art/``: the only cache, and on the SQLite backend the whole store."""

    def __init__(self, root: Path, region: str = "local") -> None:
        self.root = Path(root)
        self.region = region

    # -- layout ---------------------------------------------------------

    def _payload(self, h: str) -> Path:
        hexd = h[len("sha256:"):]
        return self.root / "sha256" / hexd[:2] / hexd[2:]

    def _sidecar(self, h: str) -> Path:
        p = self._payload(h)
        return p.with_name(p.name + SIDECAR)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / ".lock", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read_index(self) -> Dict[str, str]:
        p = self.root / INDEX
        if not p.is_file():
            return {}
        data = _json.loads(p.read_text() or "{}")
        return {str(k): str(v) for k, v in data.items()}

    def _write_atomic(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)

    def _read_sidecar(self, h: str) -> Optional[ShelfEntry]:
        p = self._sidecar(h)
        if not p.is_file():
            return None
        d = yaml.safe_load(p.read_text()) or {}
        return ShelfEntry(hash=str(d["sha256"]), type=str(d["type"]), size=int(d["size"]),
                          names=[str(n) for n in d.get("names") or []])

    def _write_sidecar(self, e: ShelfEntry) -> None:
        self._write_atomic(self._sidecar(e.hash), yaml.safe_dump(
            {"sha256": e.hash, "type": e.type, "size": e.size, "names": e.names}, sort_keys=True))

    # -- Shelf ----------------------------------------------------------

    def head(self, rid: str) -> Optional[ShelfEntry]:
        h = rid if is_hash(rid) else self._read_index().get(rid)
        return None if h is None else self._read_sidecar(h)

    def put(self, source: Source, type_token: str, name: Optional[str] = None) -> ShelfEntry:
        if name is not None and (not isinstance(name, str) or not name or name.startswith("sha256:")):
            raise ValueError(f"an artifact name is a non-empty str not starting 'sha256:', not {name!r}")
        if isinstance(source, bytes):
            h, size = "sha256:" + hashlib.sha256(source).hexdigest(), len(source)
        else:
            src = Path(source)
            h = source_sha256(src)
            size = src.stat().st_size if src.is_file() else sum(
                f.stat().st_size for f in src.rglob("*") if f.is_file())
        with self._locked():
            index = self._read_index()
            if name is not None and index.get(name, h) != h:
                raise FileExistsError(f"artifact name {name!r} already holds {index[name][:19]}…, not {h[:19]}…")
            entry = self._read_sidecar(h)
            if entry is None:
                self._store_payload(source, h)
                entry = ShelfEntry(hash=h, type=type_token, size=size)
            if name is not None and name not in entry.names:
                entry.names.append(name)
                index[name] = h
                self._write_atomic(self.root / INDEX, _json.dumps(index, sort_keys=True, indent=1))
            self._write_sidecar(entry)
        return entry

    def _store_payload(self, source: Source, h: str) -> None:
        dest = self._payload(h)
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".tmp-")) / "payload"
        if isinstance(source, bytes):
            tmp.write_bytes(source)
        elif Path(source).is_dir():
            shutil.copytree(source, tmp)
        else:
            shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
        tmp.parent.rmdir()

    def path(self, rid: str) -> Path:
        entry = self.head(rid)
        p = None if entry is None else self._payload(entry.hash)
        if p is None or not p.exists():
            raise FileNotFoundError(f"artifact {rid!r}: no store reachable from here holds it (shelf {self.root})")
        return p

    def reindex(self) -> Dict[str, str]:
        """Rebuild ``_index_.json`` from the sidecars, the index's source of truth."""
        index: Dict[str, str] = {}
        with self._locked():
            for side in sorted((self.root / "sha256").glob("*/*" + SIDECAR)):
                d = yaml.safe_load(side.read_text()) or {}
                for n in d.get("names") or []:
                    index[str(n)] = str(d["sha256"])
            self._write_atomic(self.root / INDEX, _json.dumps(index, sort_keys=True, indent=1))
        return index


def source_sha256(path: Path) -> str:
    """``"sha256:<hex>"`` of a file or folder, the hash dvc-dat's own artifact store records."""
    path = Path(path)
    if path.is_file():
        return "sha256:" + _sha256_file(str(path))
    if not path.is_dir():
        raise FileNotFoundError(f"{path}: no file or folder to hash")
    return "sha256:" + _hash_payload(str(path), ".")
