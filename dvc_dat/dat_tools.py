import os
from typing import Union, Iterable, Dict, List, Any, Callable, Tuple

import numpy as np
import pandas as pd
from pandas import DataFrame, ExcelWriter, Series
from dvc_dat import Dat, DatContainer

"""
Helper functions for creating data frames and manipulating data frames.

API
---
- from_dat(dats, point_fns)
- as_points(df)
- get_excel(df, path)
- Cube.from_df(df)
- Cube(dats, point_fns)
  .get_df()
  .points


"""


Points = List[Dict[str, Any]]
PointFn = Callable[[Dat], Any]
_INDICIES = "indicies"   # Temp key used to store the indicies in cube points

SOURCE = "source"
METRICS = "metrics"
TITLE = "title"
FOLDER = "folder"
DOCS = "docs"
SHEETS = "sheets"
VERBOSE = "verbose"
SHOW = "show"


def cmd_list(prefix: str = ""):
    """Lists all do names with a given prefix."""
    print(f"\nBase names matching: '{prefix}*'")
    for k in Dat.manager.do.keys():   # do.base_locations.items():
        v = Dat.manager.do.load(k)
        if prefix not in k:
            continue
        # elif isinstance(v, str) and v[0] != '-' and do.do_folder:
        #     size = len(os.path.commonpath([v, do.do_folder]))
        #     print(f"  {k:25} -->  .../{v[size+1:]}")   # noqa
        else:
            print(f"  {k:25} -->  {v}")  # noqa


def from_dat(source: Union[Dat, str, Iterable],
        point_fns: Any) -> DataFrame:
    """Creates a pandas DataFrame from one or more Dats and a list of do fns."""
    cube = Cube(dats=source, point_fns=point_fns)
    df = cube.get_df()
    return df


def to_excel(df: DataFrame, *,
             average: bool = False,
             columns: List[str] = None,
             docs: List[str] = None,
             folder: str = None,
             formatted_columns: List[str] = None,
             median: bool = False,
             prepend: bool = False,
             quantiles: int = None,
             sheets: List[str] = None,
             show: bool = False,
             std: bool = False,
             transform: Callable[[DataFrame], DataFrame] = None,
             title: str = None,
             transpose: bool = False,
             verbose: bool = True) -> str:
    """
    Splits a pandas DataFrame into multiple DataFrames based on the values of their
    columns.  The first set of columns split the DataFrame into slices, called
    sections which separate it into different Excel files.  Then a second set of
    columns are used to slice into separate sheets within each Excel file.


    Parameters
    ----------
    df: DataFrame
        The input data.
    average: bool
        If True, a row of averages is added to the report.
    columns: List[str]
        Trims report down to only list the specified columns.
    docs: List[str]
        The columns to join together to split the report into separate Excel files.
    folder: str
        The folder where the report is saved.
    formatted_columns: List[str]
        A list of formatted columns to add to the report.
    median: bool
        If True, a row of medians is added to the report
    prepend: bool
        If True, the average, median, etc. are prepended to the report.
    quantiles: int
        If not None, number of quantiles to show
    sheets: List[str]
        The columns to join together to split the report into separate sheets.
    show: bool
        If True, the report is displayed within an Excel viewer.
    std: bool
        If True, a row of standard deviations is added to the report.
    title: str
        The title (filename base) for the report.
    transform: Callable[[DataFrame], DataFrame]
        A function that transforms the report's DataFrame before it is printed.
    transpose: bool
        If True, the report is transposed so columns headers are on the left.
    verbose: bool,
        If True, the report is printed to the console.  (default True???)
    """
    df = df.copy()
    if transform:
        df = transform(df)
    if formatted_columns:
        _add_formatted_columns(df, formatted_columns)

    summary_rows = {}
    if average:
        numeric_columns = df.select_dtypes(include='number')
        averages = numeric_columns.mean().round(2)
        summary_rows['Average'] = averages
    if median:
        numeric_columns = df.select_dtypes(include='number')
        median_values = numeric_columns.median()
        summary_rows['Median'] = median_values
    if std:
        numeric_columns = df.select_dtypes(include='number')
        std_values = numeric_columns.std()
        summary_rows['Std'] = std_values
    if quantiles:
        numeric_columns = df.select_dtypes(include='number')
        quantile_divisions = np.linspace(0, 1, quantiles + 1)
        quantile_values = numeric_columns.quantile(quantile_divisions)
        summary_rows.update(quantile_values.to_dict(orient='index'))

    # Convert summary rows to DataFrame
    summary_df = pd.DataFrame(summary_rows).transpose()

    # Ensure the summary DataFrame contains only numeric columns
    # numeric_columns = df.select_dtypes(include='number').columns
    # summary_df = summary_df[numeric_columns].transpose()

    # Handle reorder based on the original numeric columns, without the non-numeric cols
    # No need to use intersection anymore, since we're only dealing with numeric columns
    # summary_df = summary_df[numeric_columns].transpose()

    # Prepend or append the summary rows to the DataFrame
    empty_df = pd.DataFrame(columns=df.columns)
    ordering = [empty_df, summary_df, df] if prepend else [df, summary_df]
    df = pd.concat(ordering, ignore_index=False)

    if transpose:
        df = df.T
    folder = folder or os.getcwd()
    if not docs:       # saves as a single Excel file
        path = os.path.join(folder, f'{title or "output"}.xlsx')
        _create_sheets(path, df, "", sheets, columns,
                       verbose, show, transpose)
        return path
    else:   # Splits the dataframe into multiple Excel files
        section_values: Tuple
        for section_values, section_df in df.groupby(docs):
            section_path = (title + " " if title else "") + '-'.join(section_values)
            section_path = os.path.join(folder, section_path + ".xlsx")
            _create_sheets(section_path, section_df, "", sheets,
                           columns, verbose, show, transpose)
        return folder


