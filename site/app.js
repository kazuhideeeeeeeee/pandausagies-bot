const CONTENT_ROOT = "../content";
const player = globalThis.PandaPlayerCore;

const state = { songs: [], weeks: [], current: {}, playingSongId: null };

async function loadJson(name) {
  const response = await fetch(`${CONTENT_ROOT}/${name}`);
  if (!response.ok) throw new Error(`${name}: ${response.status}`);
  return response.json();
}

function imageUrl(path) {
  return path ? `../${path.replace(/^\//, "")}` : "";
}

function multilineText(element, value) {
  element.replaceChildren();
  String(value || "").split("\n").forEach((line, index) => {
    if (index) element.append(document.createElement("br"));
    element.append(document.createTextNode(line));
  });
}

function renderCurrentWeek() {
  const week = state.weeks.find((item) => item.id === state.current.currentWeek) || state.weeks[0];
  if (!week) return;

  document.querySelectorAll("[data-current-week]").forEach((node) => {
    node.textContent = String(week.week).padStart(2, "0");
  });

  const formatted = String(week.date || "").replaceAll("-", ".");
  const date = document.querySelector("#week-date");
  date.textContent = formatted;
  date.dateTime = week.date || "";

  const src = imageUrl(week.image);
  [document.querySelector("#hero-image"), document.querySelector("#week-image")].forEach((image) => {
    if (src) image.src = src;
  });
  multilineText(document.querySelector("#week-text"), week.text);
}

function renderWeeks() {
  const list = document.querySelector("#weeks-list");
  list.replaceChildren();
  [...state.weeks].sort((a, b) => b.week - a.week).forEach((week) => {
    const figure = document.createElement("figure");
    figure.className = "week-card";

    const image = document.createElement("img");
    image.src = imageUrl(week.image);
    image.alt = `WEEK ${String(week.week).padStart(2, "0")}のpandausagies`;
    image.loading = "lazy";

    const meta = document.createElement("div");
    meta.className = "week-meta";
    const number = document.createElement("span");
    number.className = "week-number";
    number.textContent = String(week.week).padStart(2, "0");
    const caption = document.createElement("figcaption");
    multilineText(caption, week.text);
    const date = document.createElement("time");
    date.dateTime = week.date;
    date.textContent = String(week.date).replaceAll("-", ".");
    caption.append(date);
    meta.append(number, caption);
    figure.append(image, meta);
    list.append(figure);
  });
}

function playSong(song) {
  const status = document.querySelector("#player-status");
  if (!song) {
    status.textContent = "songs.jsonに実在曲を追加すると、ここで鳴ります";
    document.querySelector("#play").scrollIntoView({ behavior: "smooth" });
    return;
  }

  const videoId = player.extractVideoId(song);
  if (!videoId) {
    status.textContent = "この曲のYouTube URLを確認してください";
    return;
  }

  state.playingSongId = song.id;
  document.querySelector("#song-title").textContent = song.title;
  document.querySelector("#song-note").textContent = song.note || "";
  document.querySelector(".track-label").textContent = "NOW PLAYING";
  const stage = document.querySelector("#video-stage");
  stage.hidden = false;
  stage.innerHTML = "";
  const iframe = document.createElement("iframe");
  iframe.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}?autoplay=1`;
  iframe.title = `${song.title} — YouTube player`;
  iframe.allow = "autoplay; encrypted-media; picture-in-picture";
  iframe.allowFullscreen = true;
  iframe.addEventListener("error", () => {
    status.textContent = "YouTubeを読み込めませんでした。時間をおいてもう一度試してください";
  });
  stage.append(iframe);
  status.textContent = "";
  document.querySelector("#play").scrollIntoView({ behavior: "smooth" });
}

async function init() {
  try {
    [state.songs, state.weeks, state.current] = await Promise.all([
      loadJson("songs.json"),
      loadJson("weeks.json"),
      loadJson("current.json"),
    ]);
    renderCurrentWeek();
    renderWeeks();
    const currentSong = state.songs.find((song) => song.id === state.current.currentSong);
    if (currentSong) {
      document.querySelector("#song-title").textContent = currentSong.title;
      document.querySelector("#song-note").textContent = currentSong.note || "";
      document.querySelector(".track-label").textContent = state.current.preview ? "PREVIEW / THIS WEEK" : "THIS WEEK";
      if (state.current.preview) {
        document.querySelector("#player-status").textContent = "WEEK 00 preview — 正式な今週の曲ではありません";
      }
    }
  } catch (error) {
    document.querySelector("#player-status").textContent = "コンテンツを読み込めませんでした";
    console.error(error);
  }
}

document.querySelectorAll("[data-random-play]").forEach((button) => {
  button.addEventListener("click", () => playSong(player.selectRandomSong(state.songs)));
});
document.querySelector("[data-another-song]").addEventListener("click", () => {
  playSong(player.selectAnotherSong(state.songs, state.playingSongId));
});

init();
