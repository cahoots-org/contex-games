from sleuth.case import Crime, Record
from sleuth.episode import holds

CRIME = Crime("case-1", "steal", "bike", "v3", "v1", "elm street", 1, "night", 1400, "opportunity",
              "Someone stole Dana Reyes's bike on Elm Street last night.")


def record(rid="r-1", case="case-1", kind="memory", sound=True):
    return Record(rid, case, kind, "elm street", "11:40pm", "someone tall walked off with something", "v2", sound=sound)


def test_holds_with_the_right_culprit_and_sound_records():
    assert holds(CRIME, "v3", [record(), record("r-2", kind="clip"), record("r-3", kind="log")])


def test_rejects_the_wrong_culprit():
    assert not holds(CRIME, "v2", [record()])


def test_rejects_a_cover_story_statement():
    assert not holds(CRIME, "v3", [record(), record("r-2", kind="statement", sound=False)])


def test_rejects_no_evidence():
    assert not holds(CRIME, "v3", [])


def test_rejects_records_from_another_case():
    assert not holds(CRIME, "v3", [record(case="case-0")])
