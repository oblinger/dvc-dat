import os
import random
from typing import List

from ml_dat import dat_config, InstContainer, Inst


class Annotation:
    time: float


class Alignment(object):
    gt: Annotation
    ai: Annotation
    code: Annotation

    @staticmethod
    def align(self, sequence1: List[Annotation], sequence2: List[Annotation]) \
            -> List[Annotation]:
        pass


class CubeHelloAnnotation(Annotation):
    color: str
    time: float


def build_hello_insts():
    build_hello_runs(5)
    build_hello_runs(10)


def build_hello_runs(num):
    path = f"{dat_config.inst_folder}/runs/example/hello{num}"
    os.system(f"rm -r {path}")
    c = InstContainer(path=path, spec={})
    c.save()
    for i in range(10):
        run = Inst(path=os.path.join(c._path, f"{i}"), spec={"main": {}})
        start = random.randint(0, 10)
        range_ = random.randint(0, 10)
        count = 10   # random.choice(20)
        data = [random.randint(0, range_) + start for _ in range(count)]
        run._spec["main"].update(dict(start=start, range=range_, count=count, data=data))
        run.save()


