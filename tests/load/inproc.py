"""The in-process leg: N ``Ledger`` handles on one ledger, M threads across them, one flipper (SVP 1468, R0001).

The multiprocess harness (``harness.py``) gives every process one handle. This leg opens ``--handles``
handles on one ledger in one process and runs ``--threads`` threads over them (thread ``j`` on handle
``j % N``), each doing ``--transactions`` operations:

``write``  one transaction adding ``K`` rows ``(ip/<tag>, part, k)``, tagged ``by=<tag>``; every
           other write under ``lock=``
``read``   ``rev = h.at()``: the ``ip/*`` parts folded at ``rev``, the flipped cardinality and type
           observed at ``rev``

A flipper thread on handle 0 commits, under ``lock=``, a cycle of declaration changes: the cardinality
of ``flipc`` (``one`` / ``many``; ``flip/s`` holds two rows, so the fold answers one object or two),
the ``db/type`` of ``flipt`` (``str`` / ``json``; ``flip/t`` holds a str, so the typed read answers or
raises ``TypeError``), and a fresh ``db/index`` declaration. Right after each commit it asks every
other handle.

Invariants, checked after the run from a fresh handle:

``revisions``  revisions 1..top, one ``db/by`` each; no revision committed twice; each thread's commits
               increasing; a thread's ``h.at()`` never below its previous one or its own last commit
``no-half``    no read saw a subject holding other than ``K`` parts; every committed tag's ``K`` rows at
               its revision; no failed transaction's tag in the ledger
``as-of``      every read's digest of the ``ip/*`` subjects equals the fresh handle's at the same revision
               and the subjects the commit log puts at or below it
``flip``       every observed cardinality and type equals the last flip at or below the read's revision;
               after a flip at ``R`` every other handle's next ``at()`` is ``>= R`` and answers the new value;
               after an index declaration every other handle lists the index and reads the row

``python -m tests.load.inproc --handles 4 --threads 8 --transactions 200 --ledger <folder or DSN>``;
results in ``--results`` (a JSON and a ``summary.txt`` line, as ``harness.py``).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import platform
import random
import threading
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tests.load.harness import LOAD_DIR, is_dsn, lat, machine, make_schema, pin_env

K = 4
CARDS = ("many", "one")
TYPES = ("str", "json")


def setup(path: Any) -> int:
    from dvc_dat.ledger import Ledger

    if is_dsn(path):
        make_schema(path)
    L = Ledger(path, create=True)
    with L.transaction(by="inproc:setup") as t:
        t.add("db/pred/part", "db/cardinality", "many")
        t.add("db/pred/flipc", "db/cardinality", CARDS[0])
        t.add("flip/s", "flipc", "x")
        t.add("flip/s", "flipc", "y")
        t.add("db/pred/flipt", "db/type", TYPES[0])
        t.add("flip/t", "flipt", "hello")
    top = t.rev.id
    L.close()
    return top


def observe(rev: Any) -> Tuple[str, str]:
    """The cardinality of ``flipc`` and the type of ``flipt`` as ``rev`` answers them."""
    n = len(rev.all("flip/s", "flipc"))
    card = "many" if n == 2 else "one" if n == 1 else f"?{n}"
    try:
        typ = "str" if rev["flip/t", "flipt"] == "hello" else "?"
    except TypeError:
        typ = "json"
    return card, typ


def parts(rev: Any) -> Tuple[Dict[str, int], str]:
    """``ip/*`` subject -> parts held at ``rev``, and a digest of the subjects."""
    counts: Counter = Counter(s for s, _o in rev.all("ip/*", "part"))
    return dict(counts), hashlib.sha256("\n".join(sorted(counts)).encode()).hexdigest()


def worker(j: int, h: Any, cfg: Dict[str, Any], start: threading.Event, rec: Dict[str, Any]) -> None:
    from dvc_dat.ledger import LedgerError, LockTimeout

    rng = random.Random(cfg["seed"] * 1000 + j)
    last_at = 0
    last_commit = 0
    start.wait()
    t_start = time.perf_counter()
    for i in range(cfg["transactions"]):
        op = "write" if rng.random() < cfg["write_share"] else "read"
        tag = f"ip:t{j}:{i}"
        t0 = time.perf_counter()
        try:
            if op == "write":
                lock = cfg["lock"] if i % 2 else None
                with h.transaction(by=tag, lock=lock) as t:
                    for k in range(K):
                        t.add(f"ip/{tag}", "part", str(k))
                R = t.rev.id
                if R <= last_commit:
                    rec["violations"].append({"invariant": "revisions", "why": "a thread's commits not increasing",
                                              "thread": j, "rev": R, "previous": last_commit})
                last_commit = R
                rec["committed"].append({"tag": tag, "rev": R, "thread": j})
            else:
                rev = h.at()
                if rev.id < last_at or rev.id < last_commit:
                    rec["violations"].append({"invariant": "revisions", "why": "at() went backwards",
                                              "thread": j, "rev": rev.id, "last_at": last_at,
                                              "last_commit": last_commit})
                last_at = rev.id
                counts, digest = parts(rev)
                bad = {s: n for s, n in counts.items() if n != K}
                if bad:
                    rec["violations"].append({"invariant": "no-half", "why": "a subject with other than K parts",
                                              "thread": j, "rev": rev.id, "subjects": dict(list(bad.items())[:5])})
                card, typ = observe(rev)
                rec["reads"].append({"rev": rev.id, "n": len(counts), "digest": digest, "card": card,
                                     "type": typ, "thread": j})
            rec["counts"][op]["ok"] += 1
        except (LockTimeout, LedgerError) as e:
            rec["counts"][op][type(e).__name__] += 1
            if op == "write":
                rec["failed"].append({"tag": tag, "why": f"{type(e).__name__}: {e}"})
        except Exception as e:  # noqa: BLE001 - every other raise is an error, reported in full
            rec["counts"][op]["error"] += 1
            if op == "write":
                rec["failed"].append({"tag": tag, "why": f"{type(e).__name__}: {e}"})
            rec["errors"].append({"thread": j, "op": op, "i": i, "error": f"{type(e).__name__}: {e}",
                                  "traceback": traceback.format_exc()})
        rec["lat"][op].append(time.perf_counter() - t0)
    rec["elapsed"][j] = time.perf_counter() - t_start


def flipper(handles: List[Any], cfg: Dict[str, Any], start: threading.Event, done: threading.Event,
            rec: Dict[str, Any]) -> None:
    from dvc_dat.ledger import LockTimeout
    from dvc_dat.ledger.store import index_name

    A = handles[0]
    card, typ = CARDS[0], TYPES[0]
    start.wait()
    k = 0
    while k < cfg["flips"] and not done.is_set():
        kind = ("card", "type", "index")[k % 3]
        try:
            with A.transaction(by=f"inproc:flip:{k}", lock=cfg["lock"]) as t:
                if kind == "card":
                    new = CARDS[(CARDS.index(card) + 1) % 2]
                    t.add("db/pred/flipc", "db/cardinality", new)
                elif kind == "type":
                    new = TYPES[(TYPES.index(typ) + 1) % 2]
                    t.add("db/pred/flipt", "db/type", new)
                else:
                    new = f"idx{k}"
                    t.add(f"db/pred/{new}", "db/index", "true")
                    t.add("ix/s", new, "v")
        except LockTimeout:
            rec["flip_lock_timeouts"] += 1
            k += 1
            continue
        R = t.rev.id
        if kind == "card":
            card = new
        elif kind == "type":
            typ = new
        rec["flips"].append({"k": k, "kind": kind, "value": new, "rev": R})
        for n, h in enumerate(handles[1:], 1):
            rev = h.at()
            if rev.id < R:
                rec["violations"].append({"invariant": "flip", "why": "another handle's next at() below the flip",
                                          "handle": n, "flip": R, "at": rev.id})
            if kind == "index":
                got = rev.get("ix/s", new)
                if index_name(new) not in h._store.index_names() or got != "v":
                    rec["violations"].append({"invariant": "flip", "why": "index declaration not seen by another "
                                              "handle", "handle": n, "flip": R, "pred": new, "got": got})
            else:
                seen = observe(rev)
                if seen != (card, typ):
                    rec["violations"].append({"invariant": "flip", "why": "another handle's next read answers the "
                                              "old declaration", "handle": n, "flip": R, "kind": kind,
                                              "want": [card, typ], "got": list(seen)})
        k += 1
        time.sleep(cfg["flip_pause"])


def check(path: Any, setup_top: int, rec: Dict[str, Any]) -> Dict[str, Any]:
    from dvc_dat.ledger import Ledger

    F = Ledger(path)
    store = F._store
    top = F.at().id
    failures: List[Dict[str, Any]] = []
    counts: Counter = Counter()

    def fail(inv: str, **detail: Any) -> None:
        if counts[inv] < 25:
            failures.append({"invariant": inv, **detail})
        counts[inv] += 1

    for v in rec["violations"]:
        fail(v["invariant"], **{k: x for k, x in v.items() if k != "invariant"})

    # revisions
    revs = [r[0] for r in store.read("SELECT DISTINCT rev FROM quads ORDER BY rev")]
    if revs != list(range(1, top + 1)):
        fail("revisions", why="revisions not 1..top", top=top, missing=sorted(set(range(1, top + 1)) - set(revs))[:50])
    by_rows = store.read("SELECT rev, object FROM quads WHERE predicate = 'db/by'")
    per_rev = Counter(r[0] for r in by_rows)
    for R in range(1, top + 1):
        if per_rev.get(R, 0) != 1:
            fail("revisions", why="db/by rows at a revision", rev=R, count=per_rev.get(R, 0))
    committed = rec["committed"]
    for R, n in Counter(c["rev"] for c in committed).items():
        if n > 1:
            fail("revisions", why="two transactions report one revision", rev=R, count=n)
    flip_revs = {f["rev"] for f in rec["flips"]}
    for c in committed:
        if c["rev"] in flip_revs:
            fail("revisions", why="a write and a flip report one revision", rev=c["rev"])

    # no-half
    tag_rev = {o[len("str:"):]: r for r, o in by_rows}
    for c in committed:
        if tag_rev.get(c["tag"]) != c["rev"]:
            fail("no-half", why="committed tag not at its revision", tag=c["tag"], rev=c["rev"],
                 found=tag_rev.get(c["tag"]))
        rows = store.rows(top, subject=f"ip/{c['tag']}", predicate="part")
        if len(rows) != K or any(r[0] != c["rev"] for r in rows):
            fail("no-half", why="committed tag's parts not K rows at its revision", tag=c["tag"], rev=c["rev"],
                 rows=[r[0] for r in rows])
    for f in rec["failed"]:
        if f["tag"] in tag_rev:
            fail("no-half", why="a failed transaction's tag is in the ledger", tag=f["tag"], err=f["why"])

    # as-of
    commit_revs = sorted(c["rev"] for c in committed)
    subj_by_rev = sorted((c["rev"], f"ip/{c['tag']}") for c in committed)
    fresh: Dict[int, str] = {}
    for r in rec["reads"]:
        R = r["rev"]
        if R not in fresh:
            fresh[R] = parts(F.at(R))[1]
        if r["digest"] != fresh[R]:
            fail("as-of", why="a read's digest differs from the fresh handle's at its revision", read=r,
                 fresh=fresh[R])
        want = hashlib.sha256("\n".join(sorted(s for x, s in subj_by_rev if x <= R)).encode()).hexdigest()
        if r["digest"] != want:
            fail("as-of", why="a read's subjects are not the commit log's at its revision", read=r,
                 log_count=sum(1 for x in commit_revs if x <= R))

    # flip: ground truth at a revision is the last flip at or below it
    timeline = [(setup_top, "card", CARDS[0]), (setup_top, "type", TYPES[0])]
    timeline += [(f["rev"], f["kind"], f["value"]) for f in rec["flips"] if f["kind"] != "index"]
    timeline.sort()

    def truth(R: int) -> Tuple[str, str]:
        out = {"card": "", "type": ""}
        for x, kind, value in timeline:
            if x > R:
                break
            out[kind] = value
        return out["card"], out["type"]
    for r in rec["reads"]:
        want = truth(r["rev"])
        if (r["card"], r["type"]) != want:
            fail("flip", why="a read answers a declaration other than the one at its revision", read=r,
                 want=list(want))
    for f in rec["flips"]:
        if f["kind"] != "index" and observe(F.at(f["rev"])) != truth(f["rev"]):
            fail("flip", why="the fresh handle disagrees with the flip log", flip=f)
    F.close()
    return {"failures": failures, "counts": dict(counts), "top": top, "setup_top": setup_top,
            "checked": {"committed": len(committed), "reads": len(rec["reads"]), "flips": len(rec["flips"]),
                        "revisions_read": len(fresh)}}


def run(args: argparse.Namespace) -> Dict[str, Any]:
    pin_env()
    from dvc_dat.ledger import Ledger

    path: Any = args.ledger if is_dsn(args.ledger) else Path(args.ledger).expanduser().resolve()
    results = Path(args.results).expanduser().resolve()
    results.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    setup_top = setup(path)
    cfg = {"ledger": str(path), "handles": args.handles, "threads": args.threads,
           "transactions": args.transactions, "write_share": args.write_share, "lock": args.lock,
           "flips": args.flips, "flip_pause": args.flip_pause, "seed": args.seed, "k": K}
    handles = [Ledger(path) for _ in range(args.handles)]
    rec: Dict[str, Any] = {"committed": [], "failed": [], "reads": [], "violations": [], "errors": [],
                           "flips": [], "flip_lock_timeouts": 0, "elapsed": {},
                           "counts": {op: Counter() for op in ("write", "read")},
                           "lat": {op: [] for op in ("write", "read")}}
    start, done = threading.Event(), threading.Event()
    threads = [threading.Thread(target=worker, args=(j, handles[j % args.handles], cfg, start, rec), daemon=True)
               for j in range(args.threads)]
    flip = threading.Thread(target=flipper, args=(handles, cfg, start, done, rec), daemon=True)
    for th in (*threads, flip):
        th.start()
    t0 = time.perf_counter()
    start.set()
    deadline = t0 + args.timeout
    for th in threads:
        th.join(timeout=max(0.1, deadline - time.perf_counter()))
    done.set()
    flip.join(timeout=60)
    wall = time.perf_counter() - t0
    hung = [th.name for th in (*threads, flip) if th.is_alive()]
    for h in handles:
        h.close()
    inv = check(path, setup_top, rec)
    txs = len(rec["committed"]) + len(rec["flips"])
    res = {
        "date": stamp, "machine": machine(path), "config": cfg, "wall_s": round(wall, 3), "hung": hung,
        "transactions_committed": txs, "top": inv["top"],
        "tx_per_s": round(txs / wall, 2) if wall else None,
        "reads": len(rec["reads"]), "reads_per_s": round(len(rec["reads"]) / wall, 2) if wall else None,
        "flips": len(rec["flips"]), "flip_lock_timeouts": rec["flip_lock_timeouts"],
        "counts": {op: dict(c) for op, c in rec["counts"].items()},
        "latency": {op: lat(xs) for op, xs in rec["lat"].items()},
        "errors": rec["errors"][:20], "invariants": inv,
    }
    store = "-pg" if is_dsn(path) else ""
    out = results / (f"{stamp}-{platform.node().split('.')[0]}{store}-inproc-h{args.handles}-t{args.threads}"
                     f"-m{args.transactions}.json")
    out.write_text(json.dumps(res, indent=1))
    res["file"] = str(out)
    line = summary(res)
    with open(results / "summary.txt", "a") as fh:
        fh.write(line + "\n")
    print(line)
    return res


def summary(res: Dict[str, Any]) -> str:
    inv = res["invariants"]
    bad = ",".join(f"{k}={v}" for k, v in sorted(inv["counts"].items())) or "none"
    c, L = res["config"], res["latency"]
    lt = sum(v.get("LockTimeout", 0) for v in res["counts"].values())
    return (f"{res['date']} {res['machine']['host']} {res['machine']['store']} inproc h={c['handles']} "
            f"t={c['threads']} m={c['transactions']} wall={res['wall_s']}s tx={res['transactions_committed']} "
            f"tx/s={res['tx_per_s']} reads/s={res['reads_per_s']} flips={res['flips']} "
            f"write-p50={L.get('write', {}).get('p50_ms')}ms write-p99={L.get('write', {}).get('p99_ms')}ms "
            f"read-p50={L.get('read', {}).get('p50_ms')}ms read-p99={L.get('read', {}).get('p99_ms')}ms "
            f"lock_timeouts={lt} errors={len(res['errors'])} hung={len(res['hung'])} invariant_failures={bad} "
            f"-> {res['file']}")


def parse(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m tests.load.inproc", description=__doc__.split("\n")[0])
    ap.add_argument("--handles", type=int, default=4)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--transactions", type=int, default=200, help="operations per thread")
    ap.add_argument("--ledger", required=True, help="the ledger folder, or a Postgres DSN")
    ap.add_argument("--results", default=str(LOAD_DIR / "results"))
    ap.add_argument("--write-share", type=float, default=0.5)
    ap.add_argument("--lock", type=float, default=10.0, help="lock= seconds for every other write and the flips")
    ap.add_argument("--flips", type=int, default=60)
    ap.add_argument("--flip-pause", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=900.0)
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    res = run(parse(argv))
    return 1 if res["invariants"]["failures"] or res["errors"] or res["hung"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
