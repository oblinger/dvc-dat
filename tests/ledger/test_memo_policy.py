"""SVP 1474 (Q1 D): record the full platform at write, judge it by the ledger's memo policy at lookup.

Every memo entry stores the platform record where its function ran (``platform/record``); a lookup
hits when ``policy(stored) == policy(current)``, the policy named by the ``(db, db/memo-policy)``
triple; ``deterministic=True`` adds card and driver; an entry lacking a field the policy reads misses.
"""

import json
import sys

import pytest

from dvc_dat.ledger import LedgerError, register_policy
from dvc_dat.ledger import fn as fn_module
from dvc_dat.ledger.env import Env, discover, parse_smi, platform_record, platform_tag
from dvc_dat.ledger.policy import POLICIES, memo_index
from ledger_kinds import CALLS, Video

TAG = "linux-x86_64-py3.11"
H100 = {"os": "linux", "machine": "x86_64", "python": "3.11.9", "cpu": "AMD EPYC 9654",
        "card": "NVIDIA H100 80GB HBM3", "driver": "550.54.15", "cuda": "12.4", "torch": "2.5.1"}
PRO6000 = dict(H100, card="NVIDIA RTX PRO 6000 Blackwell", driver="575.51.03", cuda="12.8")
CPU = dict(H100, card=None, driver=None, cuda=None, torch=None)


@pytest.fixture
def world(coded, envbox):
    L = coded
    with L.transaction(by="t", lock=10) as t:
        t.add("db/pred/video", "db/type", "ledger_kinds.Video")
        t["game/G1"] = {"home": "G4", "away": "G5"}
    v = Video(b"G1 frames")
    v.preds.update(game="G1")
    with L.transaction(by="t") as t:
        v.seal(t, name="video/G1")
    CALLS.clear()
    on(envbox, H100)
    return L


def on(envbox, record, **kw):
    envbox.set(platform=TAG, record=dict(record, **kw))


def cut(L, **kw):
    return L.at().run("ledger_kinds.cut", game="G1", **kw)


def policy(L, name):
    with L.transaction(by="t") as t:
        t.add("db", "db/memo-policy", name)


def test_the_default_policy_is_todays_tag_byte_for_byte():
    assert POLICIES["platform"](platform_record()) == platform_tag()
    rec = discover().platform_record()
    assert POLICIES["platform"](rec) == platform_tag() == rec["platform"]
    assert rec["os"] == sys.platform and rec["python"].startswith(f"{sys.version_info[0]}.{sys.version_info[1]}.")
    assert {"cpu", "card", "driver", "cuda", "torch"} <= set(rec)
    assert POLICIES["platform"](Env({}, TAG, record=H100).platform_record()) == TAG


def test_a_new_ledger_names_its_policy(world):
    assert world.at()["db", "db/memo-policy"] == "platform"


def test_an_entry_records_the_full_record_and_the_short_item(world):
    a = cut(world)
    assert a.dependencies["platform"] == TAG
    assert json.loads(a.dependencies["platform/record"]) == dict(H100, platform=TAG)


def test_the_default_policy_hits_across_cards(world, envbox):
    a = cut(world)
    on(envbox, PRO6000)
    assert cut(world).subject == a.subject and CALLS["cut"] == 1


def test_a_card_policy_misses_across_cards_and_hits_on_the_same_card(world, envbox):
    policy(world, "card")
    a = cut(world)
    on(envbox, PRO6000)
    b = cut(world)
    assert b.subject != a.subject and CALLS["cut"] == 2
    on(envbox, H100)
    assert cut(world).subject == a.subject and CALLS["cut"] == 2


def test_changing_the_policy_triple_rejudges_old_entries(world, envbox):
    a = cut(world)                                  # under the default
    on(envbox, PRO6000)
    assert cut(world, seal="get").subject == a.subject
    policy(world, "card")
    assert cut(world, seal="get") is None           # the same entry, judged by the new policy
    on(envbox, H100)
    assert cut(world, seal="get").subject == a.subject
    policy(world, "platform")
    on(envbox, PRO6000)
    assert cut(world, seal="get").subject == a.subject


