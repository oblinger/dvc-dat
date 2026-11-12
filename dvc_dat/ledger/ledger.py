"""``Ledger``: the store handle. One constructor (A49), ``at`` for views, ``transaction`` for writes.

A ledger is a folder holding the database and the art store (A54.2, also
written ``sqlite://<folder>``), or a URI whose scheme a triples backend is
registered for (``postgresql://…``, ``pgstore``); its location is either, and
where its bytes live beyond this machine is its row ``(db, db/values, <uri>)``
(``backends``, SVP 1599). ``Ledger(location)`` opens it; ``Ledger()`` opens the project's *active*
ledger (A37, A44): ``DAT_LEDGER``, else the ``default:`` of the nearest
``.datconfig.yaml`` at or above the working directory, each a name (``root``,
or one registered on root) or a location. ``root:`` in that file is the root
ledger, whose registry is the list of every other ledger (``named``, SVP 239);
without it the root is a SQLite folder under the first dat folder, made on first
use. ``create=True`` is the one act that makes any other ledger
(``Ledger(location, create=True)``), or a project in the working directory
(``Ledger(create=True)``: ``default: root`` and ``namespace: ledger`` in its
``.datconfig.yaml``, and the ledger the default names).

Every stamp the ledger writes (``db/time``, ``sealed``) is UTC. The zone a time
is shown in is a setting, the row ``db db/timezone <IANA name>``, read as of a
revision (``rev.timezone``; UTC with no row): it changes only how times print, so
it may change at any revision (SVP 1505 Q2).

The named handles (``ledgers.record``) and ``L``, the active ledger as one
object, are ``named``.
"""

from __future__ import annotations

import datetime as _dt
import keyword
import os
import re
import weakref
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union

import yaml

from .codec import show
from .errors import LedgerError
from .rev import Head, Rev
from .backends import SQLITE, VALUES, is_uri, open_triples, scheme_of, sqlite_folder
from .store import Store
from .txn import Transaction
from .value import is_moment, moment, stored_moment

ENV = "DAT_LEDGER"
CONFIG = ".datconfig.yaml"
ROOT = "root"                              # the root ledger's name, and its config key: ``root: <location>``
DEFAULT_KEY = "default"                    # the config key naming the active ledger when ``DAT_LEDGER`` is unset
ROOT_FOLDER = Path(".ledgers") / ROOT      # the SQLite root under the first dat folder when ``root:`` is absent
NAME = re.compile(r"^[a-z][a-z0-9_]*$")    # a ledger's name on root's registry: a Python identifier, its database name
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_MONTH = re.compile(r"\d{4}-\d{2}")       # a ``revs`` bound written as a month, as its labels read
PERIODS = ("day", "week", "month")         # ``revs``'s calendar selectors

Target = Union[str, Path]                  # a URI, or a folder

#: Every ledger open in this process, oldest first: what ``<ledger>@<rev>`` resolves through first
#: (``opened``). The latest handle on a name wins; a name is never reused (SVP 1516).
_OPEN: List["weakref.ref[Ledger]"] = []


def opened(name: str) -> Optional["Ledger"]:
    """The latest handle open in this process on the ledger named ``name`` (``store.name``), else ``None``."""
    _OPEN[:] = [r for r in _OPEN if r() is not None]
    for r in reversed(_OPEN):
        led = r()
        if led is not None and led._store.name == name:
            return led
    return None


def opened_at(key: str) -> "Ledger":
    """A handle on the ledger ``key`` names (``fn.ledger_key``): one open in this process, else a new one."""
    from .fn import ledger_key

    _OPEN[:] = [r for r in _OPEN if r() is not None]
    for r in reversed(_OPEN):
        led = r()
        if led is not None and ledger_key(led) == key:
            return led
    return Ledger(key)


