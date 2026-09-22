def __main__(*args, **kwargs):
    """Echo the call as Python values -- what the command line parsed."""
    shown = ", ".join(f"{k}={kwargs[k]!r}" for k in sorted(kwargs))
    return f"args={list(args)!r} kwargs={{{shown}}}"
