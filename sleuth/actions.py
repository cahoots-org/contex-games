"""The villager action set, with the descriptions Jev sees."""

IGNORE = "ignore"
RETELL = "retell"
DENY = "deny"
CONFRONT = "confront"
SPEAK = "speak"
MOVE = "move"
ALIBI = "alibi"
BLAME = "blame"

ACTIONS = {
    IGNORE: "Do nothing; carry on with the day.",
    RETELL: "Pass on something just heard to one specific person nearby.",
    DENY: "Tell one specific person nearby that something being said is false.",
    CONFRONT: "Challenge one specific person nearby about what they said or did.",
    SPEAK: "Tell everyone nearby: spread what you just heard, or say what is on your mind.",
    MOVE: "Walk off to a different place in town, taking the news with you.",
    ALIBI: "Tell one specific person nearby where you supposedly were when the crime happened.",
    BLAME: "Hint to one specific person nearby that someone else had a reason to do the crime.",
}

# Option details where two actions are easy to confuse.
ACTION_NOT_FOR = {
    RETELL: "Not for telling everyone nearby (speak) or disputing it (deny).",
    SPEAK: "Not for telling one person in particular (retell).",
    DENY: "Not for personal accusations (confront).",
    CONFRONT: "Not for correcting a rumor in general (deny).",
}

STYLES = {
    "faithful": "Repeat it as it was told, as accurately as you remember.",
    "exaggerated": "Make it bigger and more dramatic than it was told.",
    "shift_blame": "Change who is responsible for it.",
    "add_detail": "Embellish it with an invented but plausible detail.",
    "soften": "Play it down and make it sound less serious.",
    "mock": "Retell it with scorn or ridicule.",
    "delighted": "Tell it with relish and delight.",
    "worried": "Tell it anxiously, worried for those involved.",
    "conspiratorial": "Share it as a juicy secret, in a hushed, confiding way, using words only.",
}

TARGET_KIND = {
    RETELL: "villager",
    DENY: "villager",
    CONFRONT: "villager",
    MOVE: "place",
    ALIBI: "villager",
    BLAME: "villager",
}

# Speech actions, which carry a style.
STYLED = (RETELL, DENY, CONFRONT, SPEAK, ALIBI, BLAME)

NEEDS_SOMEONE = (RETELL, DENY, CONFRONT, SPEAK, ALIBI, BLAME)


def available_actions(view) -> list[str]:
    """Actions this villager can take right now."""
    out = []
    for a in ACTIONS:
        if a in NEEDS_SOMEONE and not view.present:
            continue
        if a in (ALIBI, BLAME) and not view.case:
            continue
        if a == MOVE and view.night:
            continue
        out.append(a)
    return out
