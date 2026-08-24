(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PandaPlayerCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;

  function extractVideoId(song) {
    const directId = song && song.youtubeVideoId;
    if (VIDEO_ID_PATTERN.test(directId || "")) return directId;
    try {
      const url = new URL(song.youtubeUrl);
      const value = url.hostname === "youtu.be" ? url.pathname.slice(1) : url.searchParams.get("v");
      return VIDEO_ID_PATTERN.test(value || "") ? value : null;
    } catch {
      return null;
    }
  }

  function activeSongs(songs) {
    return songs.filter((song) => song.active !== false && extractVideoId(song));
  }

  function selectRandomSong(songs, random = Math.random) {
    const available = activeSongs(songs);
    if (!available.length) return null;
    return available[Math.floor(random() * available.length)];
  }

  function selectAnotherSong(songs, currentId, random = Math.random) {
    const available = activeSongs(songs);
    if (!available.length) return null;
    const alternatives = available.filter((song) => song.id !== currentId);
    const pool = alternatives.length ? alternatives : available;
    return pool[Math.floor(random() * pool.length)];
  }

  function normalizePublicState(raw) {
    const row = Array.isArray(raw) ? raw[0] : raw;
    return row && typeof row.payload === "object" ? row.payload : row;
  }

  return { extractVideoId, activeSongs, selectRandomSong, selectAnotherSong, normalizePublicState };
});
