"use strict";

/*
 * Thin hotseat frontend for issue #9: render the Grid, let whoever's turn it is
 * pick an empty Cell and name a Character, and report the claim outcome. Every
 * rule lives server-side (app/statemachine.py) - this script only draws Match
 * state and relays Guesses, so a hand-crafted request cannot bypass the Roster
 * check. No build step, no framework (ADR 0001).
 *
 * The end-of-Match banner, Pass, the Used-pool view and Rematch are issue #10;
 * this screen only degrades gracefully when a Match happens to end.
 */

const MARKS = { P1: "X", P2: "O" };
const MAX_SUGGESTIONS = 50;

const state = {
  matchId: null,
  match: null, // the latest MatchOut from the server
  roster: [], // canonical Character names, for autocomplete
  selected: null, // { row, column } of the Cell being guessed, or null
};

const els = {
  turn: document.getElementById("turn-indicator"),
  grid: document.getElementById("grid"),
  selectedCell: document.getElementById("selected-cell"),
  input: document.getElementById("guess-input"),
  suggestions: document.getElementById("roster-suggestions"),
  submit: document.getElementById("guess-submit"),
  feedback: document.getElementById("feedback"),
};

// --- API --------------------------------------------------------------------

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  // A Guess rejection (not-your-turn, unknown-character, ...) comes back as
  // 200 with an outcome in the body; a non-OK status here is a real error.
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch (_) {
      /* body was not JSON */
    }
    throw new Error(`${method} ${path} -> ${res.status}: ${detail}`);
  }
  return res.json();
}

async function loadRoster() {
  state.roster = await api("GET", "/roster");
}

async function startMatch() {
  const match = await api("POST", "/matches", {});
  state.matchId = match.id;
  state.match = match;
  state.selected = null;
  els.input.value = "";
  updateSuggestions();
  render();
  setFeedback(`New Match. ${turnLabel(match)} to move.`, "info");
}

async function submitGuess() {
  if (els.submit.disabled || !state.selected) return;
  const character = els.input.value.trim();
  const { row, column } = state.selected;
  const player = state.match.active_player;

  els.submit.disabled = true;
  let result;
  try {
    result = await api("POST", `/matches/${state.matchId}/guesses`, {
      player,
      row,
      column,
      character,
    });
  } catch (err) {
    setFeedback(String(err.message || err), "error");
    syncSubmit();
    return;
  }

  state.match = result.match;
  applyOutcome(result, character);
  els.input.value = "";
  updateSuggestions();
  render();
}

// --- outcome -> feedback --------------------------------------------------

function applyOutcome(result, character) {
  const cell = state.selected
    ? `R${state.selected.row + 1}×C${state.selected.column + 1}`
    : "the Cell";

  switch (result.outcome) {
    case "claimed": {
      const next =
        result.match.status === "in-progress"
          ? `${turnLabel(result.match)} to move.`
          : "Match over.";
      setFeedback(`${character} claimed ${cell}. ${next}`, "ok");
      state.selected = null;
      break;
    }
    case "wrong":
      setFeedback(
        `${character}: ${axisPhrase(result.row, result.column)}. ` +
          `Turn forfeited — ${turnLabel(result.match)} to move.`,
        "error",
      );
      state.selected = null;
      break;
    case "already-used":
      setFeedback(
        `${character} is already in the Used pool this Match. ` +
          `Your turn continues — name another Character.`,
        "warn",
      );
      // Keep the Cell selected so the Player can guess again straight away.
      break;
    case "rejected":
      setFeedback(rejectionPhrase(result.reason), "error");
      if (result.reason === "cell-taken" || result.reason === "match-over") {
        state.selected = null;
      }
      break;
    default:
      setFeedback(`Unexpected outcome: ${result.outcome}`, "error");
  }
}

function axisPhrase(row, column) {
  if (row === "pass" && column === "fail") return "fits the row, fails the column";
  if (row === "fail" && column === "pass") return "fails the row, fits the column";
  if (row === "fail" && column === "fail") {
    return "fails both the row and the column";
  }
  return "fits both axes"; // not reached for a "wrong" outcome
}

function rejectionPhrase(reason) {
  switch (reason) {
    case "not-your-turn":
      return "That is not your turn.";
    case "cell-taken":
      return "That Cell is already claimed.";
    case "match-over":
      return "The Match is over.";
    case "unknown-character":
      return "That name is not in the Roster — the server rejected it.";
    default:
      return `Rejected: ${reason}`;
  }
}

// --- render ---------------------------------------------------------------

function render() {
  renderTurn();
  renderGrid();
  renderSelected();
  syncSubmit();
}

function turnLabel(match) {
  const n = match.active_player.slice(1);
  return `Player ${n} (${MARKS[match.active_player]})`;
}