def period_starts(kind: str, first: _dt.date, last: _dt.date) -> Iterator[Tuple[str, _dt.date]]:
    """``(label, its first day)`` of each ``day``, ``week`` (Monday, labelled ``2026-W45``) or ``month`` from the
    one holding ``first`` through the one holding ``last``."""
    day = first
    if kind == "week":
        day -= _dt.timedelta(days=day.weekday())
    elif kind == "month":
        day = day.replace(day=1)
    while day <= last:
        if kind == "day":
            yield day.isoformat(), day
            day += _dt.timedelta(days=1)
        elif kind == "week":
            iso = day.isocalendar()
            yield f"{iso[0]}-W{iso[1]:02d}", day
            day += _dt.timedelta(days=7)
        else:
            yield f"{day.year}-{day.month:02d}", day
            day = (day.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)


_RETIRED_OVERRIDE = ".datconfig.override.yaml"  # read until 2.63 (SVP 239: one config file); now refused


def refuse_removed(path: Optional[Path], values: Dict[str, Any]) -> None:
    """`ValueError` for a config key removed in 2.63, naming what replaces it, and for an override file beside the
    config (SVP 239: one `.datconfig.yaml`, committed; the per-checkout fact is `DAT_LEDGER`)."""
    if path is not None and (Path(path).parent / _RETIRED_OVERRIDE).is_file():
        raise ValueError(f"{Path(path).parent / _RETIRED_OVERRIDE}: the override file is no longer read (dvc-dat "
                         "2.63, SVP 239: one config file); the active ledger is DAT_LEDGER=<name>, the local store "
                         "DAT_STORE_LOCAL; move what it says there and remove the file")
    if "ledger" in values:
        raise ValueError(f"{path}: 'ledger:' was removed in dvc-dat 2.63 (SVP 239): write 'root: "
                         f"{values['ledger']}' and 'default: root', and 'namespace: ledger' when its names were "
                         "the ledger's")
    if "stores" in values:
        raise ValueError(f"{path}: 'stores:' was removed (SVP 1599): where a ledger's bytes live is its own row "
                         "(db, db/values, <uri>), the same on every machine; list the modules that register its "
                         "scheme under 'backends:'")
    if "ledgers" in values:
        raise ValueError(f"{path}: 'ledgers:' was removed in dvc-dat 2.63 (SVP 239): the list of ledgers is the "
                         "registry on the root ledger; write 'root: <location of the ledger holding the registry>' "
                         "and register each ledger there (subject ledger/<name>, predicate ledger/location)")


