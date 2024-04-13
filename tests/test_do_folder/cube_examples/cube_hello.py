

"""
Cube Hello defines a couple of metrics and an execl table that reports on them.

Hello10 is a fake dataset of 10 "runs" created in the /tmp folder for this example.
Each run predicts a sequence of colored marbles, and the input dataset also has a
ground truth sequence of marbles. These metrics specify how accurately the system
predicted the ground truth marbles.

rpt .............. Generates an excel w/ all metrics run over all games from Hello10.
cube_hello ....... This is the 'main' cube metric, it's an alias for the F1 score.
cube_hello.p ..... Marble prediction precision.
cube_hello.r ..... Marble prediction recall.

CreateHello10 .... Creates the fake dataset of 10 runs in /tmp/hello10.

"""
from ml_dat.inst import Inst
# from synch.communication.models import ShotAnnotationsAlignment
# from do.reports.cube import align_pr

metrics = ["cube_hello", "cube_hello.p", "cube_hello.r", "rpt", "CreateHello10"]

descriptions = {
    "cube_hello": "This is the 'main' cube metric, it's an alias for the F1 score.",
    "cube_hello.p": "Marble prediction precision.",
    "cube_hello.r": "Marble prediction recall.",
    "rpt": "Generates an excel w/ all metrics run over all games from Hello10.",
    "CreateHello10": "Creates the fake dataset of 10 runs in /tmp/hello10.",
}


"""
Build an excel showing cube_hello metrics over the Hello10_runs.
"""
cube_hello = {
    "main": {"do": "cube.metrics_matrix"},
    "source": ["/tmp/Hello10_runs", "/tmp/Hello5_runs"],
    "metrics": ["cube_hello.is_prime", "cube_hello.data", "color_p"],
    "title": "The Hello Report",
}


def is_prime(inst: Inst):
    """Returns True if the run number is prime"""
    return int(inst.shortname) in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]


def data(inst: Inst):
    """Returns the data from the run."""
    return "-".join(map(str, Inst.get(inst.spec, "main.data")))



# def all(inst: Inst):
#     """Returns precision, recall, and F1 score over color prediction alignments."""
#     return align_pr(inst, color_match)
#
#
#
# def color_match(align: ShotAnnotationsAlignment):
#     """Returns: None if no marble found in ground truth, else
#                 True if the color prediction was correct, or
#                 False if the color prediction was incorrect."""
#     return None if align.gt_annotation is None else \
#         True if align.gt_annotation == align.ai_annotation else False
#
# class ColorMatchAligner(Aligner):
#     def measure(self, alignment: AlignmentEntry) -> PR_Result:
#         xxxx
#
#
# InstMetric = Callable[[Inst, Any]]
# SimpleInstMetric = Callable[[Inst, Union[float, int, str]]]
#
#
# color_p, color_r, color_f1 = ColorMatchAligner.precision_recall_fns()
#
#
# class Aligner:
#     @staticmethod
#     def precision_recall_fns(self) -> tuple[SimpleInstMetric, SimpleInstMetric, SimpleInstMetrc]:
#         return None
#
#     PR_Result = Enum()
#
#     @abstractmethod
#     def measure(self, al: AlignmentEntry) -> PR_Result: