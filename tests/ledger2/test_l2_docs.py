"""Executable docs: the fenced Python blocks of the SVP447 Ledger Module page, copied in, one test each.

Lines are as written on the page except where a comment marked ADAPTED says what changed and why;
the page's `# result` comments become asserts below them. The page's stand-ins (`Video(read_mp4(...))`,
`cut_by_hand`, `demo_game.identity.train`) are the test kinds in ``l2kinds``; the environment is the
suite's pinned one (repo `testrepo`), so `code/demo-game` reads `code/testrepo`.
"""

import pytest

from dvc_dat.ledger2 import Exists, Ledger, Ref, Rev, Value, attr, bump, ledger_class, ledger_fn  # noqa: F401
from l2kinds import Cut, Video


def read_mp4(name):
    return f"frames of {name}".encode()


def cut_by_hand(raw):
    return raw.frames[:6]


@pytest.fixture
def L(tmp_path):
    L = Ledger(tmp_path / "doc", create=True)        # ADAPTED: `Ledger(tmp, create=True)`
    with L.transaction(by="setup") as t:
        t.add("code/testrepo", "version", "0.2.2")
        t.add("code/testrepo", "commit", "abc1234")
        t.add("db/pred/version", "db/cardinality", "one")
        t.add("db/pred/version", "db/doc", "what bump moves")
        t.add("db/pred/game", "db/index", "true")
        t.add("db/pred/video", "db/type", "l2kinds.Video")
        t.add("db/pred/team", "db/cardinality", "many")
    return L


