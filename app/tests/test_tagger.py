import json
import re
from unittest.mock import MagicMock

import pytest

from lituk.db import get_or_create_fact, init_db
from lituk.tag.tagger import load_summaries, tag_facts


def _mock_client_dynamic():
    """Anthropic mock that parses fact IDs from the prompt and returns
    topic=3 for each."""
    client = MagicMock()

    def _respond(**kwargs):
        text = kwargs["messages"][0]["content"]
        ids = [int(m) for m in re.findall(r"ID=(\d+):", text)]
        response = MagicMock()
        msg = MagicMock()
        msg.text = json.dumps([{"id": fid, "topic": 3} for fid in ids])
        response.content = [msg]
        return response

    client.messages.create.side_effect = _respond
    return client


def _insert_fact(conn, q_text, a_text, topic=None):
    fid = get_or_create_fact(conn, q_text, a_text)
    if topic is not None:
        conn.execute("UPDATE facts SET topic=? WHERE id=?", (topic, fid))
        conn.commit()
    return fid


@pytest.fixture
def conn(tmp_path):
    c = init_db(str(tmp_path / "test.db"))
    yield c
    c.close()


def test_tag_facts_tags_untagged_fact(conn):
    fid = _insert_fact(conn, "What is Parliament?", "The legislature")
    count = tag_facts(conn, _mock_client_dynamic(), "SUMMARIES")
    assert count == 1
    row = conn.execute("SELECT topic FROM facts WHERE id=?", (fid,)).fetchone()
    assert row["topic"] == 3


def test_tag_facts_skips_already_tagged(conn):
    _insert_fact(conn, "What is Parliament?", "The legislature", topic=5)
    client = _mock_client_dynamic()
    count = tag_facts(conn, client, "SUMMARIES")
    assert count == 0
    client.messages.create.assert_not_called()


def test_tag_facts_retag_processes_tagged_facts(conn):
    _insert_fact(conn, "What is Parliament?", "The legislature", topic=5)
    client = _mock_client_dynamic()
    count = tag_facts(conn, client, "SUMMARIES", retag=True)
    assert count == 1
    client.messages.create.assert_called_once()


def test_tag_facts_batches_101_facts_into_3_calls(conn):
    for i in range(101):
        _insert_fact(conn, f"Q{i}?", f"A{i}")
    client = _mock_client_dynamic()
    count = tag_facts(conn, client, "SUMMARIES", batch_size=50)
    assert count == 101
    assert client.messages.create.call_count == 3


def test_tag_facts_idempotent(conn):
    _insert_fact(conn, "What is Parliament?", "The legislature")
    tag_facts(conn, _mock_client_dynamic(), "SUMMARIES")
    client2 = _mock_client_dynamic()
    tag_facts(conn, client2, "SUMMARIES")
    client2.messages.create.assert_not_called()


def test_load_summaries_concatenates_files(tmp_path):
    (tmp_path / "ch1.md").write_text("Chapter 1 content here")
    (tmp_path / "ch2.md").write_text("Chapter 2 content here")
    result = load_summaries(str(tmp_path))
    assert "Chapter 1 content here" in result
    assert "Chapter 2 content here" in result


def test_load_summaries_includes_filenames(tmp_path):
    (tmp_path / "ch3_history.md").write_text("History content")
    result = load_summaries(str(tmp_path))
    assert "ch3_history" in result


def test_tag_facts_strips_markdown_code_blocks(conn):
    fid = _insert_fact(conn, "What is Parliament?", "The legislature")
    client = MagicMock()

    def _respond_with_fences(**kwargs):
        response = MagicMock()
        msg = MagicMock()
        msg.text = f'```json\n[{{"id": {fid}, "topic": 3}}]\n```'
        response.content = [msg]
        return response

    client.messages.create.side_effect = _respond_with_fences
    count = tag_facts(conn, client, "SUMMARIES")
    assert count == 1
    row = conn.execute("SELECT topic FROM facts WHERE id=?", (fid,)).fetchone()
    assert row["topic"] == 3


def test_main_tags_and_exits(tmp_path):
    import runpy
    from unittest.mock import patch

    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    _insert_fact(conn, "What is Parliament?", "The legislature")
    conn.close()

    summaries_dir = str(tmp_path / "summaries")
    import os
    os.makedirs(summaries_dir)
    (tmp_path / "summaries" / "ch1.md").write_text("Chapter 1")

    mock_client = _mock_client_dynamic()

    with patch("anthropic.Anthropic", return_value=mock_client), \
         patch("sys.stdout"):
        with pytest.raises(SystemExit) as exc:
            from lituk.tag import main
            main(["--db", db_path, "--summaries", summaries_dir])
    assert exc.value.code == 0

    conn2 = init_db(db_path)
    row = conn2.execute("SELECT topic FROM facts").fetchone()
    conn2.close()
    assert row["topic"] == 3


def test_tag_main_module_calls_main():
    import runpy
    from unittest.mock import patch

    with patch("lituk.tag.main") as mock_main:
        runpy.run_module("lituk.tag", run_name="__main__")
    mock_main.assert_called_once_with()
