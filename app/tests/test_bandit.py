import random

from lituk.review.bandit import PoolPosterior, choose, update


def test_update_increments_alpha_on_hit():
    p = PoolPosterior(alpha=1.0, beta=1.0)
    p2 = update(p, correct=True)
    assert p2.alpha == 2.0
    assert p2.beta == 1.0


def test_update_increments_beta_on_miss():
    p = PoolPosterior(alpha=1.0, beta=1.0)
    p2 = update(p, correct=False)
    assert p2.alpha == 1.0
    assert p2.beta == 2.0


def test_update_is_immutable():
    p = PoolPosterior(alpha=3.0, beta=2.0)
    update(p, correct=True)
    assert p.alpha == 3.0  # original unchanged


def test_choose_picks_arm_with_higher_sample():
    rng = random.Random(42)
    # due has strong posterior (high alpha), new is weak
    due = PoolPosterior(alpha=100.0, beta=1.0)
    new = PoolPosterior(alpha=1.0, beta=100.0)
    results = [choose(rng, due, new) for _ in range(20)]
    assert all(r == "due" for r in results)


def test_choose_explores_weaker_arm_sometimes():
    rng = random.Random(0)
    # Both arms equal — should pick each roughly half the time
    due = PoolPosterior(alpha=1.0, beta=1.0)
    new = PoolPosterior(alpha=1.0, beta=1.0)
    results = [choose(rng, due, new) for _ in range(200)]
    due_count = results.count("due")
    # With equal priors, both arms drawn equally — expect 30–70%
    assert 50 < due_count < 150


def test_choose_returns_due_or_new():
    rng = random.Random(7)
    due = PoolPosterior(alpha=2.0, beta=2.0)
    new = PoolPosterior(alpha=2.0, beta=2.0)
    for _ in range(50):
        result = choose(rng, due, new)
        assert result in ("due", "new")
