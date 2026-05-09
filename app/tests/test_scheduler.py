from datetime import date, timedelta

import pytest

from lituk.review.scheduler import CardState, initial_state, update


TODAY = date(2026, 5, 9)


def test_initial_state_defaults():
    s = initial_state(TODAY)
    assert s.ease == 2.5
    assert s.interval == 0
    assert s.repetitions == 0
    assert s.due_date == TODAY
    assert s.lapses == 0


# --- lapse (grade 0) ---

def test_lapse_resets_repetitions_and_interval():
    s = CardState(ease=2.5, interval=10, repetitions=3, due_date=TODAY, lapses=0)
    s2 = update(s, 0, TODAY)
    assert s2.repetitions == 0
    assert s2.interval == 1
    assert s2.lapses == 1
    assert s2.due_date == TODAY + timedelta(days=1)


def test_lapse_reduces_ease():
    s = CardState(ease=2.5, interval=10, repetitions=3, due_date=TODAY, lapses=0)
    s2 = update(s, 0, TODAY)
    assert abs(s2.ease - 2.3) < 1e-9


def test_lapse_clamps_ease_at_floor():
    s = CardState(ease=1.4, interval=5, repetitions=2, due_date=TODAY, lapses=0)
    s2 = update(s, 0, TODAY)
    assert s2.ease == pytest.approx(1.3)


def test_lapse_already_at_floor_stays():
    s = CardState(ease=1.3, interval=5, repetitions=2, due_date=TODAY, lapses=2)
    s2 = update(s, 0, TODAY)
    assert s2.ease == pytest.approx(1.3)


# --- first repetition (grade >= 3, rep was 0 → becomes 1) ---

def test_first_rep_interval_is_1():
    s = initial_state(TODAY)
    s2 = update(s, 4, TODAY)
    assert s2.repetitions == 1
    assert s2.interval == 1
    assert s2.due_date == TODAY + timedelta(days=1)


# --- second repetition (rep was 1 → becomes 2) ---

def test_second_rep_interval_is_6():
    s = CardState(ease=2.5, interval=1, repetitions=1, due_date=TODAY, lapses=0)
    s2 = update(s, 4, TODAY)
    assert s2.repetitions == 2
    assert s2.interval == 6
    assert s2.due_date == TODAY + timedelta(days=6)


# --- subsequent repetitions (rep >= 2 → interval = round(prev * ease)) ---

def test_subsequent_rep_good_grows_interval():
    s = CardState(ease=2.5, interval=6, repetitions=2, due_date=TODAY, lapses=0)
    s2 = update(s, 4, TODAY)
    assert s2.interval == round(6 * 2.5)
    assert s2.repetitions == 3


def test_subsequent_rep_easy_raises_ease():
    s = CardState(ease=2.5, interval=6, repetitions=2, due_date=TODAY, lapses=0)
    s2 = update(s, 5, TODAY)
    assert abs(s2.ease - 2.6) < 1e-9
    assert s2.interval == round(6 * 2.6)  # new ease used for interval


def test_subsequent_rep_hard_lowers_ease():
    s = CardState(ease=2.5, interval=6, repetitions=2, due_date=TODAY, lapses=0)
    s2 = update(s, 3, TODAY)
    assert abs(s2.ease - 2.35) < 1e-9
    assert s2.interval == round(6 * 2.35)  # new ease used for interval


def test_hard_ease_clamped_at_floor():
    s = CardState(ease=1.35, interval=6, repetitions=2, due_date=TODAY, lapses=0)
    s2 = update(s, 3, TODAY)
    assert s2.ease == pytest.approx(1.3)


def test_again_on_passing_card_is_lapse():
    s = CardState(ease=2.5, interval=10, repetitions=5, due_date=TODAY, lapses=1)
    s2 = update(s, 0, TODAY)
    assert s2.lapses == 2
    assert s2.repetitions == 0
    assert s2.interval == 1


def test_lapses_not_incremented_on_pass():
    s = CardState(ease=2.5, interval=6, repetitions=2, due_date=TODAY, lapses=3)
    s2 = update(s, 4, TODAY)
    assert s2.lapses == 3


def test_due_date_advances_by_interval():
    s = CardState(ease=2.5, interval=6, repetitions=2, due_date=TODAY, lapses=0)
    s2 = update(s, 4, TODAY)
    assert s2.due_date == TODAY + timedelta(days=s2.interval)
