"""The exceptions ``dvc_dat.ledger`` raises, each also a builtin it resembles."""


class LedgerError(Exception):
    """Base of every ledger exception; also: no ledger found or opened, or the backend refused."""


class Multiple(LedgerError, LookupError):
    """A pattern matched several subjects where one was required (``value``, ``refs(one=True)``, ``select(one=True)``).
    """


class NotEvaluated(LedgerError, RuntimeError):
    """A call this environment will not run.

    A mount whose repo has no checkout here, or (unsandboxed, a miss) its code is outside any git checkout or the
    checkout is dirty; or it is unsandboxed and called inside a sandboxed body.
    """


class NotClean(NotEvaluated):
    """A ``clean=True`` call whose code is not a clean representation of a version.

    The checkout is dirty, or not at the commit the rev's ``db/repo/<repo> db/commit`` row names (or the rev names
    none).
    """


class NotPinned(LedgerError, RuntimeError):
    """A [``pin``][dvc_dat.ledger.Transaction.pin] or [``rerun``][dvc_dat.ledger.Rev.rerun] refused (SVP 250).

    The value is no run's result, its revision names no commit, the commit is unknown here or does not hold the code
    that ran, the function is not importable by its name at the commit, an input is on no ledger, the remote refused
    the push, or, for ``rerun``, the commit is not pinned.
    """


class NotCopied(LedgerError, RuntimeError):
    """A [``copy``][dvc_dat.ledger.Transaction.copy] refused, nothing written (SVP 251).

    A value on no ledger or on this one already, an input that cannot be found, a ledger declaring no lifetime for
    ``safe`` to read, or a pred declared otherwise here.
    """


class SpecOnly(LedgerError, LookupError):
    """A load of a value this ledger holds as its spec alone (SVP 251).

    Its rows, no bytes ([Copying][copying]); ``rev.rerun`` makes it again.
    """


class Differed(LedgerError, RuntimeError):
    """A ``pin(rerun=True)`` of a value claiming ``exact`` whose rerun produced a different hash.

    (SVP 250 A4, SVP 251 Q2). Nothing written.
    """


class UnmountedImport(LedgerError, ImportError):
    """A sandboxed function imported a module of a mounted repo outside that repo's mounts."""


class UntracedRead(LedgerError, PermissionError):
    """A sandboxed function read a path outside the mounts, the dats and its ``path`` folder.

    An unsandboxed one read a file of its repo outside the dats (Eval § 5.3).
    """


class ConfinedWrite(LedgerError, PermissionError):
    """A sandboxed function wrote outside its ``path`` folder, the dat being produced."""


class ConfinedNetwork(LedgerError, PermissionError):
    """A sandboxed function resolved a host name or opened a network connection.

    Other than to a Postgres ledger's own endpoint.
    """


class ConfinedProcess(LedgerError, PermissionError):
    """A sandboxed function created a process (``subprocess``, ``os.system``, ``os.exec*``, ``os.posix_spawn``,
    ``os.fork``): what a child process reads and writes is beyond the audit hook. A body that needs a tool runs
    unsandboxed (base mode) (SVP 1467 Q8 (A))."""


class LockTimeout(LedgerError, TimeoutError):
    """A ``lock=`` body ran past its limit, or the lock was not had within it; nothing written."""


class Unlocked(LedgerError, RuntimeError):
    """``t.previous_rev``, or a helper reading through it, in a transaction opened without ``lock=``.

    The helpers: ``bump``, ``t[s] = {...}``, ``del`` (``del t[s, p]``, ``del t[s]``). Nothing written.
    """


class Unindexed(LedgerError, LookupError):
    """A where clause or select key named a dotted predicate neither declared nor carried by any row."""


class Exists(LedgerError, ValueError):
    """An ``add``, ``remove``, bracket write or ``del`` on one of a sealed subject's own predicates.

    Or a ``db/tag`` name added before (a name is never reused). Raised at commit.
    """


class Undeclared(LedgerError, TypeError):
    """At the seal, a pred name the kind's ``@ledger_class(preds=...)`` did not declare."""


class AliasLoop(LedgerError, LookupError):
    """Making a ``Ref`` met a ``db/alias`` cycle or a chain longer than 8 hops."""


class SealBroken(LedgerError, ValueError):
    """Saving a value sealed by ``v.seal()`` whose bytes are no longer the bytes it was sealed with.

    It was not kept.
    """
