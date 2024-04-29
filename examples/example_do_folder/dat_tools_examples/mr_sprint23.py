
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

def my_transform(df):
    def my_result(row):
        if row['Metric'] == 'Revenue':
            percentage = (row['value'] / average_revenue) * 100
            return f"${row['value']} ({int(percentage)}%)"
        elif row['Metric'] == 'Units Sold':
            percentage = (row['value'] / average_units) * 100
            return f"{row['value']} Units ({int(percentage)}%)"
        else:
            return "???"
    average_revenue = df[df['Metric'] == 'Revenue']['value'].mean()
    average_units = df[df['Metric'] == 'Units Sold']['value'].mean()
    df['Result'] = df.apply(my_result, axis=1)
    return df


show_transform = {
    "main": {"base": "mr_sprint23.mr_sprint23"},
    "metrics_matrix": {
        "title": "S23b",
        "transform": my_transform,
        "show": False,
        "verbose": False,
    }
}

