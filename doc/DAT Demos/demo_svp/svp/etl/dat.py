"""`svp.etl.dat`: a `Dat` as a `Value`, and the dat constructor.

`dat(spec, work, **kwargs)` (SVP447 Values idea 10) builds a dat in
the folder the eval hands it (F447 Q36, lean A) and runs the spec's
`main` there. Its preds merge spec keys and result metrics under one
namespace: `game`, `stage`, `bins` from the spec, `metrics.<m>` from
the result. `main` is imported by the spec's key at run time, so the
one `fn` trace item hashes the modules the run loaded (Q37, lean A).
"""
import importlib
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


def build(rev, spec: dict, work: Path, **kwargs) -> StageDat:
    """Build a dat from its spec in `work`: the constructor's body."""
    module, name = spec["main"].rsplit(".", 1)
    main = getattr(importlib.import_module(module), name)
    args = {k: v for k, v in spec.items() if k != "main"}
    result = main(rev, work, **args, **kwargs)
    (work / "_spec_.yaml").write_text(yaml.safe_dump(spec))
    (work / "_result_.yaml").write_text(yaml.safe_dump(result))
    d = StageDat(work)
    d.preds.update({k: spec[k] for k in SPEC_PREDS if k in spec})
    for m in METRICS:
        d.preds[f"metrics.{m}"] = attr(result, f"metrics.{m}")
    return d


@ledger_fn
def dat(rev, *, spec: dict, work: Path, **kwargs) -> StageDat:
    """The dat constructor: `spec` the question, `work` the folder."""
    return build(rev, spec, work, **kwargs)