def test_usage_block(L, tmp_path, monkeypatch):
    """The usage block at the top of the page."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DAT_LEDGER", str(L.path))     # ADAPTED: `Ledger()` finds this ledger
    L = Ledger()                             # nearest .datconfig.yaml
    rev = L.at()                             # one snapshot per session
    assert rev["code/testrepo", "version"] == "0.2.2"          # "0.2.2"; one or raise
    assert rev["code/testrepo"] == {"version": "0.2.2", "commit": "abc1234"}   # its record, a dict
    assert rev.get("model/shot", "db/value") is None           # a Ref, or None
    assert rev.asserted("code/testrepo", "version", "0.2.1") == []   # [Rev]: when
    assert [(r.id, o, a) for r, o, a in rev.asserted("code/testrepo", "version")] == [(1, "0.2.2", True)]
    assert rev.rows(since=L.at(0))                              # [Row], unfolded (A48)
    assert [r.subject for r in rev.refs(s="db/pred/*", where={"db/index": "true"})] == ["db/pred/game"]
    assert ("db/pred/game", "db/index", "true") in rev

    with L.transaction(by="setup") as t:                        # ADAPTED: a game and its video to run on
        t["game/G1"] = {"home": "G4", "away": "G5"}
        raw0 = Video(read_mp4("G1.mp4"))
        raw0.preds.update(game="G1")
        t.add_value(raw0)
    rev = L.at()
    m = rev.eval("l2kinds.cut", game="G1")   # memoised  ADAPTED: l2kinds.cut for demo_game.identity.train
    assert m.trace and m.rev and m.sealed    # the model itself, with its provenance on it
    assert rev.eval("l2kinds.cut", game="G1", memo=False).sealed is False   # run, no seal
    assert rev.eval("l2kinds.cut", game="G1", memo="get").subject == m.subject   # or None

    f = rev.load_fn("l2kinds.cut")           # Fn: resolved at rev
    assert f(game="G1").subject == m.subject  # == rev.eval(...)  ADAPTED: G1, the game that exists
    assert f.module.name == "l2kinds.py" and len(f.sha) == 64 and f.mode == "base" and f.env.platform

    rev = L.at()                             # ADAPTED: refs are as-of; the entry is after the old rev
    assert len(rev.values(fn="l2kinds.cut")) == 1               # [Value], loaded
    assert rev.value(fn="l2kinds.cut", game="G1").subject == m.subject   # exactly one
    refs = rev.refs(fn="l2kinds.cut", game="G1")                # [Ref]
    assert refs[0].preds["game"] == "G1"     # its preds, nothing loaded
    assert refs[0].load().subject == m.subject                  # the value, fixed at its rev
    assert max(refs, key=lambda r: r.sealed_at.id).subject == m.subject   # the latest, nothing loaded
    assert rev.select(("game", "version"), fn="l2kinds.cut") == [("G1", "1.0.0")]   # tuples
    assert rev.all(since=L.at(1))            # every row in (1, rev.id]

    with L.transaction(by="human:dan", time=True, why="T531") as t:
        assert bump(t, "code/testrepo", "patch") == "0.2.3"     # 0.2.2 -> 0.2.3, and commit from the checkout
        t["env/prod", "rev"] = "413"         # add, on a one pred
        t.add(t.tx, "checked", "G1,G4,G5")
    assert t.rev.id == L.at().id
    assert t.rev[t.rev.tx, "db/by"] == "human:dan"

    with L.transaction(by="agent:svp", lock=30) as t:
        v = t.base["code/testrepo", "version"]       # nothing can move
        mv = Ref(t.base, m.subject).preds["version"]   # a value's version is a pred  ADAPTED: m's subject
        t.add("rel/pipe", "pair", f"{v}+{mv}")
    assert L.at()["rel/pipe", "pair"] == "0.2.3+1.0.0"

    # the worked example (SVP447 Values): a game, its video, its cut
    with L.transaction(by="human:dan") as t:
        t.add("game/G2", "home", "G4")       # ADAPTED: game/G2, G1 is above
        t.add("game/G2", "away", "G5")
    raw = Video(read_mp4("G2.mp4"))
    raw.preds.update(game="G2", camera="wide")
    with L.transaction(by="human:dan") as t:
        t.add_value(raw, provenance="import:alg2")
    cut = L.at().eval("l2kinds.cut", game="G2", version="1.5.3")
    with L.transaction(by="human:dan") as t:
        t.add("game/G2", "db/alias", cut.subject)
        t["game/G2", "court"] = "C2"         # literal: the game's own row beside its alias (A34)
    rev = L.at()
    assert rev.load("game/G2").subject == cut.subject   # the current cut, alias resolved
    assert rev["game/G2"]["court"] == "C2"               # rev["game/G2"] is the literal record
    c = Ref(rev, "game/G2")
    assert repr(c) == "game/G2"              # repr: game/G1 (A25)
    assert isinstance(c.preds["video"], Ref)  # a Ref, unloaded (Q35)
    assert c.preds["video"].load().frames == raw.frames   # the video: the one explicit act


def test_all_block(L):
    """§ Rev `all`."""
    with L.transaction(by="setup") as t:
        t.add("model/shot", "version", "1.0.0")
    v = Video(b"w")
    with L.transaction(by="setup") as t:
        t.add_value(v, alias="model/shot")
    rev = L.at()
    assert ("code/testrepo", "version", "0.2.2") in rev.all()   # list of rows: (subject, predicate, object)
    assert rev.all("code/testrepo") == [("version", "0.2.2"), ("commit", "abc1234")]
    assert rev.all("db/pred/version") == [("db/cardinality", "one"), ("db/doc", "what bump moves")]
    assert rev.all("model/shot", "db/value") == []    # ADAPTED: model/shot is an alias; the value row is
    assert isinstance(rev.all(v.subject, "db/value")[0], Ref)   #   on its subject: [Ref(...)], unloaded
    assert rev.all("db/pred/game", "db/index", "true") == [Rev(L, 1)]   # [Rev]
    assert rev.all(since=L.at(1))            # rows asserted in (1, id]: the delta
    assert rev["code/testrepo"] == {"version": "0.2.2", "commit": "abc1234"}   # the record


def test_add_value_block(L):
    """§ Transaction `add_value`: Dan cuts game G1 by hand. ADAPTED: `Cut` is ``l2kinds.Cut`` (module level,
    so `load` can import it; it also declares `team`), `Video` ``l2kinds.Video``."""
    raw0 = Video(read_mp4("G1.mp4"))
    raw0.preds.update(game="G1")
    with L.transaction(by="setup") as t:
        t.add_value(raw0)

    rev = L.at()
    raw: Video = rev.value(kind=Video, game="G1")  # loaded
    v = Cut(cut_by_hand(raw))                     # an ordinary object
    v.preds.update(game="G1", version="1.5.4",    # a dict until sealed;
                   video=raw)                     #   a typed pred (Q35)

    with L.transaction(by="human:dan") as t:
        subj: str = t.add_value(v, deps=[raw],
                                alias="game/G1",  # seal, then re-point
                                provenance="human:dan")
        t.add(subj, "note", "cut by hand")        # any further row
    assert (v.sealed, v.subject) == (True, subj)
    with pytest.raises(TypeError):
        v.preds["game"] = "G2"            # TypeError: read-only once sealed
    assert isinstance(v.preds["video"], Ref)      # a Ref now, as loaded (A36)
    rh = f"ref:l2kinds.Video:{raw.hash}"
    assert v.trace == {rh: rh, "code/testrepo": "0.2.2+abc1234", "uv.lock": "sha256:lock-1",
                       "platform": "test-platform"}
    r = L.at()
    assert r[subj, "db/kind"] == "l2kinds.Cut" and r[subj, "db/provenance"] == "human:dan"
    assert r[subj, "db/preds"] == ["game", "version", "video", "team"]
    assert r[subj, "note"] == "cut by hand" and r["game/G1", "db/alias"] == subj

    rev2 = L.at()
    again: Cut = rev2.load("game/G1")             # Ref resolves it
    assert again.same_as(v) and again.matches(rev2)   # True, moved?
    assert isinstance(again.preds["video"], Ref)  # a Ref, unloaded
    assert rev2.value(kind=Cut, game="G1", version="1.5.4").subject == subj   # by its preds
    assert repr(Ref(rev2, subj)) == "game/G1"     # repr: game/G1, shortest alias
    assert Ref(rev2, subj).aliases == ["game/G1"]  # ["game/G1"] (A25)


def test_putting_an_artifact_in_block(L):
    """§ Putting an artifact in: the two doors."""
    with L.transaction(by="setup") as t:          # ADAPTED: the game's rows the cut reads
        t["game/G1"] = {"home": "G4", "away": "G5"}
    raw = Video(read_mp4("G1.mp4"))
    raw.preds.update(game="G1", camera="wide")
    with L.transaction(by="human:dan") as t:
        t.add_value(raw, provenance="import:alg2")
    rows = {r.predicate for r in L.at().rows(since=L.at(L.at().id - 1)) if r.subject == raw.subject}
    assert {"db/value", "db/kind", "db/provenance", "db/preds", "game", "camera"} <= rows
    assert any(p.startswith("db/trace/") for p in rows)
    cut = L.at().eval("l2kinds.cut", game="G1", version="1.5.3")
    with L.transaction(by="human:dan") as t:   # seal-then-repoint
        t.add("game/G1", "db/alias", cut.subject)   # the current cut
    r = L.at()
    assert r[cut.subject, "db/fn"] == "l2kinds.cut"
    assert r[cut.subject, "db/keys"] == {"game": "G1", "version": "1.5.3"}


def test_new_pred_later_block(L):
    """§ Putting an artifact in: a new pred later, against a wrong pred. ADAPTED: the page redeclares
    `Cut` with `gameset`; here a module-level-equivalent subclass is declared and its dotted name used."""
    raw = Video(b"v")
    raw.preds.update(game="G1")
    hand = Cut(b"clip")
    with L.transaction(by="t") as t:
        t.add_value(raw)
    hand.preds.update(game="G2", version="1.5.4", video=raw)    # wrong game
    with L.transaction(by="t") as t:
        t.add_value(hand, alias="game/G1")
    rev = L.at()

    with L.transaction(by="human:dan") as t:        # allowed: gameset
        for r in rev.refs(kind=Cut):                #   is not in their
            t.add(r.subject, "gameset", "normie")   #   db/preds, so it is annotation

    c = rev.load("game/G1")              # the hand cut, sealed with game "G2": wrong
    with pytest.raises(Exists):
        with L.transaction(by="human:dan") as t:
            t.add(c.subject, "game", "G1")   # Exists at commit: game frozen

    fixed = Cut(c.clip)                  # same bytes, corrected preds
    video = c.preds["video"]             # a Ref (Q35): allowed as is
    fixed.preds.update(game="G1", version="1.5.4", video=video)
    with L.transaction(by="human:dan") as t:
        t.add_value(fixed, deps=[video], alias="game/G1")
    now = L.at()
    assert fixed.subject != c.subject and Ref(now, "game/G1").subject == fixed.subject
    assert [r.subject for r in now.refs(kind=Cut, game="G2")] == [c.subject]   # still found by game="G2"
