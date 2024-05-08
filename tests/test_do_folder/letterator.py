from ml_dat import do   # noqa

"""Silly configurable tool for applying rules to a sequence of letters."""
letterator = {
    "main": {
      "do": "letterator.run",      # example of a complex tool config
      "title": "The Letterator"
    },   
    "start": 48,
    "end": 122
}


def run(inst):
    spec = inst.get_spec()
    results = []
    for idx in range(spec["start"], spec["end"]):
        text = chr(idx)
        for step, rule_name in spec["rules"]:
            fn = do.load(rule_name)
            if idx % step == 0:
                text = fn(idx, text)
        results.append(text)
    print(spec["main"]["title"])
    return "  ".join(results)
