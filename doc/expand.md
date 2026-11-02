:>> [DAT](DAT%20Track/DAT.md) → [DAT expand](ha://p/DAT%20expand) 
# Expansion: `ns.expand`
The `{}` grammar: `ns.expand(text, **vars)` fills a string's references from its expansion variables and the namespace's names, and returns a string.

A string may carry `{…}` references of two kinds. An undotted name is an
**expansion variable**: one given to the call as a keyword, or a built-in (the
clock, the working directory, the counter). A dotted name is a **namespace
name**: `{a.b.c}` is what `ns.load("a.b.c")` returns, rendered as text. The
result is always a string. `expand` is a method of a namespace because the
namespace is the one thing it needs beyond the clock, so each namespace
expands through its own names.

```python
from dvc_dat import ns

ns.expand("runs/{YYYY}-{MM}/baseline")      # 'runs/2026-11/baseline'
ns.expand("{svp.RUN_DIR}/exp")              # through the namespace
ns.expand("ann/{g}/{kind}/{unique}",
          g="G7", kind="events")            # vars; see Counting
```

## Which namespace

| Namespace | Reached as | Dotted names resolve through |
|---|---|---|
| the default world | `dvc_dat.ns` | `Dat.manager.ns`: imports, then `ns.mount(...)` |
| a manager's | `manager.ns` | that manager's mounts and imports |
| a ledger revision's | `rev.ns`, `t.ns` in a transaction | the ledger's `db/mount` rows at that revision, then imports |

A plain `Namespace()` with no manager expands too: it names Python objects and
mounts, nothing else. `{unique}` counts only on a ledger namespace (below).

## The grammar

| Reference | Resolves to |
|-----------|-------------|
| `{name}` | an expansion variable: the keyword `name=` given to the call, else a built-in; anything else is a `KeyError` |
| `{a.b.c}` | a namespace name: `ns.load("a.b.c")`, called with no arguments when it is a function or method |
| `{a.b.c(1, "x", k=2)}` | `ns.load("a.b.c")` called with those arguments |
| `{{` `}}` | a literal `{` and `}` |

An undotted name is never looked up in the namespace, and a dotted name is
never an expansion variable, so the two cannot collide. References do not
nest: a reference holds no `{` or `}`, and a lone `{` or `}` outside a
reference is a `ValueError` (`{a.{b}}` is one). A name chosen by a variable is
built first and expanded second, `ns.expand("{" + f"svp.{kind}.cfg" + "}")`,
or loaded outright, `ns.load(f"svp.{kind}.cfg")`.

**Always a string.** Every reference must come back as a string or a number,
which is written as text; a dict, a list, a class or an object is a
`TypeError`. To hold the object a namespace name refers to, load the expanded
name: `ns.load(ns.expand("{svp.cfg_name}"))`. The one place a
reference stands for the object itself is a spec, where `expand_spec` inlines
a value that is exactly one reference ([below](#where-templates-are-expanded-for-you)).

**Calls.** A dotted name that resolves to a function or method is called with
no arguments: `{meta.commit}` puts the commit in the string. Parentheses call
it with arguments, which are Python literals only (numbers, strings, `True`
`False` `None`, and lists, tuples or dicts of them): no names, no expressions,
no `{` `}` inside a reference. Parentheses also call a class or any other
callable; without them a class or a callable object is returned as it is, so a
mounted proxy keeps answering `{asset.ocr}` with its string. A function is
called each time its reference is expanded.

## Expansion variables

An expansion variable is an undotted name. The keywords of the call are
expansion variables for that call; the rest are built in. Every clock
built-in is one moment, taken once per call, so `{YYYY}-{MM}` on either side
of midnight agrees with itself.

| Built-in             | Value                                                        |
| -------------------- | ------------------------------------------------------------ |
| `{YYYY}` `{YY}`      | 4- and 2-digit year                                          |
| `{MM}` `{DD}`        | month, day, two digits                                       |
| `{HH}` `{mm}` `{SS}` | hour, minute, second, two digits, 24-hour                    |
| `{now}`              | the timestamp `yy-mm-dd_HH-MM-SS`                            |
| `{cwd}`              | the working directory, full path                             |
| `{unique}`           | the counter (see below); empty on a namespace with no ledger |

A keyword given to the call shadows a built-in of the same name. The template
is positional only, so a variable may be called `text`.

**Time zone.** The clock built-ins are in the namespace's zone, and a name
never carries a zone suffix. A ledger's zone is fixed when the ledger is
created (`Ledger(location, create=True, tz="America/Los_Angeles")`, an IANA
name, or `tz:` in a `ledgers:` entry, `games: {location: .dat/games, tz:
America/Los_Angeles}`; UTC when none is given), is the row `db db/tz` and
`L.tz`, and never changes, so it is read once when the ledger is opened, not
looked up per expansion, and it means the same thing at every revision. Every
date the ledger writes is in it: the clock built-ins in names, and the
machine stamps (`db/time` on every transaction, `sealed`), which are ISO 8601
with the zone's offset, `2026-11-01T14:03:22-07:00`. UTC is the default
because a ledger's writers are laptops and boxes in different zones and one
moment must mint one name from all of them. A namespace with no ledger uses
the machine's local zone, as `dat.name` always has.

## What the namespace holds

A dotted name goes to `ns.load`, which looks in these places, first hit wins:

1. **Mounted names** — what `ns.mount(folder=…)`, `mount(file=…)`,
   `mount(module=…)` or `mount(value=…)` put at `at`, the longest mounted
   prefix first; the rest of the name indexes into a mounted mapping. On a
   ledger namespace the mounts are its `db/mount` rows at that revision, so a
   template resolves against the code and values that revision names, not
   against whatever is importable on the machine. [Mounts](mount-commands.md) 
   has every form.
2. **The world's own names** — `dt.*`, the dat tools every manager registers
   (`{dt.list}` is the listing function).
3. **Imports** — the longest importable prefix is imported and the rest is
   `getattr`: `{mypkg.config.RUN_DIR}`.

A mounted name never shadows an importable one; `mount` refuses the clash.

## Counting: `{unique}`

`{unique}` makes a name that no value holds yet. On a ledger namespace the
expansion is tried with the counter at 1, 2, 3, … until the name is free: no
`db/alias` row names a value by it and no folder is at it under the data
folder. Two spellings, decided by where the braces sit:

| Template | First free | Then |
|---|---|---|
| `baseline{unique}` (a suffix inside a segment) | `baseline` | `baseline_2`, `baseline_3` |
| `events/{unique}` (a whole path segment) | `events/1` | `events/2`, `events/3` |

The whole-segment form counts from 1 so that `events/*` lists every version;
a bare `events` beside `events/2` would hide the first. On a namespace with
no ledger `{unique}` is the empty string. The counter probes the revision the
namespace was made at, so a loader minting many names holds one transaction
with `lock=` rather than racing other writers on the same prefix.

Writers do not expand: `add(s, p, o)`, `t[s, p] = o` and `seal(name=…)` take
their strings literally, and `expand` is the only place a template is read.
A name is computed in one line and sealed with the next:

```python
with ledger.transaction(by="load", lock=30) as t:
    name = t.ns.expand("ann/{g}/{src}/{kind}/{unique}",
                       g="G7", src="gt", kind="events")
    events.seal(to=t, name=name)        # ann/G7/gt/events/2
```

## Where templates are expanded for you

Two places expand a template themselves, with the same `now` and `unique` for
the folder and the spec:

- **`dat.name`** in a spec, when the dat is created. The spec keeps the
  template as written; the folder it landed in is the name. Every other string
  in the spec is expanded once at create, and the expanded spec is what
  `_spec_.yaml` holds. In a dat folder `{unique}` counts as a suffix, `""`
  then `_2`, `_3`, until no folder is at the name, on any manager;
  `dat.target_exists: increment` appends `{unique}` to a plain name.
  [Spec Format](spec-format.md) § `dat` section. On a ledger (`rev.run`), the
  name a result is saved under is `rev.ns.expand` of the template, counted as
  above.
- **`path=`** on a ledger function result, with the call's keyword arguments as
  the vars: `path="runs/{game}/{unique}"` on a function taking `game=`.

`ns.expand_spec(spec, **vars)` merges a dict's `dat.base` chain (bases named
through the same namespace), then expands every string value of a dict or
list and leaves keys alone, the built-ins one moment for the whole spec. It is
the one place a reference stands for an object: a
string value that is *exactly* one reference is replaced by what the name
loads, so `cfg: "{svp.defaults}"` puts the dict itself in the spec, and
`count: "{svp.N}"` the number. `ns.quote_spec(spec)` doubles every brace so a
spec survives a second expansion unchanged.

## YAML quoting

A value that *begins* with `{` must be quoted, or YAML reads it as a flow
mapping and the spec arrives with a dict where a string belongs:

```yaml
dat:
  name: "{svp.RUN_DIR}/exp"
```

## Errors

| Case | Raised |
|---|---|
| `{name}` with no such keyword or built-in | `KeyError`, naming the built-ins and the vars given |
| `{a.b}` the namespace cannot load | the import's own `ImportError` or `AttributeError` |
| a reference returning a dict, list, class or object (outside `expand_spec`'s whole-value case) | `TypeError` |
| `{a.b(...)}` whose arguments are not literals | `ValueError` |
| a lone `{` or `}`, a nested reference `{a.{b}}` | `ValueError` |
| `{name(...)}` calling an undotted name | `ValueError` |
| `{unique}` with no free name in 100,000 tries | `RuntimeError` |
