"""The ledger load harness: N processes x M operations on one ledger, then invariants from fresh handles.

Each worker process opens its own ``Ledger`` handle and runs a seeded mix of operations:

``seal``    a unique ``Blob`` sealed by ``v.seal(t)``, plus a ``made`` row (a many pred) naming it
``shared``  one of a few ``Blob``s every worker seals: the same subject raced across processes
``alias``   an ``alias/<k>`` re-pointed at one of this worker's seals, under ``lock=``
``salt``    ``load/config salt`` changed, under ``lock=``: every memo entry's dependencies read it
``eval``    ``rev.run("tests.load.loadfns.square", n=k)``, a base-mode function: hits and misses
``read``    a load of one of this worker's seals, an alias resolution and a bracket read at the top

Every write transaction is tagged ``by=load:w<w>:<i>``. After the run the parent checks, each from a
fresh handle (and the fold from fresh processes too):

``contiguous``  revisions 1..top, each one ``db/tx/<rev> db/by`` row, ``ord`` 0..k-1 within a revision
``no-lost-row`` every committed transaction's rows at its revision; no failed one's tag anywhere;
                no tag twice
``no-dup``      no subject with two ``db/value`` rows; one memo entry per (keys, salt)
``memo``        every eval's entry: ``db/fn``/``db/keys`` right, its dependencies hold at the rev it was
                evaluated at, its bytes decode to the expected result for that rev's salt
``alias``       each re-point resolves at its revision; each alias ends at its last re-point
``fold``        the whole-ledger fold digest identical from every handle, and at the mid-run revisions
                each worker took one at
``art``         every ``db/value`` hash present in the art store with matching bytes
``reads``       every in-run read saw what it should

``LockTimeout`` and ``LedgerError`` (a busy write lock past its 30 s) are counted per operation;
anything else a worker raises is an error. Results: one JSON in ``--results`` and a one-line summary.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import multiprocessing as mp
import os
import platform
import random
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
LOAD_DIR = Path(__file__).resolve().parent
FN = "tests.load.loadfns.square"
SALTS = ("a", "b", "c")
COMMIT = "abc1234"
OPS = ("seal", "shared", "alias", "salt", "eval", "read")
MIX = {"seal": 30, "shared": 5, "alias": 10, "salt": 3, "eval": 27, "read": 25}


def pin_env() -> None:
    """The environment every handle sees: one repo, ``loadrepo``, its checkout ``tests/load``, clean."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from dvc_dat.ledger import Code, Env, set_env_provider

    env = Env({"loadrepo": Code(None, COMMIT, False, LOAD_DIR)}, "load-platform")
    set_env_provider(lambda: env)


def is_dsn(target: Any) -> bool:
    return isinstance(target, str) and target.startswith(("postgresql://", "postgres://"))


def make_schema(dsn: str) -> None:
    """A Postgres ledger's schema (the DSN's ``search_path``) made when absent: ``create=True`` wants it."""
    from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

    import psycopg

    parts = urlsplit(dsn)
    query = parse_qsl(parts.query, keep_blank_values=True)
    opts = " ".join(v for k, v in query if k == "options")
    schema = next((o.split("=", 1)[1] for o in opts.split() if o.startswith("-csearch_path=")), None)
    if not schema:
        return
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode([(k, v) for k, v in query
                                                                          if k not in ("art", "options")]), ""))
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f'CREATE SCHEMA IF NOT EXISTS "{unquote(schema)}"')


def setup(path: Any) -> int:
    """Make (or reopen) the ledger and write the rows the workload assumes; the top after."""
    from dvc_dat.ledger import Ledger

    if is_dsn(path):
        make_schema(path)

    L = Ledger(path, create=True)
    rev = L.at()
    if rev.get("code/loadrepo", "commit") != COMMIT:
        with L.transaction(by="load:setup") as t:
            t.add("code/loadrepo", "version", "1.0.0")
            t.add("code/loadrepo", "commit", COMMIT)
            t.add("db/pred/made", "db/cardinality", "many")
            t["load/config", "salt"] = SALTS[0]
    return L.at().id


