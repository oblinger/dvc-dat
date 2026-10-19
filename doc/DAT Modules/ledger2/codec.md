# ledger2.codec

A row's third position is stored as one tagged string, so a row reads
back without a schema: `str:<text>`, `json:<canonical document>`, or
`ref:<dotted class>:<hex sha256>[:<subject>]` for a sealed value. The
subject is an optional hint, written only when `add` stores a `Ref`; in
`db/value`, typed preds, `db/keys` and traces it is omitted, so a
dependency is its bytes, not its entry. Part of the
[architecture](../../DAT%20Architecture.md).

## Public surface

- `canonical(doc) -> str`: sorted keys, compact separators, unicode
  kept.
- `sha256(data) -> str`, `hash_text(text, n=64) -> str`,
  `is_hash(s) -> bool` (64 lowercase hex).
- `ref_text(cls, h, subject=None) -> str`; `parse_ref(text) -> (cls,
  h, subject | None)`, `ValueError` on a malformed ref;
  `strip_hint(text)` drops the subject from a `ref:` text.
- `encode_plain(obj) -> str | None`: `str:` for a `str`, `json:` for a
  `dict`/`list` (`TypeError` when not JSON-encodable), `None` otherwise.
- `refuse_scalar(obj)`: `TypeError` for `None`, `bool`, `int`, `float`
  (a number is its string).
- `show(text) -> str`: the stored object as one line; `tag(text) ->
  str`.

## Invariants

- One text per JSON document, so equal documents compare equal as
  stored strings.
- A trace, a key or a where clause compares refs without the hint.

## Left to other modules

Decoding a stored object into `str`, `dict`/`list` or `Ref` is
[rev](rev.md)'s (`Rev._decode`); what may be stored where is
[txn](txn.md)'s.
