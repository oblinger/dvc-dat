"""Deep scan round 4 leans (SVP 1467 Q10, Q11; auto-resolved (A)): the inline-YAML marker is `yaml` alone
on the first line; a bare folder on sys.path does not block a mount of its name."""
import sys

import pytest

from dvc_dat import Namespace
from dvc_dat.do import _parse_yaml_prefix


def test_only_a_first_line_of_yaml_alone_is_inline_yaml():
    assert _parse_yaml_prefix("yaml\na: 1\n") == {"a": 1}
    assert _parse_yaml_prefix("  YAML  \nb: [1, 2]\n") == {"b": [1, 2]}
    for text in ("yaml", "yaml-based pipeline", "YAML: 1", "yamlish\na: 1"):
        assert _parse_yaml_prefix(text) == text


def test_a_bare_folder_on_sys_path_does_not_block_a_mount(tmp_path, monkeypatch):
    (tmp_path / "scratch_r4q11").mkdir()
    monkeypatch.syspath_prepend(str(tmp_path))
    ns = Namespace()
    ns.mount(at="scratch_r4q11", value={"a": 1})
    assert ns.load("scratch_r4q11.a") == 1
    with pytest.raises(ValueError, match="importable"):
        ns.mount(at="json", value={"a": 1})                 # real code still refused
    assert "scratch_r4q11" not in sys.modules
