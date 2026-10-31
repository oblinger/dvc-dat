"""`comfort.stages`: a city's daily comfort, and its days binned by comfort level over a date range."""
from dvc_dat.ledger import ledger_fn

from .values import ComfortCounts, Days


def comfort(temp: int, humidity: int) -> int:
    """A day's comfort, 0 (miserable) to 9 (ideal): best near 72 °F and 45 % humidity."""
    return max(0, 9 - abs(temp - 72) // 4 - abs(humidity - 45) // 10)


@ledger_fn
def daily_comfort(rev, *, city: str) -> Days:
    """A city's days with a comfort column added: [date, °F, humidity %, comfort]."""
    weather = rev.load(f"weather/{city}")   # traced: the alias and the bytes it names
    days = Days([[day, temp, humidity, comfort(temp, humidity)] for day, temp, humidity in weather.days])
    days.preds["city"] = city
    return days


@ledger_fn
def city_comfort(rev, *, city: str, start: str, end: str) -> ComfortCounts:
    """A city's days from `start` up to `end`, counted per comfort level."""
    days = rev.run("mnt.comfort.stages.daily_comfort", city=city)
    counts = [0] * 10
    for day, _temp, _humidity, level in days.days:
        if start <= day < end:
            counts[level] += 1
    comfort_counts = ComfortCounts(counts)
    comfort_counts.preds["city"] = city
    return comfort_counts
