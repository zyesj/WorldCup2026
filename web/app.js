const pct = (value) => `${(value * 100).toFixed(1)}%`;
const one = (value) => value.toFixed(1);
let currentData = null;
let languageMode = localStorage.getItem("languageMode") || "both";
let userPicks = JSON.parse(localStorage.getItem("userPicks") || "{}");
let currentUser = JSON.parse(localStorage.getItem("currentUser") || "null");

const TEAM_NAMES = {
  Algeria: "阿尔及利亚",
  Argentina: "阿根廷",
  Australia: "澳大利亚",
  Austria: "奥地利",
  Belgium: "比利时",
  "Bosnia and Herzegovina": "波黑",
  Brazil: "巴西",
  Canada: "加拿大",
  "Cape Verde": "佛得角",
  Colombia: "哥伦比亚",
  Croatia: "克罗地亚",
  Curaçao: "库拉索",
  "Czech Republic": "捷克",
  "DR Congo": "刚果民主共和国",
  Ecuador: "厄瓜多尔",
  Egypt: "埃及",
  England: "英格兰",
  France: "法国",
  Germany: "德国",
  Ghana: "加纳",
  Haiti: "海地",
  Iran: "伊朗",
  Iraq: "伊拉克",
  "Ivory Coast": "科特迪瓦",
  Japan: "日本",
  Jordan: "约旦",
  Mexico: "墨西哥",
  Morocco: "摩洛哥",
  Netherlands: "荷兰",
  "New Zealand": "新西兰",
  Norway: "挪威",
  Panama: "巴拿马",
  Paraguay: "巴拉圭",
  Portugal: "葡萄牙",
  Qatar: "卡塔尔",
  "Saudi Arabia": "沙特阿拉伯",
  Scotland: "苏格兰",
  Senegal: "塞内加尔",
  "South Africa": "南非",
  "South Korea": "韩国",
  Spain: "西班牙",
  Sweden: "瑞典",
  Switzerland: "瑞士",
  Tunisia: "突尼斯",
  Turkey: "土耳其",
  "United States": "美国",
  Uruguay: "乌拉圭",
  Uzbekistan: "乌兹别克斯坦",
};

const NEWS_ITEMS = [
  {
    tagZh: "赛程",
    tagEn: "Schedule",
    level: "live",
    time: "Jun 11",
    zh: "世界杯开幕：墨西哥 vs 南非，随后韩国 vs 捷克。",
    en: "World Cup opens: Mexico vs South Africa, then South Korea vs Czech Republic.",
  },
  {
    tagZh: "冷门",
    tagEn: "Upset",
    level: "watch",
    time: "Jun 11",
    zh: "墨西哥重压主场，南非被部分市场分析视为价值冷门。",
    en: "Mexico carry home pressure; some market analysis flags South Africa as upset value.",
  },
  {
    tagZh: "伤情",
    tagEn: "Injury",
    level: "alert",
    time: "Jun 11",
    zh: "澳大利亚前锋 Mo Toure 缺席训练，对阵土耳其前锋线存疑。",
    en: "Australia striker Mo Toure missed training; forward depth in question before Turkey.",
  },
  {
    tagZh: "模型",
    tagEn: "Model",
    level: "model",
    time: "Now",
    zh: "当前冠军路径：西班牙；预计决赛：西班牙 vs 阿根廷。",
    en: "Current champion path: Spain; projected final: Spain vs Argentina.",
  },
];

const I18N = {
  title: { zh: "世界杯预测指挥中心", en: "World Cup Prediction Center" },
  currentPath: { zh: "当前冠军路径", en: "Current Champion Path" },
  todayFocus: { zh: "今日重点", en: "Today's Focus" },
  upsetRadar: { zh: "冷门雷达", en: "Upset Radar" },
  groupPrediction: { zh: "小组预测", en: "Group Forecast" },
  expectedTable: { zh: "预计积分榜", en: "Expected Table" },
  bracketTree: { zh: "淘汰赛树", en: "Bracket Tree" },
  mostLikelyPath: { zh: "最可能路径", en: "Most Likely Path" },
  allGroupMatches: { zh: "全部小组赛预测", en: "All Group Match Predictions" },
  wdw: { zh: "胜 / 平 / 负", en: "Win / Draw / Win" },
  championPath: { zh: "冠军路径", en: "Champion Path" },
  generatedAt: { zh: "生成时间", en: "Generated" },
  modelNote: { zh: "模型提示", en: "Model Note" },
  winner: { zh: "晋级", en: "Advances" },
  group: { zh: "小组", en: "Group" },
  userPick: { zh: "你的预测", en: "Your Pick" },
  noPick: { zh: "未选择", en: "No Pick" },
  modelPick: { zh: "模型倾向", en: "Model Pick" },
  picked: { zh: "已选", en: "Picked" },
  matches: { zh: "场", en: "matches" },
  myPicks: { zh: "我的竞猜", en: "My Picks" },
  leaderboard: { zh: "排行榜", en: "Leaderboard" },
  scoreRule: { zh: "命中 +3 分", en: "Correct +3 pts" },
  localOnly: { zh: "本地模式", en: "Local mode" },
  signedIn: { zh: "已登录", en: "Signed in" },
  noRank: { zh: "暂无排行榜数据", en: "No leaderboard yet" },
};

