# ledger.sandbox

A function under a mount runs where the code it can reach is bounded:
in a fresh process of its own, forked for the one call from a warm
`python -I` server, whose only importable repository code is the
mounted roots, and whose file reads and writes are confined while the
body runs. That bound is what lets one `fn` trace item, the bytes of
every module the run loaded, stand for the code: one changed byte in
any of them, third-party ones included, is a different value. The
parent side resolves a name through the mounts and sends a miss to the
server; the child installs the finder and the open hook, runs the
function, seals the entry itself, and exits. Part of the
[architecture](../../DAT%20Architecture.md).

## Public surface

Parent side:

- `load_sandboxed(rev, name, prefix, info) -> Fn`: the mount's repo
  must have a checkout in the environment (`NotEvaluated` naming the
  repo); the module must exist under the mount (`ImportError`) and
  define the function at top level (`ImportError`), marked
  `@ledger_fn` by its decorator text (`TypeError`), with the `Rev` as
  its first positional parameter (`TypeError`). The source is parsed,
  not imported. `Fn.subject` before any run is the static closure.
- `run_sandboxed(fn, rev, kw, enc, seal) -> Value`: a miss runs at
  HEAD, clean or dirty (no checkout of the repo is `NotEvaluated`);
  `clean=True` was checked before the lookup (`fn.check_clean`). It
  calls the server, or runs in-process when already inside a child.
- `Server()`: one `python -I -m dvc_dat.ledger.worker` process per
  environment (`sys.executable`), with its own scratch folder as cwd,
  environment limited to `PATH`, `HOME`, `TMPDIR`, `LANG`,
  `CUDA_VISIBLE_DEVICES`, plus `DAT_SCRATCH`. `call(…)` sends one
  request (the ledger, the rev, the name, the keys) and returns the
  sealed entry (loaded in the parent) or, unsealed, the unpickled
  value; an exception in the child is re-raised in the parent with
  `worker_traceback` set; a child that dies before replying is a
  `RuntimeError` naming its exit code.
- `shutdown()`: stops every server; registered at exit.
- `sandbox_subject_at(rev, name, modules) -> str | None`: the `fn`
  subject the recorded modules hash to now: a mounted file at the
  rev's commit (via `git show` when the rev's commit is not HEAD),
  else on disk; a third-party item as installed
  (`third_party_now`).
- `third_party_items(names) -> dict`: the `fn` items of loaded
  modules outside the mounts: `dist:<name>` →
  `<version>:<sha256 of RECORD>` for a module of an installed
  distribution with a `RECORD`, else `py:<path under its sys.path
  entry>` → `sha256` of the file (the standard library, an editable
  source). dvc-dat is never one (A56).
- `static_closure(root, start, within)`, `closure(mounts, start)`,
  `module_shas(…)`, `file_sha(checkout, rel, commit)`, `Mount`,
  `mounts_for(rev, env)`: the module walkers and hashers, shared with
  base mode's `fn` hash.

Child side:

- `MountFinder`, first on `sys.meta_path`: serves a mounted prefix from
  its root (a root without `__init__.py` imports as a namespace
  package); gives the prefix's ancestors empty namespace packages;
  raises `UnmountedImport("<module> from <importer>; mount it or move
  it")` for a module that would resolve inside a mounted repo's
  checkout under no mount.
