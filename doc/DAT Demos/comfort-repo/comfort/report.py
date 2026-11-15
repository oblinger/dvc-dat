"""`comfort.report`: the most comfortable cities in a city set."""
from dvc_dat import dat


@dat.reduce_fn
def comfort_report(rev, *, accs: list, more: list, start: str, end: str) -> dict:
    """A reduce over a city set (`rev.reduce`): its share of comfortable days (level 7+) from `start` up to `end`, and
    its two most comfortable cities. `accs` are reports over disjoint city sets already reduced, merged; `more` the
    cities none of them covers, added. A report keeps its per-city counts, which is what merging needs."""
    good, days = {}, {}                                         # per city: its comfortable days, its days in range
    for acc in accs:
        good.update(acc.obj["good"])
        days.update(acc.obj["days"])
    for c in more:
        n = rev.run("mnt.comfort.stages.city_comfort", city=c, start=start, end=end).counts
        good[c], days[c] = sum(n[7:]), sum(n)
    top = sorted(good, key=lambda c: (-good[c], c))[:2]         # a tie breaks by name, not by when a city joined
    return {"comfortable": f"{sum(good.values())}/{sum(days.values())} days", "top": top,
            "good": dict(sorted(good.items())), "days": dict(sorted(days.items()))}
