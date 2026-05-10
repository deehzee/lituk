import random

from lituk.review.bandit import PoolPosterior, choose


def test_pool_posterior_is_frozen():
    p = PoolPosterior(alpha=1.0, beta=1.0)
    assert p.alpha == 1.0
    assert p.beta == 1.0


def test_choose_picks_arm_with_higher_sample():
    rng = random.Random(42)
    # due has strong posterior (high alpha), new is weak
    due = PoolPosterior(alpha=100.0, beta=1.0)
    new = PoolPosterior(alpha=1.0, beta=100.0)
    results = [choose(rng, due, new) for _ in range(20)]
    assert all(r == "due" for r in results)


def test_choose_picks_new_when_new_has_higher_alpha():
    rng = random.Random(42)
    due = PoolPosterior(alpha=1.0, beta=100.0)
    new = PoolPosterior(alpha=100.0, beta=1.0)
    results = [choose(rng, due, new) for _ in range(20)]
    assert all(r == "new" for r in results)


def test_choose_balanced_with_equal_priors():
    rng = random.Random(0)
    due = PoolPosterior(alpha=1.0, beta=1.0)
    new = PoolPosterior(alpha=1.0, beta=1.0)
    results = [choose(rng, due, new) for _ in range(200)]
    due_count = results.count("due")
    assert 50 < due_count < 150


def test_choose_returns_due_or_new():
    rng = random.Random(7)
    due = PoolPosterior(alpha=2.0, beta=2.0)
    new = PoolPosterior(alpha=2.0, beta=2.0)
    for _ in range(50):
        result = choose(rng, due, new)
        assert result in ("due", "new")


def test_choose_high_coverage_signal_favours_new():
    # Simulates 0% explored: new_post=Beta(1001,1), due_post=Beta(1,1)
    rng = random.Random(99)
    due = PoolPosterior(alpha=1.0, beta=1.0)      # due arm (failure rate)
    new = PoolPosterior(alpha=1001.0, beta=1.0)   # new arm (coverage: all unexplored)
    results = [choose(rng, due, new) for _ in range(20)]
    assert all(r == "new" for r in results)


def test_choose_high_failure_rate_favours_due():
    # Simulates many wrong answers on due cards
    rng = random.Random(99)
    due = PoolPosterior(alpha=100.0, beta=5.0)    # due arm: high failure rate
    new = PoolPosterior(alpha=10.0, beta=90.0)    # new arm: 90% explored
    results = [choose(rng, due, new) for _ in range(20)]
    assert all(r == "due" for r in results)