def _create_sheets(path, df, sheet_prefix, sheets, columns, verbose, show, index):
    if os.path.exists(path):
        os.remove(path)
    with ExcelWriter(path, engine='xlsxwriter') as writer:
        if not sheets:
            df.to_excel(writer, sheet_name=sheet_prefix or "Sheet1", index=index)
        else:
            for sheet_values, sheet_df in df.groupby(sheets):
                sheet_values = [sheet_values] if isinstance(sheet_values,
                                                            str) else list(sheet_values)
                sheet_title = sheet_prefix+" " if sheet_prefix else ''
                sheet_title += '-'.join(sheet_values)
                if columns:
                    sheet_df = sheet_df[[col for col in columns
                                         if col in sheet_df.columns]]
                sheet_df.to_excel(writer, sheet_name=sheet_title, index=index)
    if verbose:
        print(f"# Dataframe written to {path}")
    if show:
        # print(f'  $ open "{path}" &')
        # os.system("pwd")
        os.system(f'open "{path}" &')


def _add_formatted_columns(df: DataFrame, format_cmds: List[str]):
    """Adds formatted columns to a DataFrame."""
    arg_names, format_str = [], ""

    def build_str(row: Series):
        d = row.to_dict()
        args = map(lambda x: d[x], arg_names)
        return format_str.format(*args)
    for spec in format_cmds:
        column_name, format_str, arg_names = map(str.strip, spec.split("<=="))
        arg_names = list(map(str.strip, arg_names.split(",")))
        df[column_name] = df.apply(build_str, axis=1)


# TODO rename dat_report
def dat_report(
        spec: Dat,
        *,
        title: str = None,
        folder: str = None,
        source: Dat = None,
        metrics: List = None,
        docs: List[str] = None,
        sheets: List[str] = None,
        columns: List[str] = None,
        formatted_columns: List[str] = None,
        verbose: bool = True,
        show: bool = None) -> DataFrame:
    """A dat script that runs the specified metrics over the specified "Dats".
    The results are saved to an Excel file.  The metrics are defined in the spec
    (see to_excel for more details).
    """
    d: dict = spec.get_spec() if isinstance(spec, Dat) else spec
    mm = d.get("dat_report") or {}
    title = title or mm.get(TITLE)    # or spec.shortname
    folder = folder or mm.get(FOLDER) or os.getcwd()
    source = source or mm.get(SOURCE) or (isinstance(spec, Dat) and spec)
    metrics = metrics or mm.get(METRICS)
    docs = docs or mm.get(DOCS)
    sheets = sheets or mm.get(SHEETS)
    columns = columns or mm.get("columns")
    formatted_columns = formatted_columns or mm.get("formatted_columns")
    verbose = mm.get(VERBOSE) if verbose is None else verbose
    show = mm.get(SHOW) if show is None else show
    df = Cube(dats=source, point_fns=metrics).get_df()
    if formatted_columns:
        _add_formatted_columns(df, formatted_columns)
    to_excel(df, title=title, folder=folder, docs=docs, sheets=sheets,
             columns=columns, verbose=verbose, show=show)
    return df


class Cube(object):
    """
    A data-cube is a multidimensional data-structure that organizes
    information according to a defined set of axes.  The Cube class encodes a data-cube
    as a list of data points that are each encoded as a dict. The dict's key-value pairs
    indicate both and the indicies of each point within the data cube as well as data
    values contained in those locations.

    The cube's points are computed by calling all "do_fns" that are defined at the
    moment each dat is added to the cube.  Each do_fn returns a list of points that
    are added to the cube.

    DO FNs:
    Point functions are invoked on each Dat as they are added to the cube, the results
    are added to the Cube's points. These do fns may return:
    - a scalar value (string, integer, or float) in which case a dict is created with
      the name of the point_fn as the key and the scalar value as the value.
    - a dict, which is added to the cube as a data point.
    - a list of dicts, which are all added to the cube as a points.
    ==> Index keys are added to each dict to indicate which dat it came from.
    """
    @staticmethod
    def from_df(df: DataFrame):
        points: Points = df.to_dict(orient='records')
        return Cube(points=points)

    def __init__(self, *, points: Points = None,
                 dats: Union[Dat, str, Iterable] = None,
                 point_fns: List[Union[str, PointFn]] = None):
        # from . import do
        self.points: Points = list(points) if points else []
        self.point_fns: List[Callable[[Dat], Any]] = []
        for fn_spec in point_fns or []:
            fn = Dat.manager.do.load(fn_spec) if isinstance(fn_spec, str) else fn_spec
            self.point_fns.append(fn)
        if dats:
            self._add_dats(dats, 1, {})
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

    def _add_dats(self, source: Union[Dat, str, Iterable],
            this_index: Union[int, str], indicies: Dict[str, str]) -> None:
        """Recursively scans 'source' adding points derived from each md.Dat."""
        if isinstance(source, DatContainer):
            self._add_dats(source.get_dats(), source.get_path_name(), indicies)
        elif isinstance(source, Dat):
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
                sub_indicies[this_index] = source.get_path_tail()
                point[_INDICIES] = sub_indicies
            self.points += points
        elif isinstance(source, str):
            self._add_dats(Dat.manager.load(source), this_index, indicies)
        elif isinstance(source, List):
            for element in source:
                self._add_dats(element, len(indicies) + 1, indicies)
        else:
            raise Exception(f"Expected a Dat, not: {source!r}")

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
            new_point = {}
            for k, v in point[_INDICIES].items():
                new_point[rename_index(k)] = v
            new_point.update(point)     # Adds the point's data after indices
            point.clear()
            point.update(new_point)
            del point[_INDICIES]
