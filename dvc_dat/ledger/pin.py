"""``pin`` and ``rerun`` (SVP 250): a sealed value's commit tagged and pushed, so its run can be rerun.

A memo entry names the code that made it (``db/fn``, the ``db/code/<hash 16>`` item, the ``db/repo/<repo>
db/commit`` clock at its revision), but nothing keeps that commit alive: a squash-merge with the branch
deleted leaves it unreachable, and ``git gc`` or the host's collector removes it. A **pin** is a git tag
``dat/<commit12>`` on the commit, pushed to the repo's remote before ``pin`` returns, plus two rows:

``(db/repo/<repo>/<commit12>, db/pinned, dat/<commit12>)``
    one per commit per ledger: every value sealed from that commit is pinned by it. The tag is created once
    and reused by every ledger; a second ledger pinning the same commit writes only its own row.
``(<value>, db/rerunnable, true | recursive)``
    the value's claim: its commit is pinned, its function is importable by its dotted name from that commit (a
    top-level ``@dat.fn`` in the module the name says, at that commit: no closure, no lambda), and every input
    (a key or a traced read that is a value) resolves on this ledger. ``recursive``: every input that is itself
    a run's result makes the same claim, down to values with no run.

``t.pin(value, recursive=False, rerun=False)`` refuses (``NotPinned``, nothing written, no tag pushed) a value
that is not a run's result, a run whose revision names no ``db/repo/<repo> db/commit`` (code with no
``__version__``, or outside any checkout), a commit the repo's checkout here does not hold, a commit that does
not hold the bytes the run loaded (a sandboxed run at a dirty HEAD), a function not importable by its name
at the commit, an input that resolves to nothing (a ``foreign:`` read on the ledger it names), and a push the remote
refuses. ``rerun=True`` reruns at
once (``rerun``) and writes ``(<value>, db/rerun, <outcome>)``; ``differed-deterministic`` is ``Differed``.
``L.at().pin(value)`` is the one-shot form (``Head``). Idempotent: a pinned commit pays no push, a pinned value
adds no row.

``rev.rerun(value)`` reads the pin, checks the commit out under ``<ledger>/rerun/<commit12>/<repo>`` (a
worktree of the checkout here when it holds the commit, else ``git clone --depth 1 --branch dat/<commit12>``
from the remote: one commit's tree, no history, reused across reruns), syncs its ``uv.lock`` when it has one,
and runs the function there in a fresh interpreter (``python -m dvc_dat.ledger.pin``) over the value's recorded
keys at the value's revision, writing nothing. A copied value runs at its origin, ``db/copied-from``, while that
ledger can be found, else at this ledger's copy. The hash of what it returns against the value's: ``reproduced``,
else judged by the value's claim (the ``db/reproducible`` row, ``claim``): the listed predicates of the old and new
values are compared and the first clause that matches gives the level: ``exact``, ``differed-deterministic``, the one
error, raised by ``pin(rerun=True)`` alone; ``True``, ``differed-as-allowed``, since judging "good enough" needs a
comparator that does not exist yet; ``None`` or ``False``, ``differed-nondeterministic``. Nothing
is called verified: a match proves bit-identity for this run, not a guarantee. A sandboxed function reruns
in the sandbox worker of that interpreter, an unsandboxed one in the interpreter itself, its checkout the
worktree.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from .claim import EXACT, claim_of, judged
from .codec import sha256, show
from .env import current_env
from .errors import Differed, LedgerError, NotPinned
from .fn import AT, MNT, fn_mark_in_source, mounts_at

if TYPE_CHECKING:
    from .rev import Rev
    from .txn import Transaction

#: The tag a pin makes: ``dat/`` + the commit's first 12 hex.
TAG = "dat/"
C12 = 12
PINNED = "db/pinned"
RERUNNABLE = "db/rerunnable"
RERUN = "db/rerun"
#: A rerun's outcomes.
REPRODUCED = "reproduced"
DIFFERED_NONDETERMINISTIC = "differed-nondeterministic"
DIFFERED_DETERMINISTIC = "differed-deterministic"
DIFFERED_AS_ALLOWED = "differed-as-allowed"
OUTCOMES = (REPRODUCED, DIFFERED_AS_ALLOWED, DIFFERED_NONDETERMINISTIC, DIFFERED_DETERMINISTIC)
#: Seconds a push, a fetch or a rerun may take.
GIT_TIMEOUT = 600.0


def tag_of(commit: str) -> str:
    return TAG + commit[:C12]


def _git(cwd: Any, *args: str, timeout: float = 60.0, text: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=text, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise NotPinned(f"git {' '.join(args[:2])} in {cwd}: {e}") from None


def _blob(co: Path, spec: str) -> Optional[bytes]:
    """The bytes of ``<commit>:<path>``, exactly (no newline translation); ``None`` when the commit lacks it."""
    out = _git(co, "cat-file", "blob", spec, text=False)
    return out.stdout if out.returncode == 0 else None


def git(cwd: Any, *args: str, timeout: float = 60.0) -> str:
    """``git -C cwd args``, its stdout stripped; a failure is ``NotPinned`` with git's own words."""
    out = _git(cwd, *args, timeout=timeout)
    if out.returncode != 0:
        raise NotPinned(f"git {' '.join(args)} in {cwd}: {(out.stderr or out.stdout).strip()}")
    return out.stdout.strip()


