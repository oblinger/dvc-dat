"""`demo_game.etl`: a three-stage ETL chain whose stages are dats.

Mounted as one prefix (`db/mount/demo_game.etl`), one module per
stage, so an edit to one stage moves only that stage's code in the
dependencies.
Written to the ledger design of 2026-10-18 (T534). A mounted root declares
its own version (`just bump demo_game.etl`).
"""

__version__ = "0.1.0"
