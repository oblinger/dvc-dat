import os
import pandas as pd
from typing import List, Dict, Any, Union, Iterable, Optional, Callable

# from do.hello.cube_examples.cube_hello_inst import Alignment
from dat.inst import Inst, InstContainer
from dat.do import do


Points = List[Dict[str, Any]]

SOURCE = "source"
METRICS = "metrics"
TITLE = "title"

INDICIES = "indicies"   # Temp key used to store the indicies in cube points


# TODO:
# - Add basic readme
# - Implement the 'merge_keys' method
# - Implement the 'get_csv' method
# - Support inst 'Cube' section that build data cube and cube reports
# - Support cube of cubes with cached points in sub cubes


class Cube(object):
    """
    A data-cube is a multidimensional data-structure that organizes
    information according to a defined set of axes.  The Cube class encodes a data-cube
    as a list of data points that are each encoded as a dict. The dict's key-value pairs
    indicate both and the indicies of each point within the data cube as well as data
    values contained in those locations.

    The cube's points are computed by calling all "do_fns" that are defined at the
    moment each inst is added to the cube.  Each do_fn returns a list of points that
    are added to the cube.

    API
    Cube(points=, axes=, do_fns=, insts=)   ....  Constructor
      .add_insts  ......  Adds insts to the cube and computes point
      .add_do_fns  .....  Adds do_fns to the cube
      .points  .........  An editable list of dict points representing cube data
      .point_fns  ......  An editable list of dat fns that are applied to added Insts
      .get_df  .........  Cube points expressed as a Pandas DataFrame
      .get_excel  ......  Writes cube as an Excel file
      .get_csv  ........  Writes cube as a CSV file

      cube1 + cube2.....  Calls __add__ to combine points from two cubes.

    DO FNs:
    Point functions are invoked on each Inst as they are added to the cube, the results
    are added to the Cube's points. These do fns may return:
    - a scalar value (string, integer, or float) in which case a dict is created with
      the name of the point_fn as the key and the scalar value as the value.
    - a dict, which is added to the cube as a data point.
    - a list of dicts, which are all added to the cube as a points.
    ==> Index keys are added to each dict to indicate which inst it came from.
    """

    def __init__(self, *, points: Points = None,
                 insts: Union[List, str, Inst] = None,
                 point_fns: List = None):
        # JUAN: most times the points list past is a freshly constructed list.
        # is it acceptable that we dat not copy this list when accepting it?
        # if so, then a deep copy?
        self.insts: List[Inst] = []
        self.point_fns: List[Callable[[Inst], Points]] = []
        self.points: Points = list(points) if points else []
        if point_fns:
            self.add_point_fns(point_fns)
        if insts:
            self.add_insts(insts)

    def __str__(self):
        return f"Cube({self.get_inst().name!r}, {len(self.points)} points)"

    def __repr__(self):
        result = f"+---- Cube({self.get_inst().name!r}, {len(self.insts)} insts, " + \
                 f"{len(self.points)} points, {len(self.point_fns)} do_fns) ----\n"
        for point in self.points:
            items = [f"{k}={v!r}" for k, v in point.items()]
            result += f"| {', '.join(items)}\n"
        return result + "+------------------------------------"

    def __add__(self, other: 'Cube') -> 'Cube':
        """Add the points of two cubes together.

        Adds the points from the second cube onto those of the first cube,
        and retains the dat functions of the first cube."""
        return Cube(points=self.points + other.points, point_fns=self.point_fns)

    def add_point_fns(self, do_fns: List[str]):
        """Adds a list of dat functions to the cube."""
        for do_name in do_fns:
            self.point_fns.append(do.load(do_name))

    def add_insts(self, source: Union[Inst, str, Iterable]) -> None:
        """Recursively scans 'source' adding points derived from each Inst.

        If 'source' is:
        - an Iterable, it is scanned, and its elements are added.
        - a string, the result of 'Inst.load()' is added.
        - an InstContainer is elements are added.
        - an Inst, then results of all do_fns applied to it are added.
        """
        self._add_insts(source, 1, {})
        self._inject_indicies()

    def merge_keys(self, *, keys: List[str], into: str, using: str):
        pass

    # noinspection PyUnusedLocal
    def get_df(self, *,
               slices: Optional[List[str]] = None,
               rows: Optional[List[str]] = None,
               columns: Optional[List[str]] = None,
               values: Optional[List[str]] = None):
        """Returns contents of a cube as a pandas DataFrame.

        Parameters
        ----------
        slices: Optional[List[str]]
            Multiple DataFrames are constructed by partitioning points
            into unique combinations of values from these slice keys.
        rows: Optional[List[str]]
            If specified, these keys serve as the index or multi-index
        values: Optional[List[str]]
            If specified, these keys are merged into a single value
        columns: Optional[List[str]]
            If specified, these keys define the columns for the
            all unique
        """
        return pd.DataFrame(self.points)

    def get_excel(self, *, name: str = None, title: str = None,
                  verbose: bool = False,
                  show: bool = False, **kwargs):
        """Writes the cube to an Excel file.

        Uses the 'as_df' method to create a DataFrame, and then writes it.
        """
        path = self.insts[0].path if self.insts else os.getcwd()
        file_path = os.path.join(path, name or 'Report') + ".xlsx"
        df = self.get_df(**kwargs)

        # Write the dataframe to an Excel file
        with pd.ExcelWriter(file_path, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name=title or 'Sheet1', index=False)
        if show:
            os.system(f"open {file_path}")
        if verbose:
            print(repr(self))
            print(f"(Cube written to {file_path})")
        pass

    def get_csv(self):
        raise NotImplementedError

    def get_inst(self):
        """Returns the first Inst added to this Cube."""
        if not self.insts:
            raise Exception("No Insts have been added to this Cube")
        return self.insts[0]

    def _add_insts(self, source: Union[Inst, str, Iterable],
                   this_index: Union[int, str], indicies: Dict[str, str]) -> None:
        """Recursively scans 'source' adding points derived from each Inst."""
        if isinstance(source, InstContainer):
            self._add_insts(source.insts, source.name, indicies)
        elif isinstance(source, Inst):
            the_point, points = {}, []
            for fn in self.point_fns:
                output = fn(source)
                if isinstance(output, str) or isinstance(output, int) or \
                        isinstance(output, float) or isinstance(output, bool):
                    the_point[fn.__name__] = output   # Adding single scalar to point
                elif isinstance(output, Dict):
                    the_point.update(output)          # Adding many values to point
                elif isinstance(output, List):
                    points += output              # Adding many points to result
                else:
                    raise Exception(f"The point_fn, {fn}, must return a list of dict "
                        f"not {output!r}")
            if the_point:
                points.append(the_point)
            for point in points:
                sub_indicies = dict(indicies)
                sub_indicies[this_index] = source.shortname
                point[INDICIES] = sub_indicies
            self.points += points
            self.insts.append(source)
        elif isinstance(source, str):
            self._add_insts(Inst.load(source), this_index, indicies)
        elif isinstance(source, List):
            for element in source:
                self._add_insts(element, len(indicies)+1, indicies)
        else:
            raise Exception("Illegal inst source: {source!r}")

    def _inject_indicies(self) -> None:
        """Scans points to find all existing indicies and builds a safe renaming
            of these indicies to avoid index name collisions.  Then this renaming is
            used to destructively inject indicies into each point in the cube."""
        def rename_index(key: Union[int, str]) -> str:
            if key in renaming:
                return renaming[key]
            if key not in point_keys and isinstance(key, str):
                return key
            # "idx" used for unique unnamed indicies (encoded as ints)
            new_key = base = "idx" if isinstance(key, int) else key
            i = 2
            while new_key in point_keys:
                i += 1
                new_key = f"{base}{i}"
            renaming[key] = new_key
            return new_key

        point_keys, renaming = set(), {}
        for point in self.points:
            point_keys.update(point.keys())
        for point in self.points:
            for k, v in point[INDICIES].items():
                point[rename_index(k)] = v
            del point[INDICIES]


