"""`demo_game.legacy`: `Frame`, before it was renamed `Still`.

Kept so the values notebook can seal under the old dotted name and
then record the move as `(db/kind/demo_game.legacy.Frame, db/moved,
demo_game.game.Still)`; a real rename deletes this module.
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
