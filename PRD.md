# Defiance — Product Requirements Document

## 1. Product Summary

**Defiance** is a source-backed, queryable historical system for the 2017 San Diego State baseball season.

V1 exists to help players and coaches recover specific memories from that season.

The product should not feel like a database, archive, stat website, or AI assistant. A user should be able to ask a normal baseball question and get a short, factual answer.

The core experience is:

**Ask a question → get an answer → remember something → ask another question.**

Defiance is the development and public GitHub repository name. The repository will be public from the beginning. The name intentionally does not reveal the full project from the repository title alone.

The public-facing product can use a clearer San Diego State baseball identity when V1 launches.

V1 covers **only the 2017 San Diego State baseball season**.

---

## 2. Target Users

### Primary users

**Players from the 2017 San Diego State baseball team.**

The product is primarily about their memories and their season.

Players should be able to ask about:

- themselves
- teammates
- games
- opponents
- series
- team performance
- memorable moments
- the Mountain West tournament
- season statistics
- game statistics
- series statistics

### Secondary users

**Coaches from the 2017 team.**

Coaches should receive team-level memory prompts rather than player-style personal statistics.

They can also use the general question interface.

### Other users

Parents, friends, alumni, and other people can use the public question interface.

They are not a primary V1 design target.

No user needs an account or identity.

---

## 3. Core Problem

Historical baseball information exists, but it is organized as archived schedules, statistics, box scores, recaps, and other documents.

That format is good for looking up a known fact.

It is poor for recovering a partially remembered moment from eight or more years ago.

A former player might remember:

- the opponent
- whether the game was home or away
- a home run
- a big hit
- a series
- a tournament
- part of what happened

They often will not remember the date or know which archived page contains the answer.

Defiance should turn that archive into something they can question naturally.

---

## 4. User Value

Defiance helps a player or coach recover memories from the 2017 season without manually searching the SDSU archive.

The desired reaction is not:

> “This is a comprehensive statistical database.”

The desired reaction is closer to:

> “Dude, this is kind of crazy. I can just ask it questions about baseball and it gives me an answer.”

The product succeeds when an answer causes someone to think:

> “I forgot about that.”

That memory should create the next question.

---

## 5. V1 Product Principles

### 5.1 Short by default

Every V1 answer should be concise.

Do not return essays.

Do not dump everything known about a player, game, or series.

Return the smallest useful answer first.

### 5.2 Factual baseball data must be correct

Fuzzy memory retrieval can be imperfect.

Stats cannot be.

Defiance must not confuse:

- one player with another
- a hitter with a pitcher
- one opponent with another
- one game with another
- one stat category with another

Entity confusion is a major trust failure.

### 5.3 Memory first

Defiance is not only a stat lookup product.

Stats, recaps, and memorable moments should help users recover pieces of the season.

### 5.4 Answer first

Do not make users interpret confidence scores, reasoning, or technical details.

Give the answer.

### 5.5 Mobile first

Most users are expected to open Defiance from a text message or shared link.

The phone experience sets the V1 usability bar.

Typing, reading, and choosing a follow-up question should all be easy on a phone.

### 5.6 No setup

The user needs:

- a normal web browser
- the Defiance link

The user does not need:

- an account
- Terminal
- Git
- Codex
- an API key
- an AI subscription
- their own AI account

---

## 6. V1 Scope

### 6.1 Season

V1 contains only:

**2017 San Diego State baseball**

No other season is required.

### 6.2 Source boundary

V1 uses only information from the **San Diego State website**.

External sources are excluded.

Examples of excluded V1 sources include:

- opponent websites
- NCAA sources
- newspapers
- third-party databases
- other historical websites

### 6.3 Supported factual material

V1 must support both:

**Structured baseball facts**
- player season statistics
- individual game statistics
- team statistics
- team leaders
- game scores
- series results
- opponent results
- simple multi-game statistical aggregation

**Narrative historical information**
- game recaps
- series recaps
- tournament recaps
- memorable plays or events described in SDSU content
- notable moments associated with players or the team

