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

**Category**:
A predicate over the Roster (e.g. "Race: Fish-man", "Bounty ≥ 1,000,000,000"),
paired with the list of Characters that satisfy it. Every Category belongs to one
Category Group.
_Avoid_: Criterion, Tag, Clue

**Category Group**:
One of the twelve top-level clusters a Category belongs to: Bounty, Race, Status,
Affiliation, Origin sea, Devil Fruit, Haki, Height, Age, Debut chapter,
Visited (journey), Misc. Grid generation samples Groups uniformly before choosing
a Category within each, so Groups appear about equally often across Matches.
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

**Used pool**:
The set of Characters already claimed in the current Match. It is shared by both
players; a Character in the Used pool cannot be named again in that Match.
_Avoid_: History, Claimed list

**Pass**:
A turn in which a player claims no Cell. Two Passes in immediate succession end the
Match as a draw.
_Avoid_: Skip, Forfeit
