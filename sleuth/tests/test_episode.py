from sleuth.case import Crime, Record
from sleuth.episode import holds

CRIME = Crime("case-1", "steal", "bike", "v3", "v1", "elm street", 1, "night", 1400, "opportunity",
              "Someone stole Dana Reyes's bike on Elm Street last night.")
TRAITS = {"height": "tall", "coat": "black puffer", "hair": "dark"}


def record(rid="r-1", case="case-1", kind="memory", sound=True, traits=None, place="elm street", who=None):
    return Record(rid, case, kind, place, "11:40pm", "someone tall walked off with something", "v2",
                  {"height": "tall"} if traits is None else traits, who, sound)


def test_holds_with_the_right_culprit_and_sound_records():
    assert holds(CRIME, "v3", TRAITS, [record(), record("r-2", kind="clip"), record("r-3", kind="log", who="v3")])


def test_rejects_the_wrong_culprit():
    assert not holds(CRIME, "v2", TRAITS, [record()])


def test_rejects_a_cover_story_statement():
    assert not holds(CRIME, "v3", TRAITS, [record(), record("r-2", kind="statement", sound=False)])


def test_rejects_no_evidence():
    assert not holds(CRIME, "v3", TRAITS, [])


def test_rejects_records_from_another_case():
    assert not holds(CRIME, "v3", TRAITS, [record(case="case-0")])


def test_rejects_sound_records_that_point_at_no_one():
    unrelated = [record(kind="log", who="v4"), record("r-2", kind="statement", traits={}),
                 record("r-3", kind="log", who="v3", place="bar")]
    assert not holds(CRIME, "v3", TRAITS, unrelated)


def test_holds_on_a_clip_that_fits_the_culprit():
    clip = record("r-2", kind="clip", traits={"height": "tall", "coat": "black puffer"})
    assert holds(CRIME, "v3", TRAITS, [record(kind="log", who="v4"), clip])


def test_rejects_a_sighting_that_does_not_fit():
    assert not holds(CRIME, "v3", TRAITS, [record(traits={"height": "short"})])


def test_holds_on_a_log_naming_the_culprit_at_the_scene():
    assert holds(CRIME, "v3", TRAITS, [record(kind="log", who="v3", traits={})])


def test_a_housemates_asleep_statement_does_not_point_at_the_culprit():
    assert not holds(CRIME, "v3", TRAITS, [record(kind="statement", who="v3", place="oak street", traits={})])
