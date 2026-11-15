"""`comfort.report`: the most comfortable cities in a city set."""
from dvc_dat import dat


@dat.fn
def comfort_report(rev, *, acc, more: list, start: str, end: str) -> dict:
    """A reduce over a city set (`rev.reduce`): its share of comfortable days (level 7+) from `start` up to `end`, and
    its two most comfortable cities. `acc` is the report over the cities already reduced, `more` the cities it adds."""
    good = dict(acc.obj["good"]) if acc is not None else {}     # per city: its comfortable days
    days = dict(acc.obj["days"]) if acc is not None else {}     # per city: its days in the range
    for c in more:
        n = rev.run("mnt.comfort.stages.city_comfort", city=c, start=start, end=end).counts
        good[c], days[c] = sum(n[7:]), sum(n)
    top = sorted(good, key=lambda c: (-good[c], c))[:2]         # a tie breaks by name, not by when a city joined
    return {"comfortable": f"{sum(good.values())}/{sum(days.values())} days", "top": top,
            "good": good, "days": days}
