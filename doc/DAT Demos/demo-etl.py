# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# > **Plan** (delete once the sections carry it). An ETL chain computes over a game set in stages, and the ledger recomputes only the stages whose inputs moved.
# >
# > 1. **A game set and its data**: a dataset is a list of integers, one per game; a game set is a list of games, held as rows.
# > 2. **A chain of stages**: a binning per game, a cumulative binning over a list of games built recursively, a podium over a game set; asked once, every stage runs; asked again, every stage is a hit.
# > 3. **Adding a game**: only the new game's binning and the cumulative over the whole set run.
# > 4. **Replacing a game**: only the new game's binning and the cumulatives past the change run.
# > 5. **Changing a game's data**: only that game's binning and what is downstream of it run.
# > 6. **Changing one stage's code**: only that stage runs; the stages below it are hits.
# >
# > Each section ends on the count of stages that ran, read off the ledger.

# %% [markdown]
# #### Setup

# %%
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from dvc_dat.ledger import Ledger, bump

scratch_path = Path(tempfile.mkdtemp(prefix="demo-etl-"))
repo_path = scratch_path / "bins-repo"      # the code's repo: its name is its folder's
repo_path.mkdir()


def git(*args: str) -> str:
    """Run git in the code's repo; return its stdout."""
    cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com",
           "-c", "init.defaultBranch=main", *args]
    done = subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def write_module(rel: str, source: str, message: str) -> None:
    """Write one module of the code's repo and commit it."""
    path = repo_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    git("add", rel)
    git("commit", "-q", "-m", message)


git("init", "-q")
(repo_path / "bins").mkdir()
write_module("bins/__init__.py", '"""`bins`: the ETL demo\'s stages."""\n', "bins")
sys.path.insert(0, str(repo_path))
L = Ledger(scratch_path / "ledger", create=True)

STAGES = ("bins.stages.binning", "bins.stages.cumulative", "bins.report.podium")


def entry_counts() -> dict:
    """How many results each stage has sealed on the ledger so far."""
    rev = L.at()
    return {name.rsplit(".", 1)[1]: len(rev.refs(fn=name)) for name in STAGES}


def ran_since(counts_before: dict) -> dict:
    """How many times each stage ran (missed and sealed) since `counts_before`."""
    counts_now = entry_counts()
    return {stage: counts_now[stage] - counts_before[stage] for stage in counts_now}


# %% [markdown]
# # ETL: computing over game sets, recomputing only what moved
#
# An ETL chain is a series of stages, each computing a value from the values of the stage below it, over a whole game set.
# Every stage here is a ledger function, so every result is a value sealed with its trace, the exact inputs and code it was computed from.
# Asked for a result, the ledger hands back a sealed one whose trace still holds and runs the stage only when something in its trace has moved.
# So a change anywhere in the chain recomputes that stage and what is downstream of it, and nothing else.

# %% [markdown]
# ## A game set and its data
#
# A game's dataset is a value, a list of integers, found by the alias `dataset/<game>`; a game set is a list of games, held as `contains` rows on its own subject.

# %% [markdown]
# ### The value kinds
#
# Two kinds of value: a game's dataset, and a binning, the count of integers falling in each of ten bins; a binning's `games` pred is an ordered list, so it is declared JSON.

# %%
write_module("bins/values.py", '''\
"""`bins.values`: a game's dataset and a binning."""
import json

from dvc_dat.ledger import Value, ledger_class


@ledger_class(preds=("game",))
class Dataset(Value):
    """A game's dataset: a list of integers in [0, 100)."""

    def __init__(self, ints):
        self.ints = list(ints)

    def encode(self) -> bytes:
        return json.dumps(self.ints).encode()

    @classmethod
    def decode(cls, data: bytes, store) -> "Dataset":
        return cls(json.loads(data))


@ledger_class(preds=("games",))
class Binning(Value):
    """How many integers fall in each of ten bins, 0-9 to 90-99, over the games it names."""

    def __init__(self, counts):
        self.counts = list(counts)

    def encode(self) -> bytes:
        return json.dumps(self.counts).encode()

    @classmethod
    def decode(cls, data: bytes, store) -> "Binning":
        return cls(json.loads(data))
''', "values: Dataset, Binning")
from bins.values import Dataset, Binning
with L.transaction(by="human:dan", why="a binning's games are an ordered list") as t:
    t.add("db/pred/games", "db/type", "json")


# %% [markdown]
# ### Four games' datasets

# %%
def seal_dataset(game: str, seed: int) -> None:
    """Seal a game's dataset, 50 integers drawn from `seed`, and point `dataset/<game>` at it."""
    rng = random.Random(seed)
    dataset_value = Dataset(rng.randrange(100) for _ in range(50))
    dataset_value.preds["game"] = game
    with L.transaction(by="human:dan", why=f"{game}'s data") as t:
        dataset_value.seal(t, alias=f"dataset/{game}")


for game, seed in [("G1", 1), ("G2", 2), ("G3", 3), ("G4", 4), ("G5", 5)]:
    seal_dataset(game, seed)
print(L.at().load("dataset/G1").ints[:10])
# → [17, 72, 97, 8, 32, 15, 63, 97, 57, 60]

# %% [markdown]
# ### The game set
#
# A game set is rows: `gameset/normie contains G1`, one per game; `contains` is declared many-valued, so the rows add up to a set.

# %%
with L.transaction(by="human:dan", why="the normie set") as t:
    t.add("db/pred/contains", "db/cardinality", "many")
    for game in ("G1", "G2", "G3"):
        t.add("gameset/normie", "contains", game)
print(sorted(L.at().all("gameset/normie", "contains")))
# → ['G1', 'G2', 'G3']

# %% [markdown]
# ## A chain of stages
#
# Three stages, each a ledger function evaluating the one below it: a binning per game, a cumulative binning over a list of games, and a podium over a game set.

# %% [markdown]
# ### The stages
#
# `cumulative` is recursive: the binning over a list of games is the binning over all but the last game, plus the last game's own.

# %%
write_module("bins/stages.py", '''\
"""`bins.stages`: a binning per game, and the cumulative binning over a list of games."""
from dvc_dat.ledger import ledger_fn

from .values import Binning

WIDTH = 10                                  # each bin's span: 0-9, 10-19, ...


@ledger_fn
def binning(rev, *, game: str) -> Binning:
    """One game's binning: its dataset's integers counted per bin."""
    dataset = rev.load(f"dataset/{game}")   # traced: the alias and the bytes it names
    counts = [0] * 10
    for i in dataset.ints:
        counts[i // WIDTH] += 1
    b = Binning(counts)
    b.preds["games"] = [game]
    return b


@ledger_fn
def cumulative(rev, *, games: list) -> Binning:
    """The binning over `games`: the cumulative over all but the last, plus the last game's binning."""
    if not games:
        return Binning([0] * 10)
    rest = rev.eval("bins.stages.cumulative", games=games[:-1])   # the recursion
    last = rev.eval("bins.stages.binning", game=games[-1])
    b = Binning([r + c for r, c in zip(rest.counts, last.counts)])
    b.preds["games"] = list(games)
    return b
''', "stages: binning, cumulative")

write_module("bins/report.py", '''\
"""`bins.report`: the podium over a game set."""
from dvc_dat.ledger import ledger_fn


@ledger_fn
def podium(rev, *, gameset: str) -> list:
    """The three fullest bins over a game set's games, fullest first."""
    games = sorted(rev.all(gameset, "contains"))                  # traced: the set's rows
    total = rev.eval("bins.stages.cumulative", games=games)
    fullest = sorted(range(10), key=lambda i: (-total.counts[i], i))[:3]
    return [f"{10 * i}-{10 * i + 9}" for i in fullest]
''', "report: podium")

# %% [markdown]
# ### Mounting the code
#
# Mounting `bins` makes its stages sandboxed: each call runs in a fresh process of its own, and its code is the hash of every module file the run loaded.

# %%
with L.transaction(by="human:dan", why="mount the stages") as t:
    t.add("db/mount/bins", "db/root", "bins")
    t.add("db/mount/bins", "db/repo", "bins-repo")
    bump(t, "code/bins-repo", "minor", confirm=lambda old, new: True)   # 0.1.0, at HEAD
print(L.at().load_fn("bins.report.podium").mode)
# → sandbox

# %% [markdown]
# ### Asking for the podium
#
# `rev.eval(name, **keys)` returns the stage's result, running it only when no sealed result with a holding trace answers the same question.

# %%
counts_before = entry_counts()
podium_value = L.at().eval("bins.report.podium", gameset="gameset/normie")
print(podium_value.obj)
# → ['60-69', '0-9', '20-29']
print(ran_since(counts_before))
# → {'binning': 3, 'cumulative': 4, 'podium': 1}

