"""The kept cache: the bytes of values sealed with ``v.seal(keep=True)`` and not yet saved.

``v.seal(keep=True)`` copies the value's bytes here, by hash, so a later change to the
folder or object it came from cannot break the seal; ``v.seal(t)`` saves from these bytes
and drops the entry at commit. What stays is sealed and never saved: ``listing`` shows it,
``purge`` removes it. The root is ``$DAT_KEPT``, else ``~/.cache/dvc-dat/kept``. Layout:
``blobs/<sha256>`` (one file per distinct blob) and ``sealed/<entry>.json`` (one per keep).

    just sealed                       # the listing (python -m dvc_dat.ledger.kept)
    just sealed purge [older=14d]     # drop values sealed more than 14 days ago, never saved
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .codec import sha256
from .store import Part, place


def root() -> Path:
    env = os.environ.get("DAT_KEPT")
    return Path(env) if env else Path.home() / ".cache" / "dvc-dat" / "kept"


class Kept:
    """One kept cache folder. Each ``v.seal(keep=True)`` is its own entry, so two values with equal
    bytes keep two entries over one set of blobs, and saving one leaves the other saveable."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.root = Path(path) if path is not None else root()

    def _entry_path(self, entry: str) -> Path:
        return self.root / "sealed" / f"{entry}.json"

    def _blob_path(self, h: str) -> Path:
        return self.root / "blobs" / h

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def put(self, kind: str, data: bytes, parts: Iterable[Part], sealed_at: str) -> str:
        """Keep ``data`` (the encoding) and its ``parts`` (``(sha256, source)``); return the new entry's id.

        Each part is copied into ``blobs/`` in 1 MiB blocks and checked against its hash, never read
        whole; it is copied, not linked, so a later in-place write to the source cannot reach it.
        """
        names = []
        for h, source in parts:
            place(source, self._blob_path(h), h, link=False)
            names.append(h)
        b = sha256(data)
        if not self._blob_path(b).exists():
            self._write(self._blob_path(b), data)
        names.append(b)
        entry = f"{sealed_at.replace(':', '')}-{uuid.uuid4().hex[:12]}"
        self._write(self._entry_path(entry), json.dumps(
            {"hash": names[-1], "kind": kind, "sealed_at": sealed_at, "parts": names[:-1],
             "bytes": sum(self._blob_path(n).stat().st_size for n in dict.fromkeys(names))}, indent=1).encode())
        return entry

    def get(self, h: str) -> bytes:
        """One blob by hash; ``KeyError`` when the cache does not hold it (purged)."""
        return self.blob(h).read_bytes()

    def blob(self, h: str) -> Path:
        """The file holding one blob; ``KeyError`` when the cache does not hold it (purged)."""
        p = self._blob_path(h)
        if not p.is_file():
            raise KeyError(f"{h[:12]}…: not in the kept cache {self.root} (purged?)")
        return p

    def entry(self, entry: str) -> Dict[str, Any]:
        p = self._entry_path(entry)
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            raise KeyError(f"{entry}: no readable kept entry in {self.root} (purged?)") from None

    def listing(self) -> List[Dict[str, Any]]:
        """Every kept entry, oldest first: ``entry``, ``hash``, ``kind``, ``sealed_at``, ``bytes``; an
        unreadable entry file is listed with ``kind`` ``<unreadable>`` rather than stopping the listing."""
        folder = self.root / "sealed"
        out = []
        for p in (sorted(folder.glob("*.json")) if folder.is_dir() else []):
            try:
                out.append({"entry": p.stem, **json.loads(p.read_text())})
            except (OSError, ValueError):
                out.append({"entry": p.stem, "hash": "", "kind": "<unreadable>", "sealed_at": "", "parts": [],
                            "bytes": 0})
        return sorted(out, key=lambda e: e["sealed_at"])

    def drop(self, entry: str) -> None:
        """Forget one entry; its blobs stay until ``purge`` collects what no entry names."""
        try:
            self._entry_path(entry).unlink()
        except FileNotFoundError:
            pass

    def purge(self, older: _dt.timedelta) -> List[str]:
        """Drop every entry sealed more than ``older`` ago (and every unreadable one), then every blob
        no entry names and older than an hour (a concurrent ``put`` may not have written its entry yet)."""
        cut = (_dt.datetime.now(_dt.timezone.utc) - older).strftime("%Y-%m-%dT%H:%M:%SZ")
        gone = [e["entry"] for e in self.listing() if e["sealed_at"] <= cut]
        for entry in gone:
            self.drop(entry)
        live = set()
        for e in self.listing():
            live.update(e["parts"])
            live.add(e["hash"])
        settled = _dt.datetime.now().timestamp() - 3600
        folder = self.root / "blobs"
        for p in (folder.iterdir() if folder.is_dir() else []):
            if p.name not in live and not p.name.endswith(".tmp") and p.stat().st_mtime < settled:
                p.unlink(missing_ok=True)
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
            print(f"{e['hash'][:12]:12}  {e['sealed_at']:20}  {e['bytes']:>12,}  {e['kind']}")
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
