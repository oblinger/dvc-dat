:>> [DAT](DAT%20Track/DAT.md) → [DAT expand](ha://p/DAT%20expand) 
# Expansion: `ns.expand`
The `${…}` grammar, OmegaConf's: a spec's strings are resolved once, when the dat is created, through OmegaConf with four resolvers of DAT's; on the base install `${unique:}` alone is expanded, by DAT itself.

A string may carry `${…}` references. `${batch}` is a **node of the spec**,
an absolute path from its root (`${dat.kwargs.game}`). `${ns:a.b.c}` is a
**namespace name**: what `ns.load("a.b.c")` returns. `${now:%Y}`,
`${unique:}` and `${cwd:}` are the **built-ins**. `\${` is a literal `${`. A
brace without `$` is plain text: `{asset.pose}` is the string it reads.

```python
from dvc_dat import ns

ns.expand("runs/${now:%Y-%m}/baseline")     # 'runs/2026-11/baseline'
ns.expand("${ns:svp.RUN_DIR}/exp")          # through the namespace
# keywords are top-level nodes; see Counting
ns.expand("ann/${g}/${kind}/${unique:}",
          g="G7", kind="events")
```

## The install tiers

| Install | A string may hold | Without it |
|---|---|---|
| `dvc-dat` | plain text and `${unique:}`, filled by DAT with no OmegaConf | any other `${`, and `\${`, is `ImportError` naming `dvc-dat[expand]`, raised before any folder or row is written |
| `dvc-dat[expand]` | the whole grammar (omegaconf ≥ 2.3) | — |
| `dvc-dat[hydra]` | as `[expand]`; `dat run` speaks Hydra's override grammar ([CLI](cli.md)) | — |

**The scan.** Every string value of a spec (keys are never read) is one of
three: *plain* (no `${`), *unique* (every `${` is exactly the eleven
characters `${unique:}`) or *expand* (any other `${`, or the escape `\${`). A
spec is the worst of its strings. Plain is stored as given and unique is
filled by DAT; only expand imports omegaconf. Both tiers fill `${unique:}`
by the same rule, so a spec holding nothing but `${unique:}` gives the same
strings on every install. Passing an unknown `${` through as text is never
done: it would seal `${ns:asset.detector}` as a model name.

## Which namespace

| Namespace | Reached as | `${ns:…}` resolves through |
|---|---|---|
| the default world | `dvc_dat.ns` | `Dat.manager.ns`: imports, then `ns.mount(...)` |
| a manager's | `manager.ns` | that manager's mounts and imports |
| a ledger revision's | `rev.ns`, `t.ns` in a transaction | the ledger's `db/mount` rows at that revision, then imports |

A plain `Namespace()` with no manager expands too: it names Python objects and
mounts, nothing else. `${unique:}` counts only on a ledger namespace and in a
dat folder (below).

## The grammar

| Reference | Resolves to |
|-----------|-------------|
| `${a.b}` | the node at that absolute path of the spec (for `ns.expand`, of the tree whose nodes are the keywords) |
| `${ns:a.b.c}` | `ns.load("a.b.c")`, called with no arguments when it is a function; a `mnt.` name as `ns.load` takes it |
| `${ns:a.b.c, 1, x}` | `ns.load("a.b.c")` called with those positional literals (a keyword argument is a parse error) |
| `${now:%Y-%m-%d}` | the moment, `strftime`; `${now:}` is `yy-mm-dd_HH-MM-SS` |
| `${unique:}` | the counter (see Counting) |
| `${cwd:}` | the working directory, full path |
| `\${` | a literal `${` |
| `${oc.select:a.b,${c}}` | OmegaConf's own resolvers work as written: `a.b`, else `${c}` |

An interpolation may sit inside a resolver's argument:
`${ns:asset.detector_b${batch}}`. A missing node and a cycle are each one
error at create. A value that is *exactly* one reference inlines the object:
`cfg: ${ns:svp.defaults}` puts the dict in, `${ns:mymod.fn}` the function;
inside a longer string it is text. A path cannot walk *into* an object a
resolver returned (`cfg: ${ns:svp.defaults}` then `${cfg.lr}` fails): spell it
`${ns:svp.defaults.lr}` (1519 decision 5).

**The clock.** Every `${now:…}` in one resolve is one moment, so
`${now:%Y}-${now:%m}` on either side of midnight agrees with itself, and the
folder and the spec share it. On a ledger namespace the zone is the display
zone as of its revision, the row `db db/timezone` (an IANA name; UTC with
none); a transaction's `t.ns` uses its snapshot's. A namespace with no ledger
uses the machine's local zone. Hydra registers a `now` of its own, a live
clock: DAT registers its resolvers again at the start of every resolve, so
DAT's wins whichever was imported last.

| Before 3.0 | Now |
| --- | --- |
| `{YYYY}` `{YY}` `{MM}` `{DD}` `{HH}` `{mm}` `{SS}` | `${now:%Y}` `${now:%y}` `${now:%m}` `${now:%d}` `${now:%H}` `${now:%M}` `${now:%S}` |
| `{now}` | `${now:}` |
| `{unique}` | `${unique:}` |
| `{cwd}` | `${cwd:}` |
| `{a.b}`, `{a.b(1, "x")}` | `${ns:a.b}`, `${ns:a.b, 1, x}` |
| `{game}` (a call variable) | `${dat.kwargs.game}`; kwargs over defaults: `${oc.select:dat.kwargs.game,${dat.defaults.game}}` |
| `{{` | `{` (a brace is text) |

A `dat.name` still in the old grammar is refused at create, naming its new
spelling (1519 decision 3).

## What the namespace holds

`${ns:name}` goes to `ns.load`, which looks in these places, first hit wins:

1. **Mounted names** — what `ns.mount(folder=…)`, `mount(file=…)`,
   `mount(module=…)` or `mount(value=…)` put at `at`, the longest mounted
   prefix first; the rest of the name indexes into a mounted mapping. On a
   ledger namespace the mounts are its `db/mount` rows at that revision.
   [Mounts](mount-commands.md) has every form.
2. **The world's own names** — `dt.*`, the dat tools every manager registers.
3. **Imports** — the longest importable prefix is imported and the rest is
   `getattr`: `${ns:mypkg.config.RUN_DIR}`.

## Counting: `${unique:}`

`${unique:}` makes a name that nothing holds yet. Two spellings, decided by
where it sits:

| Template | First free | Then |
|---|---|---|
| `baseline${unique:}` (a suffix inside a segment) | `baseline` | `baseline_2`, `baseline_3` |
| `events/${unique:}` (a whole path segment) | `events/1` | `events/2`, `events/3` |

The whole-segment form counts from 1 so that `events/*` lists every version.
In a dat folder (`dat.name`) the count climbs until no folder is at the name;
on a ledger namespace (`t.ns.expand`, a ledger function's `path=`) until no
`db/alias` row names a value by it and no folder is at it under the data
folder, probing the revision the namespace was made at (a transaction's: its
snapshot and the names it minted). On a namespace with neither, it is the
first count: `""`, or `1` as a whole segment.

Writers do not expand: `add(s, p, o)`, `t[s, p] = o` and `seal(name=…)` take
their strings literally, and `expand` is the only place a template is read:

```python
with ledger.transaction(by="load", lock=30) as t:
    name = t.ns.expand("ann/${g}/${src}/${kind}/${unique:}",
                       g="G7", src="gt", kind="events")
    events.seal(to=t, name=name)        # ann/G7/gt/events/2
```

## Where templates are resolved for you

- **The spec, at create.** `Dat.create` / `Dat.manager.run` merge `dat.base`
  on plain dicts (strings pass the merge untouched), then resolve the whole
  spec once, the folder's name included, with one moment and the folder's
  final count. `_spec_.yaml` holds the plain result, except `dat.name`, which
  keeps the template as written; the folder it landed in is the name.
  `dat.target_exists: increment` appends `${unique:}` to a plain name, and the
  default name is `anonymous/Dat${unique:}`. On a ledger (`rev.run`) the memo
  key is the spec resolved the same way, `dat.name` removed and `dat.preds`
  kept as its template; the name a result is saved under is `rev.ns.expand`
  of the template against the key (`${dat.kwargs.game}`), counted as above.
- **`path=`** on a ledger function result, the call's keywords the top-level
  nodes: `path="runs/${game}/${unique:}"` on a function taking `game=`.
- **A call-site value is data.** A keyword of `run`/`create`/`rev.run` reaches
  `dat.kwargs` as given: on `[expand]` each `${` in it is escaped (`\${`)
  before the merge; on the base install one holding `${` is `ValueError`
  naming `dvc-dat[expand]` (1519 decision 8). `ns.quote_spec(spec)` is that
  escape.

`ns.expand_spec(spec)` merges a dict's `dat.base` chain and resolves every
string value of it, keys left alone, the built-ins one moment.

## YAML

`${…}` is a plain scalar in YAML: no quotes needed (a value starting `{`
still is a flow mapping, as before).

```yaml
dat:
  name: runs/${now:%Y}/${dat.kwargs.game}${unique:}
  kwargs:
    detector_model: ${ns:asset.detector}
```

## Errors

| Case | Raised |
|---|---|
| a `${` other than `${unique:}` on the base install | `ImportError` naming `dvc-dat[expand]` |
| a call-site keyword holding `${` on the base install | `ValueError` naming `dvc-dat[expand]` |
| `${a.b}` with no such node | OmegaConf's `InterpolationKeyError` |
| a cycle | OmegaConf's `InterpolationResolutionError` |
| `${ns:a.b}` the namespace cannot load | the import's own `ImportError` or `AttributeError`, wrapped by OmegaConf |
| `${ns:a, k=2}` (a keyword argument) | OmegaConf's `GrammarParseError` |
| `${unique:x}` (an argument) | `ValueError` |
| `ns.expand` resolving to a dict, list or object | `TypeError` |
| a `dat.name` in the `{…}` grammar | `ValueError` naming the new spelling |
| `${unique:}` with no free name in 100,000 tries | `RuntimeError` |
