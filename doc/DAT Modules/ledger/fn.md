# ledger.fn

A value function is a plain Python function marked `@ledger_fn`; an
`Fn` is that function resolved at a revision, and calling an `Fn` is
`run`. Resolution decides the mode: a name under a mounted prefix
(`db/mount/<prefix>` rows as of the revision) is a sandboxed function,
loaded from the mounted tree and run in a worker
([sandbox](sandbox.md)); any other name is a base function, resolved in
this process. `run` is a memo: the same question asked of an unchanged
world hands back the value already sealed. Part of the
[architecture](../../DAT%20Architecture.md).

## Public surface

- `ledger_fn(func) -> func`: marks `func` (`__ledger_fn__ = True`) and
  returns it unchanged, still a plain callable. No return annotation is
  `TypeError` at decoration; a non-callable `TypeError`. Writes nothing.
- `load_fn(rev, name) -> Fn` (also `Rev.load_fn`): `name` a dotted
  `str` (else `TypeError`); the longest mounted prefix wins. Base mode:
  the name must import in this process (`ImportError`), be marked
  (`TypeError`), have a source file (`ImportError`), and take the `Rev`
  as its first positional parameter (`TypeError`); a parameter named
  `memo` is `TypeError`.
- `Fn`: a frozen dataclass with `name`, `module` (the source file),
  `sha` (sha256 of that file), `mode` (`"base"` or `"sandbox"`),
  `mount` (the prefix or `None`), `signature` (the keys, without the
  `Rev` and `path`), `env` (an `Env`; `mounts` the mount-table hash in
  sandbox mode), `subject` (`db/fn/<name>/<16 hex>`).
- `Fn.__call__(*, memo=True, clean=False, path=None, kwargs=None,
  **keys) -> Value | None`. The control options are exactly `memo`,
  `clean`, `path` and `kwargs` (Q41): never keys, never hashed.
  - `memo=True`: a hit, else run, seal, return; `memo=False`: run, seal
    nothing; `memo="get"`: a hit or `None`, never runs; anything else
    `ValueError`.
  - Keys bind to the signature with defaults applied (`TypeError` from
    `inspect` on a bad key). `kwargs={...}` is the whole key set, for
    a function that declares a key named like a control option (a
    function may; it is then called through `kwargs=`); inline keys
    beside it are `TypeError`. A declared `path` is the folder the
    function builds, never a key (`TypeError` in `kwargs=`).
  - `path=` (Q36, A70): relative (to the data folder,
    `<art store>/dats`), it is the result's name: the value's one
    alias, the name moved off any value it named and any other name
    of this value retracted, and a `Dat`'s folder rebuilt at
    `<data folder>/<path>` as a view (hardlinks into the store, a new
    folder, never edited in place). A hit asked for under a new name
    takes it. Absolute: the folder is made there and nothing is
    named. With no `path=`, a miss of a function declaring `path`
    that returns a `Dat` is named by that parameter's default, the
    path template, expanded with the keys (`{unique}` counts up to a
    free name), else `anonymous/Dat{unique}`. `memo=False`: the name
    is set on the unsaved object.
  - Base mode: a miss runs only when the function's code is in a git
    checkout and the checkout is clean; code outside any checkout or a
    dirty checkout is `NotEvaluated` (there is no byte record of what
    ran). A `code/<repo>` `commit` row does not gate a base eval: it
    pins what the version means, and the entry's `code/<repo>` item
    records the commit the code ran at, so a hit holds only at that
    commit ([trace](trace.md)).
  - Sandbox mode: a miss runs at HEAD, clean or dirty; its identity is
    the bytes of the modules it loaded ([sandbox](sandbox.md)).
  - `clean=True` (either mode): before the lookup, the checkout must be
    clean and at the commit the rev's `code/<repo>` row names, else
    `NotClean`, a `NotEvaluated`; a rev naming no commit is refused
    too. For a reader who must say simply which version of the code
    ran. No warn mode.
  - A result not an instance of a `Value`-subclass annotation is
    `TypeError`; with any other annotation a non-`Value` result is
    wrapped in `Pickled`.
- `encode_keys(kw) -> dict`: `db/keys` content; a top-level
  `Value`/`Ref` becomes `ref:<class>:<hash>`, nested one `TypeError`,
  an unsealed `Value` `ValueError`, a non-JSON value `TypeError`.
- `lookup(rev, name, enc) -> Value | None`: the memo lookup.
- `mounts_at(rev) -> {prefix: {"root", "repo", "salt"}}`,
  `mounts_hash(rev) -> str | None`, `fn_subject(name, modules, mounts)`,
  `fn_holds(rev, subject) -> bool`, `seal_entry(…)`, `wrap_result(…)`,
  `base_closure(…)`, `resolve_in_process(name)`, `signature_of(…)`:
  the machinery the other modules call.

## The memo

- Lookup: every entry at the top whose `db/keys` row is the canonical
  JSON of the bound keys and whose `db/fn` row is the dotted name,
  newest seal first; the first whose trace holds at the asked revision
  ([trace](trace.md)) is restored by `Ref.load`.
- Base run: the body gets a recording `Rev`; a function declaring
  `path` gets a fresh `ledger-work-*` folder under `work_root()`
  (`$DAT_WORK`, else `~/.cache/dvc-dat/work`), removed after the seal;
  a GB-scale result built there should sit on the filesystem it is
  saved to, so set `DAT_WORK` beside the ledger's art store. The trace is the recorded reads plus `fn`, `code/<repo>` (the
  function's own repo) and `platform`.
- Seal: one transaction `by="eval:<name>"`, subject = hash of
  `{fn, keys, trace, preds, value}`; writes the `db/fn/<name>/<hash>`
  rows (`db/name`, `db/module`, `db/sha`, `db/modules`, `db/mounts`,
  `db/mode`, `db/returns`) if absent, then the seal with `db/fn`,
  `db/keys` and `db/provenance eval:base|eval:sandbox`. A subject
  already sealed writes no revision and returns that entry.
- A call made from inside a value function records
  `eval:<name>{keys}` → the result's `ref:` (or `<none>` for a
  `memo="get"` miss) in the caller's trace.
- The base `fn` subject hashes `relpath -> sha256` of the module's
  static import closure within its checkout (the module file alone
  outside any checkout); `fn_holds` re-resolves the name at the asked
  revision and compares subjects.

## Invariants

- `@ledger_fn` never changes the function; a plain call runs the body
  with whatever `Rev` it is given, records nothing and seals nothing.
- `db/keys` is canonical JSON: sorted keys, compact, defaults bound, so
  `epochs=8` and `epochs="8"` are two questions.
- Two entries for one `(fn, keys)` coexist; the newest matching wins.

## Left to other modules

Sandbox resolution and running are [sandbox](sandbox.md)'s; the trace
items and their hit test are [trace](trace.md)'s; repos and commits
come from [env](env.md); the seal rows are written by [txn](txn.md)'s
`_seal`.
