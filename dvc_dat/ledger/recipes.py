"""The ledger's just verbs: `python -m dvc_dat.ledger.recipes <verb> [args]`.

`values`, `value`, `history`, `why`, `set`, `index` and `bump`, the recipes
`dvc_dat.just` ships beside `run` and `mounts` (SVP 1465 Q1 (A)); a project
that does not import that file trampolines to this module. Each verb is one
ledger call; running a function or a spec is not here but `just run`, the one
way to run. What a Python caller spells out the verb supplies: the ledger
(`Ledger()`: `DAT_LEDGER`, else the nearest `.datconfig.yaml`'s `ledger:`
or `ledgers:` default),
`by=human:$USER`, `confirm=` (a typed `yes`), the checkout's packages on
`sys.path` (`why`, `bump <module>`), short kind names, hash prefixes, and
`k=v` arguments (v JSON, else the text as typed: `dvc_dat.do.arg_value`).
A refusal prints `<Error>: <message>` and exits 1; no verb exits 2.
"""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from dvc_dat.do import arg_value
from dvc_dat.ledger import Ledger, LedgerError, bump, bump_source

BY = f"human:{os.environ.get('USER', 'dan')}"


def checkout() -> Path:
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        sys.exit("not in a git checkout")
    return Path(top.stdout.strip())


def import_checkout() -> None:
    """Import the checkout's top-level packages, so discovery sees the repo the recipe runs in."""
    root = checkout()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for d in sorted(root.iterdir()):
        if (d / "__init__.py").is_file():
            importlib.import_module(d.name)


def parse(args):
    out = {}
    for a in args:
        k, eq, v = a.partition("=")
        if not eq or not k:
            sys.exit(f"{a!r}: an argument is k=v (v JSON, else the text as typed)")
        out[k] = arg_value(v)
    return out


def short_kind(rev, name):
    if "." in name:
        return name
    kinds = sorted({o for _s, o in rev.all("*", "db/kind") if o.rpartition(".")[2] == name})
    if len(kinds) != 1:
        sys.exit(f"kind {name!r}: {'no' if not kinds else len(kinds)} db/kind rows match {kinds}")
    return kinds[0]


def short(subject):
    """A subject as a value prints it (DAT 1036): a 64-hex hash as ``#`` + its first 8, else as is."""
    if len(subject) == 64 and all(c in "0123456789abcdef" for c in subject):
        return "#" + subject[:8]
    return subject


def show(rev, v):
    def text(p, o):
        if isinstance(o, list) and rev._card(p) == "many":
            return ",".join(str(x) for x in o)
        if isinstance(o, (dict, list)):
            return json.dumps(o)
        return str(o)
    preds = " ".join(f"{p}={text(p, o)}" for p, o in v.preds.items())
    return f"{str(v):<10} {preds}"


def query(rev, args):
    kw = parse(args)
    if "kind" in kw:
        kw["kind"] = short_kind(rev, kw["kind"])
    return kw


def values(args):
    rev = Ledger().at()
    for v in rev.values(**query(rev, args)):
        print(show(rev, v))


def value(args):
    rev = Ledger().at()
    print(show(rev, rev.value(**query(rev, args))))


def history(args):
    rev = Ledger().at()
    print(f"{'rev':>3}  {'by':<10} {'predicate':<10} object")
    for row in rev.history():
        if row.subject == args[0]:
            obj = short(row.object) if isinstance(row.object, str) else row.object
            sign = "" if row.added else "-"
            by = rev[row.rev.tx, "db/by"]       # a str, or a JSON dict printed canonically (DAT 1024)
            by = by if isinstance(by, str) else json.dumps(by, sort_keys=True, separators=(",", ":"))
            print(f"{row.rev.id:>3}  {by:<10} {sign + row.predicate:<10} {obj}")


