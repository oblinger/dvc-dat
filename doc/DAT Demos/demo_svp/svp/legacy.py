"""`svp.legacy`: `Frame`, as it stood before it became `svp.game.Still`.

Kept so the values notebook can seal under the old dotted name and
then record the move as `(db/kind/svp.legacy.Frame, db/moved,
svp.game.Still)`; a real rename deletes this module.
"""
from dvc_dat.ledger import Value, ledger_class


@ledger_class(preds=("game",))
class Frame(Value):
    """One frame of a game's video."""

    def __init__(self, image: bytes):
        self.image = image

    def encode(self) -> bytes:
        return self.image

    @classmethod
    def decode(cls, data: bytes, store) -> "Frame":
        return cls(data)
