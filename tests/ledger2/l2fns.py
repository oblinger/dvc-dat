"""Revision functions for the ledger2 eval tests; ``CALLS`` counts real runs per name."""

from collections import Counter

from dvc_dat.ledger2 import Pickled

CALLS = Counter()


def double(rev, *, x: int):
    CALLS["double"] += 1
    return {"x": x, "out": 2 * x}


def scaled(rev, *, x: int, by: int = 3):
    CALLS["scaled"] += 1
    return x * by


def uses_model(rev, *, game: str):
    CALLS["uses_model"] += 1
    return f"{game}@{rev['model/shot', 'version']}"


def uses_norm(rev, *, game: str):
    CALLS["uses_norm"] += 1
    return {"game": game, "norm": rev.load("data/norm").obj}


def chain(rev, *, game: str):
    CALLS["chain"] += 1
    inner = rev.eval("l2fns.uses_model", game=game)
    return inner.obj + "!"


def metrics(rev, *, game: str):
    CALLS["metrics"] += 1
    return {"metrics": {"g5": 0.93 if game == "G5" else 0.5}, "game": game}


def boom(rev, *, x: int):
    CALLS["boom"] += 1
    raise RuntimeError("boom")


def returns_value(rev, *, x: int):
    CALLS["returns_value"] += 1
    return Pickled([x])


def no_keys(rev):
    CALLS["no_keys"] += 1
    return "constant"


def lists_versions(rev):
    CALLS["lists_versions"] += 1
    return sorted(r.subject for r in rev.refs(where={"version": None}))
