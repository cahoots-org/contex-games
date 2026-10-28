from random import Random

from sleuth import offenders as offenders_mod
from sleuth.config import Config
from sleuth.offenders import Offender, Offenders
from sleuth.tests.test_case import make_town


def test_the_set_is_topped_up_to_the_configured_size_from_non_offenders():
    town = make_town()
    offenders = Offenders(Config(offenders=3))
    offenders.exposed["v2"] = "stole Dana Reyes's bike"
    joined = offenders.top_up(town, Random(0))
    assert len(offenders.active) == 3 and set(joined) == set(offenders.active) and "v2" not in offenders.active
    assert offenders.top_up(town, Random(0)) == []
    assert offenders.top_up(town, Random(0), candidates=["v7"]) == []


def test_an_offender_who_gets_away_twice_moves_up_a_tier_only_when_the_catalog_has_one(monkeypatch):
    offenders = Offenders(Config(escalate_after=2))
    offenders.active.update({"v1": Offender(), "v2": Offender()})
    monkeypatch.setattr(offenders_mod, "catalog_tiers", lambda: ("petty",))
    offenders.escaped_with("v1")
    offenders.escaped_with("v1")
    assert offenders.active["v1"].tier == "petty"
    monkeypatch.setattr(offenders_mod, "catalog_tiers", lambda: ("petty", "serious"))
    offenders.escaped_with("v1")
    assert (offenders.active["v1"].tier, offenders.active["v1"].escaped) == ("serious", 0)
    offenders.escaped_with("v9")
    assert "v9" not in offenders.active


def test_a_quiet_offender_is_not_ready():
    offenders = Offenders(Config())
    offenders.active["v1"] = Offender(quiet_until=5)
    offenders.active["v2"] = Offender(tier="serious")
    assert offenders.ready(4, "petty") == set() and offenders.ready(5, "petty") == {"v1"}
    assert offenders.ready(4, "serious") == {"v2"}


def test_a_tier_nobody_holds_takes_the_offender_below_with_the_most_escapes():
    offenders = Offenders(Config())
    offenders.active.update({"v1": Offender(escaped=1), "v2": Offender(escaped=0), "v3": Offender("serious")})
    assert offenders.promote("serious") == "v1" and offenders.active["v1"].tier == "serious"
    assert offenders.promote("major") == "v1" and offenders.promote("major") is None
    offenders.drop("v1")
    assert "v1" not in offenders.active


def test_an_exposed_offender_rests_then_reforms_or_may_reoffend():
    for chance, reformed in ((1.0, ["v1"]), (0.0, [])):
        offenders = Offenders(Config(reform_chance=chance))
        offenders.active.update({"v1": Offender(quiet_until=3), "v2": Offender()})
        offenders.exposed["v1"] = "stole Dana Reyes's bike"
        assert offenders.new_day(2, Random(0)) == []
        assert offenders.new_day(3, Random(0)) == reformed
        assert ("v1" in offenders.active) == (not reformed) and "v2" in offenders.active
    assert offenders.ready(3, "petty") == {"v1", "v2"}


def test_nobody_is_promoted_to_the_lowest_tier():
    offenders = Offenders(Config())
    offenders.active["v1"] = Offender("major")
    assert offenders.promote("petty") is None and offenders.active["v1"].tier == "major"


def test_no_one_excluded_is_promoted():
    offenders = Offenders(Config())
    offenders.active.update({"v1": Offender(escaped=1), "v2": Offender(escaped=0)})
    assert offenders.promote("serious", {"v1"}) == "v2" and offenders.active["v1"].tier == "petty"


def test_the_last_offender_of_a_tier_never_moves_up(monkeypatch):
    monkeypatch.setattr(offenders_mod, "catalog_tiers", lambda: ("petty", "serious"))
    offenders = Offenders(Config(escalate_after=1))
    offenders.active.update({"v1": Offender(), "v2": Offender()})
    offenders.escaped_with("v1")
    offenders.escaped_with("v2")
    assert offenders.active["v1"].tier == "serious" and offenders.active["v2"].tier == "petty"
    assert offenders.promote("major") is None and offenders.active["v1"].tier == "serious"
