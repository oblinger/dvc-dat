# ledger.trace

A trace is the record of what producing a value read, item name to
value, and it is half the memo key: a hit is an entry every one of
whose items still holds at the revision asked. This module names the
items a recording `Rev` writes and decides whether a recorded item
still holds. It never runs a function: a nested eval is checked by a
lookup alone. Part of the [architecture](../../DAT%20Architecture.md).

## Items

| item | value | holds when |
| --- | --- | --- |
| `fn` | `db/fn/<name>/<hash>` | the name resolves at the rev to the same subject |
| `code/<repo>` | `<version>+<commit8>` | the environment's commit agrees with the recorded commit, whatever commit a `code/<repo>` row pins (6.2.0); the version is ignored |
| `uv.lock`, `platform` | the environment's | the environment, now, is the same |
| `<subject> <predicate>` | the held object (`<none>` if none) | the same object is held at the rev |
| `<name> db/alias` | `ref:<class>:<hash>` | the name still resolves to those bytes |
| `ref:<class>:<hash>` | the same text | always |
| `eval:<name>{keys}` | the result's `ref:`, or `<none>` | the lookup at the rev, never running, yields that hash (or still none) |
| `salt` | the mount's `db/salt` | the mount the `fn` subject's name resolves under has that salt |
| `q:{…}` (a query) | sorted `ref:` list as JSON | the same query at the rev answers the same list |
| `q:{"__call__": …}` | a token of the result | the same call at the rev gives the same token |

A query item is named by the whole query (`s`, `kind` dotted, `fn`,
`since`, `one`, every where entry) as canonical JSON. The other calls
(`all`, `in`, `asserted`, a 1- or 3-position bracket, `rows`, `get`
with `since`, and `preds`, `aliases`, `sealed_at` on a `Ref`) are named
by the call, its arguments and `since`.

## Public surface

- `token(obj) -> str`: a read's result as one comparable string
  (`<none>` for `None`; `Ref` and `Value` as `ref:` text; `Rev` as
  `rev:<id>`).
- `call_item(call, args, since) -> str`, `query_item(…) -> str`: item
  names.
- `present(rev, item, recorded, env, trace=None) -> bool`: whether one
  item holds.
- `trace_matches(rev, trace) -> bool`: every item holds; `fn` is
  checked last; a `LedgerError` or `ImportError` while checking is a
  miss, never an exception.
- `salt_at(rev, fn_subject) -> str`, `NONE = "<none>"`.

## Invariants

- Matching is memo-only: nothing here loads a value's bytes or runs a
  function.
- A value dependency is named by its bytes, so identical bytes from two
  entries are the same input.
- `code/<repo>` compares commits by prefix; a `bump` that changes only
  the version stales nothing, while `Value.diff` still shows it. The
  commit compared is the environment's, never the row's: an entry
  holds at the commit it ran at, tagged or not, and misses elsewhere
  (T543 Q7 (C)).

- TODO: the module docstring says each recorded call maps to "a token
  of its result"; for `rows` the recorded token is the row count
  (see [rev](rev.md)).

## Left to other modules

Recording happens in [rev](rev.md) (the `_rec` dict a recording `Rev`
carries); the `fn` check is [fn](fn.md)'s `fn_holds` (and
[sandbox](sandbox.md)'s re-hash at the rev's commit); the environment
comes from [env](env.md).
