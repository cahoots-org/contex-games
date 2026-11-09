from sleuth.case import Crime, Record
from sleuth.cases import CaseFile
from sleuth.credit import credits
from sleuth.tests.test_case import make_town

TOWN = make_town()
CRIME = Crime("case-1", "steal", "bike", "v3", "v1", "elm street", 1, "night", 1400, "opportunity",
              "Someone stole Dana Reyes's bike on Elm Street last night.")
CLIP = Record("r-clip", "case-1", "clip", "elm street", "11:40pm", "A tall figure.", traits={"height": "tall"})
WITNESS = Record("r-seen", "case-1", "memory", "elm street", "11:40pm", "Someone tall.", "v2", {"height": "tall"})


def record(rid, kind, holder="", sound=False, disproof=None, **fields):
    return Record(rid, "case-1", kind, fields.pop("place", "elm street"), "11:40pm", "", holder,
                  fields.pop("traits", {}), sound=sound, disproof=disproof, **fields)


def file_of(*records, **fields):
    return CaseFile(CRIME, {r.id: r for r in (WITNESS, CLIP, *records)}, "open", **fields)


def credited(file, cited, *held):
    return credits(file, cited, {r.id: r for r in (*cited, *held)}, TOWN)


def test_catching_a_false_sighting_earns_credit():
    fake = record("r-fake", "memory", "v7", disproof=CLIP.id, traits={"coat": "green raincoat"})
    assert credited(file_of(fake), [CLIP], fake) == [
        "Listeners loved how you caught Jo's sighting of someone in a green raincoat."]


def test_a_cited_false_piece_earns_no_credit_for_catching_it():
    fake = record("r-fake", "memory", "v7", disproof=CLIP.id, traits={"coat": "green raincoat"})
    assert credited(file_of(fake), [CLIP, fake]) == ["A solid episode."]


def test_breaking_the_accomplices_alibi_earns_credit():
    log = record("r-log", "log", sound=True, place="gym", who="v5")
    word = record("r-word", "statement", "v5", disproof=log.id, who="v3")
    assert credited(file_of(log, accomplice="v5"), [CLIP, log], word) == [
        "Listeners loved how you broke Hal's alibi for Fay."]


def test_seeing_through_a_liars_story_earns_credit():
    claim = record("r-claim", "statement", "v6")
    exposed = record("r-out", "statement", "v7", sound=True, who="v6")
    file = file_of(liars={"v6": {"kind": "covering", "exposer": "v7"}})
    assert credited(file, [CLIP], claim, exposed) == ["Listeners loved that you didn't fall for Ivy's story."]
    assert credited(file, [CLIP], claim) == ["A solid episode."]


def test_a_liar_exposed_by_a_log_in_the_notebook_earns_credit():
    log = record("r-log", "log", sound=True, place="gym", who="v6")
    claim = record("r-claim", "statement", "v6", disproof=log.id)
    file = file_of(log, liars={"v6": {"kind": "somewhere", "exposer": log.id}})
    assert credited(file, [CLIP], claim, log) == ["Listeners loved that you didn't fall for Ivy's story."]


def test_cracking_it_without_a_witness_earns_credit():
    file = CaseFile(CRIME, {CLIP.id: CLIP}, "open")
    assert credited(file, [CLIP]) == ["Listeners loved that you cracked it without a single witness."]
    victim = record("r-victim", "memory", "v1", sound=True)
    file.records[victim.id] = victim
    assert credited(file, [CLIP]) == ["Listeners loved that you cracked it without a single witness."]


def test_each_kind_of_credit_counts_once():
    fakes = [record(f"r-fake{n}", "memory", "v7", disproof=CLIP.id, traits={"coat": "green raincoat"}) for n in (1, 2)]
    claim = record("r-claim", "statement", "v6")
    exposed = record("r-out", "statement", "v7", sound=True, who="v6")
    file = CaseFile(CRIME, {CLIP.id: CLIP}, "open", liars={"v6": {"kind": "covering", "exposer": "v7"}})
    assert credited(file, [CLIP], *fakes, claim, exposed) == [
        "Listeners loved how you caught Jo's sighting of someone in a green raincoat.",
        "Listeners loved that you didn't fall for Ivy's story.",
        "Listeners loved that you cracked it without a single witness.",
    ]


def test_a_plain_held_episode_is_a_solid_episode():
    assert credited(file_of(), [CLIP, WITNESS]) == ["A solid episode."]


def test_credit_counts_only_this_cases_records():
    fake = record("r-fake", "memory", "v7", disproof=CLIP.id, traits={"coat": "green raincoat"})
    fake.case = "case-0"
    assert credited(file_of(), [CLIP], fake) == ["A solid episode."]
