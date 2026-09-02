# Category files — the agreed normalisation

The derived Category files `categories.json` and `categories.txt` must be
reproducible from the **Raw dataset** (ADR 0004). `scripts/build_categories.py`
rebuilds them; `dump_categories_json` / `dump_categories_txt` in that module are
the serialisers. This note pins the exact byte-level choices those helpers make,
reverse-engineered from the files as committed today (195 Categories, 1532 Raw
Characters).

Both round-trips are asserted in `tests/test_build_categories.py`: parsing a
committed file and re-serialising it through the matching helper reproduces the
file byte-for-byte.

## The two payloads

`build_categories` returns one payload per derived file (plus the build report):

- **`categories_json`** — a list of `CategoryEntry` (`id`, `label`, `count`,
  `characters`). This is what `dump_categories_json` serialises, and the shape
  `json.loads(categories.json)` already has.
- **`categories_txt`** — a list of `TxtCategory` (`id`, `label`, `count`,
  `group`). No `characters`: `categories.txt` shows only counts. It carries the
  Category's **Category Group** instead, which `dump_categories_txt` groups on
  directly.

`to_txt_payload` converts the first shape into the second by dropping
`characters` and attaching each Category's Group from `CATEGORY_SPECS` — so a
plain `categories.json` payload (e.g. the committed file) can be rendered to
`categories.txt` without a rebuild.

## Line endings

Both files are stored with **`\n`** line endings. `categories.json` has **no
trailing newline**; `categories.txt` ends with a **single** `\n`. The builder
writes with `newline="\n"` so output is identical on Windows and Linux. (A
Windows checkout with `core.autocrlf=true` has `\r\n` on disk; Git normalises
that away, and the tests read in text mode so the comparison is against the
canonical `\n` form.)

## `categories.json`

- A JSON array of objects, `json.dumps(..., indent=2, ensure_ascii=False)` —
  two-space indent, non-ASCII characters (`≥`, `–`, `é`, …) written literally.
- Object keys in the order **`id`, `label`, `count`, `characters`**.
- Entries sorted by **descending `count`, then `id` ascending**. `id`s are
  unique, so the order is total and deterministic.
- Each `characters` list is sorted with Python's default string ordering
  (code-point). Names are the Raw `name` values **verbatim** — no canonical-name
  collapse, so whitespace-variant duplicates such as `"Bjorn"` and `"Bjorn "`
  are both listed. `count` equals `len(characters)`.

## `categories.txt`

Four fixed header lines, then one block per **Category Group**:

```
ONE PIECE - CATEGORY LIST
Categories matched by at least 3 characters. Count = number of matching characters.
Source: characters.json (joined with devil_fruits.json and islands.json)
Total: <N> categories
```

- Groups appear in `app.domain.CategoryGroup` order (Bounty, Race, Status,
  Affiliation, Origin sea, Devil Fruit, Haki, Height, Age, Debut chapter,
  Visited (journey), Misc). A Group with no Categories is skipped.
- Each block: a rule of **70** `=`, then `<Group value>  (<M> categories)` (two
  spaces before the paren), then the rule again, then one line per Category.
- Blocks are separated by a blank line; there is **no** blank line after the
  last block, only the file's single closing `\n`.
- Category line: `"  "` + label left-padded to the **widest label in that
  Group** + count right-aligned in a column **(digits of the file's largest
  count) + 2** wide + `" characters"`. The largest count today is `1211`
  (4 digits), so the count column is **6** wide across every Group.
- Categories within a block use the same sort as the JSON file: descending
  `count`, then `id`.

## The `id` → Category Group table

`scripts/build_categories.py` carries `CATEGORY_SPECS`: every Category's `id`,
`label`, and Group, reverse-engineered from the committed files. The Group of a
Category is what `categories.txt` groups it under, which is the `id` prefix for
all but one row: **`has_df` ("Has a Devil Fruit") sits under Devil Fruit**,
not Misc. (`app.dataset.group_for_id`, used by the running app, derives Groups
from the prefix only and so puts `has_df` in Misc; that inconsistency predates
this builder and does not affect play, which reads no Group from these files.)
