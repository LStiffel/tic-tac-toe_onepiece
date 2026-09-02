"use strict";

/*
 * Thin hotseat frontend. It renders Match state and relays moves; every rule
 * lives server-side (app/statemachine.py), so a hand-crafted request cannot
 * bypass the Roster check. No build step, no framework (ADR 0001).
 *
 * Issue #9 built the Grid + claim interaction. Issue #10 completes the screen:
 * an end-of-Match banner, a Pass button, a live Used-pool view, a Rematch
 * button, and Character art that falls back to a placeholder when the
 * `/images/...webp` file is absent (which, in text-only v1, is always).
 */

const MARKS = { P1: "X", P2: "O" };
const MAX_SUGGESTIONS = 50;

const state = {
  matchId: null,
  match: null, // the latest MatchOut from the server
  roster: [], // canonical Character names, for autocomplete
  images: {}, // canonical name -> "/images/...webp" (or "" when unknown)
  selected: null, // { row, column } of the Cell being guessed, or null
  lastClaim: null, // { name } of the most recently claimed Character, or null
};

const els = {
  turn: document.getElementById("turn-indicator"),
  banner: document.getElementById("banner"),
  grid: document.getElementById("grid"),
  selectedCell: document.getElementById("selected-cell"),
  input: document.getElementById("guess-input"),
  suggestions: document.getElementById("roster-suggestions"),
  submit: document.getElementById("guess-submit"),
  passBtn: document.getElementById("pass-btn"),
  rematchBtn: document.getElementById("rematch-btn"),
  feedback: document.getElementById("feedback"),
  art: document.getElementById("art"),
  artPortrait: document.getElementById("art-portrait"),
  artCaption: document.getElementById("art-caption"),
  usedCount: document.getElementById("used-count"),
  usedPoolEmpty: document.getElementById("used-pool-empty"),
  usedPoolList: document.getElementById("used-pool-list"),
};

// --- API --------------------------------------------------------------------

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  // A Guess/Pass rejection (not-your-turn, unknown-character, ...) comes back as
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

async function loadCharacterArt() {
  const characters = await api("GET", "/characters");
  state.images = Object.fromEntries(characters.map((c) => [c.name, c.image]));
}

function applyNewMatch(match, message) {
  state.matchId = match.id;
  state.match = match;
  state.selected = null;
  state.lastClaim = null;
  els.input.value = "";
  updateSuggestions();
  render();
  setFeedback(message, "info");
}

async function startMatch() {
  const match = await api("POST", "/matches", {});
  applyNewMatch(match, `New Match. ${toMoveLine(match)}`);
}

async function rematch() {
  els.rematchBtn.disabled = true;
  let match;
  try {
    match = await api("POST", `/matches/${state.matchId}/rematch`, {});
  } catch (err) {
    setFeedback(`Could not start a rematch: ${err.message || err}`, "error");
    els.rematchBtn.disabled = false;
    return;
  }
  applyNewMatch(match, `Rematch. Fresh Grid, empty Used pool. ${toMoveLine(match)}`);
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
    syncControls();
    return;
  }

  state.match = result.match;
  applyOutcome(result, character);
  els.input.value = "";
  updateSuggestions();
  render();
}

async function submitPass() {
  if (els.passBtn.disabled) return;
  const player = state.match.active_player;

  els.passBtn.disabled = true;
  let result;
  try {
    result = await api("POST", `/matches/${state.matchId}/passes`, { player });
  } catch (err) {
    setFeedback(String(err.message || err), "error");
    syncControls();
    return;
  }

  state.match = result.match;
  state.selected = null;
  els.input.value = "";
  updateSuggestions();

  if (result.outcome === "passed") {
    if (result.match.status === "draw") {
      setFeedback("Two Passes in immediate succession — the Match is a draw.", "warn");
    } else {
      setFeedback(`Turn passed. ${toMoveLine(result.match)}`, "info");
    }
  } else {
    setFeedback(rejectionPhrase(result.reason), "error");
  }
  render();
}

// --- outcome -> feedback --------------------------------------------------

