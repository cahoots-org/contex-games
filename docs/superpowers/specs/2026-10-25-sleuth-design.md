# Sleuth: A Small-Town Deduction Game — Design

**Status:** proposed
**Author:** design conversation with Rob, 2026-10-25
**Builds on:** the shipped Whispers game (`examples/whispers`), its persistence design (`2026-10-24-whispers-persistence-design.md`), and the unbuilt village-life slices 1–2 (`2026-10-20-rumor-mill-village-life-design.md`), which this replaces.

## Intent

The first playtest feedback on the hosted game:
- "It's like the opposite of a social deduction game."
- "I think it might need some onboarding as I didn't quite understand the goal."
- "The goal of getting people kicked out of town feels... weird to me."

The weird part is the player's role. Whispers makes you a stranger who lies about real people until one of them is ruined.

The engine underneath is more general than rumors. Information moves through a population that only listens to what it cares about, drifts with each retelling, and makes people act, and the game always knows who told whom. A deduction game asks the player to work backwards through exactly that. Something happened in town, the truth is scattered across a few people who saw part of it, and the town's talk has already bent it.

So we build a second game, Sleuth, a modern small-town mystery, alongside Whispers:
- **Crimes:** petty crimes happen live in a shared town.
- **Player:** a local true-crime podcaster who investigates.
- **Win:** publish an episode naming who did it, backed by evidence that holds up.

## Goals

- **A goal anyone understands in one sentence:** "Someone keyed Dana's car last night. Find out who."
- **Deduction that rewards reasoning over guessing:** the player weighs exact-but-partial evidence against full-but-unreliable testimony, follows hearsay back to its source, and checks alibis.
- **A town that lives on its own:** people have homes, households and relationships, and they go home at night.
- **Crimes that happen live:** they happen while players are around, and every player can take the case.
- **Solvable cases:** the truth is always reachable from what the town holds.

## Non-goals

- Changing Whispers. Sleuth starts as a copy of Whispers in its own directory, `examples/sleuth`, and diverges from there. Whispers keeps running and deploying as it is.
- Sharing code between the two games. Sleuth is a copy, not a library extracted from Whispers. Fixes that matter to both get made twice.
- Keeping the rumor game inside Sleuth. The player no longer plants stories; the culprit does. In Sleuth, the rumor goals, the whisper-to-win loop and the run-out loss go away.
- Marriage, births, aging and deaths as events during play (old village-life slices 4–5). Households exist from the start and don't change.
- A graphical map or avatars.
- Police as the player. The law can exist in town as ordinary residents, but the player is never an officer.

## Anti-goals

These would make the game a failure even if it works:
- **No church or religion of any kind:** no places, roles, crimes or copy.
- **No violent crime:** no murder, no assault, no harm to children, no crime a player could find upsetting. The crimes are petty and cozy, like stolen packages or a sabotaged prize pumpkin.
- **No invented facts:** a language model never makes up a clue. If a case can only be solved by trusting text the model wrote, it's broken.
- **No unsolvable cases:** a case the player can't solve, without knowing it can't be solved, is a defect.

## The town

- **Setting:** a modern small town of about 50 residents.
- **Places:** the café, the gym, the elementary school, the bar, the dog park, the hardware store, the grocery store, town hall and the library, plus a home for every household. The current medieval places, including the chapel, are dropped.
- **Residents:** each has a name, an occupation, a temperament, things they care about (their needs, as today), grudges, and **visible traits** that a stranger would notice. Traits include build, height, hair, usual clothing, the car they drive, a dog they walk, and a limp or habit. Traits are what witnesses and cameras report, and several residents share each trait.
- **Generation:** Haiku writes the town in batches as today, from a modern prompt. Unique first names are still enforced.

### Households and homes

- **Households:** generated with the town, and fixed for the session. Kinds include married couples, unmarried partners, families with children, single parents, roommates, adult children living with a parent, and people living alone. Children appear only as household members. They are never witnesses, culprits, or people the player interviews.
- **Homes:** each household has one, on a named street, and homes are places like any other. Who lives where is public. Neighbors on the same street are more likely to see each other.

### Relationships

- **Ties:** every pair of residents who know each other has a tie, with a kind and a warmth score. The kinds are spouse, partner, parent, child, sibling, roommate, friend, coworker, neighbor and rival. Household ties are the strongest.
- **What warmth decides:**
  - who tells whom;
  - who believes whom;
  - who covers for whom;
  - who resents whom, which is where motives come from.