def fold_digest(L: Any, upto: int) -> str:
    """sha256 over every ``(subject, predicate)``'s folded held objects as of ``upto``."""
    from dvc_dat.ledger.fold import fold

    rev = L.at(upto)
    groups: Dict[tuple, list] = defaultdict(list)
    for r in L._store.rows(upto):
        groups[(r[2], r[3])].append(r)
    h = hashlib.sha256()
    for key in sorted(groups):
        held = fold(groups[key], rev._card(key[1]))
        h.update(json.dumps([key[0], key[1], [[x.obj, x.rev, x.ord] for x in held]]).encode())
        h.update(b"\n")
    return h.hexdigest()


# -- the worker ----------------------------------------------------------------------------------


def worker(cfg: Dict[str, Any], wid: int, ready: Any, start: Any, out: str) -> None:
    pin_env()
    from dvc_dat.ledger import LedgerError, LockTimeout, Ledger, Ref
    from tests.load import loadfns
    from tests.load.loadfns import Blob

    L = Ledger(cfg["ledger"])
    rng = random.Random(cfg["seed"] * 1000 + wid)
    names, weights = zip(*cfg["mix"].items())
    rec: Dict[str, Any] = {"wid": wid, "pid": os.getpid(), "committed": [], "failed": [], "evals": [],
                           "folds": [], "read_violations": [], "errors": [],
                           "lat": {op: [] for op in OPS}, "counts": {op: Counter() for op in OPS}}
    own: List[Dict[str, Any]] = []
    ready.set()
    if not start.wait(timeout=300):
        raise SystemExit("start event never set")
    t_start = time.perf_counter()
    for i in range(cfg["transactions"]):
        op = rng.choices(names, weights)[0]
        if op == "alias" and not own:
            op = "seal"
        by = f"load:w{wid}:{i}"
        t0 = time.perf_counter()
        try:
            if op in ("seal", "shared"):
                if op == "seal":
                    data = f"w{wid}-{i}-{rng.getrandbits(64):016x}".encode()
                    owner, seq = f"w{wid}", str(i)
                else:
                    j = rng.randrange(cfg["shared"])
                    data, owner, seq = f"shared-{j}".encode(), "shared", str(j)
                v = Blob(data)
                v.preds.update(owner=owner, seq=seq)
                with L.transaction(by=by) as t:
                    subject = v.seal(t)
                    t.add(f"load/w{wid}", "made", subject)
                r = {"op": op, "i": i, "by": by, "rev": t.rev.id, "subject": subject, "data": data.decode()}
                rec["committed"].append(r)
                if op == "seal":
                    own.append(r)
            elif op == "alias":
                target = rng.choice(own)["subject"]
                name = f"alias/{rng.randrange(cfg['aliases'])}"
                with L.transaction(by=by, lock=cfg["lock"]) as t:
                    t.add(name, "db/alias", target)
                rec["committed"].append({"op": op, "i": i, "by": by, "rev": t.rev.id, "name": name,
                                         "target": target})
            elif op == "salt":
                salt = rng.choice(SALTS)
                with L.transaction(by=by, lock=cfg["lock"]) as t:
                    t["load/config", "salt"] = salt
                rec["committed"].append({"op": op, "i": i, "by": by, "rev": t.rev.id, "salt": salt})
            elif op == "eval":
                n = rng.randrange(cfg["keys"])
                rev = L.at()
                before = loadfns.CALLS["square"]
                v = rev.run(FN, n=n)
                ran = loadfns.CALLS["square"] != before
                rec["counts"][op]["misses" if ran else "hits"] += 1
                rec["evals"].append({"i": i, "at": rev.id, "n": n, "subject": v.subject, "ran": ran,
                                     "sealed": v.rev.id, "obj": v.obj})
            else:
                rev = L.at()
                seen = [r for r in own if r["rev"] <= rev.id]
                if seen:
                    r = rng.choice(seen)
                    got = Ref(rev, r["subject"]).load()
                    if got.data.decode() != r["data"]:
                        rec["read_violations"].append({"at": rev.id, "subject": r["subject"], "want": r["data"],
                                                       "got": got.data.decode()})
                name = f"alias/{rng.randrange(cfg['aliases'])}"
                ref = Ref(rev, name)
                if rev.get(name, "db/alias") is not None and ref.hash is None:
                    rec["read_violations"].append({"at": rev.id, "alias": name, "why": "alias names no value"})
                if rev["load/config", "salt"] not in SALTS:
                    rec["read_violations"].append({"at": rev.id, "why": "salt not one of SALTS"})
            rec["counts"][op]["ok"] += 1
        except LockTimeout as e:
            rec["counts"][op]["lock_timeout"] += 1
            rec["failed"].append({"op": op, "i": i, "by": by, "why": f"LockTimeout: {e}"})
        except LedgerError as e:
            rec["counts"][op]["ledger_error"] += 1
            rec["failed"].append({"op": op, "i": i, "by": by, "why": f"{type(e).__name__}: {e}"})
        except Exception as e:  # noqa: BLE001 - every other raise is an error, reported in full
            rec["counts"][op]["error"] += 1
            rec["failed"].append({"op": op, "i": i, "by": by, "why": f"{type(e).__name__}: {e}"})
            if len(rec["errors"]) < 20:
                rec["errors"].append({"op": op, "i": i, "wid": wid, "error": f"{type(e).__name__}: {e}",
                                      "traceback": traceback.format_exc()})
        rec["lat"][op].append(time.perf_counter() - t0)
        if cfg["fold_checks"] and i == cfg["transactions"] // 2:
            top = L.at().id
            rec["folds"].append({"rev": top, "digest": fold_digest(L, top)})
    rec["elapsed"] = time.perf_counter() - t_start
    rec["counts"] = {op: dict(c) for op, c in rec["counts"].items()}
    Path(out).write_text(json.dumps(rec))


