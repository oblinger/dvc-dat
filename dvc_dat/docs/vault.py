"""The MkDocs plugin `dat-vault`: a site built over an Obsidian anchor vault, and its method tables.

A repo's `doc/` is both the MkDocs source and an Obsidian vault: its pages carry grammar only Obsidian and
HookAnchor read. The files keep all of it; this plugin rewrites the page MkDocs renders, and nothing on disk.

- `[[X]]`, `[[X|Label]]`, `[[X#Heading]]`: a link to the site page whose basename is X, plain text when none.
- The `:>>` breadcrumb is dropped; `-[[X]]-` becomes a bold title; a dispatch table's separator rows
  (`...`, `ooo`, `---`, `+++`, `^^^`, `!!!`, `.`) are dropped; `ha://` and `hook://` links keep their text.
- A trailing ` ^id` block id becomes an anchor, so `[at](#^at)` works on the site as in Obsidian.
- A `#Heading` fragment, GitHub-style or Obsidian-style (`#Ledger%20Interface`), becomes the site's slug.
- A relative link leaving `docs_dir` points at the file under `repo_blob`, since the site cannot serve it.
- `<!-- methods: pkg.Class -->` expands to a table: one row per public member, its name linked to that
  member's anchor in the API reference, its cell the first line of its docstring. Read with griffe, as
  mkdocstrings reads, so nothing is imported and the table cannot name a member the code lacks.
- With `packages`, a `` `Symbol` `` code span or `**Symbol**` naming one of their classes or functions, or
  a `pkg/module.py` path, links to the API reference; a name defined twice is left alone.

Options: `packages` (default none), `api_dir` (default `api`), the folder under `docs_dir` holding the
`::: dotted.name` pages; `repo_blob`, the URL prefix of a repo file. Which page documents a name is read from
those `:::` directives, so there is no second list of them.
"""
import os
import posixpath
import re
import unicodedata
from urllib.parse import quote, unquote

from mkdocs.config import base
from mkdocs.config import config_options as c
from mkdocs.exceptions import PluginError
from mkdocs.plugins import BasePlugin

WIKI = re.compile(r"\[\[([^\[\]]+?)\]\]")
HOOK_LINK = re.compile(r"\[([^\]]+)\]\((?:hook|ha)://[^)]+\)")
BREADCRUMB_TAIL = re.compile(r"<br>\s*→ .*?(?=\|[^|]*$|\|\s*$)")
LEADING_ARROW_RUN = re.compile(r"(?:→\s*\[\[[^\]]+\]\]\s*)+→?\s*")
SEPARATOR_ROW = re.compile(r"^\s*\|\s*(\.\.\.|ooo|---|\+\+\+|\^\^\^|!!!|\.)\s*\|[\s|]*$")
IDENTITY = re.compile(r"-\[\[([^\]|]+)\]\]-")
BLOCK_ID = re.compile(r"\s\^([\w-]+)\s*$")
MD_TARGET = re.compile(r"\]\(([^)\s#:]+)((?:#[^)\s]*)?)\)")
FRAGMENT = re.compile(r"\]\(([^)#\s]*)#([^)\s^]+)\)")
DIRECTIVE = re.compile(r"^:::\s+([\w.]+)\s*$", re.MULTILINE)
METHODS = re.compile(r"^\s*<!--\s*methods:\s*([\w.]+)\s*-->\s*$")
LINK_OR_SPAN = re.compile(r"(\[[^\]]*\]\([^)]*\)|`[^`]+`)")


def _slug(heading: str) -> str:
    """GitHub's slug, the form a fragment is written in."""
    s = unicodedata.normalize("NFKD", heading).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def _toc_slug(heading: str) -> str:
    """Python-Markdown's slug, the id the built page has: a run of punctuation is one hyphen."""
    s = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-\s]+", "-", s)


def _clean_heading(text: str) -> str:
    """Heading text as the slugifiers see it, inline markup stripped."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*+([^*]*)\*+", r"\1", text)
    return re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", lambda m: m.group(2) or m.group(1), text)


def _href(uri: str, here: str) -> str:
    """The relative link from a page in folder `here` to the page `uri`."""
    return quote(posixpath.relpath(uri, here or "."), safe="/-._~()")


def _first_line(obj) -> str:
    """The first line of a griffe object's docstring, safe in a table cell."""
    if obj.docstring is None:
        return ""
    lines = obj.docstring.value.strip().splitlines()
    return lines[0].strip().replace("|", "\\|") if lines else ""


