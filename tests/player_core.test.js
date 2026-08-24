const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const core = require("../site/player-core.js");

const songs = JSON.parse(fs.readFileSync(path.join(__dirname, "../content/songs.json"), "utf8"));

test("songs.json contains only unique valid video ids", () => {
  assert.equal(songs.length, 10);
  const ids = songs.map(core.extractVideoId);
  assert.ok(ids.every(Boolean));
  assert.equal(new Set(ids).size, ids.length);
});

test("inactive songs are never selected", () => {
  const candidates = [songs[0], { ...songs[1], active: false }];
  assert.equal(core.selectRandomSong(candidates, () => 0.99).id, songs[0].id);
});

test("random play selects an active valid song", () => {
  assert.equal(core.selectRandomSong(songs, () => 0).id, songs[0].id);
});

test("play something else avoids the current song when possible", () => {
  const firstTwo = songs.slice(0, 2);
  assert.equal(core.selectAnotherSong(firstTwo, firstTwo[0].id, () => 0).id, firstTwo[1].id);
});

test("invalid video ids are ignored safely", () => {
  const invalid = { id: "bad", youtubeVideoId: "not-valid", active: true };
  assert.equal(core.extractVideoId(invalid), null);
  assert.equal(core.selectRandomSong([invalid]), null);
});

test("empty song data is safe", () => {
  assert.equal(core.selectRandomSong([]), null);
  assert.equal(core.selectAnotherSong([], null), null);
});

test("Supabase public snapshot rows normalize to runtime state", () => {
  const payload = { version: 1, generated_at: "2026-08-24T00:00:00Z", currentWeek: { id: "staging-week" }, pastWeeks: [] };
  assert.deepEqual(core.normalizePublicState([{ payload }]), payload);
  assert.deepEqual(core.normalizePublicState(payload), payload);
});
