"""`svp.etl.dat`: a `Dat` as a `Value`, and the dat constructor.

`dat(spec, **kwargs)` (SVP447 Values idea 10) makes a dat from its
spec and runs the spec's `main` with the remaining arguments. Its
preds merge spec keys and result metrics under one namespace (idea
12): `game`, `stage`, `bins` from the spec, `metrics.<m>` from the
result.
"""
import importlib
import tempfile
from pathlib import Path

import yaml

from dvc_dat.ledger import Dat, attr, ledger_class, ledger_fn

SPEC_PREDS = ("game", "stage", "bins")
METRICS = ("count", "score")


@ledger_class(preds=SPEC_PREDS + ("gameset",)
              + tuple(f"metrics.{m}" for m in METRICS))
class StageDat(Dat):
    """One stage's dat: `_spec_.yaml`, `_result_.yaml`, its files."""

    @property
    def spec(self) -> dict:
        return yaml.safe_load((self.path / "_spec_.yaml").read_text())

    @property
    def result(self) -> dict:
        text = (self.path / "_result_.yaml").read_text()
        return yaml.safe_load(text)


def build(rev, spec: dict, **kwargs) -> StageDat:
    """Make a dat from its spec and run it: the constructor's body."""
    module, name = spec["main"].rsplit(".", 1)
    main = getattr(importlib.import_module(module), name)
    folder = Path(tempfile.mkdtemp(prefix=f"{spec['stage']}-"))
    args = {k: v for k, v in spec.items() if k != "main"}
    result = main(rev, folder, **args, **kwargs)
    (folder / "_spec_.yaml").write_text(yaml.safe_dump(spec))
    (folder / "_result_.yaml").write_text(yaml.safe_dump(result))
    d = StageDat(folder)
    d.preds.update({k: spec[k] for k in SPEC_PREDS if k in spec})
    for m in METRICS:
        d.preds[f"metrics.{m}"] = attr(result, f"metrics.{m}")
    return d


@ledger_fn
def dat(rev, *, spec: dict, **kwargs) -> StageDat:
    """The dat constructor: the spec first, then what `main` takes."""
    return build(rev, spec, **kwargs)
