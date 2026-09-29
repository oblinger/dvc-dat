"""The ledger's own exception: the backend refused."""


class LedgerError(Exception):
    """The backend refused: the connection failed, the lock could not be taken, the file is corrupt.

    The message names the backend and the row it was writing.
    """
