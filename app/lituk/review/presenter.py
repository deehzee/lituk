import json
import random
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    fact_id: int
    question_id: int
    text: str
    choices: list[str]
    correct_indices: list[int]
    is_multi: bool
    is_true_false: bool


def build_prompt(
    conn: sqlite3.Connection, fact_id: int, rng: random.Random
) -> Prompt:
    rows = conn.execute(
        "SELECT id, question_text, choices, correct_letters,"
        " is_true_false, is_multi FROM questions WHERE fact_id = ?",
        (fact_id,),
    ).fetchall()
    row = rng.choice(rows)

    choices: list[str] = json.loads(row["choices"])
    correct_letters: list[str] = json.loads(row["correct_letters"])

    letter_to_idx = {chr(ord("A") + i): i for i in range(len(choices))}
    original_correct = [letter_to_idx[l] for l in correct_letters]

    order = list(range(len(choices)))
    rng.shuffle(order)
    shuffled = [choices[i] for i in order]

    old_to_new = {old: new for new, old in enumerate(order)}
    new_correct = [old_to_new[i] for i in original_correct]

    return Prompt(
        fact_id=fact_id,
        question_id=row["id"],
        text=row["question_text"],
        choices=shuffled,
        correct_indices=new_correct,
        is_multi=bool(row["is_multi"]),
        is_true_false=bool(row["is_true_false"]),
    )


def grade_answer(prompt: Prompt, user_indices: list[int]) -> bool:
    return set(user_indices) == set(prompt.correct_indices)