Both layers are required for V1.

---

## 7. Definition of “2017 Complete”

The data corpus is considered **2017 complete** when Defiance contains the relevant material SDSU currently archives for the 2017 baseball season.

This includes, where available on SDSU:

- roster
- schedule
- season statistics
- box scores
- play-by-play contained within box scores
- game recaps
- series-related material
- postseason and Mountain West tournament material
- other relevant 2017 baseball content within the SDSU archive

V1 does **not** require material merely because it exists elsewhere.

Examples that are not required:

- broadcast transcripts
- external articles
- opponent recaps
- NCAA pages
- third-party databases
- privately held material

Completeness refers to the SDSU archive boundary, not every possible historical source.

---

## 8. V1 User Experience

### 8.1 Homepage goal

Within the first few seconds, the user should understand what Defiance does.

The homepage should make it obvious that users can ask questions about the 2017 SDSU baseball season.

The interface should not require an explanation of AI.

### 8.2 Primary entry point: Ask about yourself

The main homepage action should be:

**Ask about yourself**

The user enters a full player or coach name.

This is a lookup. It is not authentication.

Anyone can enter any player or coach name.

### 8.3 Player quick hitters

For a recognized player, Defiance returns approximately **3–5 short memorable quick hitters**.

These are intended to spark memories.

They should not simply repeat the player's season stat line.

Potential quick hitters can include:

- a big hit
- a game-winning play
- a strong series
- a notable recap mention
- an unusual game
- another statistically notable moment

Defiance can infer that a factual performance was notable.

The underlying facts must remain correct.

Do not label moments as “inferred.”

Present them naturally.

### 8.4 Coach quick hitters

For a recognized coach, return approximately **3–5 team-level memory triggers**.

Examples include:

- important series
- tournament runs
- comeback wins
- team streaks
- notable team performances

Do not create a broad coach-specific query product in V1.

### 8.5 Unknown name

V1 can require the user to enter the person's full name.

If Defiance cannot recognize the name, it should ask the user to try the full player or coach name.

Complex identity matching is not required.

### 8.6 General question entry

The second primary path is:

**Ask a question about the 2017 season**

The user types a natural-language question.

Input is typed text only.

Voice input is not part of V1.

### 8.7 Answer experience

The default answer is:

- short
- direct
- factual
- plain text
- natural baseball language

For example, prefer:

> You went 3-for-4 and doubled in the second.

over a robotic stat dump when the question does not require one.

Plain text is sufficient for V1.

Charts, dashboards, and elaborate visual stat components are unnecessary.

### 8.8 Stateless questions

Each question is independent.

Defiance does not need to remember:

- the previous question
- the player's name
- prior conversation context

Users should receive a subtle notice explaining this.

Example concept:

*Defiance does not remember prior questions. Include the player, opponent, or game in each question.*

Exact copy and placement are not final.

### 8.9 Suggested follow-up questions

After an answer, Defiance may show **2–3 optional follow-up questions**.

Each suggestion must:

- display the full question
- be fully self-contained
- stay tightly related to the current answer
- work without conversational memory
- be tappable to ask

Do not hide the question behind generic actions such as “Learn more.”

The user should know exactly what will be asked before tapping.

---

## 9. Key User Questions / Use Cases

### 9.1 Player season statistics

Examples:

- “What were Danny Sheehan's 2017 stats?”
- “How many home runs did Danny Sheehan hit?”
- “How many doubles did [player] have?”

If a stat exists in the SDSU archive, Defiance must return it correctly.

### 9.2 Single-game player performance

Examples:

- “What did Danny Sheehan do against Fresno State on Friday?”
- “How did [player] do in the UNLV game?”
- “Did [player] get a hit in that game?”

Return the important result concisely.

### 9.3 Series statistics

Defiance must support simple aggregation across games.

Examples:

- “What were Danny Sheehan's stats against Fresno State?”
- “What did [player] hit in that series?”

