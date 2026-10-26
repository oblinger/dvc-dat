"""The ledger-just notebook's recipe bodies: `python ledger_recipes.py <recipe> [args]`.

Each recipe is one ledger call; running a function or a spec is not here but
`just run` (dvc_dat.just), the one way to run. What a Python caller spells out the recipe
supplies: the ledger (`Ledger()`), `by=human:$USER`, `confirm=` (a typed
`yes`), the checkout's packages on `sys.path` (`bump <module>`), short kind
names, hash prefixes, and `k=v` (a string) / `k:=v` (JSON) arguments.
"""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

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
        if ":=" in a:
            k, v = a.split(":=", 1)
            out[k] = json.loads(v)
        elif "=" in a:
            k, v = a.split("=", 1)
            out[k] = v
        else:
            sys.exit(f"{a!r}: an argument is k=v (a string) or k:=v (JSON)")
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
    for row in rev.rows():
        if row.subject == args[0]:
            obj = short(row.object) if isinstance(row.object, str) else row.object
            sign = "" if row.added else "-"
            print(f"{row.rev.id:>3}  {rev[row.rev.tx, 'db/by']:<10} {sign + row.predicate:<10} {obj}")


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
        moves = [r.object for r in rev.rows(name, "db/alias") if r.added]
        prev = moves[-2] if len(moves) > 1 else None
    if prev is not None:
        other = rev.load(prev)
        moved = ", ".join(f"{brief(k)} {brief(a)} -> {brief(b)}" for k, (b, a) in v.diff(other).items())
        print(f"since {short(other.subject)}, its last target: {moved or 'nothing moved'}")


def set_recipe(args):
    L = Ledger()
    subject, kw = args[0], parse(args[1:])
    with L.transaction(by=BY) as t:
        for p, o in kw.items():
            t[subject, p] = o
    print(subject, " ".join(f"{p}={o}" for p, o in kw.items()))


def alias(args):
    L = Ledger()
    name, target = args
    rev = L.at()
    subject = target if len(target) == 64 else rev.refs(s=f"{target}*", one=True).subject
    old = rev.get(name, "db/alias")
    with L.transaction(by=BY) as t:
        t.add(name, "db/alias", subject)
    print(f"{name}: {short(old) if old else '(none)'} -> {short(subject)}")


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
    if name == "db":
        L = Ledger()
        old = L.at().get("db", "version", default="0.0.0")
        with L.transaction(by=BY, lock=10, why="release") as t:
            new = bump(t, "db", part, confirm=ask)
        print(f"db: {old} -> {new}, a release")
        return
    import_checkout()
    b = bump_source(name, part, confirm=ask)
    rel = os.path.relpath(b.path)
    print(f"{name}: {b.old} -> {b.new} in {rel}")
    print(f'commit it: git commit -am "{name} {b.new}"')


RECIPES = {"values": values, "value": value, "history": history, "why": why, "set": set_recipe,
           "alias": alias, "index": index, "bump": bump_recipe}

if __name__ == "__main__":
    try:
        RECIPES[sys.argv[1]](sys.argv[2:])
    except (LedgerError, LookupError, TypeError, ValueError, RuntimeError, ImportError) as e:
        print(f"{type(e).__name__}: {e}")
        sys.exit(1)
