from typing import Dict

from dvc_dat.dat import DatMethod


class Metric:
    all_metrics: Dict[str, 'Metric'] = {}
    name: str
    fn: DatMethod
    summary: str
    docs: str

    @staticmethod
    def get(spec: str):
        return Metric.all_metrics[spec]

    def __init__(self, name: str, *, fn: DatMethod, summary: str = None,
                 docs: str = None):
        self.name = name
        self.fn = fn
        self.summary = summary
        self.docs = docs
        Metric.all_metrics[name] = self

    def get_dat_method(self):
        return self.fn
