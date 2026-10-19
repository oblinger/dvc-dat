"""The ledger load harness (T541, R0017): N processes x M operations on one ledger, then invariants.

    uv run python -m tests.load --processes 4 --transactions 2000 --ledger /tmp/load-ledger

See ``harness`` for the workload and the invariants; ``test_load`` runs a small one under ``-m load``.
"""
