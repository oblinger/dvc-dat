"""The documentation site (246): the `dat-vault` plugin's rewrites, and, after a build, the site's shape.

The plugin needs mkdocs (`uv sync --group docs`), so these skip under the plain dev group. The checks on
`site/` skip until `mkdocs build` has run; `.github/workflows/docs.yml` runs them after its build.
"""
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

pytest.importorskip("mkdocs")
griffe = pytest.importorskip("griffe")

from mkdocs.exceptions import PluginError  # noqa: E402
from mkdocs.structure.files import File, Files  # noqa: E402

from dvc_dat.docs.vault import VaultPlugin, _first_line, public_members  # noqa: E402

REPO = Path(__file__).parent.parent
SITE = REPO / "site"
MODULE_PAGES = ["DAT Modules/DAT Dat", "DAT Modules/ledger/DAT Ledger"]
needs_site = pytest.mark.skipif(not SITE.exists(), reason="no site/: run `just docs`")


def plugin_over(tmp_path, pages: dict, **options) -> tuple:
    """A loaded plugin over a docs folder holding `pages` ({path: text}); (plugin, files, config)."""
    docs = tmp_path / "doc"
    for uri, text in pages.items():
        (docs / uri).parent.mkdir(parents=True, exist_ok=True)
        (docs / uri).write_text(text)
    config = {"docs_dir": str(docs), "config_file_path": str(tmp_path / "mkdocs.yml"), "site_dir": "site",
              "use_directory_urls": True}
    files = Files([File(uri, str(docs), "site", True) for uri in pages])
    plugin = VaultPlugin()
    plugin.load_config({"repo_blob": "https://example.com/blob/", **options})
    plugin.on_config(config)
    plugin.on_files(files, config=config)
    return plugin, files, config


def render(tmp_path, text: str, others: dict = {}, uri: str = "a/page.md", **options) -> str:
    plugin, files, config = plugin_over(tmp_path, {uri: text, **others}, **options)
    page = SimpleNamespace(file=files.get_file_from_path(uri))
    return plugin.on_page_markdown(text, page=page, config=config, files=files)


def test_a_wiki_link_finds_the_page_by_basename_and_flattens_when_none(tmp_path):
    out = render(tmp_path, "[[Other]] and [[Other|shown]] and [[Gone]] and [[Gone|named]]",
                 {"b/Other.md": "# Other\n"})
    assert out == "[Other](../b/Other.md) and [shown](../b/Other.md) and Gone and named"


def test_vault_lines_leave_the_site_and_the_grammar_inside_fences_stays(tmp_path):
    out = render(tmp_path, ":>> [x](ha://p/x)\n# T\n| ... |   |\n```\n| ... | [[a]] |\n:>> x\n```\n")
    assert out == "# T\n```\n| ... | [[a]] |\n:>> x\n```\n"


def test_an_identity_row_is_a_bold_title(tmp_path):
    out = render(tmp_path, "| -[[Name]]- | : what it is<br>→ [[Up]] → [Name](ha://p/Name) |\n")
    assert out.startswith("| **Name** | what it is")
    assert "ha://" not in out and "[[" not in out


def test_a_block_id_is_an_anchor(tmp_path):
    assert render(tmp_path, "**at** does a thing. ^at") == '<a id="^at"></a>**at** does a thing.'


def test_a_fragment_written_for_github_or_obsidian_becomes_the_sites_slug(tmp_path):
    text = "## A — B\n[x](#A%20—%20B) [y](other.md#One%20Two) [z](#a--b)"
    out = render(tmp_path, text, {"a/other.md": "## One Two\n"})
    assert "[x](#a-b)" in out and "[y](other.md#one-two)" in out and "[z](#a-b)" in out


def test_a_link_out_of_the_docs_folder_goes_to_the_repo(tmp_path):
    (tmp_path / "root.md").write_text("x")
    out = render(tmp_path, "[r](../../root.md#h)")
    assert out == "[r](https://example.com/blob/root.md#h)"


def test_code_spans_link_only_for_the_named_packages(tmp_path):
    pkg = tmp_path / "vaultpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("class Thing:\n    '''One.\n\n    Two.'''\n\ndef helper():\n    '''H.'''\n")
    api = {"api/p.md": "# P\n\n::: vaultpkg\n"}
    text = "`Thing` and **helper** and `nothing` and [`Thing`](x.md)\n# `Thing`"
    assert render(tmp_path, text, api) == text
    out = render(tmp_path, text, api, packages=["vaultpkg"])
    assert out.startswith("[`Thing`](../api/p.md#vaultpkg.Thing) and [**helper**](../api/p.md#vaultpkg.helper)")
    assert out.endswith("`nothing` and [`Thing`](x.md)\n# `Thing`")


