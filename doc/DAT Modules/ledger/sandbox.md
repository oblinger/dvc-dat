# ledger.sandbox

A function under a mount runs where the code it can reach is bounded:
in a `python -I` worker whose only importable repository code is the
mounted roots, and whose file reads and writes are confined while the
body runs. That bound is what lets one `fn` trace item, the hashes of
the mounted modules the run used, stand for the code. The parent side
resolves a name through the mounts and sends a miss to a worker; the
worker side installs the finder and the open hook, runs the function,
and seals the entry itself. Part of the
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
- `run_sandboxed(fn, rev, kw, enc, seal) -> Value`: checks the code
  (no checkout, a dirty one, or a HEAD other than the rev's
  `code/<repo>` commit is `NotEvaluated`), then calls the worker for
  the mount, or runs in-process when already inside a worker.
- `Worker(ledger_path)`: one `python -I -m dvc_dat.ledger.worker`
  process with its own scratch folder as cwd, environment limited to
  `PATH`, `HOME`, `TMPDIR`, `LANG`, `CUDA_VISIBLE_DEVICES`, plus
  `DAT_LEDGER` and `DAT_SCRATCH`. `call(…)` sends one request and
  returns the sealed entry (loaded in the parent) or, unsealed, the
  unpickled value; a worker exception is re-raised in the parent with
  `worker_traceback` set.
- `shutdown()`: stops every worker; registered at exit.
- `sandbox_subject_at(rev, name, modules) -> str | None`: the `fn`
  subject the recorded modules hash to at the rev's commit (via
  `git show` when the rev's commit is not HEAD).
- `static_closure(root, start, within)`, `closure(mounts, start)`,
  `module_shas(…)`, `file_sha(checkout, rel, commit)`, `Mount`,
  `mounts_for(rev, env)`: the module walkers and hashers, shared with
  base mode's `fn` hash.

Worker side:

- `MountFinder`, first on `sys.meta_path`: serves a mounted prefix from
  its root (a root without `__init__.py` imports as a namespace
  package); gives the prefix's ancestors empty namespace packages;
  records every module it loads against the innermost running call;
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
  parameter writes nowhere. A read outside the mounted roots, the art
  store, the worker's scratch, the interpreter's folders, `/dev` and
  the dvc-dat package is `UntracedRead`.
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
- `worker_main()`: the loop, one request and one reply until stdin
  closes; adopts the parent's `Env.code` through `set_env_provider`,
  purges the mounted modules, loads the function at the requested
  revision, runs it, seals with provenance `eval:sandbox`.
- `run_here(fn, rev, kw, enc, seal)`: one run in this process; the
  trace is the recorded reads plus `fn`, `uv.lock`, `platform` and,
  when the mount sets one, `salt`; no `code/<repo>` item.

## Invariants

- One worker per `(ledger folder, mount prefix)`, kept warm; the
  mounted modules are purged from `sys.modules` before each top-level
  call, so every run loads and records what it uses.
- The `fn` item hashes, `relpath -> sha256` at the rev's commit, the
  static import closure of the function's module plus every mounted
  module loaded during the run and their closures, and the mount-table
  hash; a mounted package's `__init__.py` counts.
- A nested eval inside a worker runs in-process and its loads count
  toward its own entry.
- Bulk data never crosses the pipe on a sealing call: the worker seals
  and returns the subject only.

- Stubs, as built: no idle retirement; reads allowed more widely than
  the design's final form; a nested
  eval under another mount runs in the same worker; a base-mode eval
  nested inside a worker is unsupported; repo files read under a mount
  are allowed and not recorded.

## Left to other modules

The memo lookup and the seal are [fn](fn.md)'s (`lookup`,
`seal_entry`); the trace's hit test is [trace](trace.md)'s; discovery
is [env](env.md)'s; the entry point is [worker](worker.md).