# %% [markdown]
# Everything ran: a binning per game, the cumulatives over `[]`, `[G1]`, `[G1, G2]` and `[G1, G2, G3]`, and the podium.

# %%
counts_before = entry_counts()
again_value = L.at().eval("bins.report.podium", gameset="gameset/normie")
print(again_value.subject == podium_value.subject)
# → True
print(ran_since(counts_before))
# → {'binning': 0, 'cumulative': 0, 'podium': 0}

# %% [markdown]
# Asked again, nothing ran: the podium is a hit.

# %% [markdown]
# ## Adding a game
#
# Adding a game to the set moves the set's rows, so the podium reruns; below it, only what the new game touches runs.

# %%
with L.transaction(by="human:dan", why="G4 joins") as t:
    t.add("gameset/normie", "contains", "G4")
counts_before = entry_counts()
podium_value = L.at().eval("bins.report.podium", gameset="gameset/normie")
print(ran_since(counts_before))
# → {'binning': 1, 'cumulative': 1, 'podium': 1}

# %% [markdown]
# G4's binning ran, and the cumulative over `[G1, G2, G3, G4]`, which found the cumulative over `[G1, G2, G3]` already sealed: three games' binnings were never touched.

# %% [markdown]
# ## Replacing a game
#
# Replacing a game in the set reruns the new game's binning and every cumulative from the replaced position on.

# %%
with L.transaction(by="human:dan", why="G5 for G3") as t:
    t.remove("gameset/normie", "contains", "G3")
    t.add("gameset/normie", "contains", "G5")
counts_before = entry_counts()
podium_value = L.at().eval("bins.report.podium", gameset="gameset/normie")
print(sorted(L.at().all("gameset/normie", "contains")))
# → ['G1', 'G2', 'G4', 'G5']
print(ran_since(counts_before))
# → {'binning': 1, 'cumulative': 2, 'podium': 1}

# %% [markdown]
# G5's binning ran; G4's was a hit. The cumulative over `[G1, G2]` was a hit, so only `[G1, G2, G4]` and `[G1, G2, G4, G5]` ran: the recursion is what lets a long prefix be reused.

# %% [markdown]
# ## Changing a game's data
#
# A new version of a game's dataset is a new value with the alias re-pointed, so every result that loaded the alias is stale.

# %%
seal_dataset("G2", seed=22)                 # G2 re-measured
counts_before = entry_counts()
podium_value = L.at().eval("bins.report.podium", gameset="gameset/normie")
print(ran_since(counts_before))
# → {'binning': 1, 'cumulative': 3, 'podium': 1}

# %% [markdown]
# G2's binning ran, and the three cumulatives that contain G2; G1's binning and the cumulative over `[G1]` were hits, since they never read `dataset/G2`.

# %% [markdown]
# ## Changing one stage's code
#
# An edit to one stage's module changes that stage's code hash, so that stage reruns; stages whose runs never loaded the module are hits.

# %%
report_path = repo_path / "bins/report.py"
report_source = report_path.read_text().replace("[:3]", "[:2]").replace("three fullest", "two fullest")
write_module("bins/report.py", report_source, "report: the podium is two bins")
counts_before = entry_counts()
podium_value = L.at().eval("bins.report.podium", gameset="gameset/normie")
print(podium_value.obj)
# → ['30-39', '20-29']
print(ran_since(counts_before))
# → {'binning': 0, 'cumulative': 0, 'podium': 1}

# %% [markdown]
# Only the podium ran: its run loaded `report.py`, and no other stage's run did.
# No `bump` was needed: a sandboxed stage's identity is the bytes of the modules its run loaded, so the edit alone made the podium a new question, and a miss runs at HEAD, clean or dirty (F520 Q39).

# %% [markdown]
# ## Reading the chain back
#
# A result's trace lists every input it read: the stage below by its result's bytes (`eval:`), the set's rows (`q:`, the `all` call and its answer), its own code (`fn`) and the environment.

# %%
for item in sorted(podium_value.trace):
    print(item)
# → eval:bins.stages.cumulative{"games":["G1","G2","G4","G5"]}
#   fn
#   platform
#   q:{"__call__":"all","args":["gameset/normie","contains"],"since":null}
print(sorted(L.at()[podium_value.trace["fn"], "db/modules"]))
# → ['bins/__init__.py', 'bins/report.py', 'bins/values.py']

# %%
# clean up
import shutil
shutil.rmtree(scratch_path)
