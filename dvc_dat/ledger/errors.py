"""The exceptions ``dvc_dat.ledger`` raises, each also a builtin it resembles."""


class LedgerError(Exception):
    """Base of every ledger exception; also: no ledger found or opened, or the backend refused."""


class Multiple(LedgerError, LookupError):
    """A pattern matched several subjects where one was required (``value``, ``refs(one=True)``)."""


class NotEvaluated(LedgerError, RuntimeError):
    """A call this environment will not run: its repo has no checkout here, or (unsandboxed, a
    miss) its code is outside any git checkout or the checkout is dirty; or it is unsandboxed and called
    inside a sandboxed body."""


class NotClean(NotEvaluated):
    """A ``clean=True`` call whose code is not a clean representation of a version: the checkout
    is dirty, or not at the commit the rev's ``db/repo/<repo> db/commit`` row names (or the rev names none)."""


class NotPinned(LedgerError, RuntimeError):
    """A pin or rerun refused (SVP 250): the value is no run's result, its revision names no commit, the
    commit is unknown here or does not hold the code that ran, the function is not importable by its name at
    the commit, an input is on no ledger, the remote refused the push, or the value's commit is not pinned."""


class NotCopied(LedgerError, RuntimeError):
    """A copy refused, nothing written (SVP 251): a value not on a ledger, an input that cannot be found, a ledger
    declaring no lifetime for ``safe`` to read."""


class SpecOnly(LedgerError, LookupError):
    """A value this ledger holds as its spec alone (SVP 251): its rows, no bytes; ``rev.rerun`` makes it again."""


class Differed(LedgerError, RuntimeError):
    """A rerun of a function claiming ``exact`` produced a different hash (SVP 250 A4, SVP 251 Q2)."""


class UnmountedImport(LedgerError, ImportError):
    """A sandboxed function imported a module of a mounted repo outside that repo's mounts."""


class UntracedRead(LedgerError, PermissionError):
    """A sandboxed function read a path outside the mounts, the dats and its path folder; or an unsandboxed
    one read a file of its repo outside the dats (Eval § 5.3)."""


class ConfinedWrite(LedgerError, PermissionError):
    """A sandboxed function wrote outside its path folder, the dat being produced."""


class ConfinedNetwork(LedgerError, PermissionError):
    """A sandboxed function resolved a host name or opened a network connection."""


class ConfinedProcess(LedgerError, PermissionError):
    """A sandboxed function created a process (``subprocess``, ``os.system``, ``os.exec*``, ``os.posix_spawn``,
    ``os.fork``): what a child process reads and writes is beyond the audit hook. A body that needs a tool runs
    unsandboxed (base mode) (SVP 1467 Q8 (A))."""


class LockTimeout(LedgerError, TimeoutError):
    """A ``lock=`` body ran past its limit, or the lock was not had within it; nothing written."""


class Unlocked(LedgerError, RuntimeError):
    """``t.previous_rev``, or a helper reading through it (``bump``, ``t[s] = {...}``, ``del``), in a
    transaction opened without ``lock=``; nothing written."""


class Unindexed(LedgerError, LookupError):
    """A where clause named a dotted predicate neither declared nor carried by any row."""


class Exists(LedgerError, ValueError):
    """An ``add``, ``remove``, bracket write or ``del`` on one of a sealed subject's own predicates, or a
    ``db/tag`` name added before (a name is never reused)."""


class Undeclared(LedgerError, TypeError):
    """At the seal, a pred name the kind's ``@ledger_class(preds=...)`` did not declare."""


class AliasLoop(LedgerError, LookupError):
    """Making a ``Ref`` met a ``db/alias`` cycle or a chain longer than 8 hops."""


class SealBroken(LedgerError, ValueError):
    """Saving a value sealed by ``v.seal()``: its bytes are no longer the bytes it was sealed with."""
