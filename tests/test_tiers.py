"""The install tiers of the expander (1519 R3): base expands `${unique:}` alone and refuses any other `${`; with
omegaconf (`dvc-dat[expand]`) the whole grammar, giving the same strings for a unique-only template.

The base tier is simulated in a fresh interpreter with `omegaconf` blocked (`sys.modules["omegaconf"] = None`), so
these run under every install.
"""
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dvc_dat.expand import EXPAND, PLAIN, UNIQUE, quote_spec, resolve_spec, scan, scan_text, unique_text

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ["events/${unique:}", "baseline${unique:}", "runs/G1/${unique:}/x", "a${unique:}/b/${unique:}",
             "${unique:}", "x/${unique:}y"]


def _base(code: str, cwd: Path = ROOT) -> str:
    """`code` run with omegaconf unimportable, as on the base install; its stdout."""
    prelude = "import sys\nsys.modules['omegaconf'] = None\n"
    out = subprocess.run([sys.executable, "-c", prelude + textwrap.dedent(code)], cwd=cwd, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_the_scan_sorts_each_string_into_one_of_three():
    assert scan_text("plain {asset.pose} $HOME") == PLAIN
    assert scan_text("events/${unique:}") == UNIQUE
    assert scan_text("a${unique:}b${unique:}") == UNIQUE
    for text in ("${now:%Y}", "${unique:%Y}", "${ns:x} ${unique:}", "\\${unique:}", "\\${HOME}", "${batch}"):
        assert scan_text(text) == EXPAND, text
    assert scan({"a": ["x", {"b": "${unique:}"}], "k": 1}) == UNIQUE
    assert scan({"a": "x", "b": ["${now:}"]}) == EXPAND
    assert scan({"${not_read}": "keys are never read"}) == PLAIN


def test_unique_text_counts_as_a_segment_or_a_suffix():
    assert [unique_text("events/${unique:}", n) for n in (1, 2, 3)] == ["events/1", "events/2", "events/3"]
    assert [unique_text("baseline${unique:}", n) for n in (1, 2, 3)] == ["baseline", "baseline_2", "baseline_3"]
    assert unique_text("runs/G1/${unique:}/x", 2) == "runs/G1/2/x"
    assert unique_text("a${unique:}/b/${unique:}", 3) == "a_3/b/3"


def test_a_plain_spec_and_a_unique_only_spec_import_no_omegaconf(tmp_path):
    out = _base(f"""
        from dvc_dat import DatManager
        m = DatManager(dat_folders=[{str(tmp_path)!r}])
        plain = {{"dat": {{"name": "runs/G1-smoke", "target_exists": "increment",
                           "kwargs": {{"game": "G1", "model": "models/detector/v3"}}}}}}
        names = [m.create(plain).get_path_name() for _ in range(3)]
        names += [m.create({{"dat": {{"name": "tables/table12${{unique:}}"}}}}).get_path_name() for _ in range(2)]
        names += [m.create({{"dat": {{"name": "events/${{unique:}}"}}}}).get_path_name() for _ in range(2)]
        print("names:", names)
        print("expand:", m.ns.expand("annset/G1/${{unique:}}"))
        print("omegaconf:", sys.modules.get("omegaconf"))
    """)
    assert ("names: ['runs/G1-smoke', 'runs/G1-smoke_2', 'runs/G1-smoke_3', 'tables/table12', 'tables/table12_2', "
            "'events/1', 'events/2']") in out
    assert "expand: annset/G1/1" in out
    assert "omegaconf: None" in out


def test_any_other_reference_on_base_is_an_import_error_naming_the_extra(tmp_path):
    out = _base(f"""
        from dvc_dat import DatManager
        m = DatManager(dat_folders=[{str(tmp_path)!r}])
        for spec in ({{"dat": {{"name": "y/${{now:%Y}}"}}}}, {{"dat": {{}}, "cmd": "echo \\\\${{HOME}}"}},
                     {{"dat": {{}}, "m": "${{ns:asset.detector}}"}}):
            try:
                m.create(spec)
            except ImportError as e:
                print("refused:", e)
        import os
        print("folders:", os.listdir({str(tmp_path)!r}))
        try:
            m.create({{"dat": {{}}}}, model="${{ns:asset.x}}")
        except ValueError as e:
            print("keyword:", e)
    """)
    assert out.count("refused: expand_spec: the spec holds a `${...}` reference other than ${unique:} and omegaconf "
                     "is not installed; install dvc-dat[expand]") == 3
    assert "folders: []" in out
    assert "keyword:" in out and "dvc-dat[expand]" in out


def test_both_tiers_give_the_same_strings():
    pytest.importorskip("omegaconf")
    base = _base(f"""
        from dvc_dat.expand import unique_text
        for t in {TEMPLATES!r}:
            print([unique_text(t, n) for n in (1, 2, 3)])
    """)
    expand = "".join(f"{[resolve_spec({'v': t, 'x': '${now:%Y}'}, load=None, count=n)['v'] for n in (1, 2, 3)]}\n"
                     for t in TEMPLATES)
    assert base == expand


def test_the_expand_tier_resolves_the_grammar(tmp_path):
    pytest.importorskip("omegaconf")
    from dvc_dat import DatManager

    m = DatManager(dat_folders=[str(tmp_path)])
    m.ns.mount(value={"detector_b8": "models/det/b8", "lr": 0.1}, at="asset")
    spec = {"batch": 8, "dat": {"name": "runs/${dat.kwargs.game}${unique:}",
                                "kwargs": {"game": "G1", "detector_model": "${ns:asset.detector_b${batch}}",
                                           "batch_size": "${batch}", "cmd": "echo \\${HOME}",
                                           "note": "{literal} stays"}}}
    a, b = m.create(spec), m.create(spec)
    assert (a.get_path_name(), b.get_path_name()) == ("runs/G1", "runs/G1_2")
    kw = b.get_spec()["dat"]["kwargs"]
    assert kw == {"game": "G1", "detector_model": "models/det/b8", "batch_size": 8, "cmd": "echo ${HOME}",
                  "note": "{literal} stays"}
    assert b.get_spec()["dat"]["name"] == "runs/${dat.kwargs.game}${unique:}"       # the template is stored


def test_a_call_site_value_is_data_on_the_expand_tier(tmp_path):
    pytest.importorskip("omegaconf")
    from dvc_dat import DatManager

    m = DatManager(dat_folders=[str(tmp_path)])
    given = {"a": "echo ${HOME}", "b": "${ns:asset.pose}", "c": "{asset.pose}", "d": "\\${x}"}
    dat = m.create({"dat": {}}, **given)
    assert {k: dat.get_spec()["dat"]["kwargs"][k] for k in given} == given
    assert resolve_spec(quote_spec(given), load=None) == given


def test_an_old_reference_in_a_dat_name_names_its_new_spelling(tmp_path):
    from dvc_dat import DatManager

    m = DatManager(dat_folders=[str(tmp_path)])
    for old, new in (("runs/{YYYY}/x", "${now:%Y}"), ("t{unique}", "${unique:}"), ("{asset.x}/y", "${ns:asset.x}"),
                     ("{game}", "${dat.kwargs.game}")):
        with pytest.raises(ValueError, match=r"retired in dvc-dat 3\.0; write " + re.escape(new)):
            m.create({"dat": {"name": old}})
