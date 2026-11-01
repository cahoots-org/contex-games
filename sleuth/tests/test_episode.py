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
    log = record("r-2", kind="log", who="v4", traits={})
    word = record("r-9", kind="statement", sound=False, traits={})
    assert holds(CRIME, "v3", TRAITS, [record(), log, word])
    word.disproof = "r-2"
    assert not holds(CRIME, "v3", TRAITS, [record(), log, word])


def test_a_description_never_clashes_with_a_sighting():
    described = record("r-2", kind="statement", traits={"height": "short"})
    stray = record("r-9", sound=False, traits={"coat": "green raincoat", "height": "tall"})
    assert holds(CRIME, "v3", TRAITS, [record(kind="log", who="v3", traits={}), described, stray])


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
    return why_wrong(named, cited, {r.id: r for r in cited}, TOWN, {r.id: r for r in records})


def test_a_false_memory_is_answered_by_the_camera_that_shows_otherwise():
    fake = piece("r-1", "memory", "v7", "r-2", traits={"coat": "green raincoat"})
    clip = record("r-2", kind="clip", traits={"height": "tall", "coat": "black puffer"})
    assert note("v2", [fake, clip]) == \
        "Jo's sighting of someone in a green raincoat: the Elm Street camera shows a black puffer."


def test_a_camera_shows_a_height_as_someone_of_it():
    fake = piece("r-1", "memory", "v7", "r-2", traits={"gender": "woman", "height": "short"})
    clip = record("r-2", kind="clip", traits={"height": "tall", "coat": "black puffer"}, place="town hall")
    assert note("v2", [fake, clip]) == "Jo's sighting of a short woman: the town hall camera shows someone tall."


def test_a_range_memory_is_labelled_as_the_witness_put_it():
    fake = piece("r-1", "memory", "v7", "r-2", traits={"coat": "in a dark coat"})
    clue = record("r-2", kind="clue", traits={"coat": "green raincoat"})
    clue.text = "A thread on Elm Street, snagged from someone in a green raincoat."
    assert note("v2", [fake, clue]) == \
        "Jo's sighting of someone in a dark coat: the thread on Elm Street shows a green raincoat."


def test_a_log_puts_whoever_left_a_trace_at_the_scene():
    fake = piece("r-1", "clue", "", "r-2", text="A thread at the gym, snagged from someone in a grey hoodie.",
                 place="gym")
    log = record("r-2", kind="log", place="gym", who="v4")
    assert note("v2", [fake, log]) == "The thread at the gym: the gym's check-ins put Gus Okafor there at 11:40pm."


def test_a_log_shows_a_liar_where_they_were():
    fake = piece("r-1", "statement", "v6", "r-2")
    log = record("r-2", kind="log", place="bar", who="v6")
    assert note("v2", [fake, log]) == "Ivy's word: the bar's tabs put Ivy Burke there at 11:40pm."


def test_a_log_that_leaves_someone_out_says_so():
    fake = piece("r-1", "statement", "v7", "r-2", who="v5")
    log = record("r-2", kind="log", place="bar", who="v4")
    assert note("v2", [fake, log]) == "Jo's word: the bar's tabs don't have Hal Burke."


def test_a_false_receipt_and_a_false_camera_clip_have_labels():
    receipt = piece("r-1", "clue", text="A grocery receipt dropped at the grocery, stamped 11:00pm.", place="grocery")
    assert note("v2", [receipt]) == "The receipt at the grocery: it doesn't hold up."
    clip = piece("r-2", "clip", place="elm street")
    assert note("v2", [clip]) == "The Elm Street camera: it doesn't hold up."


def test_a_disproof_outside_the_notebook_is_named_by_its_source_kind():
    fake = piece("r-1", "statement", "v7", "r-9")
    for kind, source in (("clip", "a camera"), ("log", "a log"), ("memory", "a witness"), ("clue", "a trace"),
                         ("statement", "an account")):
        proof = record("r-9", kind=kind)
        assert note("v2", [fake], [proof]) == f"Jo's word: {source} says otherwise."


def test_a_lie_told_in_play_has_no_disproof_to_name():
    assert note("v2", [piece("r-1", "statement", "v7")]) == "Jo's word: it doesn't hold up."


def test_the_first_false_piece_is_the_one_named():
    first, second = piece("r-1", "statement", "v7"), piece("r-2", "statement", "v8")
    assert note("v2", [first, second]).startswith("Jo's word")


def test_sound_evidence_that_points_elsewhere_or_nowhere_reads_the_same():
    assert note("v2", [record()]) == "Your evidence doesn't point at Eli Reyes."
    assert note("v3", [record(kind="log", who="v4")]) == "Your evidence doesn't point at Fay Okafor."


def test_the_culprit_is_named_like_anyone_who_said_a_piece_cited():
    assert note("v2", [piece("r-1", "statement", "v3")]) == "Fay's word: it doesn't hold up."


def test_the_note_names_the_culprit_only_as_the_holder_of_a_piece_cited():
    mistake = piece("r-1", "memory", "v7", "r-2", traits={"coat": "green raincoat"})
    clip = record("r-2", kind="clip", traits={"coat": "black puffer"})
    trace = piece("r-3", "clue", "", "r-4", text="A thread at the gym, snagged from someone tall.", place="gym")
    log = record("r-4", kind="log", place="gym", who="v4")
    cover = piece("r-5", "statement", "v3")
    for named in ("v1", "v2", "v4", "v5"):
        for cited in ([record()], [mistake, clip], [trace, log], [record(), mistake], [cover], [record(), cover]):
            said = note(named, cited)
            holds_one = any(r.holder == "v3" for r in cited)
            assert "Fay" not in said.replace("Fay's word", "") and ("Fay" in said) == holds_one
