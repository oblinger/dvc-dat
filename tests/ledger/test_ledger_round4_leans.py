"""Deep scan round 4 leans on the ledger (SVP 1467 Q9, Q12): a row read whose subject looks like another
dependency item is checked as a row read; a memo key JSON would collapse into another call's is refused."""

import pytest

import round4_kinds as K


def write(L, *triples):
    with L.transaction(by="t") as t:
        for s, p, o in triples:
            t.add(s, p, o)


@pytest.mark.parametrize("s", ["ref:thing", "code/review", "q:stuff", 'q:{"x": 1}', "eval:x"])
def test_a_row_read_whose_subject_looks_like_an_item_is_a_row_read(coded, s):
    write(coded, (s, "p", "a"))
    K.CALLS.clear()
    run = lambda: coded.at().run("round4_kinds.reads", s=s, p="p").obj     # noqa: E731
    assert run() == {"o": "a"} and run() == {"o": "a"} and K.CALLS[s] == 1      # a hit while it holds
    write(coded, (s, "p", "b"))
    assert run() == {"o": "b"} and K.CALLS[s] == 2                              # a miss once it changed


def test_a_read_of_a_db_alias_row_is_a_row_read(coded):
    from ledger_kinds import Plain

    with coded.transaction(by="t") as t:
        Plain(b"v").seal(t, name="first")
    write(coded, ("nm", "db/alias", "first"))
    K.CALLS.clear()
    run = lambda: coded.at().run("round4_kinds.reads", s="nm", p="db/alias").obj   # noqa: E731
    assert run() == {"o": "first"} and run() == {"o": "first"} and K.CALLS["nm"] == 1


@pytest.mark.parametrize("bad", [{1: "a"}, float("nan"), [float("inf")], {"k": {2.5: 1}}])
def test_a_memo_key_json_would_collapse_is_refused(coded, bad):
    with pytest.raises(TypeError):
        coded.at().run("round4_kinds.echo", x=bad)
    assert coded.at().run("round4_kinds.echo", x={"1": "a"}).obj == {"x": {"1": "a"}}
