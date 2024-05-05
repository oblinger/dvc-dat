import json

from ml_dat import Inst
from ml_dat import dat_tools as dt


def load_points_json(inst: Inst):
    with open(f"{inst._path}/points.json") as f:
        return json.load(f)


#

simple = {
    "main": {"do": "dt.metrics_matrix"},
    "metrics_matrix": {
        "title": "Retail Data Matrix",
        "source": "Datasets/Retail Data",
        "metrics": ["rpt.load_points_json"],
        "show": False,
    }
}


# this is the default report
rpt = {
    "main": {"do": "dt.metrics_matrix"},
    "metrics_matrix": {
        "title": "RPT",
        "source": "Datasets/Retail Data",
        "metrics": ["rpt.load_points_json"],
        "docs": ["list"],
        "sheets": ["Store", "Month"],
        "show": False,
    }
}


def my_test_code(inst: Inst):
    df = dt.metrics_matrix(inst)
    print(df)
    dt.to_excel(df, title="My Test", show=False)
    return df


my_test = {
    "main": {"do": my_test_code},
    "metrics_matrix": {
        "title": "My Test",
        "source": "Datasets/Retail Data/Berkeley",
        "metrics": ["rpt.load_points_json"],
        "sheets": ["Store"],
        "show": False,
    }
}


def fully_manual():
    df = dt.from_inst("Datasets/Retail Data", ["rpt.load_points_json"])
    print(df)
    dt.to_excel(df, title="fully manual test", show=False)
    return df
