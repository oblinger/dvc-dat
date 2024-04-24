import os
import sys
from pandas import DataFrame
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from ml_dat import do
from ml_dat import Inst
from ml_dat.dat_tools import get_excel, Cube, from_inst

if not do.get_base_object("test_df_tools"):  # Module might repeatedly load
    do.register_module("test_df_tools", "tests.test_df_tools")

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


def always_17(_inst: Inst):
    return 17


def always_18(_inst: Inst):
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
        cube = Cube(point_fns=[always_17], insts=[])
        return cube

    def test_add_inst(self, inst1, inst2):
        cube = Cube(insts=[inst1, inst2], point_fns=[always_17])
        pts = [{'always_17': 17, 'list': 'job_test'},
               {'always_17': 17, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Inst to Cube"

    def test_do_style_registered_module_fn(self, inst1):
        do.register_module("registered_cube",
                           "test_do_folder.df_tools_examples.cube_hello")
        cube = Cube(point_fns=["registered_cube.always_5"], insts=[inst1])
        assert cube.points == [{'always_5': 5, 'list': 'job_test'}]

    def test_do_style_point_fns(self, inst1, inst2):
        cube = Cube(insts=[inst1, inst2],
                    point_fns=["cube_hello.always_4", "registered_cube.always_5"])
        pts = [{'always_4': 4, 'always_5': 5,  'list': 'job_test'},
               {'always_4': 4, 'always_5': 5, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Inst to Cube"

    def test_multi_value_point_fns(self, inst1):
        fns = [always_17, lambda inst: {"val1": 111, "val2": 2222}]
        cube = Cube(insts=[inst1], point_fns=fns)
        assert cube.points == [{'val1': 111, 'val2': 2222,
                                'always_17': 17, 'list': 'job_test'}]

    def test_multi_point_point_fns(self, inst1):
        fns = [always_17, always_18, lambda inst: [{"val1": 1, "val2": 2}, {"val3": 3}]]
        cube = Cube(insts=[inst1], point_fns=fns)
        assert cube.points == [
            {'list': 'job_test', 'val1': 1, 'val2': 2},
            {'list': 'job_test', 'val3': 3},
            {'always_17': 17, 'always_18': 18, 'list': 'job_test'}]


class TestFromInst:
    def test_null_df_create(self):
        assert isinstance(from_inst([], []), DataFrame), "Couldn't create from df_tools"

    def test_from_inst(self, inst1, inst2):
        df = from_inst([inst1, inst2], [always_17, "test_df_tools.always_18"])
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
        path = get_excel(df_sales, title="test1", show=False)
        assert os.path.exists(path), "Couldn't create excel file"

    def test_sheet_splitting(self, df_sales):
        get_excel(df_sales, title="test2", sheets=["Store"], show=False)
        assert True

    def test_complex_sheet_splitting(self, df_sales):
        get_excel(df_sales, title="test2", sheets=["Store", "Month"], show=False)
        assert True

    def test_doc_splitting(self, df_sales):
        get_excel(df_sales, title="test2", docs=["Store"], show=False)
        assert True

    def test_complex_sheet_and_doc_splitting(self, df_sales):
        get_excel(df_sales, title="Test3",
                  docs=["Store"], sheets=["Month", "Product"], show=False)
        assert True


class TestMetricsMatrix:
    def test_metrics_matrix(self, df_sales):
        df = do("rpt.simple")
        # print(df.shape)
        assert df.shape == (16, 6), "Couldn't create metrics matrix"

    def test_default_report(self, df_sales):
        df = do("rpt")
        print(df.shape)
        assert df.shape == (16, 6), "Couldn't create metrics matrix"

    def test_my_test(self, df_sales):
        df = do("rpt.my_test")
        print(df.shape)
        assert df.shape == (16, 6), "Couldn't create metrics matrix"


#


class Example:
    def example(self):   # noqa
        # Data encoded as a list of dictionaries with simple keys

        # Convert the list of dictionaries to a DataFrame
        simple_df = DataFrame(sales_data_points)

        # # Pivot the DataFrame to create multi-level index and columns
        # pivoted_df = simple_df.pivot_table(index=['Store', 'Month'],
        #                                    columns=['Product', 'Metric'],
        #                                    values='Value')

        # Assume 'simple_df' has been created with the initial list of dicts as before

        simple_df2 = DataFrame(simple_df)
        # Update the 'Month' column in 'simple_df' to 'Jan-Feb' for all entries
        simple_df2['Month'] = 'Jan-Feb'

        # Group by 'Store', 'Month', 'Product', and 'Metric', then sum the 'Value'
        aggregated_df = simple_df2.groupby(['Store', 'Month', 'Product', 'Metric'],
                                           as_index=False).sum()

        # Pivot the aggregated DataFrame to create multi-level index and columns
        merged_pivoted_df = aggregated_df.pivot_table(index=['Store', 'Month'],
                                                      columns=['Product', 'Metric'],
                                                      values='Value')

        # Display the pivoted DataFrame
        print(simple_df)

        # Display the pivoted DataFrame
        print(aggregated_df)

        # Display the pivoted DataFrame
        print(merged_pivoted_df)


if __name__ == "__main__":
    # pytest.main([__file__])
    # TestDoIsWorking().test_load_do()
    TestMetricsMatrix().test_default_report(DataFrame(sales_data_points))
