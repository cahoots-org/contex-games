"""Sleuth settings, overridable through SLEUTH_* environment variables."""

import os
import uuid
from dataclasses import dataclass, field, fields


@dataclass(frozen=True)
class Config:
    contex_url: str = "http://localhost:8001/mcp"
    # Names this run's Contex projects; a fresh one per run starts every mind empty.
    session: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    day_seconds: float = 900.0
    # How long a subscription keeps talk for a villager to react to.
    memory_days: float = 2.0
    cooldown_seconds: float = 30.0
    renew_seconds: float = 1200.0
    population: int = 50
    # Game days before an open case goes cold, and a major one.
    case_days: float = 3.0
    major_case_days: float = 6.0
    # Fewest game days between one major case opening and the next.
    major_every_days: float = 3.0
    # How a resident's regard for a podcaster moves: a right publish, a wrong one, and being wrongly accused.
    reputation_right: float = 0.3
    reputation_wrong: float = -0.4
    reputation_accused: float = -0.4
    # How an exposed culprit's regard for the podcaster who exposed them moves, and their victim's household's.
    reputation_exposed: float = -0.6
    reputation_ally: float = 0.3
    # How the wrongly accused's household and close ties regard a podcaster who named them.
    reputation_accused_ties: float = -0.3
    # How a resident's regard moves when the culprit warns them about the podcaster.
    reputation_warned: float = -0.2
    # How far every regard drifts back toward 0 each part of the day.
    reputation_decay: float = 0.02
    # Below this regard a resident won't talk to the podcaster.
    guarded_at: float = -0.3
    # At or above this regard a witness recalls one more of the culprit's traits.
    trusted_at: float = 0.2
    # How many routine questions Jev is asked at once.
    routine_concurrency: int = 10
    turn_concurrency: int = 20
    top_k: int = 5
    # How far above a need's ordinary-talk similarity a line must score to match it.
    match_margin: float = 0.015
    # How similar a line the villager heard must be to what the player asks about to be recalled.
    heard_floor: float = 0.84
    # How much more clearance each retelling hop needs before it wakes a listener.
    fatigue_per_hop: float = 0.004
    # How much more clearance overheard room talk needs than a line told to the listener.
    overheard_margin: float = 0.01
    # How far news must clear a need for a villager who walks off to share it wherever their nature lets them.
    share_clearance: float = 0.02
    # How long one Listen lasts.
    # Where villages and need baselines are kept; empty means the working directory.
    data_dir: str = ""
    # How often the running game is saved, so a restart picks up where it left off.
    save_every_seconds: float = 60.0
    # Where need baselines are cached; empty means sleuth_baselines.json in the data directory, shared by every village.
    calibration_path: str = ""
    haiku_model: str = "claude-haiku-5-5"
    # A saved village to play again; empty means a new village, saved under sleuth_worlds/.
    seed_path: str = ""
    # Where the web game listens; 0.0.0.0 serves it to anyone who can reach the machine.
    web_host: str = "127.0.0.1"
    web_port: int = 8765
    # How long a player counts as playing after their last action or closed tab; the village thinks only while one is.
    idle_after_seconds: float = 600.0
    # How many runs that never played are kept; past it the oldest go, however new.
    max_idle_runs: int = 200
    # The chance, each part of the day while someone plays, that a resident posts on the neighborhood app.
    chatter_chance: float = 0.5
    # How many hidden offenders commit the town's crimes, and how many cases one gets away with before moving up a tier.
    offenders: int = 5
    escalate_after: int = 2
    # How many game days an exposed offender lies low, and their chance each morning after of giving it up.
    exposed_quiet_days: int = 2
    reform_chance: float = 0.3
    # The chance someone who moves in is an offender, while there are fewer than max_offenders.
    newcomer_offender_chance: float = 0.3
    max_offenders: int = 6
    # The chance a serious culprit has an accomplice who vouches for them.
    accomplice_chance: float = 0.5
    # The standing at which a podcaster is offered serious cases, and major ones.
    serious_at: int = 3
    major_at: int = 6
    # How far each district's crime, and its fear, fade each part of the day.
    district_crime_decay: float = 0.02
    district_fear_decay: float = 0.015
    # The fear at which a district with an exposure organizes a watch, and the crime and fear below which it winds down.
    organize_fear: float = 0.4
    disband_below: float = 0.05
    # How much less likely a crime is at a place in a district with a watch.
    organized_crime_weight: float = 0.25
    # The crime and fear at which a district without a watch is neglected, its chance each morning of turning a
    # resident into an offender, and the fewest offenders before the set is refilled from districts without a watch.
    neglect_at: float = 0.4
    turn_chance: float = 0.5
    min_offenders: int = 3
    # The most of the town, as a share of its residents, who are or were offenders; past it no one else takes up crime.
    offender_share: float = 0.25
    # Estimated list prices in dollars per million tokens.
    haiku_input_per_mtok: float = 0.1
    haiku_output_per_mtok: float = 0.5
    jev_input_per_mtok: float = 0.04
    jev_output_per_mtok: float = 0.0
    # Estimated dollars of model calls per UTC day after which the village rests until midnight; 0 means no cap.
    daily_spend_cap: float = 5.0

    @property
    def memory_seconds(self) -> int:
        return int(self.day_seconds * self.memory_days)

    def address(self) -> tuple[str, int]:
        """The web game's host, and its port: $PORT when set, as Railway sets it, else web_port."""
        return self.web_host, int(os.environ.get("PORT") or self.web_port)

    @classmethod
    def from_env(cls) -> "Config":
        values = {}
        for f in fields(cls):
            raw = os.environ.get(f"SLEUTH_{f.name.upper()}")
            if f.name == "contex_url" and raw is None:
                raw = os.environ.get("CONTEX_MCP_URL")
            if raw is None:
                continue
            values[f.name] = f.type(raw)
        return cls(**values)
