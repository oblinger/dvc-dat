import os
import pandas as pd
from typing import List, Dict, Any, Union, Iterable, Optional, Callable


# from do.hello.cube_examples.cube_hello_inst import Alignment
import ml_dat as md


Points = List[Dict[str, Any]]
PointFn = Callable[[md.Inst], Any]

SOURCE = "source"
METRICS = "metrics"
TITLE = "title"

INDICIES = "indicies"   # Temp key used to store the indicies in cube points


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
      .add_insts ....... Adds insts to the cube and computes point
      .add_point_fns ... Adds do_fns to the cube
      .points .......... An editable list of dict points representing cube data
      .point_fns ....... An editable list of dat fns that are applied to added Insts
      .get_df .......... Cube points expressed as a Pandas DataFrame
      .get_excel ....... Writes cube as an Excel file
      .get_csv ......... Writes cube as a CSV file

      cube1 + cube2 .... Calls __add__ to combine points from two cubes.

    DO FNs:
    Point functions are invoked on each Inst as they are added to the cube, the results
    are added to the Cube's points. These do fns may return:
    - a scalar value (string, integer, or float) in which case a dict is created with
      the name of the point_fn as the key and the scalar value as the value.
    - a dict, which is added to the cube as a data point.
    - a list of dicts, which are all added to the cube as a points.
    ==> Index keys are added to each dict to indicate which inst it came from.
    """

    @staticmethod
    def build(*, insts: Union[md.Inst, str, Iterable],
              point_fns: List[Union[str, PointFn]]) -> 'Cube':
        cube = Cube()
        cube.add_point_fns(point_fns)
        # cube.add_insts(insts)
        cube._add_insts(insts, 1, {})
        cube._inject_indicies()
        return cube

    def __init__(self, *, points: Points = None):
        self.insts: List[md.Inst] = []
        self.point_fns: List[Callable[[md.Inst], Points]] = []
        self.points: Points = list(points) if points else []

    def __str__(self):
        name = self.insts[0].name if self.insts else "No Insts"
        return f"Cube({name!r}, {len(self.points)} points)"

    def __repr__(self):
        name = self.insts[0].name if self.insts else "No Insts"
        result = f"+---- Cube({name!r}, {len(self.insts)} insts, " + \
            f"{len(self.points)} points, {len(self.point_fns)} do_fns) ----\n"
        for point in self.points:
            items = [f"{k}={v!r}" for k, v in point.items()]
            result += f"| {', '.join(items)}\n"
        return result + "+------------------------------------"

    def __add__(self, other: 'Cube') -> 'Cube':
        """Add the points of two cubes together.

        Adds the points from the second cube onto those of the first cube,
        and retains the dat functions of the first cube."""
        return Cube(points=self.points + other.points)

    def add_point_fns(self, point_fns: List[Union[str, PointFn]]):
        """Adds a list of dat functions to the cube."""
        for fn_spec in point_fns:
            fn = md.do.load(fn_spec) if isinstance(fn_spec, str) else fn_spec
            self.point_fns.append(fn)

    def add_insts(self, source: Union[md.Inst, str, Iterable]) -> None:
        """Recursively scans the provided 'source' adding points derived from each Inst.

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

    # def get_inst(self):
    #     """Returns the first Inst added to this Cube."""
    #     return self.insts[0] if self.insts else None

    def _add_insts(self, source: Union[md.Inst, str, Iterable],
                   this_index: Union[int, str], indicies: Dict[str, str]) -> None:
        """Recursively scans 'source' adding points derived from each md.Inst."""
        if isinstance(source, md.InstContainer):
            self._add_insts(source.insts, source.name, indicies)
        elif isinstance(source, md.Inst):
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
            self._add_insts(md.Inst.load(source), this_index, indicies)
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
            # "list" used for unique unnamed indicies (encoded as ints)
            new_key = base = "list" if isinstance(key, int) else key
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


class DataFrames(object):
    """A class of helper methods for working with Pandas DataFrames."""

    @staticmethod
    def get_excel(df: pd.DataFrame, *,
                  sections: List[str] = None,
                  sheets: List[str] = None,
                  title: str = None,
                  _verbose: bool = False,
                  _show: bool = False):
        """
        Split a pandas DataFrame into multiple DataFrames based on the values of their
        columns.  The first set of columns split the DataFrame into slices, called
        sections which separate it into different Excel files.  Then a second set of
        columns are used to slice into separate sheets within each Excel file.
        """

        # If no sections or sheets are provided, save as a single sheet
        if not sections and not sheets:
            with pd.ExcelWriter(f'{title or "output"}.xlsx') as writer:
                df.to_excel(writer, index=False)
            return

        # If sections are provided, split the dataframe into multiple Excel files
        if sections:
            for section_values, section_df in df.groupby(sections):
                section_values = [section_values] if isinstance(section_values, str) \
                    else list(section_values)
                section_title = '-'.join(section_values)
                with pd.ExcelWriter(f'{section_title}.xlsx') as writer:
                    if sheets:
                        DataFrames._create_sheets(writer, section_df, sheets)
                    else:
                        section_df.to_excel(writer, index=False)
        # If only sheets, split into multiple sheets in a single Excel file
        elif sheets:
            with pd.ExcelWriter(f'{title or "output"}.xlsx') as writer:
                DataFrames._create_sheets(writer, df, sheets)

    @staticmethod
    def _create_sheets(writer, df, sheets):
        for sheet_values, sheet_df in df.groupby(sheets):
            sheet_values = [sheet_values] if isinstance(sheet_values,
                                                        str) else list(sheet_values)
            sheet_title = '-'.join(sheet_values)
            sheet_df.to_excel(writer, sheet_name=sheet_title, index=False)


def metrics_matrix(spec: md.Inst, source: md.Inst = None, *,
                   metrics: List = None, title: str = None,
                   show: bool = False) -> Cube:
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
    source = source or md.Inst.get(spec, SOURCE)
    metrics = metrics or md.Inst.get(spec, METRICS)
    title = title or md.Inst.get(spec, TITLE)
    cube = Cube.build(insts=source, point_fns=metrics)
    cube.get_excel(title=title, verbose=True, show=show)
    return cube


import ml_dat
ml_dat.Cube = Cube