# -- what a value's entry says of its run -------------------------------------------------------------------

@dataclass(frozen=True)
class Run:
    """A value's run as its memo entry records it: enough to pin its commit and run it again."""

    subject: str
    rev: Any                                    # the revision it was sealed at
    at: int                                     # the revision it read: db/at, else the seal's (a copy; before 2.59)
    name: str                                   # db/fn
    keys: Dict[str, Any]                        # db/keys, as stored
    trace: Dict[str, str]                       # db/deps/*
    sandboxed: bool
    repo: str
    commit: str
    modules: Dict[str, str]                     # the db/code item's relpath -> sha256
    mount_root: Optional[str]                   # the mount's db/root, sandboxed

    @property
    def tag(self) -> str:
        return tag_of(self.commit)

    @property
    def pin_subject(self) -> str:
        return f"db/repo/{self.repo}/{self.commit[:C12]}"


def subject_of(rev: "Rev", value: Any) -> str:
    """The subject ``value`` names: a sealed ``Value``, a ``Ref``, or a name (an alias or a subject)."""
    from .rev import Ref
    from .value import Value

    if isinstance(value, Value):
        if value.subject is None:
            raise NotPinned(f"an unsaved {type(value).__name__}: save it first (v.seal(t)); only a sealed value "
                            "is pinned")
        return value.subject
    if isinstance(value, Ref):
        s = value.subject
        if s is None:
            raise NotPinned(f"{value.name!r} holds no value at rev {rev.id}")
        return s
    if isinstance(value, str) and value:
        r = Ref(rev, value)
        if r.subject is None or r.hash is None:
            raise NotPinned(f"{value!r} holds no value at rev {rev.id}")
        return r.subject
    raise TypeError(f"pin takes a sealed Value, a Ref or a name, not {type(value).__name__}")


