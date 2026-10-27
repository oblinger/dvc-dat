"""Dependency items: how a read inside a value function is traced, and whether a recorded item still holds.

Items (Module § Value ``Dependencies``):

``code``
    the ``db/code/<hash 16>`` subject of the code that ran (DAT 1037); holds when
    the function the ``fn`` item names resolves at the rev to the same subject
    (unsandboxed: the static import closure; sandbox: exactly the modules the
    run loaded, re-hashed as they are now, on disk or installed, A38, Q37, Q39).
``fn``
    the function's dotted name inside that code (``plane.measure.length``);
    holds beside a ``code`` item, which does the checking.
``code/<repo>``
    ``<commit 8>``; holds when the commit agrees with the environment's,
    whatever the ``db/repo/<repo>`` commit row says (T543 Q7 (C); Q1: the
    commit is the pin). A label, not a subject. The version is not in the
    item (T034); it stays readable from the ``db/repo/<repo>/<package>``
    clocks at the revision (DAT 1044).
``platform``
    the environment, now. (A sandboxed entry's third-party modules are in
    ``code``, each by its bytes or its distribution's ``RECORD``; there is no
    whole-``uv.lock`` item.)
``<subject> <predicate>``
    a two-position bracket read or ``get``: the held object.
``<name> db/alias``
    a load through an alias: the ``ref:`` the name resolves to (A35).
``ref:<class>:<hash>``
    a loaded value, named by its bytes; always holds (A27).
``eval:<name>{keys}``
    a nested eval: holds iff the nested lookup at the rev, never running,
    yields an entry with the recorded hash (A42, A45).
``salt``
    the ``db/salt`` of the mount a sandboxed function ran under, when set.
``q:{...}``
    a ``refs``/``values``/``value``/``select`` query (the whole query as
    canonical JSON, ``kind`` dotted, A41, A47) -> the sorted ``ref:`` list it
    answered; any other read (``all``, ``in``, a 1- or
    3-position bracket, ``history`` (recorded as ``rows``), ``get`` with
    ``since``) is ``q:{"__call__": …}`` -> a token of its result (for
    ``history``, its row count).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, Optional

from .codec import canonical, ref_text, strip_hint
from .errors import AliasLoop, LedgerError
from .value import Value, dotted

if TYPE_CHECKING:
    from .ledger import Ledger
    from .rev import Rev

NONE = "<none>"


def token(obj: Any) -> str:
    """A read's result as one comparable string."""
    from .rev import Ref, Rev, Row

    def conv(x: Any) -> Any:
        if isinstance(x, Ref):
            return x._text()
        if isinstance(x, Rev):
            return f"rev:{x.id}"
        if isinstance(x, Value):
            return ref_text(dotted(type(x)), x.hash)
        if isinstance(x, Row):
            return [conv(v) for v in x]
        if isinstance(x, (list, tuple)):
            return [conv(v) for v in x]
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        return x
    if obj is None:
        return NONE
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bool):
        return "true" if obj else "false"
    return canonical(conv(obj))


def _arg(x: Any) -> Any:
    from .rev import Ref

    if isinstance(x, Ref):
        return {"__ref__": x._text(), "subject": x.subject}
    return x


def call_item(call: str, args: Any, since: Optional["Rev"]) -> str:
    return "q:" + canonical({"__call__": call, "args": [_arg(a) for a in args],
                             "since": since.id if since is not None else None})


def query_item(ledger: "Ledger", s: Any, kind: Any, fn: Any, where: Any, one: bool, since: Any,
               preds: Dict[str, Any], rev: "Rev") -> str:
    from .rev import Ref

    q: Dict[str, Any] = {}
    for k, v in list(preds.items()) + list((where or {}).items()):
        if isinstance(v, Ref):
            v = v._text()
        elif isinstance(v, Value):
            v = ref_text(dotted(type(v)), v.hash)
        elif isinstance(v, (bool, int, float)):
            v = str(v)
        q[k] = v
    if kind is not None:
        q["kind"] = dotted(kind) if isinstance(kind, type) else kind
    if fn is not None:
        q["fn"] = fn
    if s is not None:
        q["s"] = s
    if since is not None:
        q["since"] = since.id
    if one:
        q["one"] = True
    return "q:" + canonical(q)


