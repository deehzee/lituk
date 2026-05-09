import json
import sqlite3
from pathlib import Path


def load_summaries(summaries_dir: str) -> str:
    path = Path(summaries_dir)
    parts = []
    for md_file in sorted(path.glob("*.md")):
        parts.append(f"## {md_file.stem}\n\n{md_file.read_text()}")
    return "\n\n---\n\n".join(parts)


def tag_facts(
    conn: sqlite3.Connection,
    client,
    summaries: str,
    batch_size: int = 50,
    retag: bool = False,
) -> int:
    if retag:
        rows = conn.execute(
            "SELECT id, question_text, correct_answer_text FROM facts"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, question_text, correct_answer_text"
            " FROM facts WHERE topic IS NULL"
        ).fetchall()

    facts = [dict(r) for r in rows]
    total_tagged = 0

    for start in range(0, len(facts), batch_size):
        batch = facts[start : start + batch_size]
        numbered = "\n".join(
            f"ID={f['id']}: Q: {f['question_text']} "
            f"A: {f['correct_answer_text']}"
            for f in batch
        )
        prompt = (
            "You are classifying Life in the UK (LITUK) exam questions"
            " by chapter.\n\n"
            f"CHAPTER SUMMARIES:\n{summaries}\n\n"
            "FACTS TO CLASSIFY:\n"
            f"{numbered}\n\n"
            "For each fact, determine which chapter (1-5) it belongs to"
            " based on the summaries above.\n"
            "Reply ONLY with a JSON array, no explanation:\n"
            '[{"id": <fact_id>, "topic": <1-5>}, ...]'
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        results = json.loads(text)
        for item in results:
            conn.execute(
                "UPDATE facts SET topic=? WHERE id=?",
                (item["topic"], item["id"]),
            )
        conn.commit()
        total_tagged += len(results)

    return total_tagged