function teamName(team) {
  const zh = TEAM_NAMES[team] || team;
  if (languageMode === "zh") return zh;
  if (languageMode === "en") return team;
  return `${zh} ${team}`;
}

const ROUND_LABELS = {
  "Round of 32": { zh: "32 强", en: "Round of 32" },
  "Round of 16": { zh: "16 强", en: "Round of 16" },
  "Quarter-finals": { zh: "四分之一决赛", en: "Quarter-finals" },
  "Semi-finals": { zh: "半决赛", en: "Semi-finals" },
  Final: { zh: "决赛", en: "Final" },
};

function text(key) {
  const entry = I18N[key];
  if (!entry) return key;
  if (languageMode === "zh") return entry.zh;
  if (languageMode === "en") return entry.en;
  return `${entry.zh} / ${entry.en}`;
}

function roundText(round) {
  const entry = ROUND_LABELS[round] || { zh: round, en: round };
  if (languageMode === "zh") return entry.zh;
  if (languageMode === "en") return entry.en;
  return `${entry.zh} / ${entry.en}`;
}

function pickLabel(match, pick) {
  if (pick === "home") return teamName(match.home);
  if (pick === "draw") return languageMode === "en" ? "Draw" : languageMode === "zh" ? "平局" : "平局 Draw";
  if (pick === "away") return teamName(match.away);
  return text("noPick");
}

function modelPick(match) {
  const entries = [
    ["home", match.probabilities.home_win],
    ["draw", match.probabilities.draw],
    ["away", match.probabilities.away_win],
  ];
  return entries.sort((a, b) => b[1] - a[1])[0][0];
}

function pickedCount(data) {
  if (!data) return 0;
  const validIds = new Set(data.matches.map((match) => match.id));
  return Object.keys(userPicks).filter((id) => validIds.has(id)).length;
}

function renderPickSummary(total) {
  const picked = pickedCount(currentData);
  document.getElementById("pickSummary").textContent = `${text("picked")} ${picked}/${total} ${text("matches")} · ${text("wdw")}`;
  const stats = document.getElementById("myPickStats");
  if (stats) {
    const percent = total ? Math.round((picked / total) * 100) : 0;
    stats.innerHTML = `
      <div class="pickStatsNumber">${picked}/${total}</div>
      <div class="pickStatsText">${text("picked")} ${picked} ${text("matches")} · ${percent}%</div>
      <div class="pickStatsBar"><span style="width:${percent}%"></span></div>
    `;
  }
}

function renderUserStatus() {
  const status = document.getElementById("userStatus");
  if (!status) return;
  status.textContent = currentUser ? `${text("signedIn")}：${currentUser.nickname}` : text("localOnly");
  const input = document.getElementById("nicknameInput");
  if (input && currentUser) input.value = currentUser.nickname;
}

function renderLeaderboard(rows) {
  const target = document.getElementById("leaderboard");
  if (!target) return;
  if (!rows.length) {
    target.innerHTML = `<div class="emptyRank">${text("noRank")}</div>`;
    return;
  }
  target.innerHTML = rows
    .map(
      (row, idx) => `
      <div class="rankRow">
        <span>${idx + 1}</span>
        <strong>${row.nickname}</strong>
        <span>${row.score} pts</span>
        <small>${row.correct}/${row.graded || 0}</small>
      </div>
    `,
    )
    .join("");
}

function applyStaticText() {
  document.documentElement.lang = languageMode === "en" ? "en" : "zh-CN";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = text(node.dataset.i18n);
  });
  document.querySelectorAll(".langButton").forEach((button) => {
    button.classList.toggle("active", button.dataset.lang === languageMode);
  });
}

