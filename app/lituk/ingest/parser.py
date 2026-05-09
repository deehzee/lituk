import re
import subprocess


_DATE_RE = re.compile(r'\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}')
_PAGENUM_RE = re.compile(r'^\d+/\d+$', re.MULTILINE)
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
