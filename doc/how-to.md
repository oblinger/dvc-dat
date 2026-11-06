# How-to
You have a task and know the library. Each row is one task, its page or section the preconditions, the commands and what they print.

| Task | Where |
| --- | --- |
| Set up a project: `.datconfig.yaml` | [Configuration](concepts.md#configuration-datconfigyaml) |
| Run a spec and fork it | [Arguments fork a spec](concepts.md#arguments-fork-a-spec-they-never-ride-beside-it) · [Arguments](cli.md#arguments) |
| Run from a shell | [`just run`](cli.md) · [`dvc_dat.just` in every project](cli.md#dvc_datjust-run-and-mounts-in-every-project) |
| Declare a command | [`@dat.command`](cli.md#commands-datcommand-and-dattargetsjust) |
| Mount a folder or a module | [Mounts](mount-commands.md) |
| Put a value on the ledger, find it by preds; read as of a revision | [The ledger verbs](cli.md#the-ledger-verbs) · the [ledger: values](DAT%20Demos/ledger-values.ipynb) notebook |
| Write a `{}` reference in a spec | [The {} grammar](expand.md) |
| Look up a key of `_spec_.yaml` or `_result_.yaml` | [Spec format](spec-format.md) |

No task here: [Tutorials](tutorials.md) teach the library, [API Reference](api/index.md) names every call.
