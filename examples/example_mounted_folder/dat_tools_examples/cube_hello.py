# noqa

"""
Cube Hello defines a couple of metrics and an execl table that reports on them.

Hello10 is a fake dataset of 10 "runs" created in the /tmp folder for this example.
Each run predicts a sequence of colored marbles, and the input dataset also has a
ground truth sequence of marbles. These metrics specify how accurately the system
predicted the ground truth marbles.

rpt .............. Generates an Excel w/ all metrics run over all games from Hello10.
cube_hello ....... This is the '__main__' cube metric, it's an alias for the F1 score.
cube_hello.p ..... Marble prediction precision.
cube_hello.r ..... Marble prediction recall.

CreateHello10 .... Creates the fake dataset of 10 runs in /tmp/hello10.

"""

from dvc_dat import Dat

metrics = ["cube_hello", "cube_hello.p", "cube_hello.r", "rpt", "CreateHello10"]

descriptions = {
    "cube_hello": "This is the '__main__' cube metric, it's an alias for the F1 score.",
    "cube_hello.p": "Marble prediction precision.",
    "cube_hello.r": "Marble prediction recall.",
    "rpt": "Generates an excel w/ all metrics run over all games from Hello10.",
    "CreateHello10": "Creates the fake dataset of 10 runs in /tmp/hello10.",
}


"""
Build an excel showing cube_hello metrics over the Hello10_runs.
"""
__main__ = {
    "dat": {
        "do": "dt.dat_report",
        "path": "dat_report",
        "path_overwrite": True
    },
    "source": ["runs.example.hello10", "runs.example.hello5"],
    "metrics": ["cube_hello.is_prime", "cube_hello.data", "cube_hello.color_p"],
    "title": "The Hello Report",
}


def is_prime(dat: Dat):
    """Returns True if the run number is prime"""
    return int(dat.get_path_tail()) in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]


def data(dat: Dat):
    """Returns the data from the run."""
    return "-".join(map(str, Dat.get(dat.get_spec(), "dat.data")))


def color_p(_dat: Dat):
    """Marble prediction precision."""
    return .4


def always_4(_dat: Dat):
    return 4


def always_5(_dat: Dat):
    return 5