def _read_config(cfg: Path) -> Dict[str, Any]:
    data = yaml.safe_load(cfg.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _values(cfg: Path) -> Dict[str, Any]:
    """The config's keys. A removed key (``ledger:``, ``ledgers:``) or a ``.datconfig.override.yaml`` beside it is
    ``LedgerError`` naming what replaces it (SVP 239: one config file)."""
    data = _read_config(cfg)
    try:
        refuse_removed(cfg, data)
    except ValueError as e:
        raise LedgerError(str(e)) from None
    return data


def _walk_up(start: Path) -> Tuple[Optional[Path], List[Path]]:
    """The nearest ``.datconfig.yaml`` at or above ``start`` (every config has a root, named or the default), and
    the folders searched."""
    searched = []
    for folder in (start, *start.parents):
        searched.append(folder)
        cfg = folder / CONFIG
        if cfg.is_file():
            return cfg, searched
    return None, searched


def _folder(text: str) -> str:
    """A folder location as written: ``sqlite://<folder>`` is ``<folder>``."""
    return sqlite_folder(text) if scheme_of(text) == SQLITE else text


def _relative(cfg: Path, led: str) -> Path:
    p = Path(_folder(led)).expanduser()
    return p if p.is_absolute() else (cfg.parent / p)


def _target(cfg: Path, led: str) -> Target:
    return led if is_uri(led) else _relative(cfg, led)


def _is_name(name: Any) -> bool:
    """A ledger name: ``[a-z][a-z0-9_]*`` and not a Python keyword, so ``ledgers.<name>`` reaches it and it is
    the Postgres database name unchanged."""
    return isinstance(name, str) and bool(NAME.match(name)) and not keyword.iskeyword(name)


def root_target(cfg: Path, values: Dict[str, Any]) -> Tuple[Target, bool]:
    """Where the root ledger is: ``(target, made on first use)``. ``root:`` (a folder relative to the config, or a
    DSN), else the SQLite folder ``.ledgers/root`` under the first dat folder (``DAT_FOLDERS``, else
    ``dat_folders:``, else ``data``), which is the one ledger made without ``create=True``."""
    loc = values.get(ROOT)
    if loc is not None:
        if not (isinstance(loc, str) and loc.strip()):
            raise LedgerError(f"{cfg}: root: is a folder or a DSN, got {loc!r}")
        return _target(cfg, loc), False
    folders = os.environ.get("DAT_FOLDERS") or values.get("dat_folders") or "data"
    first = folders if isinstance(folders, str) else folders[0]
    return _relative(cfg, str(first)) / ROOT_FOLDER, True


def _location(text: str) -> Target:
    """``DAT_LEDGER`` or a ``default:`` read as a location: a URI, else a folder."""
    return text if is_uri(text) else Path(_folder(text)).expanduser()


def _resolve(cfg: Optional[Path], values: Dict[str, Any],
             env: Optional[str]) -> Tuple[Target, Any, Path, Optional[Path]]:
    """The active ledger: ``(target, as named in errors, the folder it was named from, config whose mounts
    to assert or None)``. ``DAT_LEDGER`` first, then the config's ``default:``; each a name (``root``, or one
    registered on root, ``ledgers``) when the project has a config, else a location."""
    from .named import target_of

    if env:
        if cfg is not None and _is_name(env):
            return target_of(cfg, env, f"{ENV}={env}"), f"{env} ({ENV}, {cfg})", cfg.parent, cfg
        return _location(env), env, Path.cwd(), None
    if cfg is None:
        raise LedgerError(f"no ledger: {ENV} unset and no {CONFIG}")
    default = values.get(DEFAULT_KEY)
    if default is None:
        raise LedgerError(f"no active ledger: {ENV} unset and {cfg} names no 'default:'; set {ENV}=<name> (root, "
                          "or a ledger registered on root) or a location")
    if not (isinstance(default, str) and default.strip()):
        raise LedgerError(f"{cfg}: default: is a ledger name or a location, got {default!r}")
    if _is_name(default):
        return target_of(cfg, default, f"{cfg} default: {default}"), f"{default} ({cfg})", cfg.parent, cfg
    target = _target(cfg, default)
    return target, target, cfg.parent, cfg


def _find(create: bool) -> Tuple[Target, Any, Path, Optional[Path]]:
    """``Ledger(None)``'s resolution, from the working directory (``_resolve``). With ``create``: the project in
    the working directory, its ``.datconfig.yaml`` given ``default: root`` and ``namespace: ledger`` when it names no
    default (what the one ``ledger:`` key meant before 2.63)."""
    env = os.environ.get(ENV)
    if create:
        if env:
            raise ValueError(f"Ledger(create=True) makes a project in the working directory, but {ENV} is "
                             "set: ambiguous; unset it, or pass the location")
        here = Path.cwd() / CONFIG
        if here.is_file() and not isinstance(yaml.safe_load(here.read_text()) or {}, dict):
            raise LedgerError(f"{here}: not a mapping; Ledger(create=True) adds a 'default:' key to it")
        values = _values(here) if here.is_file() else {}
        default = values.get(DEFAULT_KEY)
        if default is None:
            text = here.read_text() if here.is_file() else ""
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{DEFAULT_KEY}: {ROOT}\n" + ("" if "namespace" in values else "namespace: ledger\n")
            here.write_text(text)
            default = ROOT
        if default == ROOT:
            target: Target = root_target(here, values)[0]
        elif _is_name(default):
            from .named import target_of

            target = target_of(here, default, f"{here} default: {default}")
        else:
            target = _target(here, default)
        return target, target, here.parent, here
    if env and not _is_name(env):                # a location: no config read
        return _resolve(None, {}, env)
    cfg, searched = _walk_up(Path.cwd().resolve())
    if cfg is None and not env:
        raise LedgerError(f"no ledger: {ENV} unset and no {CONFIG} in "
                          + ", ".join(str(s) for s in searched) + " (Ledger(create=True) makes one)")
    return _resolve(cfg, _values(cfg) if cfg is not None else {}, env)


class Ledger:
    """One logical store of quads ``(rev, subject, predicate, object)``."""

    path: Union[Path, str]
    """The resolved ledger folder; for any other ledger, its URI.

    ``repr`` hides a DSN's password.
    """

    def __init__(self, location: Union[str, Path, None] = None, *, create: bool = False) -> None:
        """``Ledger(location)`` opens the ledger at ``location``: a folder or a URI.

        ``location``, a ``Path``, or a ``str`` that is not ``<scheme>://…``, is a folder (``sqlite://<folder>`` names
        the same); a folder without ``ledger.db`` is ``LedgerError``, and so is a file. Any other URI is opened by
        the triples backend registered for its scheme ([Backends][backends]): ``postgresql://`` built in; a scheme
        nothing registered is ``LedgerError`` listing what is.

        ``Ledger()`` — ``location`` defaulting to ``None`` — opens the active ledger ([Many ledgers][many-ledgers]):
        ``DAT_LEDGER`` when set, else the ``default:`` of the nearest ``.datconfig.yaml`` at or above the working
        directory; each is a name (``root``, or a ledger registered on root: ``ledgers``) when a config is found, else
        a location (a folder relative to that file, or a DSN). It asserts the config's ``mounts:`` (each key the
        mount's name, ``mnt.<prefix>: <root>``, as [``t.ns.mount``][dvc_dat.ledger.Transaction.ns] takes it; a key
        outside ``mnt.`` is ``ValueError``) as ``db/mount/<prefix>`` rows in one transaction ``by="config:<path>"``
        when they differ from the ledger's. No config found, or neither ``DAT_LEDGER`` nor ``default:``, is
        ``LedgerError`` saying what to set; a name the registry does not hold is ``LedgerError`` naming it.

        ``Ledger(location, create=True)`` makes an empty ledger there if absent. ``Ledger(create=True)`` makes a
        project in the working directory: ``default: root`` and ``namespace: ledger`` written into its
        ``.datconfig.yaml`` when it names no default, and the ledger the default names made (the root: ``root:``, else the SQLite root under the first
        dat folder); with ``DAT_LEDGER`` set it is ``ValueError``.
        """
        cfg: Optional[Path] = None
        target: Target
        if location is None:
            target, given, base, cfg = _find(create)
        else:
            if isinstance(location, str) and not location.strip():
                raise TypeError("Ledger(location): an empty location; pass a folder or a DSN, or None to find it")
            target = location if is_uri(location) else Path(_folder(str(location))).expanduser()
            given, base = location, Path.cwd()
        self._open(target, given, base, create)
        if cfg is not None and not create:
            self._assert_mounts(cfg)

    @classmethod
    def _opened(cls, target: Target, given: Any, base: Path, cfg: Optional[Path],
                overlay: Optional[Path] = None) -> "Ledger":
        """A handle on a resolved target (``named``, ``do``); ``cfg`` names the config whose mounts to assert.
        ``overlay``: read-only (``read_only``), what its reads place going there (``ReadOnlyArt``)."""
        led = cls.__new__(cls)
        led._open(target, given, base, False, overlay)
        if cfg is not None:
            led._assert_mounts(cfg)
        return led

    def _open(self, target: Target, given: Any, base: Path, create: bool, overlay: Optional[Path] = None) -> None:
        self._values: Dict[Any, Any] = {}
        self._store: Store
        if isinstance(target, str):
            store = open_triples(target, create, overlay)
            self._store = store
            self.path: Union[str, Path] = getattr(store, "dsn", target)
            self._shown = getattr(store, "redacted", target)
        else:
            folder = target.resolve()
            if folder.exists() and not folder.is_dir():
                raise LedgerError(f"{folder}: a ledger is a folder (database and art store inside), not a file")
            if not (folder / "ledger.db").is_file() and not create:
                raise LedgerError(f"no ledger at {given}")
            self.path = folder
            self._shown = str(folder)
            self._store = open_triples(f"{SQLITE}://{folder}", create, overlay)
        _OPEN.append(weakref.ref(self))

    @property
    def triples(self) -> str:
        """The ledger's triples URI, where its records live: ``sqlite://<folder>``, or the URI it was opened by."""
        return f"{SQLITE}://{self.path}" if isinstance(self.path, Path) else self.path

    @property
    def values(self) -> Optional[str]:
        """The ledger's values URI, where its bytes live beyond this machine: its row ``(db, db/values, <uri>)`` at
        the top, set as any setting is (``t.add("db", "db/values", "file:///shared/art")``); ``None`` with no
        row, the bytes then living in this machine's folder alone ([Backends][backends])."""
        held = Rev(self, self._store.top())._held("db", VALUES)
        return show(held[0].obj) if held else None

    @property
    def read_only(self) -> bool:
        """Is this a read-only handle: a ledger a sandboxed body opened by name (SVP 1521 Q3 (A))."""
        return self._store.read_only

    def __repr__(self) -> str:
        return f"Ledger({self._shown!r})"

    def close(self) -> None:
        """Close the handle's database connections in every thread; a later read or write reopens one."""
        self._store.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _assert_mounts(self, cfg: Path) -> None:
        """``mounts:`` sugar: assert the rows when they differ from what the ledger holds (A47, A54.3). A key is
        the mount's name, ``mnt.<prefix>`` as ``t.ns.mount`` takes it (1505 Q1); the rows are ``db/mount/<prefix>``."""
        mounts = _read_config(cfg).get("mounts") or {}
        if not isinstance(mounts, dict) or not mounts:
            return
        from .env import _toplevel, repo_name
        from .fn import mount_prefix

        mounts = {mount_prefix(str(at), f"{cfg} mounts:"): root for at, root in mounts.items()}
        top = _toplevel(str(cfg.parent))
        repo = repo_name(Path(top)) if top else cfg.parent.name
        rev = self.at()
        todo = []
        for prefix, root in mounts.items():
            s = f"db/mount/{prefix}"
            for p, o in (("db/root", str(root)), ("db/repo", repo)):
                if rev.get(s, p) != o:
                    todo.append((s, p, o))
        if todo:
            with self.transaction(by=f"config:{cfg}") as t:
                for s, p, o in todo:
                    t.add(s, p, o)

    def at(self, which: Union[int, str, None] = None) -> Rev:
        """A frozen view of the ledger, chosen by ``which``, tried in the order below.

        ``None`` (no argument) is the top, as a ``Head``: a ``Rev`` that is also a transaction, each transaction
        method listed on it the one-shot form that opens a transaction, calls the method and commits
        (``L.at().pin(v)``, ``by=`` the writer, ``human:<user>`` by default; SVP 250 A13).

        An ``int`` or a digit string is that revision (``KeyError`` outside ``0..top``).

        ``"M.m.p"`` is the latest revision that set ``(db, db/version, M.m.p)``, the release row (``bump(t, "db")``;
        ``KeyError`` when none did).

        A timestamp, an ISO 8601 prefix at any precision (``2026-11-02``, ``2026-11-02T14``, ``2026-11-02T14:30``,
        ``2026-11-02T14:30:15``; a space may replace ``T``), is the latest revision whose ``db/time`` is at or before
        the START of its span (``2026-11-02`` is 00:00, ``2026-11-02T01`` exactly 01:00, as Delta Lake, Iceberg,
        SQL:2011 and Snowflake read one; to include Nov 2, name ``2026-11-03``), read in the display zone,
        [``timezone``][dvc_dat.ledger.Rev.timezone] at the top (UTC with no row), unless it ends ``Z`` or
        ``+hh:mm``/``-hh:mm``; a local time a DST change makes ambiguous or skips is read with ``fold=0`` (the first
        of two; a skipped one at the offset before the change); before the first stamped revision it is ``KeyError``,
        and a field out of range (``2026-13-02``) is ``ValueError`` (SVP 1507).

        Any other str is the revision whose ``(db, db/tag, name)`` row added that name, ``L.at("2026-Q4-official")``;
        the forms are tried in that order. A ``bool``, or a str that is none of them, is ``TypeError``.
        """
        top = self._store.top()
        if which is None:
            return Head(self, top)
        if isinstance(which, bool):
            raise TypeError("at takes None, an int revision or a version string")
        if isinstance(which, str) and which.isdigit():
            which = int(which)
        if isinstance(which, int):
            if not 0 <= which <= top:
                raise KeyError(f"no revision {which}: the ledger runs 0..{top}")
            return Rev(self, which)
        if isinstance(which, str) and _VERSION.match(which):
            found = [r.rev for r in Rev(self, top).history("db", "db/version", which) if r.added]
            if not found:
                raise KeyError(f"no revision set the ledger version {which}")
            return found[-1]
        if is_moment(which):
            return self._at_moment(which, top)
        if isinstance(which, str) and which:
            found = [r.rev for r in Rev(self, top).history("db", "db/tag", which) if r.added]
            if found:
                return found[-1]
        raise TypeError(f"at takes None, an int revision, a version string M.m.p, an ISO 8601 timestamp or a "
                        f"db/tag name, not {which!r}")

    def _at_moment(self, text: str, top: int) -> Rev:
        """The latest revision whose ``db/time`` is at or before the moment ``text`` names (SVP 1507)."""
        when = moment(text, Rev(self, top).timezone)
        stamped = self._stamped(top)
        found = [rev for rev, t in stamped if t <= when]
        if not found:
            first = min(stamped, key=lambda x: x[1])[1].isoformat() if stamped else None
            raise KeyError(f"no revision at or before {text} ({when.isoformat()}): the first is stamped {first}"
                           if first else f"no revision at or before {text}: the ledger has no stamped revision")
        return Rev(self, max(found))

    def _stamped(self, top: int) -> List[Tuple[int, Any]]:
        """``(revision, its db/time as a UTC datetime)`` of every stamped revision up to ``top``."""
        return [(rev, stored_moment(show(obj))) for rev, _o, subject, _p, obj, added
                in self._store.rows(top, predicate="db/time") if added and subject == f"db/tx/{rev}"]

    def revs(self, which: Union[str, Iterable[Any]], *, since: Any = None, until: Any = None) -> Dict[str, Rev]:
        """Past revisions by label, oldest first, for running present code over a span.

        It reads the ledger, runs nothing, and the loop is the caller's (``{label: rev.run("metrics.rate", game="G1")
        for label, rev in L.revs("month", since="2025-11").items()}``, [Running over past
        revisions][running-over-past-revisions]; SVP 245).

        ``which`` is ``"release"``, each ``(db, db/version, v)`` add, labelled by the version; ``"tag"``, each ``(db,
        db/tag, name)`` add, labelled by the tag; ``"day"``, ``"week"`` (a Monday) or ``"month"``, each period whose
        start lies in the span, labelled ``2026-11-02``, ``2026-W45`` or ``2026-11``, the latest revision stamped at
        or before that start in the display zone, exactly what [``at``][dvc_dat.ledger.Ledger.at] reads for it; or an
        iterable of ``at`` arguments, in the order given, labelled by ``str(each)``. Any other value, a str included,
        is ``TypeError``.

        ``since`` and ``until`` are ``at`` arguments or a month ``2026-11``, inclusive; absent, the first stamped
        revision and the top. A timestamp bounds by time and names no revision, so one before the first stamp is no
        ``KeyError``, and a period before the first stamped revision is omitted. Two labels may share a revision: its
        second run hits.
        """
        top = self._store.top()
        head = Rev(self, top)
        zone = head.timezone
        stamped = self._stamped(top)
        low, high = self._bound(since, zone), self._bound(until, zone)
        if isinstance(which, str) and which in PERIODS:
            return self._periods(which, stamped, low, high, zone)
        if which == "release" or which == "tag":
            found = [(str(r.object), r.rev) for r in head.history("db", f"db/{'version' if which == 'release' else 'tag'}")
                     if r.added]
        elif isinstance(which, (str, bytes)) or not isinstance(which, Iterable):
            raise TypeError(f"revs takes 'release', 'tag', 'day', 'week', 'month' or an iterable of at arguments, "
                            f"not {which!r}")
        else:
            found = [(str(each), self.at(each)) for each in which]
        stamps = dict(stamped)

        def inside(rev: int) -> bool:
            when = stamps.get(rev)
            if isinstance(low, int) and rev < low or isinstance(high, int) and rev > high:
                return False
            return not (isinstance(low, _dt.datetime) and (when is None or when < low)
                        or isinstance(high, _dt.datetime) and (when is None or when > high))
        out: Dict[str, Rev] = {}
        for label, rev in found:
            if inside(rev.id):
                out.pop(label, None)
                out[label] = rev
        return out

    def _bound(self, which: Any, zone: Any) -> Any:
        """A ``revs`` bound: ``None``, the UTC moment it names, or the revision ``at`` reads it as."""
        if isinstance(which, str) and _MONTH.fullmatch(which):
            which += "-01"
        return None if which is None else moment(which, zone) if is_moment(which) else self.at(which).id

    def _periods(self, kind: str, stamped: List[Tuple[int, Any]], low: Any, high: Any, zone: Any) -> Dict[str, Rev]:
        """``revs`` by calendar: ``low`` and ``high`` as ``_bound`` left them, a revision read as its stamp."""
        after = [t for rev, t in stamped if not isinstance(low, int) or rev >= low]
        before = [t for rev, t in stamped if not isinstance(high, int) or rev <= high]
        start = low if isinstance(low, _dt.datetime) else min(after, default=None)
        end = high if isinstance(high, _dt.datetime) else max(before, default=None)
        if start is None or end is None:
            return {}
        ordered = sorted((t, rev) for rev, t in stamped)
        out: Dict[str, Rev] = {}
        i, latest = 0, None
        for label, day in period_starts(kind, start.astimezone(zone).date(), end.astimezone(zone).date()):
            begins = moment(day.isoformat(), zone)
            if not start <= begins <= end:
                continue
            while i < len(ordered) and ordered[i][0] <= begins:
                latest = ordered[i][1] if latest is None else max(latest, ordered[i][1])
                i += 1
            if latest is not None:
                out[label] = Rev(self, latest)
        return out

    def transaction(self, *, by: Union[str, Dict[str, Any]], lock: Optional[float] = None,
                    **preds: Any) -> Transaction:
        """A write set that becomes one revision on exit; use it only as ``with L.transaction(by=...) as t:``.

        ``by`` names the writer and is required: a non-empty ``str`` (``"human:dan"``), or a non-empty JSON ``dict``
        for a structured identity (``{"host": ..., "user": ..., "admins": [...]}``), stored under the ``json:`` tag
        and read back as written, so no identity is parsed out of a string (DAT 1024); anything else is ``TypeError``.

        The ``eval:`` prefix convention is a string's alone; ``lock=`` holds the write lock for the whole body, at
        most that many seconds.

        Each extra keyword is a ``str`` or a JSON document and lands as a row on the transaction's ``db/tx/<rev>``
        subject beside ``db/by`` and ``db/time`` (UTC, every transaction). See [Revisions and
        transactions][revisions-and-transactions].
        """
        return Transaction(self, by, lock, preds)


__all__ = ["Ledger", "ENV", "CONFIG", "ROOT"]
