__main__ = {
    "dat": {"do": "dt.dat_report"},
    "dat_report": {
        "title": "S23",
        "source": ["runs/example/hello10", "runs/example/hello5"],
        "metrics": ["cube_hello.is_prime", "cube_hello.data", "cube_hello.color_p"],
        "show": True}
}

add_col = {
    "dat": {"base": "mr_sprint23"},
    "dat_report": {
        "title": "S23b", "show": False, "verbose": False,
        "formatted_columns":
            [" new_col <== {0}-{1} <== is_prime, color_p "]}
}
