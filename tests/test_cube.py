import os
import sys
import pandas as pd
import pytest

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from ml_dat import do, Cube
from ml_dat import Inst


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


class TestDoHello:
    def test_load_do(self):
        assert do("cube_hello", show=False)
        pass


class TestCreate:
    def test_null_create(self):
        assert Cube(), "Couldn't create Persistable"

    def test_add_do_fn(self):
        cube = Cube.build(point_fns=[always_17], insts=[])
        return cube

    def test_add_inst(self, inst1, inst2):
        cube = Cube.build(insts=[inst1, inst2], point_fns=[always_17])
        pts = [{'always_17': 17, 'list': 'job_test'},
               {'always_17': 17, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Inst to Cube"

    def test_do_style_registered_module_fn(self, inst1):
        do.register_module("registered_cube", "test_do_folder.cube_examples.cube_hello")
        cube = Cube.build(point_fns=["registered_cube.always_5"], insts=[inst1])
        assert cube.points == [{'always_5': 5, 'list': 'job_test'}]

    def test_do_style_point_fns(self, inst1, inst2):
        cube = Cube.build(insts=[inst1, inst2],
                        point_fns=["cube_hello.always_4", "registered_cube.always_5"])
        pts = [{'always_4': 4, 'always_5': 5,  'list': 'job_test'},
               {'always_4': 4, 'always_5': 5, 'list': 'job_test2'}]
        assert cube.points == pts, "Couldn't add Inst to Cube"

    def test_multi_value_point_fns(self, inst1):
        cube = Cube()
        cube.add_point_fns([lambda inst: {"val1": 111, "val2": 2222}])
        cube.add_point_fns([always_17])
        cube.add_insts([inst1])
        assert cube.points == [{'val1': 111, 'val2': 2222,
                                'always_17': 17, 'list': 'job_test'}]

    def test_multi_point_point_fns(self, inst1):
        def always_18(_inst: Inst):
            return 18
        cube = Cube()
        cube.add_point_fns([lambda inst: [{"val1": 1, "val2": 2}, {"val3": 3}]])
        cube.add_point_fns([always_17, always_18])
        cube.add_insts([inst1])
        assert cube.points == [
            {'list': 'job_test', 'val1': 1, 'val2': 2},
            {'list': 'job_test', 'val3': 3},
            {'always_17': 17, 'always_18': 18, 'list': 'job_test'}]


class Example:


    def example(self):   # noqa
        # Data encoded as a list of dictionaries with simple keys
        simple_data_dicts = [
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

        # Convert the list of dictionaries to a DataFrame
        simple_df = pd.DataFrame(simple_data_dicts)

        # # Pivot the DataFrame to create multi-level index and columns
        # pivoted_df = simple_df.pivot_table(index=['Store', 'Month'],
        #                                    columns=['Product', 'Metric'],
        #                                    values='Value')

        # Assume 'simple_df' has been created with the initial list of dicts as before

        simple_df2 = pd.DataFrame(simple_df)
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
    # import test_do_folder.cube_examples.cube_hello_inst as cube_hello_inst
    # cube_hello_inst.build_hello_insts()
    # TestDoHello().test_load_do()
    pytest.main([__file__])
