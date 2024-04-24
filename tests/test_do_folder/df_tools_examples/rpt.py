import json

from ml_dat import Inst
from ml_dat import df_tools as dt


def load_points_json(inst: Inst):
    with open(f"{inst.path}/points.json") as f:
        return json.load(f)


#

simple = {
    "main": {"do": "dt.metrics_matrix"},
    "metrics_matrix": {
        "title": "Retail Data Matrix",
        "source": "Datasets.Retail Data",
        "metrics": [load_points_json],
        "show": False,
    }
}


# this is the default report
rpt = {
    "main": {"do": "dt.metrics_matrix"},
    "metrics_matrix": {
        "title": "RPT",
        "source": "Datasets.Retail Data",
        "metrics": [load_points_json],
        "docs": ["Store"],
        "sheets": ["Month", "Product"],
        "show": True,
    }
}


def my_test_code(inst: Inst):
    df = dt.metrics_matrix(inst)
    print(df)
    dt.get_excel(df, title="My Test", show=True)
    return df


my_test = {
    "main": {"do": my_test_code},
    "metrics_matrix": {
        "title": "My Test",
        "source": "Datasets.Retail Data",
        "metrics": [load_points_json],
        "sheets": ["Store"],
        "show": True,
    }
}
