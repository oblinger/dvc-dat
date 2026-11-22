# Namespace
`dvc_dat.do`: the namespace `ns`, which maps dotted names to Python objects, and the command line.

![DAT Dat](DAT%20Dat.svg)

Part of the dat half: [DAT Dat](core.md).

## Namespace Interface
A namespace of dotted names, bound to the `DatManager` whose world it names; not callable (running is `manager.run`). Every manager builds its own, reached as `manager.ns`; `Dat.ns` forwards to `Dat.manager.ns`. `Namespace(manager=None)` is the constructor: a bare `Namespace()` mounts, loads and names with no world, and its `manager` is `RuntimeError` until a manager built with `ns=` adopts it. A dotted name is a mounted name first, else exactly what `import` means in this environment, `getattr` below that.

<!-- methods: dvc_dat.namespace.Namespace -->

# Reference

::: dvc_dat.do
    options:
      show_root_heading: false
      members: false

::: dvc_dat.namespace.Namespace

::: dvc_dat.do.cli_main

::: dvc_dat.do.arg_value
