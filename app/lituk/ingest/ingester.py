import json
import sqlite3

from lituk.db import get_or_create_fact
from lituk.ingest.parser import parse_pdf


def ingest_pdf(
    conn: sqlite3.Connection, pdf_path: str, test_num: int
) -> int:
    rows = parse_pdf(pdf_path, test_num)
    inserted = 0
    for row in rows:
        fact_id = get_or_create_fact(
            conn,
            row['question_text'],
            row['correct_answer_text']
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO questions
                (source_test, q_number, question_text, choices,
                 correct_letters, explanation, is_true_false, is_multi,
                 fact_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row['source_test'],
                row['q_number'],
                row['question_text'],
                row['choices'],
                json.dumps(row['correct_letters']),
                row['explanation'],
                row['is_true_false'],
                row['is_multi'],
                fact_id,
            ),
        )
        inserted += conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    return inserted
