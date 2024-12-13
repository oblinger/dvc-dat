
NO_DAT_DVC_INIT = True

from dvc_dat import dat_tools as dt, Dat
from examples.simple.metrics import Metric


RUNSET = "Datasets/Retail Data"
METRICS = ["test.hello", "test.ds name", "test.name len"]


def snap():
    metrics = [Metric.get(m).get_dat_method() for m in METRICS]
    df = dt.from_dat(RUNSET, metrics)
    dt.to_excel(df, title="Metrics", columns=METRICS, transpose=True, show=True,
                prepend=True, average=True, median=True, std=False, quantiles=None)


def world(_dat: Dat):
    return "World!"


def tail(dat: Dat):
    return dat.get_path_tail()


def tail_len(dat: Dat):
    return len(dat.get_path())


Metric("test.hello", fn=world)
Metric("test.ds name", fn=tail)
Metric("test.name len", fn=tail_len)


if __name__ == "__main__":
    snap()
