import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDS = re.compile(r"\b(church|chapel|priest|pious|pray|sermon|religio\w*)\b", re.I)


def test_no_religion_in_code_or_copy():
    files = [*ROOT.glob("*.py"), ROOT / "static" / "index.html"]
    assert not [f.name for f in files if WORDS.search(f.read_text())]
