"""``svp.identity.train``, as the module doc names it: a revision function of a game."""


def train(rev, *, game: str, epochs: int = 8):
    base = rev.get("model/player-id", "version", default="0.0.0")
    return {"model": f"identity-{game}-{epochs}", "base": base}
