from random import Random

from sleuth.case import Crime
from sleuth.cases import CaseFile
from sleuth.lineage import Ids
from sleuth.photos import KEPT, Album, photo_json, posted
from sleuth.tests.test_cases import make_cases
from sleuth.tests.test_persist import VILLAGERS, build
from sleuth.traits import IN_PERSON, describe, face

AT_BAR = ["v1", "v3", "v5", "v7"]


def evening_at_the_bar():
    """make_cases's town dressed for day 2, with four residents logged at the bar that evening."""
    cases, _, town = make_cases()
    for vid, coat in zip(AT_BAR, ("green raincoat", "denim jacket", "plaid flannel", "black puffer")):
        town.get(vid).wardrobe = [coat]
    town.dress(2, Random(0))
    whereabouts = {v.id: ["bar"] if v.id in AT_BAR else [v.home] for v in town.villagers}
    return cases, town, whereabouts


def test_a_photo_shows_two_or_three_people_who_were_there_in_what_they_wore():
    _, town, whereabouts = evening_at_the_bar()
    p = Album(Random(1)).take(town, 2, "evening", whereabouts, Ids())
    assert p.place == "bar" and 2 <= len(p.people) <= 3 and set(p.people) <= set(AT_BAR)
    assert all(p.people[v] == {c: town.looks(v, 2)[c] for c in IN_PERSON} for v in p.people)
    others = [v for v in p.people if v != p.poster]
    assert p.caption == "Evening at the bar with " + " and ".join(
        f"{town.get(v).name} in a {town.outfit(v, 2)}" for v in others) + "!"
    first = list(p.people)[0]
    shown = photo_json(p, town)
    assert set(shown) == {"id", "poster", "caption", "people"} and shown["poster"] == town.get(p.poster).name
    assert shown["people"][0] == {"id": first, "name": town.get(first).name, "looks": describe(p.people[first]),
                                  "face": face(p.people[first])}


def test_one_of_the_people_in_a_photo_posts_it():
    _, town, whereabouts = evening_at_the_bar()
    album = Album(Random(2))
    posters = {album.take(town, 2, "evening", whereabouts, Ids()).poster for _ in range(40)}
    assert all(p.poster in p.people for p in album.photos) and len(posters) > 1
    p = album.photos[-1]
    assert posted(p, town) == f"{town.get(p.poster).name} posted: {p.caption}"


def test_no_photo_at_night_or_with_fewer_than_two_people():
    _, town, whereabouts = evening_at_the_bar()
    album = Album(Random(1))
    assert album.take(town, 2, "night", whereabouts, Ids()) is None
    assert album.take(town, 2, "evening", whereabouts, Ids(), exclude={"v1", "v3", "v5"}) is None
    assert album.photos == []


def test_a_culprit_is_never_photographed_at_their_crime():
    cases, town, whereabouts = evening_at_the_bar()
    crime = Crime("case-1", "steal", "bike", "v3", "v2", "bar", 2, "evening", 1200, "rival", "Someone stole a bike.")
    cases.files[crime.id] = CaseFile(crime, {}, "open")
    assert cases.hidden(2, "evening") == {"v3"} and cases.hidden(2, "afternoon") == set()
    album = Album(Random(3))
    for _ in range(50):
        assert "v3" not in album.take(town, 2, "evening", whereabouts, Ids(), exclude=cases.hidden(2, "evening")).people
    cases.files[crime.id].state = "closed"
    assert cases.hidden(2, "evening") == set()


def test_the_album_keeps_the_newest_and_round_trips():
    _, town, whereabouts = evening_at_the_bar()
    a, ids = Album(Random(1)), Ids()
    taken = [a.take(town, 2, "evening", whereabouts, ids) for _ in range(KEPT + 5)]
    assert len(a.photos) == KEPT and a.photos == taken[5:] and a.get(taken[0].id) is None
    assert a.get(taken[-1].id) is taken[-1]
    back = Album()
    back.restore(a.to_state())
    assert back.photos == a.photos


def test_photos_are_taken_only_while_someone_plays():
    g = build()
    for v in VILLAGERS:
        g.engine.town.add(v, "cafe")
    at_cafe = {v.id: ["cafe"] for v in VILLAGERS}
    g.engine._photograph(1, "morning", at_cafe)
    assert not [e for e in g.feed.recent if e.kind == "photo"]
    player = g.make("p-1", "o-1")
    g.players.add(player)
    player.touch()
    g.engine._photograph(1, "morning", at_cafe)
    [event] = [e for e in g.feed.recent if e.kind == "photo"]
    assert event.player is None and event.line == f"{event.data['photo']['poster']} posted: {event.data['photo']['caption']}"
    assert g.engine.album.get(event.data["photo"]["id"])
