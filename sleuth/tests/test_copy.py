import ast
import re
from html.parser import HTMLParser
from pathlib import Path

from sleuth.districts import FORMED, TOLD, WATCH_NAMES, WOUND_DOWN
from sleuth.faith import FAITH as WORDS, GORE

ROOT = Path(__file__).resolve().parent.parent
# The word lists themselves, and the tests that feed them religious or gory residents, posts and talk.
LISTS = ("test_copy.py", "faith.py", "test_town_gen.py", "test_chatter.py")


def test_no_religion_in_code_or_copy():
    files = [f for f in ROOT.rglob("*.py") if f.name not in LISTS]
    files += [ROOT / "README.md", ROOT / "static" / "index.html"]
    assert not [f.name for f in files if WORDS.search(f.read_text())]


def test_no_gore_in_code_or_copy():
    files = [f for f in ROOT.rglob("*.py") if f.name not in LISTS]
    files += [ROOT / "README.md", ROOT / "static" / "index.html"]
    assert not [f.name for f in files if GORE.search(f.read_text().replace("GORE", ""))]


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


META = re.compile(r"\b(practi[cs]e|tutorial|real town|you're in)\b", re.I)
OVERLAY = ("replay", "coach-tag", "coach-skip", "intro-tag", "handoff-tag")


def test_no_talk_of_a_tutorial_in_copy():
    found = [s for f in ROOT.glob("*.py") for s in _sentences(f)]
    page = Copy()
    # The owner's exceptions: the menu control that plays the first case again, and the tutorial layer's own labels.
    html = (ROOT / "static" / "index.html").read_text()
    page.feed(re.sub(f'(id="(?:{"|".join(OVERLAY)})"[^>]*>)[^<]*', r"\1", html))
    found += page.found
    assert not [s for s in found if META.search(s)]


def test_watch_names_are_secular():
    copy = [*WATCH_NAMES, FORMED, TOLD, WOUND_DOWN]
    assert not [s for s in copy if WORDS.search(s) or MEDIEVAL.search(s)]
