# One Piece Trivia Tic-Tac-Toe

A competitive two-player game: players take turns claiming cells on a 3×3 grid of
One Piece trivia categories by naming characters that satisfy both the cell's row
and column category. Three-in-a-row wins.

## Language

**Match**:
One complete play session on a single Grid, between two players, ending in a win
(three-in-a-row) or a draw.
_Avoid_: Game, Round

**Grid**:
The 3×3 board for a Match: three row Categories and three column Categories,
forming nine Cells.
_Avoid_: Board

**Cell**:
One position on the Grid, defined by the intersection of its row Category and its
column Category. Claimed by naming a Character that satisfies both.
_Avoid_: Square, Tile, Box

**Line**:
Three Cells in a straight run on the Grid — one of the eight: three rows, three
columns, two diagonals. A Match is won the moment one player holds a full Line;
the player who does is the winner.
_Avoid_: Row (a Line may be a column or diagonal), Streak, Run

**Category**:
A predicate over the Roster (e.g. "Race: Fish-man", "Bounty ≥ 1,000,000,000"),
paired with the list of Characters that satisfy it. Every Category belongs to one
Category Group.
_Avoid_: Criterion, Tag, Clue

**Category Group**:
One of the twelve top-level clusters a Category belongs to: Bounty, Race, Status,
Affiliation, Origin sea, Devil Fruit, Haki, Height, Age, Debut chapter,
Visited (journey), Misc. Grid generation samples Groups uniformly, then picks a
Category within each Group weighted toward the ones with more Valid partners, so
Groups show up roughly evenly across Matches — not perfectly even (Groups whose
Categories are all small, like Affiliation and Race, still land a little below
the others), but no Group dominates or is squeezed out. See
`docs/adr/0003-even-category-group-sampling.md`.
_Avoid_: Theme, Section

**Character**:
A One Piece character eligible to be named in a Cell. Identity is the character's
canonical name: the normalized form of its `characters.json` entry (whitespace
trimmed and collapsed, Unicode NFC). "Bjorn" is preferred over "Bjorn ".
_Avoid_: Entry, Person

**Roster**:
The full set of Characters, taken solely from `characters.json`. A name referenced
by a Category that does not resolve to a Roster entry is a data defect, not a
playable Character.
_Avoid_: Cast, Pool, Database

**Playable set**:
The Characters of a Category that resolve to a Roster entry by canonical name.
Names a Category references that do not resolve are data defects: they are
excluded from the playable set and recorded in the Data-quality report.
_Avoid_: Answer key, Members

**Viable threshold**:
The minimum size of a Category's playable set — three — for the Category to be
used in a Match. A Category with fewer resolved Characters is excluded from play.

**Trivial Category**:
A Category whose playable set is so large — more than a set fraction of the
Roster — that naming almost any Character satisfies it, making it a poor trivia
clue. Trivial Categories are dropped from the candidate pool before a Grid is
generated. A forced Grid (an explicit Category list) is an override and keeps
them. The fraction and the decision are recorded in
`docs/adr/0002-trivial-category-exclusion.md`.
_Avoid_: Gimme Category (a gimme is a Cell, not a Category), Broad tag

**Valid partner**:
Of a Category, another Category it could sit opposite on a Grid and still make a
playable Cell: their playable sets intersect, neither is a subset of the other,
and the pair is not a known gimme. A Category's count of valid partners predicts
how often it survives Grid generation, so it drives both the Dead Category prune
and the weighting of the within-Group Category draw
(`docs/adr/0003-even-category-group-sampling.md`).

**Dead Category**:
A Category with fewer than three Valid partners. A row needs three Categories for
its columns (and a column three for its rows), so a Dead Category cannot appear
in any solvable Grid; it is dropped from the candidate pool before a Grid is
generated. As with a Trivial Category, a forced Grid is an override and keeps
them. Decided in `docs/adr/0003-even-category-group-sampling.md`.
_Avoid_: Orphan Category, Isolated Category

**Data-quality report**:
The record, produced when the dataset loads, of the Category-referenced names
that do not resolve to a Roster Character, together with the Categories excluded
for falling below the Viable threshold. Logged at startup and served from a
diagnostic endpoint.

**Upstream**:
The external site the Raw dataset is pulled from — oparchive.com, which publishes
`characters.json`, `devil_fruits.json` and `islands.json` as static files and
tracks the manga chapter by chapter. It is a fan project with no API and no
stated licence, so it is treated as a best-effort source and credited in
`data/PROVENANCE.md`.
_Avoid_: Source, the wiki, the scrape

**Raw dataset**:
The three JSON files as pulled from Upstream (`characters.json`,
`devil_fruits.json`, `islands.json`), committed to the repo verbatim. The Roster
and every Category's characters are derived from it. It is never hand-edited, so
a Refresh overwrites it wholesale.
_Avoid_: Scrape output, source data, the dump

**Refresh**:
Re-pulling the current Raw dataset from Upstream and regenerating the derived
files from it (`categories.json`, `categories.txt`), then validating the result
before it can be accepted. A Refresh replaces the Raw dataset wholesale, is
always reviewed before it lands, and never re-tunes the Grid-generation knobs
(`docs/adr/0002`, `docs/adr/0003`) — a data shift that moves those knobs'
invariants is flagged for a human, not acted on. See
`docs/adr/0004-dataset-refresh-pipeline.md`.
_Avoid_: Update, Sync, Re-scrape, Reload

**Used pool**:
The set of Characters already claimed in the current Match. It is shared by both
players; a Character in the Used pool cannot be named again in that Match.
_Avoid_: History, Claimed list

**Pass**:
A turn in which a player claims no Cell, identified by the Match and the acting
player. Allowed only on the player's turn while the Match is in progress;
otherwise **rejected** with a reason (`not-your-turn`, `match-over` — no state
change). An accepted Pass hands the turn over and increments a consecutive-Pass
counter; two Passes in immediate succession end the Match as a draw. Any claim or
wrong Guess resets the counter, so only immediate succession counts.
_Avoid_: Skip, Forfeit

**Guess**:
An Active player's attempt to claim a Cell by naming a Character, identified by
the Match, the Cell coordinates, and the acting player. It resolves to exactly
one outcome: **claimed** (the Character satisfies both axes — the Cell is marked
and the Character joins the Used pool), **wrong** (fails at least one axis — the
turn is forfeited, with a per-axis row/column pass/fail), **already-used** (the
Character is in the Used pool — the turn is not forfeited), or **rejected** with
a reason (`not-your-turn`, `cell-taken`, `match-over`, `unknown-character` — no
state change).
_Avoid_: Move, Attempt, Submission

**Rematch**:
Starting a fresh Match from an existing one, without restarting the server. It is
a plain new Match — a newly generated Grid, an empty Used pool, a zeroed
consecutive-Pass counter, `in-progress` status, and a first player chosen anew at
random — with its own id. The previous Match is left untouched; its id may simply
be dropped.
_Avoid_: Restart, Replay, New round