def checker(path: str, upto: int, out: str) -> None:
    """A fresh process, a fresh handle: the fold digest at ``upto``."""
    pin_env()
    from dvc_dat.ledger import Ledger

    Path(out).write_text(fold_digest(Ledger(path), upto))


# -- invariants ----------------------------------------------------------------------------------


def check(path: Path, setup_top: int, recs: List[Dict[str, Any]], ctx: Any, workdir: Path,
          handles: int) -> Dict[str, Any]:
    from dvc_dat.ledger import Ledger, Ref
    from dvc_dat.ledger.codec import parse_ref, sha256
    from dvc_dat.ledger.trace import trace_matches
    from tests.load.loadfns import expected

    L = Ledger(path)
    store = L._store
    top = L.at().id
    failures: List[Dict[str, Any]] = []

    def fail(inv: str, **detail: Any) -> None:
        if sum(1 for f in failures if f["invariant"] == inv) < 25:
            failures.append({"invariant": inv, **detail})
        counts[inv] += 1
    counts: Counter = Counter()

    # contiguous
    revs = [r[0] for r in store.read("SELECT DISTINCT rev FROM quads ORDER BY rev")]
    if revs != list(range(1, top + 1)):
        missing = sorted(set(range(1, top + 1)) - set(revs))
        fail("contiguous", why="revisions not 1..top", top=top, missing=missing[:50])
    for rev, n, lo, hi in store.read("SELECT rev, COUNT(*), MIN(ord), MAX(ord) FROM quads GROUP BY rev"):
        if lo != 0 or hi != n - 1:
            fail("contiguous", why="ord not 0..k-1", rev=rev, count=n, min=lo, max=hi)
    by_rows = store.read("SELECT rev, subject, object FROM quads WHERE predicate = 'db/by'")
    per_rev = Counter(r[0] for r in by_rows)
    for rev in range(1, top + 1):
        if per_rev.get(rev, 0) != 1:
            fail("contiguous", why="db/tx db/by rows at a revision", rev=rev, count=per_rev.get(rev, 0))
    for rev, s, _o in by_rows:
        if s != f"db/tx/{rev}":
            fail("contiguous", why="db/by on a subject not db/tx/<rev>", rev=rev, subject=s)

    # no lost row
    tags = Counter(o[len("str:"):] for _r, _s, o in by_rows)
    rev_of_tag = {o[len("str:"):]: r for r, _s, o in by_rows}
    for tag, n in tags.items():
        if n > 1 and tag.startswith("load:w"):
            fail("no-lost-row", why="a transaction tag committed twice", by=tag, count=n)
    committed = [c for r in recs for c in r["committed"]]
    for c in committed:
        R = c["rev"]
        if rev_of_tag.get(c["by"]) != R:
            fail("no-lost-row", why="committed transaction's db/by not at its revision", by=c["by"], rev=R,
                 found=rev_of_tag.get(c["by"]))
            continue
        rows = {(s, p, o, a) for (_r, _o, s, p, o, a) in store.rows(R, after=R - 1)}
        if c["op"] in ("seal", "shared"):
            wid = c["by"].split(":")[1]
            if (f"load/{wid}", "made", "str:" + c["subject"], True) not in rows:
                fail("no-lost-row", why="seal's made row missing at its revision", by=c["by"], rev=R)
            if not L.at()._held(c["subject"], "db/value"):
                fail("no-lost-row", why="sealed subject holds no db/value", by=c["by"], subject=c["subject"])
        elif c["op"] == "alias":
            if (c["name"], "db/alias", "str:" + c["target"], True) not in rows:
                fail("no-lost-row", why="alias row missing at its revision", by=c["by"], rev=R)
        elif c["op"] == "salt":
            if ("load/config", "salt", "str:" + c["salt"], True) not in rows and \
                    L.at(R - 1).get("load/config", "salt") != c["salt"]:
                fail("no-lost-row", why="salt row missing at its revision", by=c["by"], rev=R)
    for r in recs:
        for f in r["failed"]:
            if f["by"] in tags:
                fail("no-lost-row", why="a failed transaction's tag is in the ledger", by=f["by"], err=f["why"],
                     rev=rev_of_tag[f["by"]])

    # no duplicate subject
    for s, n in store.read("SELECT subject, COUNT(*) FROM quads WHERE predicate = 'db/value' AND added "
                           "GROUP BY subject HAVING COUNT(*) > 1"):
        fail("no-dup", why="a subject with several db/value rows", subject=s, count=n)
    seals = Counter(c["subject"] for c in committed if c["op"] == "seal")
    for s, n in seals.items():
        if n > 1:
            fail("no-dup", why="two distinct seals gave one subject", subject=s, count=n)
    head = L.at()
    memo: Dict[tuple, List[str]] = defaultdict(list)
    for s in store.subjects(top, predicate="db/fn", obj="str:" + FN):
        keys = head.get(s, "db/keys")
        salt = head.get(s, "db/deps/load/config salt")
        memo[(json.dumps(keys, sort_keys=True), salt)].append(s)
    for k, subs in memo.items():
        if len(subs) > 1:
            fail("no-dup", why="several memo entries for one (keys, salt)", key=k, subjects=subs)

    # memo traceable
    salt_at: Dict[int, Optional[str]] = {}
    for r in recs:
        for e in r["evals"]:
            s = e["subject"]
            if not head._held(s, "db/value"):
                fail("memo", why="eval entry holds no db/value", eval=e)
                continue
            if head.get(s, "db/fn") != FN or head.get(s, "db/keys") != {"n": e["n"]}:
                fail("memo", why="entry's db/fn or db/keys wrong", eval=e, fn=head.get(s, "db/fn"),
                     keys=head.get(s, "db/keys"))
            at = L.at(e["at"])
            trace = {p[len("db/deps/"):]: h.obj.partition(":")[2]
                     for _s, p, h in head._held_rows(subject=s) if p.startswith("db/deps/")}
            if not trace_matches(at, trace):
                fail("memo", why="entry's dependencies do not hold at the rev it was evaluated at", eval=e,
                     dependencies=trace, salt_at=at.get("load/config", "salt"))
            if e["at"] not in salt_at:
                salt_at[e["at"]] = at.get("load/config", "salt")
            want = expected(e["n"], salt_at[e["at"]])
            got = Ref(head, s).load().obj
            if e["obj"] != want or got != want:
                fail("memo", why="eval result is not the function at its rev", eval=e, want=want, stored=got)
            if e["ran"] and e["sealed"] <= e["at"]:
                fail("memo", why="a miss sealed at or before the rev it evaluated at", eval=e)

    # alias
    last: Dict[str, Dict[str, Any]] = {}
    for c in committed:
        if c["op"] != "alias":
            continue
        got = Ref(L.at(c["rev"]), c["name"]).subject
        if got != c["target"]:
            fail("alias", why="re-point does not resolve at its revision", rec=c, got=got)
        if c["name"] not in last or c["rev"] > last[c["name"]]["rev"]:
            last[c["name"]] = c
    for name, c in last.items():
        got = Ref(head, name).subject
        if got != c["target"]:
            fail("alias", why="alias does not end at its last re-point", name=name, want=c, got=got)

    # art
    for (o,) in store.read("SELECT object FROM quads WHERE predicate = 'db/value' AND added"):
        h = parse_ref(o)[1]
        try:
            data = store.art.get(h)
        except FileNotFoundError:
            fail("art", why="db/value bytes missing", hash=h)
            continue
        if sha256(data) != h:
            fail("art", why="art bytes do not hash to their name", hash=h, size=len(data))

    # reads
    for r in recs:
        for v in r["read_violations"]:
            fail("reads", wid=r["wid"], **v)

    # fold: this handle, fresh processes, and the mid-run digests
    mine = fold_digest(L, top)
    digests = {"parent": mine}
    procs = []
    for k in range(handles):
        out = workdir / f"fold-{k}.txt"
        p = ctx.Process(target=checker, args=(str(path), top, str(out)))
        p.start()
        procs.append((k, p, out))
    for k, p, out in procs:
        p.join(timeout=600)
        if p.is_alive():
            p.terminate()
            fail("fold", why="fold checker timed out", handle=k)
            continue
        digests[f"process-{k}"] = out.read_text() if out.exists() else "<none>"
    for k, d in digests.items():
        if d != mine:
            fail("fold", why="fold digest differs between handles", handle=k, digest=d, parent=mine)
    for r in recs:
        for f in r["folds"]:
            d = fold_digest(L, f["rev"])
            if d != f["digest"]:
                fail("fold", why="mid-run fold differs from the fresh handle's at the same rev", wid=r["wid"],
                     rev=f["rev"], mid=f["digest"], after=d)

    return {"failures": failures, "counts": dict(counts), "top": top, "setup_top": setup_top,
            "fold_digest": mine, "fold_handles": len(digests),
            "checked": {"committed": len(committed), "evals": sum(len(r["evals"]) for r in recs),
                        "memo_entries": sum(len(v) for v in memo.values())}}


