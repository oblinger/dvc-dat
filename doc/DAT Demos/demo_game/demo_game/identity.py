"""`demo_game.identity.train`: a revision function of a game."""


def train(rev, *, game: str, epochs: int = 8):
    base = rev["model/player-id", "version"]
    run = rev.load(f"run/0-2-2/{game}")
    acc = 0.93 if game == "G5" else 0.88
    return {"model": f"identity-{game}-{epochs}", "base": base,
            "frames": len(run.table), "acc": acc}