Simple addition and aggregation across a known set of games is within V1.

### 9.4 Best series for hitters

Example:

- “What was Danny Sheehan's best series?”

For V1, “best series” for a hitter means the series with the **highest batting average**.

Pitcher “best performance” is not automatically defined.

A pitcher question should specify a metric if a subjective comparison is required.

### 9.5 Team statistics and leaders

Examples:

- “Who led the team in home runs?”
- “Who had the highest batting average?”
- “What was our conference record?”
- “What was our record?”

Team questions are a core part of the memory experience.

### 9.6 Series recap questions

Example:

- “What happened in the home series against Fresno State?”

If an opponent is named without a specific game, Defiance should generally interpret the request at the **series level**.

A default series summary should include:

- series record
- game scores
- approximately 1–2 notable moments from each game

Keep the overall answer short.

### 9.7 Tournament and event questions

Example:

- “What happened in the Mountain West tournament?”

Return a short overall narrative.

Do not default to a full game-by-game dump.

### 9.8 Game recap questions

Examples:

- “What happened in the Fresno State game on Friday?”
- “What happened in the UNLV game?”

When the game can be identified, return a short factual summary using the available SDSU material.

### 9.9 Fuzzy memory questions

Users may remember only fragments such as:

- opponent
- home or away
- player
- a home run
- a hit
- another memorable play

V1 does not need advanced fuzzy reconstruction to be considered successful.

Clear questions with obvious anchors must work.

Fuzzy questions are best-effort.

When multiple matches are plausible, the preferred experience is:

1. give the most likely match
2. offer one alternate possibility

Avoid forcing the user through unnecessary clarification steps.

---

## 10. Derived Statistics

V1 can calculate simple derived answers when they require straightforward aggregation of factual archived statistics.

### In scope

Examples:

- player stats across a three-game series
- player stats against one opponent
- highest batting average across series
- team or player rankings from archived season stats

### Out of scope

Complex situational analysis is not required.

Examples:

- stats with runners on third and fewer than one out
- situational batting splits
- count-based performance
- advanced inning-state queries
- custom event-state slicing
- complex conditional records

A previous example such as:

> “What was our record when this player had two or more hits?”

is not required for V1.

The V1 line is:

**simple aggregation: yes  
advanced situational analysis: no**

---

## 11. Trust and Sourcing Expectations

### 11.1 Answer simplicity

Do not make users think about sourcing unless they want to.

The answer comes first.

### 11.2 Original SDSU sources

When a verification source is available to the user, it should point to the **original public SDSU source**.

Do not make an internal Defiance copy the primary user-facing source.

### 11.3 Source visibility

Sources should stay out of the main experience unless the user wants to verify an answer.

Do not clutter every response with provenance information.

### 11.4 Derived answers

For simple derived answers, return the result.

Do not show:

- calculation steps
- a source dump
- every box score used
- internal reasoning

Example:

> You hit .417 in that series.

is sufficient.

### 11.5 Source authority

When SDSU sources conflict, use this hierarchy for factual baseball data:

1. box score
2. official season statistics
3. recap narrative

A recap can provide useful narrative details that a box score does not contain.

Examples include:

- a diving catch
- descriptions of a clutch hit
- narrative game context

Those details can appear in Defiance when supported by the recap.

### 11.6 No confidence-label burden

Do not expose technical confidence labels by default.

The user should not have to decide whether an answer is trustworthy based on model terminology.

### 11.7 Subjective or off-topic questions

For subjective questions that the archive cannot answer, Defiance can use a short, playful response.

Example category:

- “Who was the funniest player?”
- “What was the locker room like?”

The exact fallback copy is TBD.

This fallback must **not** be used when Defiance fails to answer a valid baseball question.

---

## 12. Accuracy Expectations

The highest-risk failures are:

- wrong player
- wrong opponent
- wrong game
- wrong stat
- hitter/pitcher confusion
- mixing multiple games together incorrectly

For valid statistical questions, accuracy is non-negotiable.

A factual stat contained in the source corpus must be returned correctly.

