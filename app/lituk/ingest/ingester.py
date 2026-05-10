import json
import pathlib
import re
import sqlite3

from lituk.db import get_or_create_fact, init_db
from lituk.ingest.parser import parse_pdf


def ingest_pdf(
    conn: sqlite3.Connection, pdf_path: str, test_num: int
) -> int:
    rows = parse_pdf(pdf_path, test_num)
    inserted = 0
    for row in rows:
        # Repair stale facts that previously had an empty correct_answer_text
        # due to the no-space answer-line parsing bug.
        if row['correct_answer_text']:
            conn.execute(
                "UPDATE facts SET correct_answer_text = ?"
                " WHERE question_text = ? AND correct_answer_text = ''",
                (row['correct_answer_text'], row['question_text']),
            )
        fact_id = get_or_create_fact(
            conn,
            row['question_text'],
            row['correct_answer_text']
        )
        conn.execute(
            """
            INSERT INTO questions
                (source_test, q_number, question_text, choices,
                 correct_letters, explanation, is_true_false, is_multi,
                 fact_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_test, q_number) DO UPDATE SET
                question_text   = excluded.question_text,
                choices         = excluded.choices,
                correct_letters = excluded.correct_letters,
                explanation     = excluded.explanation,
                is_true_false   = excluded.is_true_false,
                is_multi        = excluded.is_multi,
                fact_id         = excluded.fact_id
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


def ingest_all(db_path: str, mock_tests_dir: str) -> None:
    conn = init_db(db_path)
    pdf_dir = pathlib.Path(mock_tests_dir)
    _num_re = re.compile(r'Practice Test #(\d+) of')
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        m = _num_re.search(pdf_path.name)
        if not m:
            continue
        test_num = int(m.group(1))
        ingest_pdf(conn, str(pdf_path), test_num)
    conn.close()