function renderTurn() {
  const m = state.match;
  if (!m) {
    els.turn.textContent = "";
    return;
  }
  if (m.status !== "in-progress") {
    // Win/draw detection is live (issue #6) so a Match can end on this screen.
    // The banner that announces the result is issue #10; here we just stop.
    els.turn.textContent = "Match over";
    els.turn.className = "turn over";
  } else {
    els.turn.textContent = `${turnLabel(m)} to move`;
    els.turn.className = `turn ${m.active_player.toLowerCase()}`;
  }
}

function renderGrid() {
  const grid = state.match.grid;
  const inProgress = state.match.status === "in-progress";
  const byPos = {};
  for (const cell of grid.cells) byPos[`${cell.row},${cell.column}`] = cell;

  els.grid.replaceChildren();
  els.grid.appendChild(corner());
  for (const cat of grid.column_categories) {
    els.grid.appendChild(categoryTag(cat, "col"));
  }
  for (let r = 0; r < 3; r++) {
    els.grid.appendChild(categoryTag(grid.row_categories[r], "row"));
    for (let c = 0; c < 3; c++) {
      els.grid.appendChild(cellButton(byPos[`${r},${c}`], inProgress));
    }
  }
}

function corner() {
  const d = document.createElement("div");
  d.className = "corner";
  return d;
}

function categoryTag(cat, kind) {
  const wrap = document.createElement("div");
  wrap.className = `category ${kind}`;
  const label = document.createElement("span");
  label.className = "cat-label";
  label.textContent = cat.label;
  const group = document.createElement("span");
  group.className = "cat-group";
  group.textContent = cat.group;
  wrap.append(label, group);
  return wrap;
}

function cellButton(cell, inProgress) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "cell";
  btn.setAttribute(
    "aria-label",
    `Row ${cell.row + 1}, Column ${cell.column + 1}`,
  );

  if (cell.claimed_by !== null) {
    btn.classList.add("claimed", cell.claimed_by.toLowerCase());
    btn.disabled = true;
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = MARKS[cell.claimed_by];
    const name = document.createElement("span");
    name.className = "cell-name";
    name.textContent = cell.character;
    btn.append(mark, name);
    return btn;
  }

  btn.disabled = !inProgress;
  if (
    state.selected &&
    state.selected.row === cell.row &&
    state.selected.column === cell.column
  ) {
    btn.classList.add("selected");
  }
  btn.addEventListener("click", () => selectCell(cell.row, cell.column));
  return btn;
}

function selectCell(row, column) {
  if (!state.match || state.match.status !== "in-progress") return;
  state.selected = { row, column };
  setFeedback("", "info");
  render();
  els.input.focus();
}

function renderSelected() {
  els.selectedCell.replaceChildren();
  if (!state.selected) {
    els.selectedCell.textContent = "Select an empty Cell to guess.";
    return;
  }
  const grid = state.match.grid;
  const rowCat = grid.row_categories[state.selected.row];
  const colCat = grid.column_categories[state.selected.column];
  els.selectedCell.append(
    document.createTextNode("Guessing "),
    axisChip("Row", rowCat),
    document.createTextNode(" ∩ "),
    axisChip("Column", colCat),
  );
}

function axisChip(axis, cat) {
  const span = document.createElement("span");
  span.className = "axis-chip";
  span.textContent = `${axis}: ${cat.label} (${cat.group})`;
  return span;
}

function syncSubmit() {
  els.submit.disabled = !(
    state.selected &&
    state.match &&
    state.match.status === "in-progress" &&
    els.input.value.trim().length > 0
  );
}

// --- autocomplete -------------------------------------------------------

function updateSuggestions() {
  const q = els.input.value.trim().toLowerCase();
  els.suggestions.replaceChildren();
  if (q.length === 0) return;

  // Names that start with the query rank above names that merely contain it, so
  // a short common substring still surfaces the obvious matches within the cap.
  const prefix = [];
  const contains = [];
  for (const name of state.roster) {
    const at = name.toLowerCase().indexOf(q);
    if (at === 0) prefix.push(name);
    else if (at > 0) contains.push(name);
  }

  for (const name of prefix.concat(contains).slice(0, MAX_SUGGESTIONS)) {
    const opt = document.createElement("option");
    opt.value = name;
    els.suggestions.appendChild(opt);
  }
}

function setFeedback(text, kind) {
  els.feedback.textContent = text;
  els.feedback.className = `feedback ${kind || ""}`.trim();
}

// --- wiring -----------------------------------------------------------------

els.input.addEventListener("input", () => {
  updateSuggestions();
  syncSubmit();
});
els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    submitGuess();
  }
});
els.submit.addEventListener("click", submitGuess);

async function init() {
  try {
    await loadRoster();
    await startMatch();
  } catch (err) {
    setFeedback(`Could not start: ${err.message || err}`, "error");
  }
}

init();