async function loadData() {
  for (const url of ["/api/tournament", "./tournament_predictions.json", "../outputs/tournament_predictions.json"]) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) return res.json();
    } catch (error) {
      console.warn(`Could not load ${url}`, error);
    }
  }
  return window.__TOURNAMENT_DATA__;
}

async function apiPost(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API ${path} failed`);
  return res.json();
}

async function loadLeaderboard() {
  try {
    const res = await fetch("/api/leaderboard", { cache: "no-store" });
    if (!res.ok) throw new Error("leaderboard unavailable");
    return (await res.json()).leaderboard;
  } catch {
    return [];
  }
}

async function loadUpdateStatus() {
  try {
    const res = await fetch("/api/update-status", { cache: "no-store" });
    if (!res.ok) throw new Error("update status unavailable");
    return res.json();
  } catch {
    return null;
  }
}

async function savePickRemote(matchId, pick) {
  if (!currentUser) return;
  try {
    await apiPost("/api/picks", { user_id: currentUser.id, match_id: matchId, pick });
    renderLeaderboard(await loadLeaderboard());
  } catch (error) {
    console.warn("Could not save pick remotely", error);
  }
}

function matchMini(match) {
  const p = match.probabilities;
  return `
    <div class="miniMatch">
      <div class="teams"><span>${teamName(match.home)}</span><span>${teamName(match.away)}</span></div>
      <div class="bar" title="${pct(p.home_win)} / ${pct(p.draw)} / ${pct(p.away_win)}">
        <span style="width:${p.home_win * 100}%"></span>
        <span style="width:${p.draw * 100}%"></span>
        <span style="width:${p.away_win * 100}%"></span>
      </div>
      <div class="meta"><span>${match.city}</span><span>${pct(p.home_win)} · ${pct(p.draw)} · ${pct(p.away_win)}</span></div>
    </div>
  `;
}

function renderHero(data) {
  document.getElementById("champion").textContent = `${text("championPath")}：${teamName(data.champion)}`;
  document.getElementById("championBig").textContent = teamName(data.champion);
  document.getElementById("modelVersion").textContent = data.model_version;
  document.getElementById("generatedAt").textContent = `${text("generatedAt")}：${data.generated_at}`;

  const today = data.matches.filter((m) => m.date === "2026-06-11");
  document.getElementById("todayMatches").innerHTML = today.map(matchMini).join("");

  const upsets = [...data.matches].sort((a, b) => b.upset_score - a.upset_score).slice(0, 5);
  document.getElementById("upsetRadar").innerHTML = upsets
    .map(
      (m) => `
      <div class="miniMatch">
        <div class="teams"><span>${teamName(m.home)}</span><span>${teamName(m.away)}</span></div>
        <div class="meta"><span>${m.date} · ${text("group")} ${m.group}</span><span>${one(m.upset_score)}/100</span></div>
      </div>
    `,
    )
    .join("");
}

function renderUpdateStatus(status) {
  const node = document.getElementById("modelVersion");
  if (!node || !status) return;
  const mins = status.interval_seconds ? Math.round(status.interval_seconds / 60) : "-";
  node.textContent = `${currentData?.model_version || "Model"} · ${status.mode} · ${mins}m`;
}

function renderTicker(data) {
  const newsLabel = languageMode === "en" ? "News" : languageMode === "zh" ? "快讯" : "快讯 / News";
  const items = NEWS_ITEMS.map((item) => {
    const tag = languageMode === "en" ? item.tagEn : languageMode === "zh" ? item.tagZh : `${item.tagZh}/${item.tagEn}`;
    const body = languageMode === "en" ? item.en : languageMode === "zh" ? item.zh : `${item.zh} / ${item.en}`;
    return `<span class="newsBadge ${item.level}">${tag}</span><span class="newsTime">${item.time}</span><b>${newsLabel}</b>${body}`;
  });
  const html = [...items, ...items].map((item) => `<span class="tickerItem">${item}</span>`).join("");
  document.getElementById("tickerTrack").innerHTML = html;
}

function renderGroups(data) {
  const html = Object.entries(data.group_tables)
    .map(([group, rows]) => {
      const teamRows = rows
        .map(
          (r, idx) => `
          <div class="teamRow">
            <span>${idx + 1}</span>
            <strong>${teamName(r.team)}</strong>
            <span>${one(r.points)}</span>
          </div>
        `,
        )
        .join("");
      return `
        <div class="groupBox">
          <div class="groupTitle">${text("group")} ${group}</div>
          ${teamRows}
        </div>
      `;
    })
    .join("");
  document.getElementById("groups").innerHTML = html;
}

function renderBracket(data) {
  const rounds = ["Round of 32", "Round of 16", "Quarter-finals", "Semi-finals", "Final"];
  const html = rounds
    .map((round) => {
      const nodes = data.bracket
        .filter((m) => m.round === round)
        .map(
          (m) => `
          <div class="node">
            <div>${teamName(m.home)}</div>
            <div>${teamName(m.away)}</div>
            <div class="nodeWinner">→ ${text("winner")}：${teamName(m.winner)}</div>
            <div class="prob">${pct(m.home_advance)} / ${pct(m.away_advance)} · ${m.scoreline}</div>
          </div>
        `,
        )
        .join("");
      return `<div class="round"><div class="roundTitle">${roundText(round)}</div>${nodes}</div>`;
    })
    .join("");
  document.getElementById("bracket").innerHTML = html;
}

function renderMatches(data) {
  renderPickSummary(data.matches.length);
  const html = data.matches
    .map((m) => {
      const p = m.probabilities;
      const pick = userPicks[m.id];
      const model = modelPick(m);
      return `
        <article class="matchCard">
          <div class="teams"><span>${teamName(m.home)}</span><span>${teamName(m.away)}</span></div>
          <div class="bar">
            <span style="width:${p.home_win * 100}%"></span>
            <span style="width:${p.draw * 100}%"></span>
            <span style="width:${p.away_win * 100}%"></span>
          </div>
          <div class="meta"><span>${m.date} · ${text("group")} ${m.group}</span><span>${m.scoreline}</span></div>
          <div class="meta"><span>${m.city}</span><span>${pct(p.home_win)} / ${pct(p.draw)} / ${pct(p.away_win)}</span></div>
          <div class="pickBox">
            <div class="pickTitle">${text("userPick")}：<strong>${pickLabel(m, pick)}</strong></div>
            <div class="pickButtons" data-match-id="${m.id}">
              <button class="pickButton ${pick === "home" ? "selected" : ""}" data-pick="home">${teamName(m.home)}</button>
              <button class="pickButton ${pick === "draw" ? "selected" : ""}" data-pick="draw">${languageMode === "en" ? "Draw" : languageMode === "zh" ? "平局" : "平局 Draw"}</button>
              <button class="pickButton ${pick === "away" ? "selected" : ""}" data-pick="away">${teamName(m.away)}</button>
            </div>
            <div class="meta pickMeta">
              <span>${text("modelPick")}：${pickLabel(m, model)}</span>
              <span>${pick ? (pick === model ? "✓" : "↯") : ""}</span>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
  document.getElementById("matchList").innerHTML = html;
  document.querySelectorAll(".pickButton").forEach((button) => {
    button.addEventListener("click", () => {
      const matchId = button.parentElement.dataset.matchId;
      userPicks[matchId] = button.dataset.pick;
      localStorage.setItem("userPicks", JSON.stringify(userPicks));
      savePickRemote(matchId, button.dataset.pick);
      renderMatches(currentData);
    });
  });
}