- The audit hook, active only while a function body (or its module's
  first load) runs. Writes go only into that body's `work` folder,
  the dat being produced, and `/dev/null`; anywhere else, the worker's
  scratch and the art store included, is `ConfinedWrite("<path>: a
  sandboxed function writes only in its work folder")`. Checked:
  `open` and `os.open` for writing (a mode with `w`, `a`, `x` or `+`,
  or `O_WRONLY`, `O_RDWR`, `O_CREAT`, `O_TRUNC`); every path-changing
  `os` call (`mkdir`, `rmdir`, `remove`, `rename`/`replace` and `link`
  on both paths, `symlink`, `chmod`, `chown`, `utime`, `truncate`,
  `chflags`, `setxattr`, `removexattr`), a `dir_fd` resolved to its
  folder and a descriptor to its file; `sqlite3.connect` on any
  database but the ledger's own; and through these `pathlib`,
  `shutil` and `tempfile` (a default temp file lands in `$TMPDIR`, so
  it is refused; pass `dir=work`). A function with no `work`
  parameter writes nowhere. Reads go only into the mounted roots, the
  art store (the dats) and that `work` folder; anywhere else, the
  worker's scratch, the interpreter's folders, `site-packages`, the
  dvc-dat package and the rest of a mounted repo included, is
  `UntracedRead("<path>: outside the mounts, the dats and the work
  folder")`. Checked: `open`/`os.open` for reading and the listings
  `os.listdir`, `os.scandir`, `os.listxattr`, `os.getxattr`, and
  through them `pathlib`, `shutil` and `glob`. The ledger's own reads
  (`rev[...]`, `rev.load`, queries) are the view, not file opens.
  Two reads stay open because their content is already in the trace:
  the import system reading a module file (the finder decides what
  imports; every module loaded is in `fn`), and, while a module from
  outside the mounts is being imported, that import's reads in the
  interpreter's folders (a library loading its bundled data, which
  its `RECORD` covers). A library's data read after its import is
  refused.
- While a body with a `work` folder runs, the worker's current
  directory is that folder, so a relative path lands in the dat being
  produced.
- `unguarded()`: the ledger's own machinery inside a body (a nested
  `rev.eval`'s lookup and seal, a `Dat` materialised into the art
  store on load) runs with the hook stood aside; a nested body is
  confined again, to its own `work` folder.
- The same hook on the network, active while a function body runs:
  resolving a host name (`socket.getaddrinfo`, `gethostbyname`,
  `gethostbyaddr`, `getnameinfo`) or sending to an internet address
  (`socket.connect`, `sendto`, `sendmsg` on an `AF_INET`/`AF_INET6`
  socket) is `ConfinedNetwork("<host or address:port>: a sandboxed
  function does not use the network")`, raised before the call
  reaches the system. Allowed: the ledger's own endpoint when it is
  Postgres (the DSN's hosts, and their addresses at the port, resolved
  when the worker installs), and local
  `AF_UNIX` sockets and socket pairs, which are not the network.
- `worker_main()`: the server's loop. It first loads the ledger's
  machinery and the installed distributions' map (never a mounted
  module, never CUDA), then per request forks a child and relays its
  one reply, until stdin closes.
- `serve(req, out)`: in the child: adopts the parent's `Env.code`
  through `set_env_provider`, opens the request's ledger, installs the
  finder and the hook, loads the function at the requested revision,
  runs it, seals with provenance `eval:sandbox`, replies.
- `run_here(fn, rev, kw, enc, seal)`: one run in this process; the
  modules it loaded are those new in `sys.modules` over the body less
  any a nested body loaded; the trace is the recorded reads plus
  `fn`, `platform` and, when the mount sets one, `salt`; no
  `code/<repo>` item.

## Invariants

- One warm server per environment; a fresh forked child per top-level
  call, so every run loads and records what it uses and nothing a body
  loaded or changed outlives the call. The server holds only the
  ledger's machinery (the standard library pieces it uses, pyyaml,
  dvc-dat): what it holds is infrastructure, not recorded.
- The `fn` item hashes the modules the run loaded: mounted ones (with
  the static import closure of the function's module and of each),
  `relpath -> sha256` of the file as read, a dirty tree's bytes
  included; third-party ones by distribution `RECORD` or file bytes;
  and the mount-table hash. A mounted package's `__init__.py` counts.
- A nested eval inside a child runs in-process and its loads count
  toward its own entry, not the caller's.
- Bulk data never crosses the pipe on a sealing call: the child seals
  and returns the subject only.

- Stubs, as built: a nested eval under another mount runs in the same
  child; a base-mode eval nested inside a child is unsupported; repo
  files read under a mount are allowed and not recorded; a nested
  function's imports the caller already loaded are not recorded for
  it beyond its static closure.

## Left to other modules

The memo lookup and the seal are [fn](fn.md)'s (`lookup`,
`seal_entry`); the trace's hit test is [trace](trace.md)'s; discovery
is [env](env.md)'s; the entry point is [worker](worker.md).
