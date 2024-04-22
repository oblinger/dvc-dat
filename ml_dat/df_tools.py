import os
from typing import Union, Iterable, Dict, List, Any, Callable, Hashable, Tuple

from pandas import DataFrame, ExcelWriter
from ml_dat import Inst, InstContainer, load_inst, do

"""
Helper functions for creating data frames and manipulating data frames.

API
---
- from_inst(insts, point_fns)
- as_points(df)
- get_excel(df, path)
- Cube.from_df(df)
- Cube(insts, point_fns)
  .get_df()
  .points


"""


Points = List[Dict[str, Any]]
PointFn = Callable[[Inst], Any]
_INDICIES = "indicies"   # Temp key used to store the indicies in cube points

SOURCE = "source"
METRICS = "metrics"
TITLE = "title"


def cmd_list(prefix: str = ""):
    for k, v in do.module_index.items():
        if prefix not in k:
            continue
        elif isinstance(v, str):
            l = len(os.path.commonpath([v, do.do_folder]))
            print(f"  {k:25} -->   .../{v[l+1:]}")
        else:
            print(f"  {k:25} --> {v}")


do.register_value("dt.list", cmd_list)


def from_inst(source: Union[Inst, str, Iterable],
              point_fns: Any) -> DataFrame:
    """Creates a DataFrame from one or more Insts and a list of point_fns."""
    cube = Cube(insts=source, point_fns=point_fns)
    df = cube.get_df()
    return df


def get_excel(df: DataFrame, *,
              folder: str = None,
              docs: List[str] = None,
              sheets: List[str] = None,
              title: str = None,
              verbose: bool = True,
              show: bool = False):
    """
    Splits a pandas DataFrame into multiple DataFrames based on the values of their
    columns.  The first set of columns split the DataFrame into slices, called
    sections which separate it into different Excel files.  Then a second set of
    columns are used to slice into separate sheets within each Excel file.
    """
    folder = folder or os.getcwd()
    if not docs:       # saves as a single excel file
        path = os.path.join(folder, f'{title or "output"}.xlsx')
        _create_sheets(path, df, "Sheet1", sheets, verbose, show)
        return path
    else:   # Splits the dataframe into multiple Excel files
        section_values: Tuple
        for section_values, section_df in df.groupby(docs):
            # section_values = [section_values] if isinstance(section_values, str) \
            #     else list(section_values)
            section_path = (title + " " if title else "") + '-'.join(section_values)
            section_path = os.path.join(folder, section_path + ".xlsx")
            _create_sheets(section_path, section_df, "Sheet1", sheets, verbose, show)
        return folder


def _create_sheets(path, df, sheet_prefix, sheets, verbose, show):
    with ExcelWriter(path, engine='xlsxwriter') as writer:
        if not sheets:
            df.to_excel(writer, sheet_name='Sheet1', index=False)
        else:
            for sheet_values, sheet_df in df.groupby(sheets):
                sheet_values = [sheet_values] if isinstance(sheet_values,
                                                            str) else list(sheet_values)
                sheet_title = '-'.join(sheet_values)
                sheet_df.to_excel(writer, sheet_name=sheet_title, index=False)
    if verbose:
        # print(repr(df))
        print(f"# Dataframe written to {path}")
    if show:
        os.system(f'open "{path}" &')