- **Visibility:** the kind of each tie is public, like "Dana's husband" or "coworker of Sam". The warmth scores are hidden.

### Routines

- **Phases:** the game clock keeps its four phases: morning, afternoon, evening and night.
- **Where people go:** each resident starts and ends the day at home. Work and leisure places are chosen once, as today, and night is home.
- **Expected location:** at any phase the code can say where each resident is supposed to be. That baseline is what makes an alibi checkable and an absence suspicious.

## Crimes

- **When:** a crime happens during play, only while someone is playing, and at most one case is open at a time. The town's feed (the neighborhood app, below) breaks the news when the crime is discovered.
- **Templates:** crimes come from templates such as these:
  - X steals Y from Z;
  - X vandalizes Z's Y;
  - X sabotages Z's entry before the county fair;
  - X lets Z's dog out;
  - X takes the high school marching band's trailer.

  Code fills the slots from the town, as goal templates are filled today. The culprit is chosen with a motive in mind, such as a rival tie or a grudge against the victim. Haiku writes a pool of crime wording once per town, like the goal pool.
- **When and where it happens:** the phase is picked at random. The place is semi-random: somewhere the culprit could plausibly be, and near the victim's home or routine. The culprit leaves their expected location to do it, and that gap is the core evidence.
- **The truth:** code holds the record of who did it, what, where, when and why. Nothing else is canonical.

## Evidence

The case can be solved from three kinds of evidence. All of them are records held in code.

| Kind | Exact? | Complete? | Example |
|---|---|---|---|
| **Eyewitness memory** | yes, for the witness's own account | partial: traits, not names | "Someone tall in a grey hoodie, by the café's side door, just after 11" |
| **Camera footage** | yes, timestamped | partial: what's in frame | "11:42pm, Elm St doorbell: a figure in a grey hoodie carrying something square, heading north" |
| **Logs** | yes, timestamped | narrow: one fact | "Gym check-in: Sam R., 10:15pm" · "Bar tab closed: 11:30pm" |

- **Eyewitnesses:** residents whose expected location at that phase is the crime's place or near it. Each gets one first-hand memory, published into their mind like anything they hear. They see traits and partial actions, never the culprit's name. Their own memory is exact and never drifts. Their retellings drift, as today.
- **Cameras:** some places and some homes have them. Footage is a fixed record a player can view once they know to look.
- **Logs:** some places keep them, for example gym check-ins, bar tabs and grocery receipts. They confirm or break an alibi for one place and time.
- **Hearsay:** everything the town says about the case after that. It spreads by the existing rules, drifts, and can always say who it came from, since lineage is already tracked. Following hearsay back to an eyewitness is one path to the truth.

## Alibis and the culprit

- **Asking where someone was:** the resident answers from their routine and the truth. An innocent resident who was where they were supposed to be says so.
- **Household alibis:** "I was home with Dana all night" is the common case. Whether Dana confirms it is a Jev judgment from the tie's warmth, what Dana actually knows (were they awake?) and how much Dana stands to lose. Dana might tell the truth, cover, or honestly not know. Residents who live alone have no household alibi.
- **The culprit hides:** the culprit gets two new actions, chosen by Jev like every other action:
  - **Offer an alibi:** claim to have been somewhere else, sometimes leaning on a household member.
  - **Shift blame:** point at someone with a motive, usually a rival.

  Both spread by the normal rules. A cover story has a trail like any other, but it never leads back to an eyewitness or a record.
- **The culprit notices pressure:** a culprit who hears the player is asking around becomes more active, and may turn residents against the podcaster.

## The player: a true-crime podcaster

- **The neighborhood app:** a public feed where the town speculates out loud. It replaces "village talk" and overhearing. This is where the news breaks, where hearsay surfaces and where the culprit's stories show up.
- **Interviewing:** the player asks a resident about the case. The answer comes from the resident's mind, as today's ask and talk do. Haiku phrases only what the resident's memories and the code's records give it. Someone who doesn't know says so.
- **Pulling footage and logs:** requesting records from a place or a household. A resident who trusts the podcaster shares more readily.
- **Publishing an episode:** the player's verdict names a culprit, the place and time, and at least one piece of evidence, which can be a statement, a clip or a log line. The judge checks two things. Is the named culprit right? Does the evidence actually support it, meaning it traces back to the true record rather than to hearsay or the cover story?
- **Consequences:** the episode then spreads through town like anything else.
  - **Right:** the culprit is exposed, the case closes, and the podcaster's reputation rises.
  - **Wrong:** the town now believes something false about an innocent resident. The podcaster's reputation falls, and residents become guarded with them.
