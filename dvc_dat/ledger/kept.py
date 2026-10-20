"""The kept cache: the bytes of values sealed with ``v.seal(keep=True)`` and not yet saved.

``v.seal(keep=True)`` copies the value's bytes here, by hash, so a later change to the
folder or object it came from cannot break the seal; ``v.seal(t)`` saves from these bytes
and drops the entry at commit. What stays is sealed and never saved: ``listing`` shows it,
``purge`` removes it. The root is ``$DAT_KEPT``, else ``~/.cache/dvc-dat/kept``. Layout:
``blobs/<sha256>`` (one file per distinct blob) and ``sealed/<hash>.json`` (one per value).

    just sealed                       # the listing (python -m dvc_dat.ledger.kept)
    just sealed purge [older=14d]     # drop values sealed more than 14 days ago, never saved
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .codec import sha256


def root() -> Path:
    env = os.environ.get("DAT_KEPT")
    return Path(env) if env else Path.home() / ".cache" / "dvc-dat" / "kept"


class Kept:
    """One kept cache folder."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.root = Path(path) if path is not None else root()

    def _entry_path(self, h: str) -> Path:
        return self.root / "sealed" / f"{h}.json"

    def _blob_path(self, h: str) -> Path:
        return self.root / "blobs" / h

    def put(self, kind: str, data: bytes, parts: Iterable[bytes], sealed_at: str) -> str:
        """Keep ``data`` (the encoding) and its ``parts``; return the encoding's hash."""
        h = sha256(data)
        names = []
        for blob in [*parts, data]:
            b = sha256(blob)
            p = self._blob_path(b)
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + ".tmp")
                tmp.write_bytes(blob)
                os.replace(tmp, p)
            names.append(b)
        e = self._entry_path(h)
        e.parent.mkdir(parents=True, exist_ok=True)
        e.write_text(json.dumps({"kind": kind, "sealed_at": sealed_at, "parts": names[:-1],
                                 "bytes": sum(self._blob_path(n).stat().st_size for n in names)}, indent=1))
        return h

    def get(self, h: str) -> bytes:
        """One blob by hash; ``KeyError`` when the cache does not hold it (purged)."""
        p = self._blob_path(h)
        if not p.is_file():
            raise KeyError(f"{h[:12]}…: not in the kept cache {self.root} (purged?)")
        return p.read_bytes()

    def entry(self, h: str) -> Dict[str, Any]:
        p = self._entry_path(h)
        if not p.is_file():
            raise KeyError(f"{h[:12]}…: no kept value in {self.root} (purged?)")
        return json.loads(p.read_text())

    def listing(self) -> List[Dict[str, Any]]:
        """Every kept value, oldest first: ``hash``, ``kind``, ``sealed_at``, ``bytes``."""
        folder = self.root / "sealed"
        out = [{"hash": p.stem, **json.loads(p.read_text())} for p in folder.glob("*.json")] if folder.is_dir() else []
        return sorted(out, key=lambda e: e["sealed_at"])

    def drop(self, h: str) -> None:
        """Forget one value and every blob no other kept value names."""
        e = self._entry_path(h)
        if not e.is_file():
            return
        e.unlink()
        live = set()
        for other in self.listing():
            live.update(other["parts"])
            live.add(other["hash"])
        folder = self.root / "blobs"
        for p in (folder.iterdir() if folder.is_dir() else []):
            if p.name not in live:
                p.unlink()

    def purge(self, older: _dt.timedelta) -> List[str]:
        """Drop every value sealed more than ``older`` ago; return their hashes."""
        cut = (_dt.datetime.now(_dt.timezone.utc) - older).strftime("%Y-%m-%dT%H:%M:%SZ")
        gone = [e["hash"] for e in self.listing() if e["sealed_at"] <= cut]
        for h in gone:
            self.drop(h)
        return gone


def age(text: str) -> _dt.timedelta:
    """``14d``, ``12h``, ``30m``: a purge age."""
    m = re.fullmatch(r"(\d+)([dhm])", text)
    if not m:
        raise ValueError(f"an age is <n>d, <n>h or <n>m, not {text!r}")
    n, unit = int(m.group(1)), m.group(2)
    return _dt.timedelta(**{{"d": "days", "h": "hours", "m": "minutes"}[unit]: n})


def main(argv: List[str]) -> int:
    k = Kept()
    if not argv:
        rows = k.listing()
        for e in rows:
            print(f"{e['hash'][:12]}  {e['sealed_at']}  {e['bytes']:>12,}  {e['kind']}")
        print(f"{len(rows)} kept, sealed and never saved, in {k.root}")
        return 0
    if argv[0] == "purge" and len(argv) <= 2:
        gone = k.purge(age(argv[1].removeprefix("older=") if len(argv) == 2 else "14d"))
        print(f"purged {len(gone)} from {k.root}")
        return 0
    print("usage: just sealed [purge [older=14d]]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
