from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class CardState:
    ease: float
    interval: int
    repetitions: int
    due_date: date
    lapses: int


def initial_state(today: date) -> CardState:
    return CardState(
        ease=2.5,
        interval=0,
        repetitions=0,
        due_date=today,
        lapses=0,
    )


_EASE_DELTA = {3: -0.15, 4: 0.0, 5: 0.10}
_EASE_FLOOR = 1.3


def update(state: CardState, grade: int, today: date) -> CardState:
    if grade < 3:
        new_ease = max(_EASE_FLOOR, state.ease - 0.2)
        new_interval = 1
        new_reps = 0
        new_lapses = state.lapses + 1
    else:
        new_ease = max(_EASE_FLOOR, state.ease + _EASE_DELTA[grade])
        new_reps = state.repetitions + 1
        if new_reps == 1:
            new_interval = 1
        elif new_reps == 2:
            new_interval = 6
        else:
            new_interval = round(state.interval * new_ease)
        new_lapses = state.lapses

    return CardState(
        ease=new_ease,
        interval=new_interval,
        repetitions=new_reps,
        due_date=today + timedelta(days=new_interval),
        lapses=new_lapses,
    )