def public_members(obj) -> list:
    """A griffe class or module's (name, member) pairs a reader sees: no `_` prefix, or a documented dunder."""
    picked = []
    for name, member in obj.members.items():
        target = member.final_target if member.is_alias else member
        documented_dunder = name.startswith("__") and name != "__init__" and target.docstring is not None
        if not name.startswith("_") or documented_dunder:
            picked.append((name, target))
    return picked


class VaultConfig(base.Config):
    packages = c.ListOfItems(c.Type(str), default=[])
    api_dir = c.Type(str, default="api")
    repo_blob = c.Optional(c.Type(str))


class VaultPlugin(BasePlugin[VaultConfig]):
    """Render a vault's pages for the site; see the module docstring."""

    def on_config(self, config):
        self._loaded = {}       # package -> griffe module
        self._headings = {}     # src_uri -> {GitHub slug: site slug}
        self._directives = []   # (dotted name, API page src_uri), in page order
        self._symbols = None    # identifier or path -> (API page src_uri, anchor id)
        return config

    def on_files(self, files, *, config):
        """Read the API pages' `:::` directives: which page documents which name."""
        prefix = self.config.api_dir.rstrip("/") + "/"
        self._directives = [
            (name, f.src_uri)
            for f in files.documentation_pages()
            if f.src_uri.startswith(prefix) and f.src_uri.endswith(".md")
            for name in DIRECTIVE.findall(f.content_string)
        ]
        self._wiki = {}
        for f in files.documentation_pages():
            stem = posixpath.basename(f.src_uri)
            if stem.endswith(".md"):
                self._wiki.setdefault(stem[:-3], f.src_uri)
        self._repo = os.path.dirname(os.path.realpath(config["config_file_path"]))
        self._docs = os.path.realpath(config["docs_dir"])
        return files

    def _griffe(self, dotted: str):
        """The griffe object at a dotted name, aliases followed; loads its package once."""
        import griffe

        package, _, rest = dotted.partition(".")
        if package not in self._loaded:
            self._loaded[package] = griffe.load(package, search_paths=[self._repo], resolve_aliases=True)
        obj = self._loaded[package][rest] if rest else self._loaded[package]
        return obj.final_target if obj.is_alias else obj

    def _api_page(self, dotted: str) -> str:
        """The API page documenting a dotted name: the page of the longest directive covering it."""
        covering = [(name, uri) for name, uri in self._directives if dotted == name or dotted.startswith(name + ".")]
        if not covering:
            raise PluginError(f"dat-vault: no ':::' directive under {self.config.api_dir}/ documents {dotted}")
        return max(covering, key=lambda hit: len(hit[0]))[1]

    def _methods_table(self, dotted: str, here: str) -> list:
        """The rows of `<!-- methods: dotted -->`."""
        try:
            obj = self._griffe(dotted)
        except KeyError as e:
            raise PluginError(f"dat-vault: <!-- methods: {dotted} --> names nothing in the source") from e
        href = _href(self._api_page(dotted), here)
        rows = [f"| {dotted.rsplit('.', 1)[-1]} | |", "| --- | --- |"]
        for name, member in public_members(obj):
            rows.append(f"| [{name}]({href}#{dotted}.{name}) | {_first_line(member)} |")
        return rows

    def _symbol_index(self) -> dict:
        """Every class, function and module of `packages` under a directive: its API page and anchor."""
        if self._symbols is not None:
            return self._symbols
        self._symbols = {}
        dupes = set()

        def add(key, uri, anchor):
            if key in dupes:
                return
            if key in self._symbols and self._symbols[key][1] != anchor:
                del self._symbols[key]
                dupes.add(key)
                return
            self._symbols.setdefault(key, (uri, anchor))

        def harvest(module, uri):
            if module.name.startswith("_"):     # a private module has no rendered section
                return
            add(module.path.replace(".", "/") + ".py", uri, module.path)
            for name, member in module.members.items():
                if name.startswith("_") or member.is_alias:
                    continue
                if member.is_class or member.is_function:
                    add(name, uri, member.path)
                elif member.is_module:
                    harvest(member, uri)

        for name, uri in self._directives:
            if name.split(".")[0] in self.config.packages:
                obj = self._griffe(name)
                if obj.is_module:
                    harvest(obj, uri)
                else:
                    add(obj.name, uri, name)
        return self._symbols

    def _autolink(self, line: str, here: str) -> str:
        """Link the code spans and bold names of `packages`; a span already in a link is left alone."""
        index = self._symbol_index()

        def href(name):
            hit = index.get(name)
            return None if hit is None else f"{_href(hit[0], here)}#{hit[1]}"

        def span(part):
            target = href(part[1:-1])
            return f"[{part}]({target})" if target else part

        def bold(m):
            target = href(m.group(1))
            return f"[**{m.group(1)}**]({target})" if target else m.group(0)

        out = []
        for part in LINK_OR_SPAN.split(line):
            if part.startswith("["):
                out.append(part)
            elif part.startswith("`"):
                out.append(span(part))
            else:
                out.append(re.sub(r"\*\*([A-Za-z_]\w*)\*\*", bold, part))
        return "".join(out)

    def _heading_map(self, f) -> dict:
        """A page's headings: {GitHub slug: site slug}."""
        if f.src_uri not in self._headings:
            mapping = {}
            in_fence = False
            for line in f.content_string.splitlines():
                if line.lstrip().startswith(("```", "~~~")):
                    in_fence = not in_fence
                m = None if in_fence else re.match(r"#{1,6}\s+(.*)", line)
                if m:
                    head = _clean_heading(m.group(1).strip())
                    mapping[_slug(head)] = _toc_slug(head)
            self._headings[f.src_uri] = mapping
        return self._headings[f.src_uri]

    def _wiki_link(self, m: re.Match, here: str) -> str:
        """`[[X]]` as a markdown link, or its text when the site has no page X."""
        target, _, label = m.group(1).replace("\\|", "|").partition("|")
        name, _, fragment = target.partition("#")
        name = name.strip()
        if not name:
            head = fragment.lstrip("^")
            return f"[{label or head}](#{_toc_slug(head)})"
        uri = self._wiki.get(name)
        if uri is None:
            return label or name
        href = _href(uri, here)
        if fragment and not fragment.startswith("^"):
            href += f"#{_toc_slug(fragment)}"
        return f"[{label or name}]({href})"

    def _fragment(self, m: re.Match, page, here: str, files) -> str:
        """A link's `#fragment`, written GitHub-style or Obsidian-style, as the target page's id."""
        path, fragment = m.group(1), m.group(2)
        if path == "":
            target = page.file
        elif path.endswith(".md"):
            target = files.get_file_from_path(posixpath.normpath(posixpath.join(here, unquote(path))))
        else:
            target = None
        if target is None:
            return m.group(0)
        new = self._heading_map(target).get(_slug(_clean_heading(unquote(fragment))))
        return f"]({path}#{new})" if new else m.group(0)

    def _out_of_docs(self, line: str, here: str) -> str:
        """A relative link climbing out of `docs_dir`, pointed at the repo file."""
        def repl(m):
            target = os.path.normpath(os.path.join(self._docs, here, unquote(m.group(1))))
            outside = not target.startswith(self._docs + os.sep) and target.startswith(self._repo + os.sep)
            if not outside or not os.path.exists(target):
                return m.group(0)
            rel = os.path.relpath(target, self._repo).replace(os.sep, "/")
            return f"]({self.config.repo_blob}{quote(rel, safe='/-._~()')}{m.group(2)})"

        return MD_TARGET.sub(repl, line)

    def on_page_markdown(self, markdown, *, page, config, files):
        """The page as MkDocs renders it; a page without vault grammar passes through unchanged."""
        if not page.file.src_uri.endswith(".md"):
            return markdown
        here = posixpath.dirname(page.file.src_uri)
        is_api = page.file.src_uri.startswith(self.config.api_dir.rstrip("/") + "/")
        out = []
        in_fence = False
        for line in markdown.split("\n"):
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                out.append(line)
                continue
            if in_fence:
                out.append(line)
                continue
            if SEPARATOR_ROW.match(line) or "file:///" in line or stripped.startswith(":>>"):
                continue
            methods = METHODS.match(line)
            if methods:
                out.extend(self._methods_table(methods.group(1), here))
                continue
            if stripped.startswith("api:: "):
                line = line.replace("api:: ", "**API:** ", 1)
            if "hook://" in line or "ha://" in line:
                line = BREADCRUMB_TAIL.sub("", line)
                line = HOOK_LINK.sub(r"\1", line)
                line = LEADING_ARROW_RUN.sub("", line)
            line = IDENTITY.sub(r"**\1**", line)
            if "**" in line and stripped.startswith("|"):
                line = re.sub(r"\|\s*:\s+", "| ", line, count=1)
            line = WIKI.sub(lambda m: self._wiki_link(m, here), line)
            line = FRAGMENT.sub(lambda m: self._fragment(m, page, here, files), line)
            if "../" in line and self.config.repo_blob:
                line = self._out_of_docs(line, here)
            block = None if stripped.startswith("#") else BLOCK_ID.search(line)   # a heading's id is its slug
            if block:
                line = f'<a id="^{block.group(1)}"></a>' + line[: block.start()]
            if self.config.packages and not is_api and not stripped.startswith("#"):
                line = self._autolink(line, here)
            out.append(line)
        return "\n".join(out)
