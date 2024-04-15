import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from ml_dat.inst import Inst  # noqa: E402
from ml_dat.do import do
from ml_dat.cube import Cube
import ml_dat.inst as inst_module
from ml_dat.inst import MAIN_CLASS, Inst, InstContainer


TMP_PATH = "/tmp/job_test"
TMP_PATH2 = "/tmp/job_test2"


@pytest.fixture
def spec1():
    return {
        "main": {"my_key1": "my_val1", "my_key2": "my_val2"}
    }


@pytest.fixture
def inst1(spec1):
    return Inst(spec=spec1, path=TMP_PATH)


@pytest.fixture
def spec2():
    return {"main": {"my_key1": "my_val1", "my_key2": "my_val2"}, "other": "key_value"}


@pytest.fixture
def inst2(spec2):
    return Inst(spec=spec2, path=TMP_PATH2)



def always_17(inst: Inst):
    return 17


class TestDoHello:
    def test_load_do(self):
        assert do("cube_hello", show=False)
    pass


class TestCreate:
    def test_null_create(self):
        assert Cube(), "Couldn't create Persistable"

    def test_add_do_fn(self):
        cube = Cube()
        cube.add_point_fns([always_17])
        return cube

    def test_add_inst(self, inst1, inst2):
        cube = self.test_add_do_fn()
        cube.add_insts([inst1, inst2])
        pts = [{'always_17': 17, 'list': 'job_test'},
               {'always_17': 17, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Inst to Cube"

    def test_do_style_registered_module_fn(self, inst1):
        do.register_module("registered_cube", "test_do_folder.cube_examples.cube_hello")
        cube = Cube(point_fns=["registered_cube.always_5"], insts=[inst1])
        assert cube.points == [{'always_5': 5, 'list': 'job_test'}]

    def test_do_style_point_fns(self, inst1, inst2):
        cube = Cube()
        cube.add_point_fns(["cube_hello.always_4",
                            "registered_cube.always_5"])
        cube = self.test_add_do_fn()
        cube.add_insts([inst1, inst2])
        pts = [{'always_17': 17, 'list': 'job_test'},
               {'always_17': 17, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Inst to Cube"


    def test_multi_value_point_fns(self, inst1) :
        cube = Cube()
        cube.add_point_fns([lambda inst: {"val1": 111, "val2": 2222}])
        cube.add_point_fns([always_17])
        cube.add_insts([inst1])
        assert cube.points == [{'val1': 111, 'val2': 2222,
                                'always_17': 17, 'list': 'job_test'}]

    def test_multi_point_point_fns(self, inst1):
        def always_18(inst: Inst):
            return 18
        cube = Cube()
        cube.add_point_fns([lambda inst: [{"val1": 1, "val2": 2}, {"val3": 3}]])
        cube.add_point_fns([always_17, always_18])
        cube.add_insts([inst1])
        assert cube.points == [
            {'list': 'job_test', 'val1': 1, 'val2': 2},
            {'list': 'job_test', 'val3': 3},
            {'always_17': 17, 'always_18': 18, 'list': 'job_test'}]


if __name__ == "__main__":
    # import test_do_folder.cube_examples.cube_hello_inst as cube_hello_inst
    # cube_hello_inst.build_hello_insts()
    # TestDoHello().test_load_do()
    pytest.main([__file__])
