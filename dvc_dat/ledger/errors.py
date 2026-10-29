"""The exceptions ``dvc_dat.ledger`` raises, each also a builtin it resembles."""


class LedgerError(Exception):
    """Base of every ledger exception; also: no ledger found or opened, or the backend refused."""


class Multiple(LedgerError, LookupError):
    """A pattern matched several subjects where one was required (``value``, ``refs(one=True)``)."""


class NotEvaluated(LedgerError, RuntimeError):
    """A call this environment will not run: its repo has no checkout here, or (unsandboxed, a
    miss) its code is outside any git checkout or the checkout is dirty."""


class NotClean(NotEvaluated):
    """A ``clean=True`` call whose code is not a clean representation of a version: the checkout
    is dirty, or not at the commit the rev's ``db/repo/<repo> db/commit`` row names (or the rev names none)."""


class UnmountedImport(LedgerError, ImportError):
    """A sandboxed function imported a module of a mounted repo outside that repo's mounts."""


class UntracedRead(LedgerError, PermissionError):
    """A sandboxed function read a path outside the mounts, the dats and its path folder; or an unsandboxed
    one read a file of its repo outside the dats (Eval § 5.3)."""


class ConfinedWrite(LedgerError, PermissionError):
    """A sandboxed function wrote outside its path folder, the dat being produced."""


class ConfinedNetwork(LedgerError, PermissionError):
    """A sandboxed function resolved a host name or opened a network connection."""


class LockTimeout(LedgerError, TimeoutError):
    """A ``lock=`` body ran past its limit, or the lock was not had within it; nothing written."""


class Unlocked(LedgerError, RuntimeError):
    """``t.previous_rev``, or a helper reading through it (``bump``, ``t[s] = {...}``, ``del``), in a
    transaction opened without ``lock=``; nothing written."""


class Unindexed(LedgerError, LookupError):
    """A where clause named a dotted predicate neither declared nor carried by any row."""


class Exists(LedgerError, ValueError):
    """An ``add``, ``remove``, bracket write or ``del`` on one of a sealed subject's own predicates."""


class Undeclared(LedgerError, TypeError):
    """At the seal, a pred name the kind's ``@ledger_class(preds=...)`` did not declare."""


class AliasLoop(LedgerError, LookupError):
    """Making a ``Ref`` met a ``db/alias`` cycle or a chain longer than 8 hops."""


class SealBroken(LedgerError, ValueError):
    """Saving a value sealed by ``v.seal()``: its bytes are no longer the bytes it was sealed with."""
