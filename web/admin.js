const tokenInput = document.getElementById("adminToken");
const matchSelect = document.getElementById("matchSelect");
const statusSelect = document.getElementById("statusSelect");
const minuteInput = document.getElementById("minuteInput");
const homeScoreInput = document.getElementById("homeScoreInput");
const awayScoreInput = document.getElementById("awayScoreInput");
const noteInput = document.getElementById("noteInput");
const adminStatus = document.getElementById("adminStatus");
const liveAdminUpdated = document.getElementById("liveAdminUpdated");
const adminLiveList = document.getElementById("adminLiveList");

let matches = [];

function setStatus(message, kind = "") {
  adminStatus.textContent = message;
  adminStatus.className = `adminStatus ${kind}`;
}

function teamLabel(match) {
  return `${match.date} · ${match.home} vs ${match.away} · ${match.city}`;
}

function saveToken() {
  localStorage.setItem("adminToken", tokenInput.value.trim());
}

function loadSavedToken() {
  tokenInput.value = localStorage.getItem("adminToken") || "";
}

function numberOrNull(value) {
  if (value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function liveScore(match) {
  const home = match.home_score ?? "-";
  const away = match.away_score ?? "-";
  return `${home} - ${away}`;
}

function liveStatus(match) {
  const minute = match.minute ? `${match.minute}'` : "";
  const injury = match.injury_time ? `+${match.injury_time}` : "";
  return [match.status, `${minute}${injury}`].filter(Boolean).join(" · ");
}

async function loadMatches() {
  const res = await fetch("/api/tournament", { cache: "no-store" });
  if (!res.ok) throw new Error("Could not load matches");
  const data = await res.json();
  matches = data.matches || [];
  matchSelect.replaceChildren();
  matches.forEach((match) => {
    const option = document.createElement("option");
    option.value = match.id;
    option.textContent = teamLabel(match);
    matchSelect.appendChild(option);
  });
}

async function loadLive() {
  const res = await fetch("/api/live", { cache: "no-store" });
  if (!res.ok) throw new Error("Could not load live data");
  const data = await res.json();
  liveAdminUpdated.textContent = data.last_checked_at || "-";
  if (!data.matches?.length) {
    adminLiveList.innerHTML = `<div class="liveEmpty"><strong>暂无实时赛况</strong><span>${data.last_error || "No live matches"}</span></div>`;
    return;
  }
  adminLiveList.innerHTML = data.matches
    .map(
      (match) => `
        <article class="liveCard ${match.status?.toLowerCase() || ""}">
          <div class="teams"><span>${match.home}</span><span>${match.away}</span></div>
          <div class="liveScore">${liveScore(match)}</div>
          <div class="meta"><span>${liveStatus(match)}</span><span>${match.note || match.source || ""}</span></div>
        </article>
      `,
    )
    .join("");
}

async function saveLiveUpdate(event) {
  event.preventDefault();
  const token = tokenInput.value.trim();
  if (!token) {
    setStatus("请先输入管理员密码。", "error");
    return;
  }
  saveToken();

  const payload = {
    match_id: matchSelect.value,
    status: statusSelect.value,
    minute: numberOrNull(minuteInput.value),
    home_score: numberOrNull(homeScoreInput.value),
    away_score: numberOrNull(awayScoreInput.value),
    note: noteInput.value.trim(),
  };

  setStatus("Saving...");
  const res = await fetch("/api/live", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": token,
    },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    setStatus(data.error || "保存失败。", "error");
    return;
  }
  setStatus("已保存，首页实时赛况会自动更新。", "success");
  await loadLive();
}

document.getElementById("adminForm").addEventListener("submit", saveLiveUpdate);

loadSavedToken();
loadMatches()
  .then(loadLive)
  .then(() => setStatus("Ready"))
  .catch((error) => setStatus(error.message, "error"));

setInterval(() => {
  loadLive().catch(() => {});
}, 30000);