Recap-based answers are also a core V1 requirement.

V1 should therefore be evaluated across both:

- statistical questions
- narrative recap questions

---

## 13. Performance Expectations

Accuracy has priority over raw speed.

A response taking approximately **4–6 seconds** is acceptable if the interface immediately indicates that Defiance is working.

V1 does not require a specific streaming behavior.

The product requirement is:

**the user should immediately know that the request is being processed.**

---

## 14. Validation and Success Criteria

### 14.1 Core launch standard

Before broader release, Defiance should survive repeated questioning across:

- different players
- hitters
- pitchers
- everyday players
- limited-appearance players
- games
- opponents
- series
- team stats
- player stats
- recaps
- tournament questions
- derived series statistics

The goal is to exhaust the product with representative questions and continue receiving factual answers.

### 14.2 Sparse-player validation

At least part of the test set should include players with very limited participation.

Examples:

- approximately one inning pitched
- approximately five at-bats
- another very small sample

Correctly handling sparse records is a valuable validation case.

### 14.3 Representative roster validation

V1 does not require exhaustive manual validation of every rostered player before launch.

A strong representative sample is sufficient.

This matters because many rostered players may have little or no game participation.

### 14.4 Repeatable evaluation set

V1 should have a repeatable question set used before launch.

The exact evaluation mechanics are not defined in this PRD.

The product requirement is that Defiance can be tested repeatedly against representative known-answer questions.

### 14.5 Product success

The product succeeds when players and coaches:

- understand how to use it without instruction
- receive factual answers
- recover memories they had not thought about recently
- think the experience is interesting or fun
- continue asking questions

A strong qualitative signal is:

> “I completely forgot about that.”

followed by another question.

---

## 15. Operator Visibility

Danny should be able to review anonymous Defiance usage after launch.

This exists to find failures even when users never report them.

The operator needs enough visibility to inspect:

1. the question
2. the exact answer Defiance returned
3. the evidence or source material used to produce that answer

The goal is debugging incorrect product behavior.

The operator does not need user identities.

Anonymous usage is sufficient for V1.

This PRD does not specify the technical observability implementation.

---

## 16. Private Testing Plan

### Stage 1: Dad

The first usability tester should be Danny's dad.

His role is primarily to test whether a nontechnical person can:

1. open the link
2. understand what Defiance does
3. ask a question
4. receive an answer
5. immediately understand how to ask another question

He should not require assistance.

This is the primary first-use usability test.

### Stage 2: Close players

After basic usability works, send Defiance to approximately **2–3 close former teammates**.

Use them to identify:

- factual mistakes
- weird questions
- confusing interactions
- memory prompts that work
- unexpected behavior

Feedback can be informal.

V1 does not need a built-in feedback or correction system.

### Stage 3: Broader player group

Expand to more members of the 2017 team after initial issues are corrected.

The exact group sequence is not yet fixed.

### Stage 4: Wider program circle

Later, Defiance can be shared with a wider set of people connected to the program.

---

## 17. Launch Approach

The launch should be staged rather than one large release.

Current expected direction:

1. Danny's dad
2. 2–3 close teammates
3. broader group of players
4. wider program circle

Danny may record a short demonstration video and send it with the link.

The demo is **launch collateral**, not part of the Defiance product.

Whether recipients should watch the demo before opening the product is still undecided.

The broader launch should feel like a surprise.

The basic message is:

**Here is our 2017 season. Ask it questions. Try to break it.**

Exact launch copy is outside this PRD.

---

## 18. Explicit Non-Goals for V1

The following are intentionally excluded.

### Historical expansion

- other SDSU seasons
- full program history
- alumni history across seasons

### External data

- opponent websites
- NCAA data
- newspaper articles
- third-party baseball databases
- sources outside the SDSU website

### Video

- Synergy coaching video
- multi-angle video
- linking game events to video

### Advanced statistics

- complex situational splits
- custom conditional records
- runners-in-scoring-position analysis
- count-based analysis
- advanced event-state queries

