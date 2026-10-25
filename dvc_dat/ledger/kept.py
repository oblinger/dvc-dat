"""The seal records and the kept cache: every ``v.seal()``, and the bytes of those sealed with ``keep=True``.

Every ``v.seal()`` writes a record, ``sealed/<entry>.json``: the hash, the kind, the time, the
folder (``path``, for a ``Dat``), the deps (as ``ref:`` texts with their subject, hash and
name), the provenance, the preds, the environment, ``kept``, and ``bytes``. A later process
reopens a sealed ``Dat`` from it (``Dat.sealed_at_path``) and saves it exactly as the sealing
process would. ``v.seal(keep=True)`` also copies the value's bytes here, by hash, so a later
change to the folder or object it came from cannot break the seal. ``v.seal(t)`` drops the
record at commit. What stays is sealed and never saved: ``listing`` shows it, ``purge``
removes it. The root is ``$DAT_KEPT``, else ``~/.cache/dvc-dat/kept``. Layout:
``blobs/<sha256>`` (one file per distinct kept blob) and ``sealed/<entry>.json`` (one per seal).
A new seal of a folder replaces the unkept records of that folder (their bytes are gone).

    just sealed                       # the listing (python -m dvc_dat.ledger.kept)
    just sealed purge [older=14d]     # drop values sealed more than 14 days ago, never saved
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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

    def seal(self, record: Dict[str, Any], data: Optional[bytes] = None, parts: Iterable[Part] = ()) -> str:
        """Write the record of one ``v.seal()``; with ``data`` (``keep=True``) keep the encoding and its
        ``parts`` (``(sha256, source)``) too. Returns the new entry's id.

        Each part is cloned into ``blobs/`` copy-on-write where the filesystem can (APFS ``clonefile``,
        Linux reflink: no disk), else copied in 1 MiB blocks; either way checked against its hash, never
        read whole, and never linked, so a later in-place write to the source cannot reach it.
        An unkept record of a folder replaces the unkept records of that folder.
        """
        rec = dict(record)
        rec["kept"] = data is not None
        rec["parts"] = []
        if data is not None:
            names = []
            for h, source in parts:
                place(source, self._blob_path(h), h, link=False, clone_ok=True)
                names.append(h)
            b = sha256(data)
            if not self._blob_path(b).exists():
                self._write(self._blob_path(b), data)
            rec["parts"] = names
            rec["bytes"] = sum(self._blob_path(n).stat().st_size for n in dict.fromkeys(names + [b]))
        entry = f"{rec['sealed_at'].replace(':', '')}-{time.time_ns():x}-{uuid.uuid4().hex[:8]}"   # sorts by time
        if rec.get("path") and not rec["kept"]:
            for e in self.listing():
                if e.get("path") == rec["path"] and not e.get("kept"):
                    self.drop(e["entry"])
        self._write(self._entry_path(entry), json.dumps(rec, indent=1).encode())
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
        """One record, ``entry`` included; ``KeyError`` when gone (saved, superseded or purged)."""
        p = self._entry_path(entry)
        try:
            return {"entry": entry, **json.loads(p.read_text())}
        except (OSError, ValueError):
            raise KeyError(f"{entry}: no readable kept entry in {self.root} (purged?)") from None

    def listing(self) -> List[Dict[str, Any]]:
        """Every record, oldest first: ``entry`` and the record's fields; an unreadable record file is
        listed with ``kind`` ``<unreadable>`` rather than stopping the listing."""
        folder = self.root / "sealed"
        out = []
        for p in (sorted(folder.glob("*.json")) if folder.is_dir() else []):
            try:
                out.append({"entry": p.stem, **json.loads(p.read_text())})
            except (OSError, ValueError):
                out.append({"entry": p.stem, "hash": "", "kind": "<unreadable>", "sealed_at": "", "parts": [],
                            "bytes": 0})
        return sorted(out, key=lambda e: (e.get("sealed_at") or "", e["entry"]))

    def for_path(self, path: Any) -> Optional[Dict[str, Any]]:
        """The latest record of the folder ``path`` (resolved), or ``None``."""
        want = str(Path(path).resolve())
        found = [e for e in self.listing() if e.get("path") == want]
        return found[-1] if found else None

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
        gone = [e["entry"] for e in self.listing() if (e.get("sealed_at") or "") <= cut]
        for entry in gone:
            self.drop(entry)
        live = set()
        for e in self.listing():
            live.update(e.get("parts") or [])
            live.add(e.get("hash") or "")
        settled = _dt.datetime.now().timestamp() - 3600
        folder = self.root / "blobs"
        for p in (folder.iterdir() if folder.is_dir() else []):
            if p.name not in live and not p.name.endswith(".tmp") and p.stat().st_mtime < settled:
                p.unlink(missing_ok=True)
        return gone


# -- the record's deps, preds and environment ---------------------------------------------------

class SealedRef:
    """A dep or a typed pred as a seal record holds it: the ``ref:`` text, and the subject when it was
    saved by then, else the name it will be found by (``Dat.sealed_at_path(..., name=)``)."""

    __slots__ = ("text", "subject", "hash", "name")

    def __init__(self, text: str, subject: Optional[str], hash: Optional[str], name: Optional[str]) -> None:
        self.text, self.subject, self.hash, self.name = text, subject, hash, name

    def __repr__(self) -> str:
        return self.name or self.subject or self.text


class SealedFn:
    """A function dep as a seal record holds it: its subject and its ``db/fn`` rows."""

    __slots__ = ("subject", "rows")

    def __init__(self, subject: str, rows: Sequence[Tuple[str, str]]) -> None:
        self.subject, self.rows = subject, [tuple(r) for r in rows]

    def _rows(self) -> List[Tuple[str, str]]:
        return list(self.rows)


def ref_record(x: Any) -> Dict[str, Any]:
    """A ``Value``, ``Ref``, ``Fn`` (or one of the above) as JSON."""
    from .codec import ref_text
    from .fn import Fn
    from .rev import Ref
    from .value import Value, dotted

    if isinstance(x, (Fn, SealedFn)):
        return {"fn": x.subject, "rows": [list(r) for r in x._rows()]}
    if isinstance(x, SealedRef):
        return {"text": x.text, "subject": x.subject, "hash": x.hash, "name": x.name}
    if isinstance(x, Ref):
        s = x.subject
        return {"text": x._text(), "subject": s, "hash": x.hash, "name": x.name if x.name and x.name != s else None}
    if isinstance(x, Value):
        h = x.hash
        return {"text": ref_text(dotted(type(x)), h), "subject": x.subject, "hash": h,
                "name": x.__dict__.get("_loaded_as")}
    raise TypeError(f"a dep is a Value, a Ref or an Fn, not {type(x).__name__}")


def ref_from(d: Dict[str, Any]) -> Any:
    if "fn" in d:
        return SealedFn(d["fn"], d["rows"])
    return SealedRef(d["text"], d["subject"], d["hash"], d["name"])


def preds_record(preds: Dict[str, Any]) -> Dict[str, Any]:
    """A value's preds as JSON: plain values as they are, an edge to a value as its ref."""
    from .rev import Ref
    from .value import Value

    def enc(k: str, v: Any) -> Any:
        if isinstance(v, (Value, Ref, SealedRef)):
            return {"ref": ref_record(v)}
        if isinstance(v, (list, tuple)):
            return {"list": [enc(k, m) for m in v]}
        if isinstance(v, dict):
            try:
                json.dumps(v)
            except (TypeError, ValueError):
                raise TypeError(f"pred {k!r}: a dict of plain values, not {v!r}") from None
            return {"json": v}
        if v is None or isinstance(v, (str, bool, int, float)):
            return {"v": v}
        raise TypeError(f"pred {k!r}: a pred value is a str (an int, float or bool is coerced), "
                        f"not {type(v).__name__}")
    return {k: enc(k, v) for k, v in preds.items()}