def run_of(rev: "Rev", subject: str) -> Run:
    """What the entry ``subject`` records of its run; ``NotPinned`` when it is no run's result, or its
    revision names no commit for its repo (or another than the run's)."""
    from .rev import Ref

    rows = rev._held_rows(subject=subject)
    held = {p: show(h.obj) for _s, p, h in rows}
    if "db/value" not in held:
        raise NotPinned(f"{subject[:12]}… holds no value at rev {rev.id}")
    prov = held.get("db/provenance", "")
    name = held.get("db/fn")
    if not prov.startswith("eval:") or not name:
        raise NotPinned(f"{subject[:12]}… is not a run's result (provenance {prov or 'none'}): nothing to rerun")
    sealed_at = Ref(rev, subject).sealed_at
    assert sealed_at is not None
    trace = {p[len("db/deps/"):]: show(h.obj) for _s, p, h in rows if p.startswith("db/deps/")}
    sandboxed = prov == "eval:sandbox"
    mount_root = None
    if sandboxed:
        if not name.startswith(MNT + "."):
            raise NotPinned(f"{subject[:12]}…: a sandboxed run of {name!r}, which is under no mount")
        mounts = mounts_at(sealed_at)
        prefix = max((p for p in mounts if name[len(MNT) + 1:] == p or name[len(MNT) + 1:].startswith(p + ".")),
                     key=len, default=None)
        if prefix is None or "repo" not in mounts[prefix]:
            raise NotPinned(f"{subject[:12]}…: {name!r} is under no mount at rev {sealed_at.id}")
        repo, mount_root = mounts[prefix]["repo"], mounts[prefix]["root"]
    else:
        repos = [k[len("code/"):] for k in trace if k.startswith("code/")]
        if len(repos) != 1:
            raise NotPinned(f"{subject[:12]}…: its run names {len(repos)} repos, not one; its code is outside "
                            "any git checkout")
        repo = repos[0]
    commit = held.get("db/commit") or sealed_at.get(f"db/repo/{repo}", "db/commit")   # a copy's own row, else the clock
    if not isinstance(commit, str) or not commit:
        raise NotPinned(f"{subject[:12]}…: rev {sealed_at.id} names no db/repo/{repo} db/commit (the first clean "
                        "run of code with a __version__ writes it); no commit vouches for this run")
    short = trace.get(f"code/{repo}")
    if short and not commit.startswith(short):
        raise NotPinned(f"{subject[:12]}…: its run was at {repo} {short}, but rev {sealed_at.id} names "
                        f"{commit[:8]}; the ledger does not say which commit made it")
    code = trace.get("code")
    mods = rev._held(code, "db/modules") if code else []
    modules = json.loads(show(mods[0].obj)) if mods else {}
    return Run(subject=subject, rev=sealed_at, at=int(held.get(AT, sealed_at.id)), name=name,
               keys=json.loads(held.get("db/keys", "{}")), trace=trace, sandboxed=sandboxed, repo=repo, commit=commit,
               modules=modules, mount_root=mount_root)


def value_inputs(keys: Dict[str, Any], trace: Dict[str, str]) -> List[str]:
    """The ``ref:`` texts of every value a run consumed on its own ledger: its value keys, and the values and
    nested results its trace recorded."""
    out: List[str] = []
    for v in keys.values():
        if isinstance(v, str) and v.startswith("ref:"):
            out.append(v)
    for k, v in trace.items():
        if k.startswith("ref:"):
            out.append(k)
        elif (k.endswith(" db/alias") or k.startswith("eval:")) and v.startswith("ref:"):
            out.append(v)
    return sorted(set(out))


def inputs_of(run: Run) -> List[str]:
    return value_inputs(run.keys, run.trace)


def foreign_inputs(trace: Dict[str, str]) -> List[Tuple[str, str]]:
    """``(<ledger>@<rev>, ref: text)`` of each value the run reached through another ``Rev`` (SVP 1521)."""
    from .trace import foreign_of

    return sorted({(body["at"], v) for k, v in trace.items() if (body := foreign_of(k)) is not None})


def inputs_in(rev: "Rev", subject: str) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """``(db/keys, the trace)`` of any sealed value: a hand seal has its deps, and no keys."""
    held = rev._held(subject, "db/keys")
    keys = json.loads(show(held[0].obj)) if held else {}
    trace = {p[len("db/deps/"):]: show(h.obj) for _s, p, h in rev._held_rows(subject=subject) if p.startswith("db/deps/")}
    return keys, trace


def holder_of(rev: "Rev", text: str) -> Optional[str]:
    """The subject holding the bytes ``text`` names at ``rev`` (the latest, as a hint-less row ref resolves)."""
    from .rev import Ref

    return Ref._from_text(rev, text).subject


# -- the checks at the commit ----------------------------------------------------------------------------------

def _tree(co: Path, commit: str) -> List[str]:
    return git(co, "ls-tree", "-r", "--name-only", commit).splitlines()


