# Commands
`dvc_dat.just`: `@command` declares a function as a command, and each mounted command becomes a `just <name>` recipe in `.dat/targets.just`.

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