# -- the run -------------------------------------------------------------------------------------


def pct(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))] * 1000, 3)


def lat(xs: List[float]) -> Dict[str, Any]:
    return {"n": len(xs), "p50_ms": pct(xs, 0.50), "p90_ms": pct(xs, 0.90), "p99_ms": pct(xs, 0.99),
            "max_ms": round(max(xs) * 1000, 3) if xs else None}


def machine(ledger: Any = None) -> Dict[str, Any]:
    import sqlite3

    m = {"host": platform.node(), "platform": platform.platform(), "machine": platform.machine(),
         "cpus": os.cpu_count(), "python": platform.python_version(), "sqlite": sqlite3.sqlite_version}
    if is_dsn(ledger):
        from dvc_dat.ledger import Ledger

        m["store"] = "pg"
        with Ledger(ledger) as L:
            m["postgres"] = L._store.read("SHOW server_version")[0][0]
    else:
        m["store"] = "sqlite"
    return m


def run(args: argparse.Namespace) -> Dict[str, Any]:
    pin_env()
    path: Any = args.ledger if is_dsn(args.ledger) else Path(args.ledger).expanduser().resolve()
    results = Path(args.results).expanduser().resolve()
    results.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir = results / f".work-{stamp}-{os.getpid()}"
    workdir.mkdir()
    setup_top = setup(path)
    cfg = {"ledger": str(path), "transactions": args.transactions, "seed": args.seed, "lock": args.lock,
           "keys": args.keys, "aliases": args.aliases, "shared": args.shared, "mix": MIX,
           "fold_checks": not args.no_fold_checks}
    ctx = mp.get_context("spawn")
    start = ctx.Event()
    procs, readies = [], []
    for w in range(args.processes):
        ready = ctx.Event()
        p = ctx.Process(target=worker, args=(cfg, w, ready, start, str(workdir / f"w{w}.json")))
        p.start()
        procs.append(p)
        readies.append(ready)
    for ready in readies:                   # every worker imported and holds its handle: start the clock
        ready.wait(timeout=300)
    t0 = time.perf_counter()
    start.set()
    deadline = t0 + args.timeout
    timed_out = []
    for w, p in enumerate(procs):
        p.join(timeout=max(1.0, deadline - time.perf_counter()))
        if p.is_alive():
            p.terminate()
            p.join(timeout=10)
            timed_out.append(w)
    wall = time.perf_counter() - t0
    recs = []
    errors: List[Dict[str, Any]] = []
    for w, p in enumerate(procs):
        f = workdir / f"w{w}.json"
        if f.exists():
            recs.append(json.loads(f.read_text()))
        else:
            errors.append({"wid": w, "error": f"worker wrote no record (exit {p.exitcode}, "
                                              f"{'timed out' if w in timed_out else 'died'})"})
    for r in recs:
        errors.extend(r["errors"])
    t1 = time.perf_counter()
    inv = check(path, setup_top, recs, ctx, workdir, args.handles)
    check_s = time.perf_counter() - t1
    ops: Dict[str, Any] = {}
    for op in OPS:
        c: Counter = Counter()
        xs: List[float] = []
        for r in recs:
            c.update(r["counts"].get(op, {}))
            xs.extend(r["lat"][op])
        ops[op] = {**dict(c), **lat(xs)}
    all_lat = [x for r in recs for op in OPS for x in r["lat"][op]]
    write_lat = [x for r in recs for op in ("seal", "shared", "alias", "salt") for x in r["lat"][op]]
    n_ops = sum(len(r["lat"][op]) for r in recs for op in OPS)
    txs = inv["top"] - setup_top
    lock_timeouts = sum(r["counts"].get(op, {}).get("lock_timeout", 0) for r in recs for op in OPS)
    ledger_errors = sum(r["counts"].get(op, {}).get("ledger_error", 0) for r in recs for op in OPS)
    res = {
        "date": stamp, "machine": machine(path), "config": {**cfg, "processes": args.processes},
        "wall_s": round(wall, 3), "check_s": round(check_s, 3), "timed_out": timed_out,
        "transactions_committed": txs, "tx_per_s": round(txs / wall, 2) if wall else None,
        "ops_done": n_ops, "ops_per_s": round(n_ops / wall, 2) if wall else None,
        "lock_timeouts": lock_timeouts, "ledger_errors": ledger_errors,
        "latency": {"all": lat(all_lat), "writes": lat(write_lat)},
        "per_process": [{"wid": r["wid"], "elapsed_s": round(r["elapsed"], 3),
                         **lat([x for op in OPS for x in r["lat"][op]])} for r in recs],
        "ops": ops, "errors": errors, "invariants": inv,
    }
    store = "-pg" if is_dsn(path) else ""
    out = results / f"{stamp}-{platform.node().split('.')[0]}{store}-p{args.processes}-m{args.transactions}.json"
    out.write_text(json.dumps(res, indent=1))
    for f in workdir.iterdir():
        f.unlink()
    workdir.rmdir()
    res["file"] = str(out)
    line = summary(res)
    with open(results / "summary.txt", "a") as fh:
        fh.write(line + "\n")
    print(line)
    return res


