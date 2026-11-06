:>> [DAT](DAT%20Track/DAT.md) → [DAT index](ha://p/DAT%20index) 
# dvc_dat Documentation
The front page of the dvc_dat docs: what the package does, and where to read next.

**dvc_dat** manages data artifacts as folders that describe themselves. A dat
is a folder whose `_spec_.yaml` is a complete, argumentless recipe for itself;
`_result_.yaml` holds what running it produced, written once when `dat.save()` seals it.

## Quick Start

```python
from dvc_dat import Dat

ns = Dat.ns   # the namespace shortcut; follows Dat.manager

# Importing reads nothing; the first use below finds the nearest
# .datconfig.yaml, walking up from the working directory.

# Create a dat with its own metadata
dat = Dat.create(
    path="experiments/exp1",
    spec={"params": {"lr": 0.01}},
)

# Open it later
dat = Dat.load("experiments/exp1")
print(dat.get_spec()["params"]["lr"])   # 0.01

# Fork a template and run the fork: the arguments go into the new
# dat's spec, and the run reads them back from there.
result = Dat.manager.run("catalog.experiment", epochs=200)
```

## Where to read next

| | |
| --- | --- |
| **[Tutorials](tutorials.md)** | Learn the library by running it: ten notebooks with their outputs kept |
| **[How-to](how-to.md)** | One task per row, for a reader who knows the library |
| **[Architecture](DAT%20Architecture.md)** | The dat and the ledger, how they meet, a module page for each |
| **[API Reference](api/index.md)** | Every public class and function, generated from the source |