def metrics_matrix(spec: Inst, source: Inst = None, *,
               metrics: List = None, title: str = None,
               show: bool = False) -> DataFrame:
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
    df = Cube(insts=source, point_fns=metrics).get_df()
    get_excel(df, title=title, verbose=True, show=show)
    return df


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
    def from_df(df: DataFrame):
        return Cube(points=df.to_dict(orient='records'))

    def __init__(self, *, points: List[Points] = None,
                 insts: Union[Inst, str, Iterable] = None,
                 point_fns: List[Union[str, PointFn]] = None):
        from . import do
        self.points: Points = list(points) if points else []
        self.point_fns: List[Callable[[Inst], Any]] = []
        for fn_spec in point_fns or []:
            fn = do.load(fn_spec) if isinstance(fn_spec, str) else fn_spec
            self.point_fns.append(fn)
        if insts:
            self._add_insts(insts, 1, {})
            self._inject_indicies()

    def __str__(self):
        return f"Cube({len(self.points)} points)"

    def __repr__(self):
        result = f"+---- Cube" + \
                 f"{len(self.points)} points, {len(self.point_fns)} do_fns) ----\n"
        for point in self.points:
            items = [f"{k}={v!r}" for k, v in point.items()]
            result += f"| {', '.join(items)}\n"
        return result + "+------------------------------------"

    def get_df(self) -> DataFrame:
        """Returns the cube as a Pandas DataFrame."""
        return DataFrame(self.points)

    def _add_insts(self, source: Union[Inst, str, Iterable],
                   this_index: Union[int, str], indicies: Dict[str, str]) -> None:
        """Recursively scans 'source' adding points derived from each md.Inst."""
        if isinstance(source, InstContainer):
            self._add_insts(source.insts, source.name, indicies)
        elif isinstance(source, Inst):
            the_point, points = {}, []
            for fn in self.point_fns:
                output = fn(source)
                if isinstance(output, str) or isinstance(output, int) or \
                        isinstance(output, float) or isinstance(output, bool):
                    the_point[fn.__name__] = output  # Adding single scalar to point
                elif isinstance(output, Dict):
                    the_point.update(output)  # Adding many values to point
                elif isinstance(output, List):
                    points += output  # Adding many points to result
                else:
                    raise Exception(
                        f"The point_fn, {fn}, must return a list of dict "
                        f"not {output!r}")
            if the_point:
                points.append(the_point)
            for point in points:
                sub_indicies = dict(indicies)
                sub_indicies[this_index] = source.shortname
                point[_INDICIES] = sub_indicies
            self.points += points
        elif isinstance(source, str):
            self._add_insts(load_inst(source), this_index, indicies)
        elif isinstance(source, List):
            for element in source:
                self._add_insts(element, len(indicies) + 1, indicies)
        else:
            raise Exception(f"Illegal inst source: {source!r}")

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
            for k, v in point[_INDICIES].items():
                point[rename_index(k)] = v
            del point[_INDICIES]

    #
    # # noinspection PyUnusedLocal
    # def get_df(self, *,
    #            slices: Optional[List[str]] = None,
    #            rows: Optional[List[str]] = None,
    #            columns: Optional[List[str]] = None,
    #            values: Optional[List[str]] = None):
    #     """Returns contents of a cube as a pandas DataFrame.
    #
    #     Parameters
    #     ----------
    #     slices: Optional[List[str]]
    #         Multiple DataFrames are constructed by partitioning points
    #         into unique combinations of values from these slice keys.
    #     rows: Optional[List[str]]
    #         If specified, these keys serve as the index or multi-index
    #     values: Optional[List[str]]
    #         If specified, these keys are merged into a single value
    #     columns: Optional[List[str]]
    #         If specified, these keys define the columns for the
    #         all unique
    #     """
    #     return DataFrame(self.points)
    #
    # def get_excel(self, *, name: str = None, title: str = None,
    #               verbose: bool = False,
    #               show: bool = False, **kwargs):
    #     """Writes the cube to an Excel file.
    #
    #     Uses the 'as_df' method to create a DataFrame, and then writes it.
    #     """
    #     path = self.insts[0].path if self.insts else os.getcwd()
    #     file_path = os.path.join(path, name or 'Report') + ".xlsx"
    #     df = self.get_df(**kwargs)
    #
    #     # Write the dataframe to an Excel file
    #     with ExcelWriter(file_path, engine='xlsxwriter') as writer:
    #         df.to_excel(writer, sheet_name=title or 'Sheet1', index=False)
    #     pass