- **Reputation:** reputation replaces suspicion and run-out. It is per resident, the same shape as today's rapport. Higher reputation means people talk more freely and share footage. It persists across cases.
- **Rivals:** every player works the same case. The first accurate episode wins it. A wrong episode costs only its author.
- **Onboarding:** the first case for a new player is an easy one: a crime with a clear camera clip and one eyewitness. Short prompts walk them through reading the app, interviewing, pulling a clip and publishing.

## Fairness

- **Code owns every fact.** The model phrases; it never decides what is true or invents a detail.
- **Exact sources are fixed.** First-hand memories, footage and logs never drift.
- **Every case is checked for solvability.** Once a crime has played out for its setup period, code checks that the truth can still be reached:
  - at least one eyewitness memory or record is intact;
  - it narrows the traits to the culprit, together with the alibis that can be checked.

  If the check fails, the game adds a witness or a camera before the news breaks.

## What carries over

| Unchanged | Changed |
|---|---|
| Contex minds, needs as subscriptions, listen streams, forgetting | Town generation prompt, places, routines through home |
| Jev turn decisions, scores, the judge's yes/no checks | The action list: add alibi and shift blame; drop the rumor-only actions the town no longer needs |
| Haiku writing lines, capped | Goal templates become crime templates |
| Lineage, drift, rumor-card-style trails | Rumor cards become case threads |
| Persistence, hosting (a separate service when Sleuth is hosted), the spend cap, analytics | Faces: modern portraits; feed copy throughout |
| Overhearing machinery | Overhearing becomes the neighborhood app |

## Stages

Each stage is its own PR, in this order:
0. **The copy:** `examples/whispers` copied to `examples/sleuth`, with:
   - imports renamed to `examples.sleuth`;
   - environment variables prefixed `SLEUTH_`;
   - Contex projects named `sleuth:<session>:…`, so the two games never share minds;
   - its own data files and test run in CI.

   It plays exactly like Whispers at this point.
1. **The modern town:** places, residents with visible traits, households, homes, relationship ties and routines through home. In Sleuth, the rumor game keeps running on the new town until stage 4 replaces it, so the medieval role weights and goal wording can be rough in between.
2. **Crimes and evidence:** templates, the crime as it happens, eyewitness memories, cameras, logs, and the solvability check. The case shows up in the feed.
3. **The culprit:** alibi and shift-blame actions, household alibis, and reacting to pressure.
4. **The podcaster:** interviewing about a case, pulling records, publishing, the judge's verdict, and reputation. The rumor goals and the run-out loss are removed.
5. **Rivals and onboarding:** shared cases, first accurate episode wins, and the guided first case.

## Calls made in review

These answer a builder's questions. They are my calls, made without Rob, and marked so he can check them.

- **One shared town (as hosted today).**
  - The open case is shared, and the first accurate episode closes it for everyone.
  - Reputation is per player, per resident, like rapport today.
  - A new player's guided first case is a small private case that only their feed shows. It runs alongside the shared one.
- **Evidence is cited, not typed.** The player builds an episode by picking the statements, clips and log lines they've collected. The judge is code, not Jev. An episode wins when two things hold:
  - the named culprit is right;
  - every cited item traces, by lineage or record id, to the true record and is consistent with the culprit's traits.

  Cited evidence doesn't have to single out the culprit on its own.
- **Solvable means narrowed to one.** The intact records, plus the alibis that can be checked, must narrow the suspects to exactly one resident.
  - First-hand memories and records are held in code for the life of the case. Contex's forgetting window doesn't touch them.
  - Witnesses don't leave town while their case is open.
- **Time works in phases.** All reasoning, alibis and routines are at phase level. The clock times shown on clips and logs are display detail drawn from within the phase, and they stay consistent with each other.
- **Where people actually were is logged.** Code stages the crime and moves the culprit. Residents can still wander by Jev's choice, so the game records where each resident actually was in each phase. Alibi truth comes from that log, not from the routine. The routine is only what people expect.
- **The neighborhood app shows talk, not testimony.** It carries public posts and hearsay. An eyewitness's own account comes out only when that witness is interviewed.