def module_file(run: Run) -> str:
    """The relpath (as the ``db/code`` item keys it) of the module the function's name says."""
    if run.sandboxed:
        rest = run.name[len(MNT) + 1:]
        mounts = mounts_at(run.rev)
        prefix = max(p for p in mounts if rest == p or rest.startswith(p + "."))
        parts = rest[len(prefix):].lstrip(".").split(".")[:-1]
        base = "/".join([str(run.mount_root).strip("/"), *parts]).strip("/")
    else:
        base = "/".join(run.name.split(".")[:-1])
    for rel in (base + ".py", base + "/__init__.py"):
        if rel in run.modules:
            return rel
    raise NotPinned(f"{run.subject[:12]}…: the code item of its run holds no module for {run.name!r} "
                    f"(looked for {base}.py); the function is not reachable by its name")


def tree_offset(co: Path, run: Run, tree: List[str]) -> str:
    """Where the module relpaths sit in the commit's tree (``""`` at the root, ``src/`` in a src layout)."""
    rel = module_file(run)
    hits = sorted((p[: -len(rel)] for p in tree if p == rel or p.endswith("/" + rel)), key=len)
    if not hits:
        raise NotPinned(f"{run.subject[:12]}…: commit {run.commit[:12]} of {run.repo} holds no {rel}; the "
                        "function is not importable from it")
    return hits[0]


def check_code_at(co: Path, run: Run) -> str:
    """The commit holds the bytes the run loaded, and the function's module defines it at the top level, marked
    ``@dat.fn``; returns the tree offset. ``NotPinned`` otherwise."""
    tree = _tree(co, run.commit)
    offset = tree_offset(co, run, tree)
    for rel, want in run.modules.items():
        if rel.startswith(("dist:", "py:")):
            continue                                # a third-party module: the lockfile's, not the tree's
        if offset + rel not in tree:
            raise NotPinned(f"{run.subject[:12]}…: commit {run.commit[:12]} of {run.repo} holds no {offset + rel}, "
                            "which its run loaded; the run was not of this commit's code")
        blob = _blob(co, f"{run.commit}:{offset + rel}")
        if blob is None or sha256(blob) != want:
            raise NotPinned(f"{run.subject[:12]}…: {offset + rel} at commit {run.commit[:12]} of {run.repo} is "
                            "not the file its run loaded (a run from a dirty checkout); commit the code and run "
                            "it again")
    src = _blob(co, f"{run.commit}:{offset + module_file(run)}")
    attr = run.name.rpartition(".")[2]
    try:
        tree_ast = ast.parse(src or b"")
    except SyntaxError as e:
        raise NotPinned(f"{run.subject[:12]}…: {module_file(run)} at commit {run.commit[:12]} does not parse: {e}")
    fdef = next((n for n in tree_ast.body if isinstance(n, ast.FunctionDef) and n.name == attr), None)
    if fdef is None or fn_mark_in_source(tree_ast, fdef) is None:
        raise NotPinned(f"{run.subject[:12]}…: {run.name!r} is not a top-level @dat.fn of {module_file(run)} at "
                        f"commit {run.commit[:12]} (a closure, a lambda, or a function made at import); a fresh "
                        "interpreter could not reach it by its name")
    return offset


def checkout_of(repo: str) -> Path:
    env = current_env()
    co = env.code.get(repo)
    if co is None or co.path is None:
        raise NotPinned(f"repo {repo!r} has no checkout in this environment; pin and rerun work from one")
    return Path(co.path)


