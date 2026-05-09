from lituk.review.presenter import Prompt
from lituk.review.session import SessionResult


_LETTER_TO_GRADE = {"a": 0, "h": 3, "g": 4, "e": 5}


def _parse_answer(raw: str, n_choices: int) -> list[int]:
    letters = [c.strip().upper() for c in raw.replace(",", " ").split()]
    indices = []
    for l in letters:
        if len(l) == 1 and "A" <= l <= chr(ord("A") + n_choices - 1):
            idx = ord(l) - ord("A")
            if idx not in indices:
                indices.append(idx)
    return indices


class TerminalUI:
    def __init__(self) -> None:
        self._card_num = 0

    def show_prompt(self, prompt: Prompt) -> list[int]:
        self._card_num += 1
        print(f"\n--- Card {self._card_num} ---")
        print(prompt.text)
        for i, choice in enumerate(prompt.choices):
            print(f"  {chr(ord('A') + i)}) {choice}")
        if prompt.is_multi:
            hint = " (select TWO, e.g. A,C)"
        else:
            hint = ""
        while True:
            raw = input(f"Your answer{hint}: ").strip()
            indices = _parse_answer(raw, len(prompt.choices))
            if indices:
                return indices
            print("  Invalid — enter one or more letters (e.g. A or A,C).")

    def show_feedback(self, prompt: Prompt, correct: bool) -> int:
        if correct:
            print("  Correct!")
            while True:
                raw = input(
                    "  Grade: [a]gain  [h]ard  [g]ood  [e]asy: "
                ).strip().lower()
                if raw in _LETTER_TO_GRADE:
                    return _LETTER_TO_GRADE[raw]
                print("  Enter a, h, g, or e.")
        else:
            correct_text = ", ".join(
                prompt.choices[i] for i in sorted(prompt.correct_indices)
            )
            print(f"  Wrong! Answer: {correct_text}")
            return 0

    def show_summary(self, result: SessionResult) -> None:
        pct = (
            round(100 * result.correct / result.total)
            if result.total else 0
        )
        print(
            f"\n--- Session complete: {result.correct}/{result.total}"
            f" ({pct}%) ---"
        )
        if result.weak_facts:
            print(f"  Weak cards this session: {len(result.weak_facts)}")
