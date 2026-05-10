import random
from dataclasses import dataclass


@dataclass(frozen=True)
class PoolPosterior:
    alpha: float
    beta: float


def choose(rng: random.Random, due: PoolPosterior, new: PoolPosterior) -> str:
    theta_due = rng.betavariate(due.alpha, due.beta)
    theta_new = rng.betavariate(new.alpha, new.beta)
    return "due" if theta_due >= theta_new else "new"