def _requery(rev: "Rev", body: Dict[str, Any]) -> str:
    from .rev import Ref

    if "__call__" in body:
        call, args = body["__call__"], body["args"]
        args = [Ref(rev, a["subject"]) if isinstance(a, dict) and "__ref__" in a else a for a in args]
        since = rev.ledger.at(body["since"]) if body.get("since") is not None else None
        try:
            if call == "getitem":
                return token(rev[tuple(args) if len(args) > 1 else args[0]])
            if call == "get":
                return token(rev.get(*args, since=since))
            if call == "all":
                return token(rev.all(*args, since=since))
            if call == "in":
                return token(tuple(args) in rev)
            if call == "rows":
                return token(len(rev.history(*args, since=since)))
            if call == "preds":
                return token(dict(Ref(rev, args[0])._preds()))
            if call == "aliases":
                return token(sorted(Ref(rev, args[0])._p._aliases_of(Ref(rev, args[0]).subject or "")))
            if call == "sealed_at":
                return token(Ref(rev, args[0])._sealed_at())
        except KeyError:
            return NONE
        raise ValueError(f"unknown recorded call {call!r}")
    q = dict(body)
    kw: Dict[str, Any] = {}
    for k in ("kind", "fn", "s"):
        if k in q:
            kw[k] = q.pop(k)
    if "since" in q:
        kw["since"] = rev.ledger.at(q.pop("since"))
    q.pop("one", None)
    where = {}
    for k, v in q.items():
        if isinstance(v, str) and v.startswith("ref:"):
            where[k] = _RefText(v)
        else:
            where[k] = v
    subs = rev._subjects(kw.get("s"), kw.get("kind"), kw.get("fn"), where, kw.get("since"), {})
    return canonical(sorted(rev._ref_text_of(x) for x in subs))


class _RefText(str):
    """A recorded where value naming a value by its ``ref:`` text."""

    _is_ref = True


def salt_at(rev: "Rev", nm: Optional[str]) -> str:
    """The ``salt`` of the mount the function named ``nm`` (an ``fn`` item) resolves under, at ``rev``."""
    from .fn import mounts_at

    if not nm:
        return NONE
    best = None
    for prefix, info in mounts_at(rev).items():
        if nm.startswith(prefix + ".") and (best is None or len(prefix) > len(best[0])):
            best = (prefix, info)
    return best[1].get("salt", NONE) if best else NONE


def present(rev: "Rev", item: str, recorded: str, env: Any, trace: Optional[Dict[str, str]] = None) -> bool:
    """Does the recorded item still hold at ``rev``."""
    from .rev import Ref

    if item == "salt":
        return salt_at(rev, (trace or {}).get("fn")) == recorded

    if item == "fn":                            # the name; the code item beside it is the check
        return "code" in (trace or {})
    if item == "code":
        from .fn import code_holds

        return code_holds(rev, recorded, (trace or {}).get("fn"))
    if item == "platform":
        return env().platform == recorded
    if item.startswith("ref:"):
        return True
    if item.startswith("code/"):                # the environment's commit, row or no row
        code = env().code.get(item[len("code/"):])
        c = code.commit if code is not None else None
        return bool(c) and bool(recorded) and (c.startswith(recorded) or recorded.startswith(c))
    if item.startswith("eval:"):
        from .fn import lookup_encoded

        i = item.index("{")
        hit = lookup_encoded(rev, item[5:i], item[i:])
        if hit is None:
            return recorded == NONE          # no entry then, and still none
        return ref_text(dotted(type(hit)), hit.hash) == recorded
    if item.startswith("q:"):
        return _requery(rev, json.loads(item[2:])) == recorded
    if item.endswith(" db/alias"):
        name = item[: -len(" db/alias")]
        try:
            r = Ref(rev, name)
        except AliasLoop:
            return recorded == NONE
        return (r._text() if r.hash else NONE) == recorded
    s, _, p = item.rpartition(" ")
    held = rev._held(s, p)
    if not held:
        return recorded == NONE
    text = held[0].obj
    from .codec import show

    return (strip_hint(text) if text.startswith("ref:") else show(text)) == recorded


def trace_matches(rev: "Rev", trace: Dict[str, str]) -> bool:
    """Every item holds at ``rev``: the memo's hit test. Never runs a function."""
    from .env import current_env

    plain = rev._plain()
    cache: list = []

    def env() -> Any:
        if not cache:
            cache.append(current_env())
        return cache[0]
    try:
        return all(present(plain, k, v, env, trace)
                   for k, v in sorted(trace.items(), key=lambda kv: kv[0] == "code"))
    except (LedgerError, ImportError):
        return False
