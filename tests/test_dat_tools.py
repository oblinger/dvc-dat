import os
import subprocess
import sys
from pandas import DataFrame
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from dvc_dat import do
from dvc_dat import Dat
from dvc_dat.dat_tools import to_excel, Cube, from_dat
# do.register_module("test_dat_tools", "tests.test_dat_tools")
do.mount(at="test_dat_tools", module="tests.test_dat_tools")

TMP_PATH = "/tmp/job_test"
TMP_PATH2 = "/tmp/job_test2"


def run_capture(line: str) -> str:
    result = subprocess.run(line, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()


@pytest.fixture
def spec1():
    return {
        "dat": {"my_key1": "my_val1", "my_key2": "my_val2"}
    }


@pytest.fixture
def dat1(spec1):
    return Dat.create(spec=spec1, path=TMP_PATH, overwrite=True)


@pytest.fixture
def spec2():
    return {"dat": {"my_key1": "my_val1", "my_key2": "my_val2"}, "other": "key_value"}


@pytest.fixture
def dat2(spec2):
    return Dat.create(spec=spec2, path=TMP_PATH2, overwrite=True)


def always_17(_dat: Dat):
    return 17


def always_18(_dat: Dat):
    return 18


sales_data_points = [
    {'Store': 'Store A', 'Month': 'January', 'Product': 'Product 1',
     'Metric': 'Units Sold', 'Value': 8},
    {'Store': 'Store A', 'Month': 'January', 'Product': 'Product 1',
     'Metric': 'Revenue', 'Value': 23},
    {'Store': 'Store A', 'Month': 'January', 'Product': 'Product 2',
     'Metric': 'Units Sold', 'Value': 80},
    {'Store': 'Store A', 'Month': 'January', 'Product': 'Product 2',
     'Metric': 'Revenue', 'Value': 88},
    {'Store': 'Store A', 'Month': 'February', 'Product': 'Product 1',
     'Metric': 'Units Sold', 'Value': 76},
    {'Store': 'Store A', 'Month': 'February', 'Product': 'Product 1',
     'Metric': 'Revenue', 'Value': 18},
    {'Store': 'Store A', 'Month': 'February', 'Product': 'Product 2',
     'Metric': 'Units Sold', 'Value': 54},
    {'Store': 'Store A', 'Month': 'February', 'Product': 'Product 2',
     'Metric': 'Revenue', 'Value': 98},
    {'Store': 'Store B', 'Month': 'January', 'Product': 'Product 1',
     'Metric': 'Units Sold', 'Value': 51},
    {'Store': 'Store B', 'Month': 'January', 'Product': 'Product 1',
     'Metric': 'Revenue', 'Value': 25},
    {'Store': 'Store B', 'Month': 'January', 'Product': 'Product 2',
     'Metric': 'Units Sold', 'Value': 85},
    {'Store': 'Store B', 'Month': 'January', 'Product': 'Product 2',
     'Metric': 'Revenue', 'Value': 31},
    {'Store': 'Store B', 'Month': 'February', 'Product': 'Product 1',
     'Metric': 'Units Sold', 'Value': 95},
    {'Store': 'Store B', 'Month': 'February', 'Product': 'Product 1',
     'Metric': 'Revenue', 'Value': 82},
    {'Store': 'Store B', 'Month': 'February', 'Product': 'Product 2',
     'Metric': 'Units Sold', 'Value': 55},
    {'Store': 'Store B', 'Month': 'February', 'Product': 'Product 2',
     'Metric': 'Revenue', 'Value': 4},
]


@pytest.fixture
def df_sales():
    return DataFrame(sales_data_points)


class TestDoIsWorking:
    def test_load_do(self):
        assert isinstance(do("cube_hello", show=False), DataFrame)


class TestCube:
    def test_null_create(self):
        assert Cube(), "Couldn't create Cube"

    def test_add_do_fn(self):
        cube = Cube(point_fns=[always_17], dats=[])
        return cube

    def test_add_dat(self, dat1, dat2):
        cube = Cube(dats=[dat1, dat2], point_fns=[always_17])
        pts = [{'always_17': 17, 'list': 'job_test'},
               {'always_17': 17, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Dat to Cube"

    def test_do_style_registered_module_fn(self, dat1):
        do.mount(at="registered_cube",
                 module="test_mounted_folder.dat_tools_examples.cube_hello")
        cube = Cube(point_fns=["registered_cube.always_5"], dats=[dat1])
        assert cube.points == [{'always_5': 5, 'list': 'job_test'}]

    def test_do_style_point_fns(self, dat1, dat2):
        cube = Cube(dats=[dat1, dat2],
                    point_fns=["cube_hello.always_4", "registered_cube.always_5"])
        pts = [{'always_4': 4, 'always_5': 5,  'list': 'job_test'},
               {'always_4': 4, 'always_5': 5, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Dat to Cube"

    def test_multi_value_point_fns(self, dat1):
        fns = [always_17, lambda dat: {"val1": 111, "val2": 2222}]
        cube = Cube(dats=[dat1], point_fns=fns)
        assert cube.points == [{'val1': 111, 'val2': 2222,
                                'always_17': 17, 'list': 'job_test'}]

    def test_multi_point_point_fns(self, dat1):
        fns = [always_17, always_18, lambda dat: [{"val1": 1, "val2": 2}, {"val3": 3}]]
        cube = Cube(dats=[dat1], point_fns=fns)
        assert cube.points == [
            {'list': 'job_test', 'val1': 1, 'val2': 2},
            {'list': 'job_test', 'val3': 3},
            {'always_17': 17, 'always_18': 18, 'list': 'job_test'}]


class TestFromDat:
    def test_null_df_create(self):
        assert isinstance(from_dat([], []), DataFrame), \
            "Couldn't create from df_tools"

    def test_from_dat(self, dat1, dat2):
        df = from_dat([dat1, dat2],
                      [always_17, "test_dat_tools.always_18"])
        assert df.to_dict() == {
            'always_17': {0: 17, 1: 17},
            'always_18': {0: 18, 1: 18},
            'list': {0: 'job_test', 1: 'job_test2'}}
        assert Cube.from_df(df).points == [
            {'always_17': 17, 'always_18': 18, 'list': 'job_test'},
            {'always_17': 17, 'always_18': 18, 'list': 'job_test2'}
        ]


class TestGetExcel:
    def test_get_excel(self, df_sales):
        path = to_excel(df_sales, title="test1", show=False)
        assert os.path.exists(path), "Couldn't create excel file"

    def test_sheet_splitting(self, df_sales):
        to_excel(df_sales, title="test2", sheets=["Store"], show=False)
        assert True

    def test_complex_sheet_splitting(self, df_sales):
        to_excel(df_sales, title="test2", sheets=["Store", "Month"], show=False)
        assert True

    def test_doc_splitting(self, df_sales):
        to_excel(df_sales, title="test2", docs=["Store"], show=False)
        assert True

    def test_complex_sheet_and_doc_splitting(self, df_sales):
        to_excel(df_sales, title="Test3",
                 docs=["Store"], sheets=["Month", "Product"], show=False)
        assert True


class TestMetricsMatrix:
    def test_dat_report(self, df_sales):
        df = do("rpt.simple")
        # print(df.shape)
        assert df.shape == (48, 6), "Couldn't create metrics matrix"

    def test_default_report(self, df_sales):
        df = do("rpt")
        print(df.shape)
        assert df.shape == (48, 6), "Couldn't create metrics matrix"

    def test_my_test(self, df_sales):
        df = do("rpt.my_test")
        print(df.shape)
        assert df.shape == (16, 6), "Couldn't create metrics matrix"

    def test_fully_manual(self, df_sales):
        df = do("rpt.fully_manual")
        print(df.shape)
        assert df.shape == (48, 6), "Couldn't create metrics matrix"


class TestCommands:
    def test_dt_list(self):
        text = run_capture("./do dt.list")
        size = len(text.split("\n"))
        assert size > 5, f"Couldn't list do modules.  Only found {size} lines."


class TestCleanup:
    def test_cleanup(self):
        os.system("rm *.xlsx")  # remove all excel files
        os.system("rm -r test_sync_folder/anonymous")  # remove all anon dats
        Dat.load("simple_report").delete()
        Dat.load("dat_report").delete()

#


if __name__ == "__main__":
    pytest.main([__file__])
    # TestDoIsWorking().test_load_do()
    # TestMetricsMatrix().test_default_report(DataFrame(sales_data_points))
