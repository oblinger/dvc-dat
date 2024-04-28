
mr_sprint23 = {
    "main": {"do": "dt.metrics_matrix"},
    "metrics_matrix": {
        "title": "S23",
        "source": ["runs.example.hello10", "runs.example.hello5"],
        "metrics": ["cube_hello.is_prime", "cube_hello.data", "cube_hello.color_p"],
        "show": True,
    }
}

add_col = {
    "main": {"base": "mr_sprint23.mr_sprint23"},
    "metrics_matrix": {
        "title": "S23b",
        "formatted_columns": [
            " new_col <== {0}-{1} <== is_prime, color_p "
        ],
        "show": False,
        "verbose": False,
    }
}