function renderAll(data) {
  applyStaticText();
  renderUserStatus();
  renderHero(data);
  renderTicker(data);
  renderGroups(data);
  renderBracket(data);
  renderMatches(data);
}

document.querySelectorAll(".langButton").forEach((button) => {
  button.addEventListener("click", () => {
    languageMode = button.dataset.lang;
    localStorage.setItem("languageMode", languageMode);
    if (currentData) renderAll(currentData);
    loadLeaderboard().then(renderLeaderboard);
  });
});

document.getElementById("loginForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const nickname = document.getElementById("nicknameInput").value;
  try {
    const payload = await apiPost("/api/users", { nickname });
    currentUser = payload.user;
    localStorage.setItem("currentUser", JSON.stringify(currentUser));
    renderUserStatus();
    renderLeaderboard(await loadLeaderboard());
  } catch (error) {
    alert(languageMode === "en" ? "Could not save nickname." : "昵称保存失败。");
  }
});

loadData().then((data) => {
  currentData = data;
  renderAll(data);
  loadLeaderboard().then(renderLeaderboard);
  loadUpdateStatus().then(renderUpdateStatus);
});

setInterval(async () => {
  const latest = await loadData();
  if (latest?.generated_at && latest.generated_at !== currentData?.generated_at) {
    currentData = latest;
    renderAll(latest);
  }
  loadUpdateStatus().then(renderUpdateStatus);
}, 60000);

setInterval(() => {
  loadLeaderboard().then(renderLeaderboard);
}, 30000);