def summary(res: Dict[str, Any]) -> str:
    inv = res["invariants"]
    bad = ",".join(f"{k}={v}" for k, v in sorted(inv["counts"].items())) or "none"
    return (f"{res['date']} {res['machine']['host']} {res['machine']['store']} p={res['config']['processes']} "
            f"m={res['config']['transactions']} wall={res['wall_s']}s tx={res['transactions_committed']} "
            f"tx/s={res['tx_per_s']} ops/s={res['ops_per_s']} p50={res['latency']['all']['p50_ms']}ms "
            f"p99={res['latency']['all']['p99_ms']}ms write-p99={res['latency']['writes']['p99_ms']}ms "
            f"lock_timeouts={res['lock_timeouts']} ledger_errors={res['ledger_errors']} "
            f"errors={len(res['errors'])} invariant_failures={bad} -> {res['file']}")


def parse(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m tests.load", description=__doc__.split("\n")[0])
    ap.add_argument("--processes", type=int, default=2)
    ap.add_argument("--transactions", type=int, default=200, help="operations per process")
    ap.add_argument("--ledger", required=True, help="the ledger folder, or a Postgres DSN (made if absent; "
                    "a DSN's search_path schema is created when missing)")
    ap.add_argument("--results", default=str(LOAD_DIR / "results"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--lock", type=float, default=10.0, help="lock= seconds for alias and salt transactions")
    ap.add_argument("--keys", type=int, default=12, help="distinct eval keys (fewer: more memo hits)")
    ap.add_argument("--aliases", type=int, default=8)
    ap.add_argument("--shared", type=int, default=6, help="distinct shared seals raced across processes")
    ap.add_argument("--handles", type=int, default=3, help="fresh processes that recompute the fold")
    ap.add_argument("--timeout", type=float, default=1800.0, help="seconds before workers are killed")
    ap.add_argument("--no-fold-checks", action="store_true", help="skip the workers' mid-run fold digests")
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    res = run(parse(argv))
    bad = res["invariants"]["failures"] or res["errors"] or res["timed_out"]
    return 1 if bad else 0
