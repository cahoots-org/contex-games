import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDS = re.compile(r"\b(church\w*|chapel\w*|priest\w*|pious|pray\w*|sermon\w*|religio\w*)\b", re.I)


def test_no_religion_in_code_or_copy():
    files = [f for f in ROOT.rglob("*.py") if f.name != "test_copy.py"]
    files += [ROOT / "README.md", ROOT / "static" / "index.html"]
    assert not [f.name for f in files if WORDS.search(f.read_text())]
