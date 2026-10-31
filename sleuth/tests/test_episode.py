from sleuth.case import Crime, Record
from sleuth.episode import holds, why_wrong
from sleuth.tests.test_case import make_town

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


def test_rejects_two_cover_story_statements():
    covers = [record(f"r-{n}", kind="statement", sound=False) for n in (2, 3)]
    assert not holds(CRIME, "v3", TRAITS, [record(), *covers])


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


def test_one_stray_piece_that_clashes_with_nothing_still_holds():
    stray = record("r-9", kind="statement", sound=False, traits={})
    assert holds(CRIME, "v3", TRAITS, [record(), stray])


def test_two_false_pieces_sink_it():
    strays = [record(f"r-{n}", kind="statement", sound=False, traits={}) for n in (8, 9)]
    assert not holds(CRIME, "v3", TRAITS, [record(), *strays])


def test_a_false_piece_cited_beside_what_disproves_it_sinks_it():
    clip = record("r-2", kind="clip", traits={"coat": "black puffer"})
    memory = record("r-9", sound=False, traits={"coat": "green raincoat"})
    memory.disproof = "r-2"
    assert not holds(CRIME, "v3", TRAITS, [record(), clip, memory])


def test_a_false_piece_that_clashes_in_a_trait_sinks_it():
    memory = record("r-9", sound=False, traits={"coat": "green raincoat"})
    assert not holds(CRIME, "v3", TRAITS, [record(), record("r-2", traits={"coat": "black puffer"}), memory])


def test_overlapping_ranges_do_not_clash():
    log = record(kind="log", who="v3", traits={})
    stray = record("r-9", sound=False, traits={"height": "not tall"})
    assert holds(CRIME, "v3", TRAITS, [log, record("r-2", traits={"height": "short"}), stray])


def test_a_range_clashes_with_an_exact_value_outside_it():
    log = record(kind="log", who="v3", traits={})
    stray = record("r-9", sound=False, traits={"height": "tall"})
    assert not holds(CRIME, "v3", TRAITS, [log, record("r-2", traits={"height": "not tall"}), stray])


def test_a_false_piece_alone_never_holds():
    assert not holds(CRIME, "v3", TRAITS, [record(sound=False)])


TOWN = make_town()


def piece(rid, kind, holder="", disproof=None, text="", **fields):
    return Record(rid, "case-1", kind, fields.pop("place", "elm street"), "11:40pm", text, holder,
                  fields.pop("traits", {}), sound=False, disproof=disproof, **fields)


def note(named, cited, records=()):
    return why_wrong(CRIME, named, cited, {r.id: r for r in cited}, TOWN, {r.id: r for r in records})


def test_a_false_memory_is_answered_by_the_camera_that_shows_otherwise():
    fake = piece("r-1", "memory", "v7", "r-2", traits={"coat": "green raincoat"})
    clip = record("r-2", kind="clip", traits={"coat": "black puffer"}, place="library")
    assert why_wrong(CRIME, "v2", [fake, clip], {r.id: r for r in (fake, clip)}, TOWN, {}) == \
        "Jo's green raincoat: the library camera shows a black puffer."


def test_a_range_memory_is_labelled_as_the_witness_put_it():
    fake = piece("r-1", "memory", "v7", "r-2", traits={"coat": "in a dark coat"})
    log = record("r-2", kind="log", place="gym", who="v4")
    assert why_wrong(CRIME, "v2", [fake, log], {r.id: r for r in (fake, log)}, TOWN, {}) == \
        "Jo's in a dark coat: the gym's check-ins."


def test_a_false_clue_is_labelled_by_its_trace_and_place():
    fake = piece("r-1", "clue", "", "r-2", text="A thread on Elm Street, snagged from a tall figure.", place="elm street")
    log = record("r-2", kind="log", place="bar", who="v4")
    assert why_wrong(CRIME, "v2", [fake, log], {r.id: r for r in (fake, log)}, TOWN, {}) == \
        "the thread on Elm Street: the bar's tabs."


def test_a_false_receipt_and_a_false_camera_clip_have_labels():
    receipt = piece("r-1", "clue", text="A grocery receipt dropped at the grocery, stamped 11:00pm.", place="grocery")
    assert note("v2", [receipt]) == "the receipt at the grocery: someone's account says otherwise."
    clip = piece("r-2", "clip", place="bar")
    assert note("v2", [clip]) == "the bar camera: someone's account says otherwise."


def test_a_disproof_outside_the_notebook_is_named_by_its_source_kind():
    fake = piece("r-1", "statement", "v7", "r-9")
    for kind, source in (("clip", "camera"), ("log", "log"), ("memory", "witness"), ("clue", "trace"), ("statement", "account")):
        proof = record("r-9", kind=kind)
        assert note("v2", [fake], [proof]) == f"Jo's word: a {source} says otherwise."


def test_a_lie_told_in_play_has_no_disproof_to_name():
    assert note("v2", [piece("r-1", "statement", "v7")]) == "Jo's word: someone's account says otherwise."


def test_the_first_false_piece_is_the_one_named():
    first, second = piece("r-1", "statement", "v7"), piece("r-2", "statement", "v8")
    assert note("v2", [first, second]).startswith("Jo's word")


def test_sound_evidence_that_points_elsewhere_or_nowhere_reads_the_same():
    assert note("v2", [record()]) == "Your evidence doesn't point at Eli Reyes."
    assert note("v3", [record(kind="log", who="v4")]) == "Your evidence doesn't point at Fay Okafor."


def test_the_note_never_names_the_culprit_of_an_open_case():
    cover = piece("r-1", "statement", "v3")
    for named in ("v1", "v2", "v4", "v5"):
        for cited in ([record()], [cover], [record(), cover]):
            assert "Fay" not in note(named, cited)
