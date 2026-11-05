# Ledger
`dvc_dat.ledger`: the dat's record in time. Every fact is a quad `(rev, subject, predicate, object)`, every read a function of a `Rev`, every write a `Transaction`.

::: dvc_dat.ledger
    options:
      show_root_heading: false
      members: false

## The ledger and its revisions

::: dvc_dat.ledger.Ledger

::: dvc_dat.ledger.Rev

::: dvc_dat.ledger.Ref

::: dvc_dat.ledger.Row

::: dvc_dat.ledger.Transaction

::: dvc_dat.ledger.attr

## The active ledger

`from dvc_dat import L, ledgers`: `L` is the active ledger, `ledgers` the project's ledgers by name.

::: dvc_dat.ledger.named.Ledgers

## Values and ledger functions

::: dvc_dat.ledger.Value

::: dvc_dat.ledger.ledger_class

::: dvc_dat.ledger.Fn

::: dvc_dat.ledger.Code

::: dvc_dat.ledger.register_policy

::: dvc_dat.ledger.register_store

::: dvc_dat.ledger.Remote

## Decorators

`from dvc_dat import dat`: `@dat.fn`, `@dat.warm`, `@dat.command` (SVP 250).

::: dvc_dat.dat
    options:
      show_root_heading: false
      members: false

::: dvc_dat.ledger.fn.fn

::: dvc_dat.ledger.FnMark

::: dvc_dat.ledger.warm.Warm

::: dvc_dat.just.command

## Rerunnability

::: dvc_dat.ledger.pin
    options:
      show_root_heading: false
      members: false

::: dvc_dat.ledger.Rerun

::: dvc_dat.ledger.Head

## The namespace over a ledger

::: dvc_dat.ledger.LedgerNamespace

## Releases

::: dvc_dat.ledger.bump

::: dvc_dat.ledger.bump_source

::: dvc_dat.ledger.SourceBump

## Errors

::: dvc_dat.ledger.errors
    options:
      show_root_heading: false
      heading_level: 3