function applyOutcome(result, character) {
  const cell = state.selected
    ? `R${state.selected.row + 1}×C${state.selected.column + 1}`
    : "the Cell";

  switch (result.outcome) {
    case "claimed": {
      state.lastClaim = { name: character };
      const next =
        result.match.status === "in-progress"
          ? toMoveLine(result.match)
          : "Match over.";
      setFeedback(`${character} claimed ${cell}. ${next}`, "ok");
      state.selected = null;
      break;
    }
    case "wrong":
      setFeedback(
        `${character}: ${axisPhrase(result.row, result.column)}. ` +
          `Turn forfeited — ${toMoveLine(result.match)}`,
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
  renderBanner();
  renderGrid();
  renderSelected();
  renderArt();
  renderUsedPool();
  syncControls();
}

function playerLabel(player) {
  return `Player ${player.slice(1)} (${MARKS[player]})`;
}

function turnLabel(match) {
  return playerLabel(match.active_player);
}

function toMoveLine(match) {
  return `${turnLabel(match)} to move.`;
}

function renderTurn() {
  const m = state.match;
  if (!m) {
    els.turn.textContent = "";
    return;
  }
  if (m.status !== "in-progress") {
    els.turn.textContent = "Match over";
    els.turn.className = "turn over";
  } else {
    els.turn.textContent = `${turnLabel(m)} to move`;
    els.turn.className = `turn ${m.active_player.toLowerCase()}`;
  }
}

function renderBanner() {
  const m = state.match;
  if (!m || m.status === "in-progress") {
    els.banner.hidden = true;
    els.banner.textContent = "";
    els.banner.className = "banner";
    return;
  }
  els.banner.hidden = false;
  if (m.status === "won") {
    els.banner.textContent = `${playerLabel(m.winner)} wins the Match!`;
    els.banner.className = "banner banner-win";
  } else {
    els.banner.textContent = "The Match is a draw.";
    els.banner.className = "banner banner-draw";
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
    btn.append(mark, portrait(cell.character, "sm"), name);
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

// --- Character art ------------------------------------------------------

// A portrait node: an <img> pointing at the known `/images/...webp` path, or a
// styled placeholder when there is no path or the file 404s — so the text-only
// v1 still looks deliberate. `size` is "sm" or "lg".
function portrait(name, size) {
  const wrap = document.createElement("span");
  wrap.className = `portrait portrait-${size}`;
  const src = state.images[name] || "";
  if (src) {
    const img = document.createElement("img");
    img.src = src;
    img.alt = "";
    img.loading = "lazy";
    img.addEventListener("error", () => {
      wrap.classList.add("portrait-missing");
      wrap.replaceChildren(placeholderGlyph());
    });
    wrap.appendChild(img);
  } else {
    wrap.classList.add("portrait-missing");
    wrap.appendChild(placeholderGlyph());
  }
  return wrap;
}

function placeholderGlyph() {
  const glyph = document.createElement("span");
  glyph.className = "portrait-glyph";
  glyph.textContent = "☠";
  glyph.setAttribute("aria-hidden", "true");
  return glyph;
}

function renderArt() {
  if (!state.lastClaim) {
    els.art.hidden = true;
    return;
  }
  const { name } = state.lastClaim;
  els.art.hidden = false;
  // Insert the portrait node itself (not its children) so its own `error`
  // handler still points at a node that is in the DOM — otherwise a 404 on the
  // large art would leave a broken <img> instead of the placeholder.
  els.artPortrait.replaceChildren(portrait(name, "lg"));
  els.artCaption.textContent = `Last claimed: ${name}`;
}

// --- Used-pool view ---------------------------------------------------

function renderUsedPool() {
  const used = (state.match && state.match.used_pool) || [];
  els.usedCount.textContent = String(used.length);
  els.usedPoolEmpty.hidden = used.length > 0;
  els.usedPoolList.replaceChildren(
    ...used.map((name) => {
      const li = document.createElement("li");
      li.className = "used-entry";
      const label = document.createElement("span");
      label.className = "used-name";
      label.textContent = name;
      li.append(portrait(name, "sm"), label);
      return li;
    }),
  );
}

// --- controls -------------------------------------------------------

function syncControls() {
  const m = state.match;
  const inProgress = Boolean(m && m.status === "in-progress");
  els.submit.disabled = !(
    inProgress &&
    state.selected &&
    els.input.value.trim().length > 0
  );
  els.passBtn.disabled = !inProgress;
  els.rematchBtn.disabled = !m;
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
  syncControls();
});
els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    submitGuess();
  }
});
els.submit.addEventListener("click", submitGuess);
els.passBtn.addEventListener("click", submitPass);
els.rematchBtn.addEventListener("click", rematch);

async function init() {
  try {
    await Promise.all([loadRoster(), loadCharacterArt()]);
    await startMatch();
  } catch (err) {
    setFeedback(`Could not start: ${err.message || err}`, "error");
  }
}

init();