### Conversation memory

- remembering the previous question
- remembering the user's name
- carrying conversation state between questions

### Complex fuzzy reconstruction

Sophisticated recovery from highly ambiguous memories is not a launch requirement.

It can work best-effort.

### Voice

- voice questions
- speech input
- voice answers

### Accounts and identity

- user accounts
- login
- authentication
- profiles
- identifying which person asked which question

### Built-in correction workflow

- feedback forms
- correction submission
- user voting
- formal issue reporting

Early feedback will be handled informally.

### Rich data visualization

- charts
- dashboards
- interactive statistical graphics
- complex stat cards

V1 is primarily plain-text question and answer.

### Date-first exploration

Date-based browsing is not a primary V1 experience.

People are not expected to remember exact dates from the 2017 season.

### Broad coach analytics

Coaches can receive team-level memory quick hitters.

A dedicated coach-query product is out of scope.

### Architecture work

This PRD does not define:

- hosting
- database design
- model provider
- retrieval architecture
- caching
- streaming implementation
- ingestion architecture
- observability vendor
- API design

Those decisions come after product definition.

---

## 19. Future Backlog

The following ideas are worth preserving but are not V1 requirements.

### Additional seasons

Expand beyond 2017 into other SDSU seasons.

### External sources

Add material from:

- opponents
- NCAA
- newspapers
- other archives
- third-party databases

### Video linkage

Connect structured game events or historical moments to old Synergy coaching video, including multi-angle footage where available.

### Alumni and historical player pages

Create richer historical views for individual SDSU players.

### Historical corrections

Allow deeper archival cleanup or correction workflows.

### Advanced statistical questions

Support richer conditional and situational analysis.

### Better fuzzy retrieval

Handle increasingly incomplete or incorrect memories across players, opponents, locations, and events.

### Conversational context

Allow follow-up questions to inherit previous context.

Example:

> “What did Danny do Friday?”

followed by:

> “What about Saturday?”

This is explicitly not required for V1.

### Broader program history

Eventually turn Defiance into a deeper historical system for San Diego State baseball.

---

## 20. Open Questions / Assumptions

### 20.1 Homepage image

A strong historical team image may appear on the opening experience.

Current candidates include:

- the “Rage State” beer-die team photo
- the Mountain West championship team photo

No choice has been made.

### 20.2 Player quick-hitter selection

The requirement is 3–5 memorable items.

The exact selection rules are not yet fixed.

V1 can begin with obvious notable events from stats and recaps, then improve based on testing.

### 20.3 Coach quick-hitter selection

Coach results should contain team-level memories.

The exact ranking or selection logic is still open.

### 20.4 Season-level summary

The answer to a broad question such as:

> “How did we do in 2017?”

has not been defined.

V1 should keep it short, but the exact content remains open.

### 20.5 Pitcher “best” definition

There is no default definition of a pitcher's “best” outing or series.

V1 should require a more specific metric rather than inventing one.

### 20.6 Name aliases

Full official names are sufficient for the required V1 behavior.

A small manually supplied list of common names or nicknames may be added if useful.

Broad typo correction is not required.

### 20.7 Subjective fallback copy

Subjective and off-topic questions should receive a short, playful response.

The exact wording is not final.

### 20.8 Stateless notice placement

Users should know that each question is independent.

The notice may appear:

- below the question box
- after an answer
- in another subtle nearby location

The exact placement is not important to the core product.

### 20.9 Response formatting

Bullets versus short paragraphs is not a core requirement.

Use whichever format is easiest to scan on mobile.

### 20.10 Launch sequence

The launch will be staged.

The exact number of people in each group and timing between stages are not yet fixed.

### 20.11 Demo usage

Danny plans to record a demo and send it to users.

Whether users should watch it before opening Defiance is undecided.

---

## 21. V1 in One Sentence

**Defiance V1 lets 2017 San Diego State baseball players and coaches ask simple questions about their season and get short, factual answers that help bring old memories back.**