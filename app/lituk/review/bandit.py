import random
from dataclasses import dataclass


@dataclass(frozen=True)
class PoolPosterior:
    alpha: float
    beta: float


def choose_with_samples(
    rng: random.Random, due: PoolPosterior, new: PoolPosterior
) -> tuple[str, float, float]:
    theta_due = rng.betavariate(due.alpha, due.beta)
    theta_new = rng.betavariate(new.alpha, new.beta)
    return ("due" if theta_due >= theta_new else "new"), theta_due, theta_new


def choose(rng: random.Random, due: PoolPosterior, new: PoolPosterior) -> str:
    arm, _, _ = choose_with_samples(rng, due, new)
    return arm


