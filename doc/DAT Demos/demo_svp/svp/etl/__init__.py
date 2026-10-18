"""`svp.etl`: a three-stage ETL chain whose stages are dats.

Mounted as one prefix (`db/mount/svp.etl`), one module per stage, so
an edit to one stage moves only that stage's code in the trace.
Written to the ledger design of 2026-10-18; runs once `ledger2` is
rebuilt to it (T534).
"""