def test_deterministic_adds_card_and_driver(world, envbox):
    a = cut(world)
    on(envbox, PRO6000)
    assert cut(world, seal="get").subject == a.subject
    assert cut(world, seal="get", deterministic=True) is None
    on(envbox, H100, driver="560.35.03")            # same card, another driver
    assert cut(world, seal="get", deterministic=True) is None
    on(envbox, H100, cuda="12.6", torch="2.6.0")    # card and driver agree; the rest is the policy's
    assert cut(world, seal="get", deterministic=True).subject == a.subject
    assert world.at().ns.load("ledger_kinds.cut")(game="G1", seal="get", deterministic=True).subject == a.subject


def test_an_old_short_record_entry_never_false_hits(world, envbox, monkeypatch):
    monkeypatch.setattr(fn_module, "platform_items", lambda env: {"platform": env.platform})
    a = cut(world)                                  # as written before 1474: the short item alone
    monkeypatch.undo()
    assert "platform/record" not in a.dependencies
    assert cut(world, seal="get").subject == a.subject      # the default still hits it
    assert cut(world, seal="get", deterministic=True) is None
    policy(world, "card")
    for rec in (H100, CPU):
        on(envbox, rec)
        assert cut(world, seal="get") is None


def test_a_cpu_entry_hits_a_cpu_host_under_the_card_policy(world, envbox):
    policy(world, "card")
    on(envbox, CPU)
    a = cut(world)
    on(envbox, CPU, cpu="Intel Xeon")               # the card policy reads platform, card and driver only
    assert cut(world, seal="get").subject == a.subject
    on(envbox, H100)
    assert cut(world, seal="get") is None


def test_a_draft_keeps_the_record_where_it_ran(world, envbox):
    d = cut(world, seal=False)
    on(envbox, PRO6000)
    d.seal(world)
    assert json.loads(world.at()[d.subject, "db/deps/platform/record"])["card"] == H100["card"]


def test_the_index_is_built_once_then_reused(world, envbox):
    a = cut(world)
    idx = memo_index(world)
    built = idx.builds
    for _ in range(3):
        assert cut(world, seal="get").subject == a.subject
    assert idx.builds == built == 1
    on(envbox, PRO6000)
    b = cut(world, seal=world, deterministic=True)  # a new entry: the next lookup adds it, no rebuild
    assert cut(world, seal="get").subject == b.subject
    assert b.subject != a.subject and idx.builds == 1 and idx.keys[b.subject] == idx.keys[a.subject] == TAG
    policy(world, "card")
    assert cut(world, seal="get").subject == b.subject and idx.builds == 2
    assert idx.stamp[0] == "card" and idx.keys[a.subject] != idx.keys[b.subject]
    on(envbox, H100)
    assert cut(world, seal="get").subject == a.subject and idx.builds == 2


def test_an_unknown_policy_is_refused_by_name(world):
    policy(world, "nope")
    with pytest.raises(LedgerError, match="nope"):
        cut(world, seal="get")


def test_a_registered_policy_is_named_by_the_triple(world, envbox):
    register_policy("test-cuda", lambda r: f"{r['platform']}|cuda={r['cuda']}")
    try:
        policy(world, "test-cuda")
        a = cut(world)
        on(envbox, H100, card="other card")
        assert cut(world, seal="get").subject == a.subject
        on(envbox, H100, cuda="12.8")
        assert cut(world, seal="get") is None
    finally:
        POLICIES.pop("test-cuda")
    with pytest.raises(ValueError, match="built-in"):
        register_policy("platform", lambda r: "x")


def test_nvidia_smi_output_parses_to_card_and_driver():
    text = "0, NVIDIA H100 80GB HBM3, 550.54.15\n1, NVIDIA RTX PRO 6000 Blackwell, 550.54.15\n"
    assert parse_smi(text, None) == ("NVIDIA H100 80GB HBM3 + NVIDIA RTX PRO 6000 Blackwell", "550.54.15")
    assert parse_smi(text, "1") == ("NVIDIA RTX PRO 6000 Blackwell", "550.54.15")
    assert parse_smi("", None) == (None, None)
