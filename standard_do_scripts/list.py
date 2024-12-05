from dvc_dat import do


def __main__(prefix: str = ""):
    """Lists all do names with a given prefix."""
    print(f"\nBase names matching: '{prefix}*'")
    for k, v in do.base_locations.items():
        if prefix not in k:
            continue
        # elif isinstance(v, str) and v[0] != '-' and do.do_folder:
        #     size = len(os.path.commonpath([v, do.do_folder]))
        #     print(f"  {k:25} -->  .../{v[size+1:]}")   # noqa
        else:
            print(f"  {k:25} -->  {v}")  # noqa
