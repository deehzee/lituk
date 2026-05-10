import json
import re
import subprocess


_ANSWERS_SPLIT = re.compile(r'\nAnswers\n')
_ANSWER_LINE_RE = re.compile(r'^([A-D])\s*-\s*.+$')
_ANSWER_NUM_SPLIT = re.compile(r'\n(\d+)\.\n')
_CHOICE_LINE_RE = re.compile(r'^([A-D])\.$')
_DATE_RE = re.compile(r'\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}')
_PAGENUM_RE = re.compile(r'^\d+/\d+$', re.MULTILINE)
_QUESTION_SPLIT = re.compile(r'\n(\d+)\. ')
_TITLE_RE = re.compile(
    r'Life in the UK Test - Practice Test #\d+ of 45 \[Updated for \d+\]'
)
_URL_RE = re.compile(r'https?://\S+')


def extract_raw(pdf_path: str) -> str:
    result = subprocess.run(
        ['pdftotext', pdf_path, '-'],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def clean_text(text: str) -> str:
    text = _DATE_RE.sub('', text)
    text = _PAGENUM_RE.sub('', text)
    text = _TITLE_RE.sub('', text)
    text = _URL_RE.sub('', text)
    return text


def parse_questions_block(block: str) -> list[dict]:
    parts = _QUESTION_SPLIT.split(block)
    # parts: [preamble, num, body, num, body, ...]
    questions = []
    for i in range(1, len(parts), 2):
        qnum = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ''
        lines = [l.strip() for l in body.split('\n') if l.strip()]

        choice_start = next(
            (j for j, l in enumerate(lines)
             if _CHOICE_LINE_RE.match(l)),
            None,
        )
        if choice_start is None:
            q_text = ' '.join(lines)
            choices, letters = [], []
        else:
            q_text = ' '.join(lines[:choice_start])
            raw = lines[choice_start:]
            choices, letters = [], []
            cur_letter, cur_words = None, []
            for line in raw:
                m = _CHOICE_LINE_RE.match(line)
                if m:
                    if cur_letter is not None:
                        choices.append(' '.join(cur_words))
                        letters.append(cur_letter)
                    cur_letter, cur_words = m.group(1), []
                elif cur_letter is not None:
                    cur_words.append(line)
            if cur_letter is not None:
                choices.append(' '.join(cur_words))
                letters.append(cur_letter)

        is_tf = (
            len(choices) == 2
            and {c.lower() for c in choices}
            == {'true', 'false'}
        )
        is_multi = bool(re.search(r'\bTWO\b', q_text, re.IGNORECASE))

        questions.append({
            'q_number': qnum,
            'question_text': q_text,
            'choices': choices,
            'choice_letters': letters,
            'is_true_false': is_tf,
            'is_multi': is_multi,
        })
    return questions


def parse_answers_block(block: str) -> list[dict]:
    parts = _ANSWER_NUM_SPLIT.split(block)
    # parts: [preamble, num, body, num, body, ...]
    answers = []
    for i in range(1, len(parts), 2):
        qnum = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ''
        lines = [l.strip() for l in body.split('\n') if l.strip()]

        correct_letters, explanation_lines = [], []
        for line in lines:
            if not explanation_lines and _ANSWER_LINE_RE.match(line):
                correct_letters.append(line[0])
            else:
                explanation_lines.append(line)

        answers.append({
            'q_number': qnum,
            'correct_letters': correct_letters,
            'explanation': ' '.join(explanation_lines),
        })
    return answers


def parse_pdf(pdf_path: str, test_num: int) -> list[dict]:
    raw = extract_raw(pdf_path)
    text = clean_text(raw)

    halves = _ANSWERS_SPLIT.split(text, maxsplit=1)
    if len(halves) != 2:
        raise ValueError(f"No 'Answers' section found in {pdf_path}")

    q_block, a_block = halves
    questions = parse_questions_block(q_block)
    answers = parse_answers_block('\n' + a_block)
    ans_map = {a['q_number']: a for a in answers}

    rows = []
    for q in questions:
        n = q['q_number']
        ans = ans_map.get(n, {'correct_letters': [], 'explanation': ''})
        letter_to_text = dict(zip(q['choice_letters'], q['choices']))
        correct_texts = [
            letter_to_text.get(l, l) for l in ans['correct_letters']
        ]
        rows.append({
            'source_test':         test_num,
            'q_number':            n,
            'question_text':       q['question_text'],
            'choices':             json.dumps(q['choices']),
            'correct_letters':     ans['correct_letters'],
            'correct_answer_text': ', '.join(correct_texts),
            'explanation':         ans.get('explanation', ''),
            'is_true_false':       int(q['is_true_false']),
            'is_multi':            int(q['is_multi']),
        })
    return rows