def metrics_matrix(spec: Inst, source: Inst = None, *,
                   metrics: List = None, title: str = None,
                   show: bool = False) -> None:
    """A dat script that runs the specified metrics over the specified "Insts".

    Parameters
    ----------
    spec: Inst
        Provides default parameters for the report.
    source: Union[Inst, str, Iterable]
        The source of 'Insts' to be analyzed.  (See Cube.add_insts.)
    metrics: List
        A list of functions that are applied to each Inst.
    title: str
        The title of the report.
    show: bool
        If True, the report is displayed in a window.
    """
    source = source or Inst.get(spec, SOURCE)
    metrics = metrics or Inst.get(spec, METRICS)
    title = title or Inst.get(spec, TITLE)
    cube = Cube(insts=source, point_fns=metrics)
    cube.get_excel(title=title, verbose=True, show=show)


# def align_pr(source: Inst, metric: Callable[[Alignment], Any]) \
#               -> Dict[str, float]:
#    """Scans all alignments from the given sources and returns precision-recall data"""
#     count, recall, precision = 0, 0, 0
#     if isinstance(source, InstContainer):
#         itr = source.insts
#     else:
#         itr = iter([source])
#     for inst in itr:
#         for align in inst.aligns:
#             count += 1
#             result = do(metric, align)
#             if result is not None:
#                 recall += 1
#                 if result is not False:
#                     precision += 1
#     return dict(
#         count=count,
#         recall=0 if count == 0 else recall/count,
#         precision=0 if recall == 0 else precision/recall,
#         f1=0 if recall == 0 else (precision*recall)/(precision+recall))


def example():

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

    # Assum'simple_df' has been created with the initial list of dictionaries as before

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
    example()
