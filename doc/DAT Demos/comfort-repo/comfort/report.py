"""`comfort.report`: the most comfortable cities in a city set."""
from dvc_dat.ledger import ledger_fn


@ledger_fn
def comfort_report(rev, *, cityset: str, start: str, end: str) -> dict:
    """The city set's share of comfortable days (level 7+) from `start` up to `end`, and its two most comfortable cities."""
    cities = sorted(rev.all(cityset, "contains"))   # traced: the set's rows; sorted, so a tie breaks by name, not by when a city joined
    counts = {c: rev.run("comfort.stages.city_comfort", city=c, start=start, end=end).counts for c in cities}
    good = {c: sum(n[7:]) for c, n in counts.items()}
    top = sorted(cities, key=lambda c: -good[c])[:2]
    return {"comfortable": f"{sum(good.values())}/{sum(sum(n) for n in counts.values())} days", "top": top}
