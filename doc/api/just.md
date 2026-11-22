# Commands
`dvc_dat.just`: `@dat.command` (`dvc_dat.just.command`) declares a function as a command, and each mounted command becomes a `just <name>` recipe in `.dat/targets.just`.

![DAT Ledger execution](DAT%20Ledger%20Execution.svg)

Module page: [DAT Ledger § Execution Semantics](ledger.md#execution-semantics).

::: dvc_dat.just
    options:
      show_root_heading: false
      members:
        - command
        - declared
        - commands
        - render
        - refresh
        - ARGS_MAX
        - HELP_MAX