def test_a_methods_directive_lists_each_public_member_with_its_first_line(tmp_path):
    pkg = tmp_path / "vaultpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "class Thing:\n"
        "    def run(self):\n        '''Run | it.\n\n        Second paragraph.'''\n"
        "    def bare(self):\n        pass\n"
        "    def _hidden(self):\n        '''Private.'''\n")
    api = {"api/p.md": "::: vaultpkg\n\n::: vaultpkg.Thing\n"}
    out = render(tmp_path, "<!-- methods: vaultpkg.Thing -->", api).split("\n")
    assert out == ["| Thing | |", "| --- | --- |",
                   "| [run](../api/p.md#vaultpkg.Thing.run) | Run \\| it. |",
                   "| [bare](../api/p.md#vaultpkg.Thing.bare) |  |"]


def test_a_methods_directive_refuses_a_name_the_code_lacks_or_no_api_page_documents(tmp_path):
    pkg = tmp_path / "vaultpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("class Thing: pass\n")
    with pytest.raises(PluginError, match="names nothing"):
        render(tmp_path, "<!-- methods: vaultpkg.Gone -->", {"api/p.md": "::: vaultpkg\n"})
    with pytest.raises(PluginError, match="no ':::' directive"):
        render(tmp_path, "<!-- methods: vaultpkg.Thing -->", {"api/p.md": "# empty\n"})


def directives(page: str) -> list:
    return re.findall(r"^<!-- methods: ([\w.]+) -->$", (REPO / "doc" / f"{page}.md").read_text(), re.MULTILINE)


@pytest.mark.parametrize("page", MODULE_PAGES)
def test_every_member_in_a_module_pages_table_has_a_first_line(page):
    root = griffe.load("dvc_dat", search_paths=[str(REPO)], resolve_aliases=True)
    names = directives(page)
    assert names
    for dotted in names:
        obj = root[dotted.removeprefix("dvc_dat.")]
        obj = obj.final_target if obj.is_alias else obj
        empty = [name for name, member in public_members(obj) if not _first_line(member)]
        assert not empty, f"{dotted}: no docstring on {empty}"


@pytest.mark.parametrize("page", sorted((REPO / "doc" / "api").glob("*.md")), ids=lambda p: p.stem)
def test_every_api_page_opens_with_its_modules_figure_and_a_link_back(page):
    head = page.read_text().split("\n")[:7]
    figure = next((line for line in head if line.startswith("![")), None)
    back = next((line for line in head if line.startswith("Module page: [")), None)
    assert figure and back, f"{page.name}: no figure and link back in its first lines"
    for target in (re.search(r"\]\(([^)#]+)", line).group(1) for line in (figure, back)):
        assert (page.parent / unquote(target)).exists(), target


@needs_site
@pytest.mark.parametrize("folder", ["tutorials", "how-to", "DAT Architecture", "api"])
def test_the_four_lenses_are_built(folder):
    assert (SITE / folder / "index.html").exists()


@needs_site
def test_every_notebook_is_a_page():
    stems = [p.stem for p in (REPO / "doc" / "DAT Demos").glob("*.ipynb")]
    assert stems
    for stem in stems:
        assert (SITE / "DAT Demos" / stem / "index.html").exists()


@needs_site
@pytest.mark.parametrize("page", MODULE_PAGES)
def test_every_method_row_resolves_to_an_id_in_the_api_reference(page):
    html = (SITE / page / "index.html").read_text()
    ids = {i for p in (SITE / "api").glob("*/index.html") for i in re.findall(r'id="([^"]+)"', p.read_text())}
    hrefs = {unquote(h) for h in re.findall(r'href="[^"#]*api/[^"#]*#(dvc_dat\.[^"]+)"', html)}
    assert len(hrefs) > 20
    missing = sorted(hrefs - ids)
    assert not missing, f"{page}: method rows with no API anchor: {missing}"


@needs_site
def test_only_the_published_paths_are_on_the_site():
    names = {p.relative_to(SITE).as_posix() for p in SITE.rglob("*")}
    for excluded in ("DAT Track", "DAT Design", "DAT Hooks", "Docs", "DAT User Docs", "overview",
                     "DAT Modules/dat", "DAT Demos/demo_game", "DAT Demos/demo_kinds", "DAT Demos/comfort-repo"):
        assert excluded not in names, excluded
    assert not [n for n in names if n.endswith(".py")]
