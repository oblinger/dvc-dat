"""The exceptions ``dvc_dat.ledger2`` raises, each also a builtin it resembles."""


class LedgerError(Exception):
    """Base of every ledger2 exception; also: no ledger found or opened, or the backend refused."""


class Multiple(LedgerError, LookupError):
    """A pattern matched several subjects where one was required (``value``, ``refs(one=True)``)."""


class NotEvaluated(LedgerError, RuntimeError):
    """A miss at a revision this environment cannot run, or a mount whose repo has no checkout here."""


class UnmountedImport(LedgerError, ImportError):
    """A sandboxed function imported a repo module outside every mount."""


class UntracedRead(LedgerError, PermissionError):
    """A sandboxed function opened a path outside the mounts, the dats and its scratch."""


class LockTimeout(LedgerError, TimeoutError):
    """A ``lock=`` body ran past its limit, or the lock was not had within it; nothing written."""


class Unindexed(LedgerError, LookupError):
    """A where clause named a dotted predicate neither declared nor carried by any row."""


class Exists(LedgerError, ValueError):
    """An ``add``, ``remove``, bracket write or ``del`` on one of a sealed subject's own predicates."""


class Undeclared(LedgerError, TypeError):
    """At the seal, a pred name the kind's ``@ledger_class(preds=...)`` did not declare."""


class AliasLoop(LedgerError, LookupError):
    """Making a ``Ref`` met a ``db/alias`` cycle or a chain longer than 8 hops."""
