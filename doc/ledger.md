# The ledger

The ledger is the dat's record in time: every fact a quad
`(rev, subject, predicate, object)`, every read a function of one
revision, every value stored by its content. Since 5.0.0 it is the
value-space design; the 4.0 ledger (`Ledger.open`, `assign`, `last`,
`SqliteLedger`) is gone.

- [Architecture § The ledger](DAT%20Architecture.md#the-ledger-facts-read-as-of-a-moment):
  the design, end to end.
- [`DAT Modules/ledger/`](DAT%20Modules/ledger/ledger.md): one page per
  module.
- [`ledger-triples`](DAT%20Demos/ledger-triples.py),
  [`ledger-values`](DAT%20Demos/ledger-values.py),
  [`ledger-dats`](DAT%20Demos/ledger-dats.py),
  [`ledger-just`](DAT%20Demos/ledger-just.py): the four notebooks.