def brief(text):
    """A dependency item or value, short: hashes to 8 hex, a query to its answer's size."""
    if text is None:
        return "(none)"
    if text.startswith("ref:"):
        cls, _, h = text[4:].partition(":")
        return f"{cls.rpartition('.')[2]}:{h[:8]}"
    if text.startswith("sha256:"):
        return text[7:15]
    if text.startswith("db/code/"):
        return text.rpartition("/")[2][:8]
    if text.startswith("q:"):
        return "query " + text[2:]
    if text.startswith("["):
        return f"-> {len(json.loads(text))} value(s)"
    return text


def why(args):
    import_checkout()                       # a mounted stage's code is checked against this checkout
    rev = Ledger().at()
    name, rest = args[0], parse(args[1:])
    v = rev.load(name)
    print(f"{name}: {short(v.subject)}, {'matches' if v.matches(rev) else 'does not match'} the head")
    print("dependencies: " + ", ".join(f"{brief(k)} {brief(t)}" for k, t in sorted(v.dependencies.items())
                                if not k.startswith("ref:")))
    prev = rest.get("against")
    if prev is None:
        moves = [r.object for r in rev.history(name, "db/alias") if r.added]
        prev = moves[-2] if len(moves) > 1 else None
    if prev is not None:
        other = rev.load(prev)
        moved = ", ".join(f"{brief(k)} {brief(a)} -> {brief(b)}" for k, (b, a) in v.diff(other).items())
        print(f"since {short(other.subject)}, its last target: {moved or 'nothing moved'}")


def set_recipe(args):
    """Rows on a subject: `k=v` a fact (v JSON, else the text); `alias=TARGET` is the name's `db/alias` row."""
    L = Ledger()
    subject, kw = args[0], parse(args[1:])
    kw.pop("alias", None)
    target = next((a.partition("=")[2] for a in args[1:] if a.startswith("alias=")), None)  # a name: as typed
    rev = L.at()
    if target is not None:
        aim = target if len(target) == 64 else rev.refs(s=f"{target}*", one=True).subject
        old = rev.get(subject, "db/alias")
    with L.transaction(by=BY) as t:
        for p, o in kw.items():
            t[subject, p] = o
        if target is not None:
            t.add(subject, "db/alias", aim)
    if kw:
        print(subject, " ".join(f"{p}={o}" for p, o in kw.items()))
    if target is not None:
        print(f"{subject}: {short(old) if old else '(none)'} -> {short(aim)}")


def index(args):
    L = Ledger()
    pred = args[0]
    with L.transaction(by=BY) as t:
        t.add(f"db/pred/{pred}", "db/index", "true")
    n = len(L.at().refs(where={pred: None}))
    print(f"{pred}: indexed; {n} subjects hold it")


def confirm(subject):
    def ask(old, new):
        print(f"{subject}: {old} -> {new}? ", end="", flush=True)
        answer = sys.stdin.readline().strip()
        print(answer)
        return answer == "yes"
    return ask


def bump_recipe(args):
    name, part = args[0], (args[1] if len(args) > 1 else "patch")
    ask = None if part == "patch" else confirm(name)
    if name == "db" or "/" in name:         # a ledger clock (db: the release); a module has no slash
        L = Ledger()
        old = L.at().get(name, "db/version", default="0.0.0")
        extra = {"why": "release"} if name == "db" else {}
        with L.transaction(by=BY, lock=10, **extra) as t:
            new = bump(t, name, part, confirm=ask)
        print(f"{name}: {old} -> {new}" + (", a release" if name == "db" else ""))
        return
    import_checkout()
    b = bump_source(name, part, confirm=ask)
    print(f"{name}: {b.old} -> {b.new} in {os.path.relpath(b.path)}")
    print(f'commit it: git commit -am "{name} {b.new}"')


RECIPES = {"values": values, "value": value, "history": history, "why": why, "set": set_recipe,
           "index": index, "bump": bump_recipe}

USAGE = "usage: python -m dvc_dat.ledger.recipes {" + ",".join(RECIPES) + "} [ARG ...]"


def main(argv: list) -> int:
    if not argv or argv[0] not in RECIPES:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        RECIPES[argv[0]](argv[1:])
    except (LedgerError, LookupError, TypeError, ValueError, RuntimeError, ImportError) as e:
        print(f"{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
