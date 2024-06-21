from dvc_dat import do  # noqa

"""Silly configurable tool for applying rules to a sequence of letters."""
__main__ = {
    "dat": {
      "do": "letterator.run",      # example of a complex tool config
      "title": "The Letterator"
    },   
    "start": 48,
    "end": 122
}


def run(dat):
    spec = dat.get_spec()
    results = []
    for idx in range(spec["start"], spec["end"]):
        text = chr(idx)
        for step, rule_name in spec["rules"]:
            fn = do.load(rule_name)
            if idx % step == 0:
                text = fn(idx, text)
        results.append(text)
    print(spec["dat"]["title"])
    return "  ".join(results)