def preds_from(d: Dict[str, Any]) -> Dict[str, Any]:
    def dec(x: Dict[str, Any]) -> Any:
        if "ref" in x:
            return ref_from(x["ref"])
        if "list" in x:
            return [dec(m) for m in x["list"]]
        return x["json"] if "json" in x else x["v"]
    return {k: dec(v) for k, v in d.items()}


def env_record(env: Any) -> Dict[str, Any]:
    return {"code": {repo: {"version": c.version, "commit": c.commit, "dirty": c.dirty,
                            "path": None if c.path is None else str(c.path)} for repo, c in env.code.items()},
            "platform": env.platform, "mounts": env.mounts}


def env_from(d: Dict[str, Any]) -> Any:
    from .env import Checkout, Env

    code = {repo: Checkout(c["version"], c["commit"], bool(c["dirty"]), None if c["path"] is None else Path(c["path"]))
            for repo, c in d["code"].items()}
    return Env(code, d["platform"], d.get("mounts"))



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
            what = e.get("path") or e.get("kind", "")
            print(f"{(e.get('hash') or '')[:12]:12}  {e.get('sealed_at') or '':20}  {e.get('bytes') or 0:>12,}  "
                  f"{'kept' if e.get('kept', True) else '    '}  {what}")
        print(f"{len(rows)} sealed and never saved ({sum(1 for e in rows if e.get('kept', True))} kept) in {k.root}")
        return 0
    if argv[0] == "purge" and len(argv) <= 2:
        gone = k.purge(age(argv[1].removeprefix("older=") if len(argv) == 2 else "14d"))
        print(f"purged {len(gone)} from {k.root}")
        return 0
    print("usage: just sealed [purge [older=14d]]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