## Left to the builder

- **Crime and place details:** the exact crime templates, the place list and street names.
- **Trait vocabulary:** how many residents share each trait.
- **Numbers to tune:** relationship score constants, decay, and how warmth feeds who-tells-whom and who-covers-whom.
- **Case pacing:** how often a crime happens, and how long a case stays open.
- **Records:** which places have cameras and logs, and how often homes do.
- **Reputation:** its constants, and the thresholds for sharing records.
- **Copy:** the wording of the neighborhood app, episodes and verdicts.
- **Tests:**
  - routine and alibi checks with an injected clock;
  - crime generation determinism given a seed;
  - the solvability check, including a forced failure that adds a witness;
  - the judge accepting supported evidence and rejecting evidence from the cover story;
  - household alibi judgments with stubbed Jev answers.

## Addendum, 2026-10-26: conversations and searching the scene

From the owner's first play: interviews couldn't be steered, and there was no real way to gather clues.

### Interviews are conversations
- **Threads.** Interviewing a resident opens a conversation thread with them, kept per player and per resident, like Whispers' conversations. The player can leave and come back to it later; the thread shows everything said so far.
- **Free-text questions.** The player types what they want to ask. Jev reads the question, with the thread so far, and routes it to one of a few kinds the game can answer, filling in who and when it's about:
  - where the resident was at a part of the day;
  - where someone else was;
  - what they saw;
  - who they heard something from;
  - who'd have a reason (a grudge or rival tie with the victim);
  - what they think of someone;
  - none of these.
- **Answers come from records.** Code looks up what that resident actually knows for the routed kind. Haiku phrases the reply in their voice, with the thread as context, and never adds a fact. "None of these", or nothing known, gets an honest "I wouldn't know about that." Anything new goes into the notebook as a record, as interviews do today.
- **Limits.** A handful of messages per resident per part of the day, then "Let's talk later." Each message costs at most one Jev and one Haiku call.

### Searching the scene
- At the crime place, a player can search once per case. They find one or two physical clues, held in code when the crime is staged:
  - a trace that narrows a trait, like a boot print for height or a thread of the culprit's coat;
  - or an item that ties someone to a place and time, like a dropped receipt.
- Clues are records like any other, so they can be cited, and the solvability check counts them.

## Addendum, 2026-10-27: knowing people, outfits and photos

From the owner: the puzzle was a lookup, because everyone's looks were on screen from the start, so the only unknown was the crime. Identifying people becomes something the player investigates.

### Looks are learned, not given
- **Public:** the people list starts with name, job, street and household.
- **Learned:** a person's looks are known only once the player has:
  - talked to them, which shows how they look now, including today's outfit;
  - been told by someone who describes them (hearsay, which can be wrong);
  - or seen them in a photo or camera clip.
- **Recorded:** each learned look records how and when it was learned ("you talked, day 3", "Bev described, day 3", "in a photo, day 2"). The people list and cards show what's known and how.
- **No knowledge by presence:** being at a place doesn't reveal anyone.

### Outfits
- **Wardrobe:** every resident owns three outfits, coat or top colour and style, assigned by code from the trait vocabulary. Height and hair stay fixed.
- **Daily choice:** code picks the outfit each resident wears each day. It is recorded, so "what did Cal wear on day 2?" has one true answer.
- **Culprit's caution:** a culprit may avoid the outfit they wore for the crime on later days.
- **Trait checks:** witnesses and camera clips report the outfit worn at that moment, not a fixed coat. Trait matching, the judge's pointing rule and the solvability check work against what each resident wore at the time.

### Photos on the neighborhood app
- **Sparing posts:** a few posts per game day at public places, such as trivia night at the bar or the dog park in the morning. Each shows two or three residents, with the place, the day and part of day, and what each wore.
- **Code-held records:** photos are true, and appear in the notebook when the player saves one.
- **Photo feed:** the page gets a scrollable photo feed, newest first, so players can browse what was posted. A photo is drawn from the residents' portraits in that day's outfits, with a one-line caption.
- **Solvability doesn't need photos:** a case is still made solvable by witnesses, clips, logs and clues, which now include what was worn. Photos are a second route, not the only one.
