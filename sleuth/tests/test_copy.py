import ast
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDS = re.compile(r"\b(church\w*|chapel\w*|priest\w*|pious|pray\w*|sermon\w*|religio\w*|cults?|creed\w*|preach\w*)\b", re.I)


def test_no_religion_in_code_or_copy():
    files = [f for f in ROOT.rglob("*.py") if f.name != "test_copy.py"]
    files += [ROOT / "README.md", ROOT / "static" / "index.html"]
    assert not [f.name for f in files if WORDS.search(f.read_text())]


MEDIEVAL = re.compile(r"\b(villages?|villagers?|lamps?|lamplit|newcomers?)\b", re.I)
JS_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`')


class Copy(HTMLParser):
    """The page's visible text and labels, and the sentences in its script."""

    def __init__(self):
        super().__init__()
        self.tag, self.found = "", []

    def handle_starttag(self, tag, attrs):
        self.tag = tag
        self.found += [v for k, v in attrs if k in ("aria-label", "placeholder", "title") and v]

    def handle_data(self, data):
        if self.tag == "script":
            self.found += [re.sub(r"\$\{[^}]*\}", "", s) for s in JS_STRING.findall(data) if " " in s]
        elif self.tag != "style":
            self.found.append(data)


def _sentences(path: Path) -> list[str]:
    """String constants with a space in them, outside docstrings: what players read and what models are told."""
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and " " in n.value and id(n) not in docs]


def test_no_medieval_village_in_copy_or_prompts():
    found = [s for f in ROOT.glob("*.py") for s in _sentences(f)]
    page = Copy()
    page.feed((ROOT / "static" / "index.html").read_text())
    found += page.found
    assert not [s for s in found if MEDIEVAL.search(s)]
