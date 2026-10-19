"""Trace items: how a read inside a value function is named, and whether a recorded item still holds.

Items (Module § Value ``Trace``):

``fn``
    the ``db/fn/<name>/<hash>`` subject of the code that ran; holds when the
    name resolves at the rev to the same subject (base: the module's source;
    sandbox: the recorded modules re-hashed at the rev's commit, A38, Q37).
``code/<repo>``
    ``<version>+<commit 8>``; holds when the commit agrees with the rev's
    ``code/<repo>`` row (or, no row, the environment's), the version being
    informational (Q1: the commit is the pin).
``uv.lock``, ``platform``
    the environment, now.
``<subject> <predicate>``
    a two-position bracket read or ``get``: the held object.
``<name> db/alias``
    a load through an alias: the ``ref:`` the name resolves to (A35).
``ref:<class>:<hash>``
    a loaded value, named by its bytes; always holds (A27).
``eval:<name>{keys}``
    a nested eval: holds iff the nested lookup at the rev, never running,
    yields an entry with the recorded hash (A42, A45).
``q:{...}``
    a ``refs``/``values``/``value``/``select`` query (the whole query as
    canonical JSON, ``kind`` dotted, A41, A47) -> the sorted ``ref:`` list it
    answered; any other read (``all``, ``in``, ``asserted``, a 1- or
    3-position bracket, ``rows``, ``get`` with ``since``) is
    ``q:{"__call__": …}`` -> a token of its result.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, Optional

from .codec import canonical, parse_ref, ref_text, strip_hint
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
            if call == "asserted":
                return token(rev.asserted(*args))
            if call == "rows":
                return token(len(rev.rows(since=since)))
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


def present(rev: "Rev", item: str, recorded: str, env: Any) -> bool:
    """Does the recorded item still hold at ``rev``."""
    from .rev import Ref

    if item == "fn":
        from .fn import fn_holds

        return fn_holds(rev, recorded)
    if item == "uv.lock":
        return env().lock == recorded
    if item == "platform":
        return env().platform == recorded
    if item.startswith("ref:"):
        return True
    if item.startswith("code/"):
        repo = item[len("code/"):]
        c = rev.get(item, "commit")
        if c is None:
            code = env().code.get(repo)
            c = code.commit if code is not None else None
        want = recorded.rpartition("+")[2]
        return bool(c) and bool(want) and (c.startswith(want) or want.startswith(c))
    if item.startswith("eval:"):
        from .fn import lookup_encoded

        i = item.index("{")
        hit = lookup_encoded(rev, item[5:i], item[i:])
        return hit is not None and ref_text(dotted(type(hit)), hit.hash) == recorded
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
        return all(present(plain, k, v, env) for k, v in sorted(trace.items(), key=lambda kv: kv[0] == "fn"))
    except (LedgerError, ImportError):
        return False
