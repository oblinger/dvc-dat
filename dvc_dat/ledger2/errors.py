"""The exceptions ``dvc_dat.ledger2`` raises, each also a builtin it resembles."""


class LedgerError(Exception):
    """Base of every ledger2 exception; also raised when the backend refuses."""


class Multiple(LedgerError, LookupError):
    """A pattern matched several rows where one was required."""


class NotEvaluated(LedgerError, RuntimeError):
    """A miss at a revision this environment cannot run."""


class UnmountedImport(LedgerError, ImportError):
    """A sandboxed function imported a repo module outside every mount (sandbox only)."""


class UntracedRead(LedgerError, PermissionError):
    """A sandboxed function opened a path outside the mounts, the dats and scratch (sandbox only)."""


class LockTimeout(LedgerError, TimeoutError):
    """A ``lock=`` body ran past its limit, or the lock was not had within it; nothing written."""


class Unindexed(LedgerError, LookupError):
    """A where clause named a dotted attribute that is neither declared indexed nor present on any row."""


class Exists(LedgerError, ValueError):
    """An ``add`` or ``remove`` on one of a sealed subject's own predicates."""