def has_commit(co: Path, commit: str) -> bool:
    return _git(co, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def remote_of(co: Path) -> str:
    """The remote a tag is pushed to: the upstream of HEAD's branch, else ``origin``, else the one remote."""
    remotes = [r for r in git(co, "remote").splitlines() if r]
    if not remotes:
        raise NotPinned(f"{co}: no remote; a pin pushes its tag, so the checkout needs one")
    up = _git(co, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up.returncode == 0 and "/" in up.stdout.strip():
        name = up.stdout.strip().split("/", 1)[0]
        if name in remotes:
            return name
    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    raise NotPinned(f"{co}: {len(remotes)} remotes and no upstream; which one a pin pushes to is unclear")


def ensure_tag(co: Path, commit: str) -> bool:
    """The tag ``dat/<commit12>`` on ``commit`` in ``co``, pushed: made and pushed when absent (one push per
    commit; a failed push removes the tag, so a later pin pushes again); present, taken as pushed. Returns
    whether a push happened."""
    tag = tag_of(commit)
    if not has_commit(co, commit):
        raise NotPinned(f"commit {commit[:12]} is unknown to the checkout of {co} (gone with a deleted branch?); "
                        "nothing to tag")
    at = _git(co, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if at.returncode == 0:
        if at.stdout.strip() != commit:
            raise NotPinned(f"tag {tag} is on {at.stdout.strip()[:12]}, not {commit[:12]}; a tag names one commit")
        return False
    git(co, "tag", tag, commit)
    remote = remote_of(co)
    push = _git(co, "push", remote, f"refs/tags/{tag}", timeout=GIT_TIMEOUT)
    if push.returncode != 0:
        _git(co, "tag", "-d", tag)
        raise NotPinned(f"git push {remote} refs/tags/{tag} in {co} failed: {(push.stderr or push.stdout).strip()}; "
                        "the commit is not pinned")
    return True


# -- pin -------------------------------------------------------------------------------------------------------

def pin(t: "Transaction", value: Any, *, recursive: bool = False, rerun: bool = False) -> str:
    """``Transaction.pin``: see the module doc. Returns the tag."""
    t._open("pin")
    if not isinstance(recursive, bool) or not isinstance(rerun, bool):
        raise TypeError("recursive and rerun are True or False")
    rev = t._snapshot()
    subject = subject_of(rev, value)
    return _pin(t, rev, subject, recursive, rerun, set())


def check_input(rev: "Rev", subject: str) -> Run:
    """What the claim on ``subject`` rests on, checked: its run, its code at the commit, every input found (a
    ``foreign:`` read on the ledger it names). ``NotPinned`` otherwise."""
    from .named import rev_named

    run = run_of(rev, subject)
    co = checkout_of(run.repo)
    if not has_commit(co, run.commit):
        raise NotPinned(f"{subject[:12]}…: commit {run.commit[:12]} of {run.repo} is unknown to the checkout at {co} "
                        "(gone with a deleted branch?); it cannot be pinned")
    check_code_at(co, run)
    for text in inputs_of(run):
        if holder_of(rev, text) is None:
            raise NotPinned(f"{subject[:12]}…: its input {text[:40]}… is on no ledger here; a rerun could not "
                            "find it, so the claim is refused")
    for at, text in foreign_inputs(run.trace):
        try:
            found = holder_of(rev_named(at, rev.ledger), text)
        except (LedgerError, KeyError):
            found = None
        if found is None:
            raise NotPinned(f"{subject[:12]}…: its input {text[:40]}… at {at} cannot be found, so the claim is refused")
    return run


def assert_claim(t: "Transaction", rev: "Rev", run: Run, want: Optional[str], *, push: bool = False,
                 pin_only: bool = False) -> None:
    """The rows of a claim, in ``t`` (``rev`` its snapshot): the commit's ``db/pinned`` once per ledger, and unless
    ``pin_only`` the value's ``db/rerunnable``; ``push``: the tag made and pushed first."""
    if push:
        ensure_tag(checkout_of(run.repo), run.commit)
    pending = {(op.s, op.p): show(op.o) for op in t._ops if op.added}
    if rev.get(run.pin_subject, PINNED) != run.tag and pending.get((run.pin_subject, PINNED)) != run.tag:
        t.add(run.pin_subject, PINNED, run.tag)
    if pin_only:
        return
    held = pending.get((run.subject, RERUNNABLE), rev.get(run.subject, RERUNNABLE))
    if held != "recursive" and held != want:
        t.add(run.subject, RERUNNABLE, want)


def _pin(t: "Transaction", rev: "Rev", subject: str, recursive: bool, rerun: bool, seen: Set[str]) -> str:
    if subject in seen:
        return ""
    seen.add(subject)
    run = check_input(rev, subject)
    if recursive:
        for text in inputs_of(run):
            holder = holder_of(rev, text)
            if holder is not None and rev._held(holder, "db/fn"):   # a run's result: the same claim; a hand seal is a leaf
                _pin(t, rev, holder, True, False, seen)
    assert_claim(t, rev, run, "recursive" if recursive else "true", push=True)
    if rerun:
        outcome = _rerun(rev, run)
        t.add(subject, RERUN, outcome.outcome)
        if outcome.outcome == DIFFERED_DETERMINISTIC:
            raise Differed(f"{subject[:12]}…: {run.name} claims reproducible \"exact\", and its rerun at {run.tag} "
                           f"gave {outcome.hash[:12]}, not {outcome.expected[:12]}; nothing written")
    return run.tag


# -- rerun ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Rerun:
    """What a rerun found: ``outcome`` (one of ``OUTCOMES``), the ``hash`` it produced against the ``expected``
    one, ``reproducible``, the level the value's claim gave it (``claim.judged``), the ``commit``, its ``tag``
    and the ``worktree``."""

    outcome: str
    hash: str
    expected: str
    reproducible: Any
    commit: str
    tag: str
    worktree: Path

    @property
    def reproduced(self) -> bool:
        return self.outcome == REPRODUCED

    def __repr__(self) -> str:
        return f"<Rerun {self.outcome} {self.tag} {self.hash[:12]}>"


def rerun(rev: "Rev", value: Any) -> Rerun:
    """``Rev.rerun``: see the module doc."""
    plain = rev._plain()
    subject = subject_of(plain, value)
    run = run_of(plain, subject)
    if plain.get(run.pin_subject, PINNED) != run.tag:
        raise NotPinned(f"{subject[:12]}…: commit {run.commit[:12]} of {run.repo} is not pinned on this ledger; "
                        "pin the value first (t.pin(value))")
    home = origin_of(plain, subject)
    return _rerun(plain, run) if home is None else _rerun(home, run_of(home, subject))


def origin_of(rev: "Rev", subject: str) -> Optional["Rev"]:
    """The revision a copied value was copied from, while its ledger can be found (SVP 251); ``None`` otherwise."""
    from .named import rev_named

    text = rev.get(subject, "db/copied-from")
    if not isinstance(text, str):
        return None
    try:
        return rev_named(text)
    except (LedgerError, KeyError):
        return None


def worktree_root(ledger: Any) -> Path:
    """Where reruns check code out: ``rerun/`` beside the ledger's art store."""
    return Path(ledger._store.art.root).parent / "rerun"


def checkout_at(co: Path, run: Run, where: Path) -> Path:
    """The commit's tree at ``where``: reused when it is there at that commit; else a worktree of ``co`` when
    it holds the commit, else a depth-1 clone of the tag from ``co``'s remote."""
    if where.is_dir():
        head = _git(where, "rev-parse", "HEAD")
        if head.returncode == 0 and head.stdout.strip() == run.commit:
            return where
        if (where / ".git").is_file():          # a linked worktree of co
            _git(co, "worktree", "remove", "--force", str(where))
        shutil.rmtree(where, ignore_errors=True)
    where.parent.mkdir(parents=True, exist_ok=True)
    if has_commit(co, run.commit):
        git(co, "worktree", "add", "--detach", str(where), run.commit)
        return where
    remote = remote_of(co)
    url = git(co, "remote", "get-url", remote)
    out = _git(co.parent, "clone", "--quiet", "--depth", "1", "--branch", run.tag, url, str(where),
               timeout=GIT_TIMEOUT)
    if out.returncode != 0:
        raise NotPinned(f"git clone --depth 1 --branch {run.tag} {url}: {(out.stderr or out.stdout).strip()}; "
                        "the pin's tag is not on the remote")
    head = git(where, "rev-parse", "HEAD")
    if head != run.commit:
        raise NotPinned(f"{run.tag} on {url} is {head[:12]}, not {run.commit[:12]}")
    return where


def interpreter_for(where: Path) -> str:
    """The interpreter a rerun uses: the worktree's own venv from its ``uv.lock`` (``uv sync --frozen``), else
    this one."""
    if (where / "uv.lock").is_file():
        uv = shutil.which("uv")
        if uv is None:
            raise NotPinned(f"{where} has a uv.lock and uv is not on PATH; the rerun needs its locked environment")
        out = subprocess.run([uv, "sync", "--frozen", "--project", str(where)], capture_output=True, text=True,
                             timeout=GIT_TIMEOUT)
        if out.returncode != 0:
            raise NotPinned(f"uv sync in {where}: {(out.stderr or out.stdout).strip()}")
        py = where / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
        return str(py)
    return sys.executable


def _rerun(rev: "Rev", run: Run) -> Rerun:
    from .rev import Ref

    expected = Ref(rev, run.subject).hash
    assert expected is not None
    co = checkout_of(run.repo)
    where = checkout_at(co, run, worktree_root(rev.ledger) / run.commit[:C12] / run.repo)
    offset = check_code_at(where, run)
    for text in inputs_of(run):
        if holder_of(rev, text) is None:
            raise NotPinned(f"{run.subject[:12]}…: its input {text[:40]}… is on no ledger here; the rerun would "
                            "substitute nothing for it")
    py = interpreter_for(where)
    req = {"ledger": str(rev.ledger.path), "rev": run.at, "name": run.name, "keys": run.keys,
           "repo": run.repo, "commit": run.commit, "worktree": str(where),
           "preds": sorted({p for _level, preds in claim_of(rev, run.subject) for p in preds})}
    env = dict(os.environ)
    root = str(where / offset) if offset else str(where)
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("DAT_LEDGER", None)
    out = subprocess.run([py, "-m", "dvc_dat.ledger.pin"], input=json.dumps(req), capture_output=True, text=True,
                         cwd=str(where), env=env, timeout=GIT_TIMEOUT)
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if out.returncode != 0 or not lines:
        raise NotPinned(f"the rerun of {run.name} at {run.tag} failed (exit {out.returncode}):\n{out.stderr.strip()}")
    reply = json.loads(lines[-1])
    h = reply["hash"]
    claim = claim_of(rev, run.subject)
    old = {p: show(held[0].obj) for _level, preds in claim for p in preds if (held := rev._held(run.subject, p))}
    level = judged(claim, old, reply["preds"])
    return Rerun(outcome=outcome_of(h == expected, level), hash=h, expected=expected, reproducible=level,
                 commit=run.commit, tag=run.tag, worktree=where)


def outcome_of(same: bool, level: Any) -> str:
    """A rerun's outcome: the bits, then the level the claim gave."""
    if same:
        return REPRODUCED
    if level is True:
        return DIFFERED_AS_ALLOWED
    return DIFFERED_DETERMINISTIC if level == EXACT else DIFFERED_NONDETERMINISTIC


def child_main() -> int:
    """``python -m dvc_dat.ledger.pin``: the rerun's interpreter. Reads the request on stdin, runs the function
    at the worktree (its checkout) over the recorded keys, writing nothing, and prints the hash and the
    predicates its claim lists, as the new value carries them, as one JSON line."""
    from .env import Checkout, Env, platform_record, platform_tag, set_env_provider
    from .fn import work_root
    from .ledger import Ledger
    from .namespace import LedgerNamespace
    from .rev import Ref
    from .rundat import run_fn
    from ..core import Dat

    req = json.load(sys.stdin)
    where = Path(os.path.realpath(req["worktree"]))
    co = Checkout(None, req["commit"], False, where)
    set_env_provider(lambda: Env({req["repo"]: co}, platform_tag(), record=platform_record()))
    ledger = Ledger(req["ledger"])
    rev = ledger.at(req["rev"])
    keys = {k: (Ref._from_text(rev, v) if isinstance(v, str) and v.startswith("ref:") else v)
            for k, v in req["keys"].items()}
    ns = LedgerNamespace(rev=rev)
    obj = ns.load(req["name"])
    fn = obj if getattr(obj, "kind", None) == "ledger" else run_fn(rev, ns, keys)
    value = fn(kwargs=keys, seal=False)
    new = value.preds
    reply = {"hash": value.hash, "preds": {p: str(new[p]) for p in req["preds"] if p in new}}
    if isinstance(value, Dat):
        p = os.path.realpath(value.path)
        if p.startswith(os.path.realpath(work_root()) + os.sep):
            shutil.rmtree(Path(p).parent if Path(p).name == "dat" else p, ignore_errors=True)
    sys.stdout.flush()
    print(json.dumps(reply))
    return 0


if __name__ == "__main__":
    sys.exit(child_main())
