/* Sports by Numbers — basketball views (college and NBA share this script). Reads the JSON the daily job writes. */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const poss = (name) => (/s$/.test(name) ? name + "\u2019" : name + "\u2019s");  // Giants' / Duke's
  const f1 = (x) => (x == null ? "–" : Number(x).toFixed(1));
  const sgn = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
  const cls = (x) => (x > 0.05 ? "pos" : x < -0.05 ? "neg" : "");
  const pct = (p) => (p >= 0.995 ? ">99%" : p <= 0.005 ? "<1%" : Math.round(p * 100) + "%");
  const VIEWS = ["rankings", "players", "lineups", "games", "matchup", "bracket", "value", "method"];

  let D = {};
  let LG = { nba: false, level: "Division I", short: "D-I", minutes: 40 };  // replaced by meta.league on load
  const teamById = {};

  function store(k, v) { try { v === undefined ? localStorage.getItem(k) : localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
  function recall(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  async function load() {
    const names = ["meta", "teams", "players", "lineups", "games"];
    const res = await Promise.all(names.map((n) => fetch("data/" + n + ".json").then((r) => { if (!r.ok) throw new Error(n); return r.json(); })));
    names.forEach((n, i) => (D[n] = res[i]));
    D.bracket = await fetch("data/bracket.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    D.value = await fetch("data/value.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    D.teams.forEach((t) => (teamById[t.id] = t));
    if (D.meta.league) LG = D.meta.league;
    $("#stamp").textContent = D.meta.season + " · updated " + new Date(D.meta.updated).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    if (/simulat/i.test(D.meta.season)) {
      if ($("#banner")) $("#banner").hidden = false;
    }
    window.addEventListener("hashchange", route);
    document.addEventListener("click", (e) => {
      const card = e.target.closest(".card.game");
      if (card && !e.target.closest("a")) location.hash = card.dataset.href;
    });
    route();
  }

  function teamLink(id, withConf) {
    const t = teamById[id];
    if (!t) return esc(id);
    return '<span class="dot" style="background:#' + esc(t.color) + '"></span><a href="#team-' + esc(t.id) + '">' + esc(t.short || t.name) + "</a>" +
      (withConf && t.conf ? '<span class="sub">' + esc(t.conf) + "</span>" : "");
  }

  function netBar(x, max) {
    const w = Math.min(Math.abs(x) / max, 1) * 50;
    const style = x >= 0 ? "left:50%;width:" + w + "%;background:var(--pos)" : "right:50%;width:" + w + "%;background:var(--neg)";
    return '<span class="bar"><span class="' + cls(x) + '">' + sgn(x) + '</span><i><b style="' + style + '"></b></i></span>';
  }

  /* Sortable table. cols: {key,label,left,html(row),val(row),asc} */
  function table(el, cols, rows, sortKey, opts) {
    opts = opts || {};
    let key = sortKey, asc = !!(cols.find((c) => c.key === sortKey) || {}).asc, shown = opts.page || 100;
    function draw() {
      const col = cols.find((c) => c.key === key);
      const v = col.val || ((r) => r[key]);
      const sorted = rows.slice().sort((a, b) => {
        const x = v(a), y = v(b);
        if (x == null) return 1; if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
      });
      const head = cols.map((c) => '<th scope="col" data-k="' + c.key + '" class="' + (c.left ? "l " : "") + (c.key === key ? "sorted" + (asc ? " asc" : "") : "") + '">' + c.label + "</th>").join("");
      const body = sorted.slice(0, shown).map((r) => "<tr>" + cols.map((c) => '<td class="' + (c.left ? "l " : "") + (c.cls || "") + '">' + (c.html ? c.html(r) : esc(r[c.key])) + "</td>").join("") + "</tr>").join("");
      el.innerHTML = '<div class="table-box"><table><thead><tr>' + head + "</tr></thead><tbody>" + (body || '<tr><td class="l" colspan="' + cols.length + '">Nothing matches these filters.</td></tr>') + "</tbody></table></div>" +
        (sorted.length > shown ? '<div class="more"><button type="button" data-more>Show ' + Math.min(100, sorted.length - shown) + " more of " + sorted.length + "</button></div>" : "");
      el.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
        const c = cols.find((x) => x.key === th.dataset.k);
        if (key === c.key) asc = !asc; else { key = c.key; asc = !!c.asc; }
        draw();
      }));
      const more = el.querySelector("[data-more]");
      if (more) more.addEventListener("click", () => { shown += 100; draw(); });
    }
    draw();
  }

  function confOptions(sel) {
    const confs = [...new Set(D.teams.map((t) => t.conf).filter(Boolean))].sort();
    return '<option value="">All conferences</option>' + confs.map((c) => '<option' + (c === sel ? " selected" : "") + ">" + esc(c) + "</option>").join("");
  }
  function teamOptions(sel, blank) {
    return (blank ? '<option value="">' + blank + "</option>" : "") +
      D.teams.slice().sort((a, b) => (a.short || a.name).localeCompare(b.short || b.name))
        .map((t) => '<option value="' + t.id + '"' + (t.id === sel ? " selected" : "") + ">" + esc(t.short || t.name) + "</option>").join("");
  }

  /* ---------------- views ---------------- */

  function rankings(main) {
    main.innerHTML = '<div><h1>Team Ratings</h1><p class="lede">Points per 100 possessions against an average opponent on a neutral floor. Net is offense minus defense; ± shows one standard error.</p></div>' +
      '<div class="controls"><div class="field"><label for="r-q">Search</label><input type="search" id="r-q" placeholder="Team name"></div>' +
      '<div class="field"><label for="r-c">Conference</label><select id="r-c">' + confOptions(recall("sbn-conf")) + "</select></div></div><div id='r-t'></div>";
    const max = Math.max(...D.teams.map((t) => Math.abs(t.net)), 1);
    const cols = [
      { key: "rank", label: "Rk", asc: true },
      { key: "name", label: "Team", left: true, cls: "name", html: (t) => teamLink(t.id, true), val: (t) => t.short, asc: true },
      { key: "rec", label: "W-L", html: (t) => t.w + "-" + t.l, val: (t) => t.w - t.l },
      { key: "net", label: "Net", html: (t) => netBar(t.net, max) },
      { key: "net_se", label: "±", html: (t) => f1(t.net_se), asc: true },
      { key: "o", label: "Off", html: (t) => f1(t.o) + '<span class="rk">' + t.o_rank + "</span>" },
      { key: "d", label: "Def", asc: true, html: (t) => f1(t.d) + '<span class="rk">' + t.d_rank + "</span>" },
      { key: "tempo", label: "Tempo", html: (t) => f1(t.tempo) + '<span class="rk">' + t.t_rank + "</span>" },
      { key: "pre", label: "Pre", html: (t) => (t.pre == null ? "–" : '<span class="' + cls(t.pre) + '">' + sgn(t.pre) + "</span>") },
      { key: "ret", label: "Ret", html: (t) => (t.ret == null ? "–" : Math.round(t.ret * 100) + "%") },
    ];
    const draw = () => {
      const q = $("#r-q").value.trim().toLowerCase(), c = $("#r-c").value;
      store("sbn-conf", c);
      table($("#r-t"), cols, D.teams.filter((t) => (!c || t.conf === c) && (!q || (t.name + " " + t.abbr).toLowerCase().includes(q))), "net", { page: 400 });
    };
    $("#r-q").addEventListener("input", draw);
    $("#r-c").addEventListener("change", draw);
    draw();
  }

  function posLabel(p) {
    if (!p.pos) return "";
    return p.pos_inferred
      ? '<abbr title="Position inferred from height; not officially listed">' + esc(p.pos) + "*</abbr>"
      : esc(p.pos);
  }
  function htInches(ht) {
    const m = /^(\d+)'(\d+)/.exec(ht || "");
    return m ? +m[1] * 12 + +m[2] : null;
  }
  const POS_NOTE = '<p class="note">* Position inferred from height because none is officially listed.</p>';

  function playerCols(showTeam) {
    const c = [
      { key: "name", label: "Player", left: true, cls: "name", html: (p) => esc(p.name) + '<span class="sub">' + posLabel(p) + "</span>", asc: true },
      { key: "ht", label: "Ht", html: (p) => esc(p.ht || "–"), val: (p) => htInches(p.ht) },
    ];
    if (showTeam) c.push({ key: "team", label: "Team", left: true, cls: "name", html: (p) => teamLink(p.team), val: (p) => (teamById[p.team] || {}).short, asc: true });
    return c.concat([
      { key: "total", label: "Impact", html: (p) => '<b class="' + cls(p.total) + '">' + sgn(p.total, 2) + "</b>" },
      { key: "off", label: "Off", html: (p) => '<span class="' + cls(p.off) + '">' + sgn(p.off, 2) + "</span>" },
      { key: "def", label: "Def", html: (p) => '<span class="' + cls(p.def) + '">' + sgn(p.def, 2) + "</span>" },
      { key: "prior", label: "Prior", html: (p) => sgn(p.prior, 2) },
      { key: "poss", label: "Poss" },
      { key: "mpg", label: "MPG", html: (p) => f1(p.mpg) },
      { key: "ppg", label: "PPG", html: (p) => f1(p.ppg) },
      { key: "ts", label: "TS%", html: (p) => (p.ts == null ? "–" : (p.ts * 100).toFixed(1)) },
    ]);
  }

  function players(main) {
    const minDefault = recall("sbn-minposs") || 150;
    main.innerHTML = '<div><h1>Player Impact</h1><p class="lede">Estimated points per 100 possessions a player adds over an average player, at both ends, from who was on the floor when points were scored. Prior is where each player started this season: last season\'s rating carried forward for returning players, the box-score estimate for everyone else.</p></div>' +
      '<div class="controls"><div class="field"><label for="p-q">Search</label><input type="search" id="p-q" placeholder="Player or team"></div>' +
      '<div class="field"><label for="p-c">Conference</label><select id="p-c">' + confOptions() + "</select></div>" +
      '<div class="field"><label for="p-m">Min. possessions</label><input type="number" id="p-m" min="0" step="50" value="' + minDefault + '" style="width:110px"></div></div><div id="p-t"></div><div id="p-note"></div>';
    const draw = () => {
      const q = $("#p-q").value.trim().toLowerCase(), c = $("#p-c").value, m = +$("#p-m").value || 0;
      store("sbn-minposs", m);
      const rows = D.players.filter((p) => {
        const t = teamById[p.team] || {};
        return p.poss >= m && (!c || t.conf === c) && (!q || (p.name + " " + (t.name || "")).toLowerCase().includes(q));
      });
      table($("#p-t"), playerCols(true), rows, "total");
      $("#p-note").innerHTML = rows.some((p) => p.pos_inferred) ? POS_NOTE : "";
    };
    ["#p-q", "#p-c", "#p-m"].forEach((s) => $(s).addEventListener("input", draw));
    draw();
  }

  function lineupTable(el, rows) {
    table(el, [
      { key: "players", label: "Lineup", left: true, cls: "name", html: (l) => l.players.map(esc).join(", "), val: (l) => l.players.join(), asc: true },
      { key: "poss", label: "Poss", html: (l) => Math.round(l.poss) },
      { key: "net", label: "Net", html: (l) => '<b class="' + cls(l.net) + '">' + sgn(l.net) + "</b>" },
      { key: "off", label: "Off", html: (l) => f1(l.off) },
      { key: "def", label: "Def", asc: true, html: (l) => f1(l.def) },
    ], rows, "poss");
  }

  function lineups(main) {
    const sel = recall("sbn-lineup-team") || D.teams[0].id;
    main.innerHTML = '<div><h1>Lineups</h1><p class="lede">Raw results for each five-player group, per 100 possessions. Small samples swing wildly; trust groups with a few hundred possessions.</p></div>' +
      '<div class="controls"><div class="field"><label for="l-t">Team</label><select id="l-t">' + teamOptions(sel) + "</select></div></div><div id='l-tab'></div>";
    const draw = () => {
      const id = $("#l-t").value;
      store("sbn-lineup-team", id);
      lineupTable($("#l-tab"), D.lineups.filter((l) => l.team === id));
    };
    $("#l-t").addEventListener("change", draw);
    draw();
  }

  function gameCard(g) {
    const when = g.start ? new Date(g.start) : null;
    const whenTxt = when && !isNaN(when) ? when.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    return '<article class="card game" data-href="' + gameHref(g) + '"><div class="when">' + esc(whenTxt) + (g.neutral ? " · neutral site" : "") + "</div>" +
      '<div class="row"><span class="t">' + teamLink(g.away) + '</span><span class="s">' + f1(g.away_score) + "</span></div>" +
      '<div class="row"><span class="t">' + (g.neutral ? "" : "@ ") + teamLink(g.home) + '</span><span class="s">' + f1(g.home_score) + "</span></div>" +
      '<div class="prob" role="img" aria-label="Win probability: ' + esc((teamById[g.home] || {}).short) + " " + pct(g.home_win) + '"><span class="a" style="width:' + (100 - g.home_win * 100) + '%"></span><span class="h" style="width:' + g.home_win * 100 + '%"></span></div>' +
      '<div class="probtxt"><span>' + pct(1 - g.home_win) + "</span><span>" + Math.round(g.poss) + " poss</span><span>" + pct(g.home_win) + "</span></div>" +
      '<a class="more-link" href="' + gameHref(g) + '">Matchup details →</a></article>';
  }

  let SCHEDULE = null;  // full remaining schedule, loaded on first search
  function loadSchedule() {
    if (!SCHEDULE) {
      SCHEDULE = fetch("data/schedule.json").then((r) => (r.ok ? r.json() : null)).then((d) =>
        d ? d.games.map((row) => Object.fromEntries(d.fields.map((f, i) => [f, row[i]]))) : null).catch(() => null);
    }
    return SCHEDULE;
  }

  function games(main) {
    main.innerHTML = '<div><h1>Upcoming Games</h1><p class="lede" id="g-lede">Projected scores and win chances for the next three days, from the current team ratings. Search for a team to see its whole remaining schedule.</p></div>' +
      '<div class="controls"><div class="field"><label for="g-q">Team</label><input type="search" id="g-q" placeholder="Search by team" autocomplete="off"></div></div>' +
      '<div id="g-l"></div>';
    const label = (id, fallback) => { const t = teamById[id]; return t ? [t.short, t.name, t.abbr].join(" ") : fallback || ""; };
    let seq = 0;
    const draw = async () => {
      const q = $("#g-q").value.trim().toLowerCase(), mine = ++seq;
      if (!q) {
        $("#g-lede").textContent = "Projected scores and win chances for the next three days, from the current team ratings. Search for a team to see its whole remaining schedule.";
        $("#g-l").innerHTML = D.games.length ? '<div class="grid">' + D.games.map(gameCard).join("") + "</div>" : '<p class="lede">No " + LG.level + " games are scheduled in the next three days.</p>';
        return;
      }
      const all = (await loadSchedule()) || D.games;
      if (mine !== seq) return;  // a newer keystroke already redrew
      // Exact school name first ("duke" means Duke, not the Duquesne Dukes), then names that
      // start with the search, then any partial match (mascots, full names)
      const low = (x) => String(x || "").toLowerCase();
      const tiers = [
        D.teams.filter((t) => [t.short, t.abbr].some((v) => low(v) === q)),
        D.teams.filter((t) => [t.short, t.name].some((v) => low(v).startsWith(q))),
        D.teams.filter((t) => low(label(t.id)).includes(q)),
      ];
      const hit = tiers.find((tier) => tier.length) || [];
      const ids = new Set(hit.map((t) => t.id));
      const rows = all.filter((g) => ids.has(g.home) || ids.has(g.away) ||
        (!hit.length && (low(g.home_name) + " " + low(g.away_name)).includes(q)));
      const matched = hit.map((t) => t.short);
      $("#g-lede").textContent = "Every remaining scheduled game" + (matched.length && matched.length <= 3 ? " for " + matched.join(", ") : "") +
        ". Games further out use today's ratings, so their projections will change as the season goes on. " + (LG.nba ? "Playoff games appear once they're scheduled." : "Conference and NCAA tournament games appear once they're scheduled.") + "";
      $("#g-l").innerHTML = rows.length
        ? '<p class="note">' + rows.length + " game" + (rows.length === 1 ? "" : "s") + "</p>" + '<div class="grid">' + rows.map(gameCard).join("") + "</div>"
        : '<p class="lede">No scheduled games match “' + esc(q) + "”.</p>";
    };
    $("#g-q").addEventListener("input", draw);
    draw();
  }

  function predict(h, a, neutral) {
    const m = D.meta.model, idx = {};
    m.ids.forEach((id, i) => (idx[id] = i));
    const hi = idx[h], ai = idx[a];
    if (hi == null || ai == null) return null;
    const hf = neutral ? 0 : 1, mu = D.meta.mu, H = D.meta.hca;
    const poss = D.meta.tau + m.T[hi] + m.T[ai];
    const hs = poss * (mu + m.O[hi] + m.D[ai] + hf * H / 2) / 100;
    const as = poss * (mu + m.O[ai] + m.D[hi] - hf * H / 2) / 100;
    return { home_score: hs, away_score: as, poss, home_win: normCdf((hs - as) / D.meta.sd) };
  }
  function normCdf(z) { // Abramowitz-Stegun
    const t = 1 / (1 + 0.2316419 * Math.abs(z));
    const d = 0.3989423 * Math.exp(-z * z / 2);
    const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
    return z > 0 ? 1 - p : p;
  }

  function matchup(main) {
    const a0 = recall("sbn-m-away") || D.teams[1].id, h0 = recall("sbn-m-home") || D.teams[0].id;
    main.innerHTML = '<div><h1>Matchup</h1><p class="lede">Pick any two teams to project a score and win chance.</p></div>' +
      '<div class="controls"><div class="field"><label for="m-a">Away</label><select id="m-a">' + teamOptions(a0) + "</select></div>" +
      '<div class="field"><label for="m-h">Home</label><select id="m-h">' + teamOptions(h0) + "</select></div>" +
      '<div class="field"><label for="m-v">Site</label><select id="m-v"><option value="0">Home court</option><option value="1">Neutral</option></select></div></div><div id="m-out"></div>';
    const draw = () => {
      const a = $("#m-a").value, h = $("#m-h").value, n = $("#m-v").value === "1";
      store("sbn-m-away", a); store("sbn-m-home", h);
      if (a === h) { $("#m-out").innerHTML = '<p class="lede">Choose two different teams.</p>'; return; }
      const p = predict(h, a, n);
      $("#m-out").innerHTML = p ? '<div class="grid">' + gameCard(Object.assign({ home: h, away: a, neutral: n }, p)) + "</div>" +
        '<p class="lede">Projected margin ' + sgn(p.home_score - p.away_score) + " for " + esc(teamById[h].short) + ". Typical miss: about " + Math.round(D.meta.sd) + ' points. <a href="' + gameHref({ away: a, home: h, neutral: n }) + '">Full matchup report →</a></p>' : "";
    };
    ["#m-a", "#m-h", "#m-v"].forEach((s) => $(s).addEventListener("change", draw));
    draw();
  }

  /* Prior vs. current belief about a team's net rating, as two normal curves */
  function beliefChart(t) {
    const psd = D.meta.prior_sd, se = t.net_se;
    if (t.pre == null || !psd || !se) return "";
    const W = 640, H = 190, padL = 12, padR = 12, padB = 30, top = 18;
    const lo = Math.min(t.pre - 3 * psd, t.net - 3 * se), hi = Math.max(t.pre + 3 * psd, t.net + 3 * se);
    const x = (v) => padL + (v - lo) / (hi - lo) * (W - padL - padR);
    const dens = (v, m, s) => Math.exp(-0.5 * ((v - m) / s) ** 2) / s;
    const peak = 1 / Math.min(psd, se);
    const y = (d) => H - padB - d / peak * (H - padB - top);
    const curve = (m, s) => {
      let d = "M" + x(lo).toFixed(1) + " " + y(0).toFixed(1);
      for (let i = 0; i <= 120; i++) { const v = lo + (hi - lo) * i / 120; d += " L" + x(v).toFixed(1) + " " + y(dens(v, m, s)).toFixed(1); }
      return d + " L" + x(hi).toFixed(1) + " " + y(0).toFixed(1) + " Z";
    };
    const step = (hi - lo) > 40 ? 10 : 5, ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
    const share = Math.min(1, (se * se) / (psd * psd));
    const gp = t.w + t.l;
    return '<section class="belief"><h2>From opinion to evidence</h2>' +
      '<p class="lede">Before the season, the model\'s belief about ' + esc(t.short || t.name) + " was a net rating of <b>" + sgn(t.pre) + " ± " + psd.toFixed(1) +
      "</b>, built from last season and this year\'s roster. After " + gp + " game" + (gp === 1 ? "" : "s") + " it is <b>" + sgn(t.net) + " ± " + se.toFixed(1) +
      "</b>. The preseason opinion now carries about <b>" + Math.round(share * 100) + "%</b> of the weight; the games carry the rest.</p>" +
      (t.coach ? '<p class="note">New head coach: ' + esc(t.coach.coach) + " replaced " + esc(t.coach.prev) + ". Teams with a new coach have tended to land below what last season predicts, and last season carries less" +
        (t.coach.seasons ? "; " + esc(t.coach.coach) + (t.coach.record >= 0 ? " beat" : " fell short of") + " expectations at his previous stops by " + Math.abs(t.coach.record).toFixed(1) + " points a game (shrunk, " + t.coach.seasons + " season" + (t.coach.seasons === 1 ? "" : "s") + ")" : "") +
        ". Together these moved the preseason rating " + sgn(t.coach.delta) + ".</p>" : "") +
      '<div class="chart-box"><svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Preseason belief ' + sgn(t.pre) + ", current belief " + sgn(t.net) + '">' +
      ticks.map((v) => '<line class="grid" x1="' + x(v) + '" x2="' + x(v) + '" y1="' + top + '" y2="' + (H - padB) + '"/>' +
        '<text class="tick" x="' + x(v) + '" y="' + (H - padB + 16) + '">' + (v > 0 ? "+" : "") + v + "</text>").join("") +
      '<line class="axis" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + (H - padB) + '" y2="' + (H - padB) + '"/>' +
      '<path class="prior" d="' + curve(t.pre, psd) + '"/><path class="post" d="' + curve(t.net, se) + '"/>' +
      '<line class="mark-prior" x1="' + x(t.pre) + '" x2="' + x(t.pre) + '" y1="' + y(dens(t.pre, t.pre, psd)) + '" y2="' + (H - padB) + '"/>' +
      '<line class="mark-post" x1="' + x(t.net) + '" x2="' + x(t.net) + '" y1="' + y(dens(t.net, t.net, se)) + '" y2="' + (H - padB) + '"/>' +
      "</svg></div>" +
      '<p class="legend"><span class="key prior"></span>Preseason belief <span class="key post"></span>Current belief, after this season\'s games <span class="axis-note">Net points per 100 possessions vs. an average team</span></p></section>';
  }

  function team(main, id) {
    const t = teamById[id];
    if (!t) { main.innerHTML = '<p class="lede">That team isn’t in the current ratings. <a href="#rankings">Back to rankings</a></p>'; return; }
    const roster = D.players.filter((p) => p.team === id);
    const up = D.games.filter((g) => g.home === id || g.away === id);
    main.innerHTML = '<div><h1><span class="dot" style="background:#' + esc(t.color) + ';width:16px;height:16px"></span>' + esc(t.name) + '</h1><p class="lede">' + esc(t.conf) + " · " + t.w + "-" + t.l + "</p></div>" +
      '<dl class="kv"><div><dt>Rank</dt><dd>' + t.rank + "</dd></div><div><dt>Net</dt><dd class='" + cls(t.net) + "'>" + sgn(t.net) + "</dd></div>" +
      "<div><dt>Offense</dt><dd>" + f1(t.o) + '<span class="rk">' + t.o_rank + "</span></dd></div><div><dt>Defense</dt><dd>" + f1(t.d) + '<span class="rk">' + t.d_rank + "</span></dd></div>" +
      "<div><dt>Tempo</dt><dd>" + f1(t.tempo) + "</dd></div></dl>" +
      beliefChart(t) +
      (up.length ? "<h2>Next up</h2><div class='grid'>" + up.map(gameCard).join("") + "</div>" : "") +
      "<h2>Players</h2><div><div id='t-p'></div><div id='t-pn'></div></div><h2>Lineups</h2><div id='t-l'></div>";
    table($("#t-p"), playerCols(false), roster, "poss");
    $("#t-pn").innerHTML = roster.some((p) => p.pos_inferred) ? POS_NOTE : "";
    lineupTable($("#t-l"), D.lineups.filter((l) => l.team === id));
  }

  function bracket(main) {
    const B = D.bracket;
    if (!B) { main.innerHTML = '<div><h1>Tournament Odds</h1><p class="lede">Tournament odds will appear after the next daily update.</p></div>'; return; }
    const R = B.rounds, names = B.region_names || ["Region 1", "Region 2", "Region 3", "Region 4"];
    const regionSel = recall("sbn-region") || "";
    main.innerHTML = '<div><h1>Tournament Odds</h1><p class="lede">Chances of reaching each round, from ' + B.sims.toLocaleString() +
      " simulations of the projected " + B.field_size + "-team field. The field and seeds come from the " +
      '<a href="' + esc(B.url) + '" target="_blank" rel="noopener">Bracket Matrix</a>, a consensus of ' + B.n_brackets +
      " published brackets (" + esc(B.label) + (B.latest_bracket ? ", newest bracket " + esc(B.latest_bracket) : "") +
      "). Games are played by this site's ratings, so a strong team on a low seed line can carry good odds.</p></div>" +
      '<p class="note">' + B.days_to_selection + " days to Selection Sunday. Each simulation lets every team's true strength differ from today's rating by an amount that shrinks as the season goes on. Teams on the top four seed lines are placed at the nearest open region and first-weekend site in S-curve order, never on their own home floor; teams marked OR start in the opening round." +
      (B.distance_coef ? " Every game includes the distance edge measured in past tournaments: about 2 points for a team 50 miles from the arena against one 1,000 miles away." : "") + "</p>" +
      '<div class="controls"><div class="field"><label for="b-r">Region</label><select id="b-r"><option value="">All regions</option>' +
      names.map((n, i) => '<option value="' + (i + 1) + '"' + (String(i + 1) === regionSel ? " selected" : "") + ">" + esc(n) + "</option>").join("") +
      "</select></div></div><div id='b-t'></div>" +
      '<p class="note">Last 4 tournaments: wins and losses, and average points per game above or below what the ratings expected. Shown for context only; across 2012–2026, past over- or under-performance didn\'t reliably carry into the next tournament, so it doesn\'t move the odds.</p>';
    const odds = (i) => (t) => t.odds[i];
    const pctCell = (i) => (t) => { const v = t.odds[i]; return v >= 0.995 ? "✓" : v < 0.001 ? "<0.1" : (v * 100).toFixed(v < 0.1 ? 1 : 0); };
    const shortRegion = (n) => String(n).split(" ")[0];
    const cols = [
      { key: "seed", label: "Seed", asc: true, html: (t) => t.seed + (t.opening ? '<span class="rk">OR</span>' : "") },
      { key: "team", label: "Team", left: true, cls: "name", html: (t) => (teamById[t.id] ? teamLink(t.id) : esc(t.team)), asc: true },
      { key: "region", label: "Region", left: true, asc: true, html: (t) => esc(shortRegion(names[t.region - 1])) },
      { key: "site", label: "First weekend", left: true, asc: true, html: (t) => (t.site ? esc(t.site) + (t.miles != null ? '<span class="rk">' + t.miles.toLocaleString() + " mi</span>" : "") : "–"), val: (t) => t.miles },
      { key: "rec", label: "Last 4", html: (t) => (t.record ? t.record.wins + "-" + (t.record.games - t.record.wins) + '<span class="rk ' + cls(t.record.vs_exp) + '">' + sgn(t.record.vs_exp) + "</span>" : "–"), val: (t) => (t.record ? t.record.vs_exp : null) },
    ];
    [1, 2, 3, 4, 5, 6, 7].forEach((i) => cols.push({ key: "r" + i, label: R[i], val: odds(i), html: pctCell(i) }));
    const draw = () => {
      const r = $("#b-r").value;
      store("sbn-region", r);
      table($("#b-t"), cols, B.teams.filter((t) => !r || String(t.region) === r), "r7", { page: 100 });
    };
    $("#b-r").addEventListener("change", draw);
    draw();
  }

  const money = (x) => (x == null ? "–" : (Math.abs(x) >= 1e6 ? (x < 0 ? "−$" : "$") + (Math.abs(x) / 1e6).toFixed(1) + "M" : (x < 0 ? "−$" : "$") + Math.round(Math.abs(x) / 1e3) + "K"));

  function value(main) {
    const V = D.value;
    if (!V) { main.innerHTML = '<div><h1>Player Value</h1><p class="lede">Salary data will appear after the next weekly update.</p></div>'; return; }
    main.innerHTML = '<div><h1>Player Value</h1><p class="lede">What each player adds in wins, and what teams pay for it. Wins added counts points above a replacement-level player (' + V.replacement +
      " per 100 possessions vs. average) on both ends, from the impact ratings, at about " + V.points_per_win + " points per win. A win costs about <b>" + money(V.per_win) +
      "</b> on today's market: teams' spending above the league minimum divided by the wins it buys. Surplus is a player's wins added at that price minus his salary above the minimum.</p></div>" +
      '<p class="note">Wins added are on an 82-game pace from games so far; early in the season they swing a lot. Salaries are current-season figures from ESPN.</p>' +
      '<div class="controls"><div class="field"><label for="v-q">Search</label><input type="search" id="v-q" placeholder="Player or team"></div></div><div id="v-p"></div>' +
      "<h2>Teams</h2><p class='note'>Payroll against wins added: who gets the most for their money.</p><div id='v-t'></div>";
    const pcols = [
      { key: "name", label: "Player", left: true, cls: "name", html: (r) => esc(r.name), asc: true },
      { key: "team", label: "Team", left: true, cls: "name", html: (r) => teamLink(r.team), val: (r) => (teamById[r.team] || {}).short, asc: true },
      { key: "salary", label: "Salary", html: (r) => money(r.salary) },
      { key: "pace", label: "Wins added (82-game pace)", html: (r) => '<span class="' + cls(r.pace) + '">' + f1(r.pace) + "</span>" },
      { key: "surplus", label: "Surplus value", html: (r) => '<b class="' + cls(r.surplus) + '">' + money(r.surplus) + "</b>" },
    ];
    const draw = () => {
      const q = $("#v-q").value.trim().toLowerCase();
      table($("#v-p"), pcols, V.players.filter((r) => !q || (r.name + " " + ((teamById[r.team] || {}).name || "")).toLowerCase().includes(q)), "surplus");
    };
    $("#v-q").addEventListener("input", draw);
    draw();
    table($("#v-t"), [
      { key: "team", label: "Team", left: true, cls: "name", html: (r) => teamLink(r.id), val: (r) => (teamById[r.id] || {}).short, asc: true },
      { key: "payroll", label: "Payroll", html: (r) => money(r.payroll) },
      { key: "war_pace", label: "Wins added (pace)", html: (r) => f1(r.war_pace) },
      { key: "net", label: "Net rating", html: (r) => sgn((teamById[r.id] || {}).net), val: (r) => (teamById[r.id] || {}).net },
      { key: "per_win", label: "Cost per win", asc: true, html: (r) => money(r.per_win) },
    ], V.teams, "per_win");
  }

  function method(main) {
    const m = D.meta;
    main.innerHTML = '<div class="prose"><h1>How It Works</h1>' +
      "<p>Every rating here comes from a regression fit to every game this season, refit each morning. The current fit uses " + m.games.toLocaleString() + " games and " + m.stints.toLocaleString() + " lineup stints.</p>" +
      "<h2>Team ratings</h2><p>Each game gives two observations, one per offense. For offense <i>o</i> facing defense <i>d</i>:</p>" +
      '<span class="eq">100 × points / possessions = μ + O[o] + D[d] + h·H/2 + ε</span>' +
      "<p>μ is the league average (" + m.mu + " this season). h is +1 for the home offense, −1 for the road offense and 0 at a neutral site, so H is the full home-court swing, currently estimated at " + m.hca + " points per 100 possessions. Possessions come from the box score: FGA − OREB + TO + 0.475 × FTA, averaged over both teams.</p>" +
      "<p>The fit is Bayesian ridge regression. Games are weighted by possessions and by recency, with a 60-day half-life, and home court starts from the long-run " + (LG.nba ? "NBA" : "college") + " average until the data can pin it down. Tempo is fit the same way on possessions per game.</p>" +
      "<h2>Preseason ratings</h2><p>Each team's O and D start from a preseason estimate built from two ingredients:</p>" +
      "<p><b>Program.</b> Last season's full-season rating. Weighting last season toward its final weeks, or using only its last 15 games, predicted this season's early games worse: the full season is a bigger sample, and late-season form is mostly noise.</p>" +
      "<p><b>Roster.</b> Every player on this season's roster carries his own impact rating from last season, wherever he played it, so " + (LG.nba ? "trades and free-agent signings" : "transfers") + " bring their value with them. A returning rating is projected forward with a rule learned from consecutive seasons (players who stay and players who transfer are fit separately). " + (LG.nba ? "Rookies and players new to the league" : "Freshmen and players new to Division I") + " get the average newcomer rating. The team's projection weights each player by expected minutes.</p>" +
      '<span class="eq">preseason = ' + ((m.preseason || {}).w_program || 0.69) + " × program + " + ((m.preseason || {}).w_roster || 0.5) + " × roster</span>" +
      (LG.nba ? "" : "<p><b>Coaching change.</b> When a school has a new head coach, the estimate moves down about 2 points per 100 possessions, last season counts about 10% less, and the new coach's record of beating or missing expectations at his previous school (last 5 seasons, shrunk toward zero) carries over at 1.5×. A coach's record at his current school adds nothing, because last season's rating already contains it. Tested on 4,139 team-seasons from 2015 to 2026, one season held out at a time: the adjustment helped in all 12 seasons.</p>") +
      "<p>The weights come from regressing 2025-26 full-season ratings on both ingredients and from replaying this season's games. The preseason estimate counts as about " + ((m.preseason || {}).games || 2.7) + " games of evidence, so by January it carries little weight beside 15 or more real games. It doesn't fade beyond that: forcing it to zero by mid-season made January–March predictions slightly worse. The Teams table shows each team's preseason rating (Pre) and the share of its projected minutes going to players who were on last season's team (Ret).</p>" +
      "<h2>Predictions</h2><p>Projected possessions are the two teams' tempo effects added to the average. Each side's points are possessions × its expected efficiency. The win chance treats the actual margin as normal around the projection with a standard deviation of " + m.sd + " points, measured from how far past games landed from their fitted margins.</p>" +
      (LG.nba ? "<p><b>Back-to-backs.</b> A team playing the second night of a back-to-back loses about " + f1(m.b2b || 1.8) + " points of margin. This held up in both halves of the 2025-26 season when fit on one half and tested on the other.</p>" : "") +
      factorTable() +
      "<h2>Player impact</h2><p>Play-by-play is cut into stints, stretches with the same ten players on the floor. Each stint again gives two rows:</p>" +
      '<span class="eq">100 × points / possessions − μ = Σ Off[5 on offense] + Σ Def[5 on defense] + h·H/2 + ε</span>' +
      "<p>Teammates who always play together are hard to separate, so each player gets a normal prior centered on a box-score estimate. That box-score model is itself learned from the data: a first, heavily shrunk pass of the regression is regressed on per-40-minute box stats (points, shot attempts, free throws, threes, assists, turnovers and offensive rebounds for offense; steals, blocks, defensive rebounds and fouls for defense). The final rating is the posterior mean</p>" +
      '<span class="eq">β = prior + (XᵀWX + λI)⁻¹ XᵀW (y − X·prior)</span>' +
      "<p>with W the stint possessions. λ" + (m.lambda ? " (currently " + Math.round(m.lambda).toLocaleString() + " possessions)" : "") + " sets how much on-court evidence it takes to move a player off the box-score estimate. It is chosen by cross-validation: hold out every fifth game, fit on the rest, and keep the λ that best predicts scoring in the held-out stints. Defense is reported with the sign flipped so higher is better on both ends.</p>" +
      "<p>Returning players get a better starting point than the box score: their prior is " + Math.round((m.player_carry_weight || 0.8) * 100) + "% their own rating from last season, projected forward with the same carry-over rule as the preseason team ratings, and the rest the box-score estimate. Testing on held-out games this season, that beat the box score alone at every level of shrinkage.</p>" +
      (LG.nba ? "" : "<h2>Tournament odds</h2><p>The Bracket tab simulates the projected field (the Bracket Matrix consensus until Selection Sunday) 20,000 times. Each simulation draws every team's true strength around its rating, with a spread measured from how much ratings moved between December and March in 2025-26, then plays each game by the prediction formula above at its announced site. Tests on every tournament from 2012 to 2026 decided what else counts. Distance from campus to arena does: margins shift about 0.75 points per unit of log(1 + miles). A team's road and neutral-court form during the season doesn't, beyond its overall rating. A program's record against expectations in recent tournaments showed a small effect that didn't hold up when each tournament was predicted from the others, so it's shown only as context.</p>") +
      "<h2>Lineups</h2><p>Lineup numbers are raw on-court results per 100 possessions, not adjusted for opponents. Use them to see how a coach deploys a roster, and lean on the player ratings for talent.</p>" +
      (LG.nba ? "<h2>Player value</h2><p>Wins added start from each player's impact rating: points per 100 possessions above an average player, at both ends. A replacement-level player (someone a team can sign for the minimum) is about 2 points per 100 below average, so points above replacement = (impact + 2) × possessions ÷ 100. In the NBA about 30 points of season-long margin make one win. The price of a win is set by the market: what all teams spend above the league minimum divided by all the wins it buys. A player's surplus value is his wins added at that price, minus what he's paid above the minimum. Salaries come from ESPN and update weekly.</p>" : "") +
      "<h2>Data</h2><p>Box scores and play-by-play come from ESPN's public scoreboard feed, pulled after each day's games. Stints with lineup gaps (a missed substitution in the feed) are dropped rather than guessed.</p></div>";
  }

  /* ===================== Matchup page: prediction, comparison, scouting, lineups ===================== */
  let STATS = null;
  function loadStats() {
    if (!STATS) STATS = fetch("data/teamstats.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    return STATS;
  }
  const pctf = (x, d = 1) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
  const ordinal = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");

  function gameHref(g) {
    return g.id ? "#game-" + g.id : "#vs-" + g.away + "-" + g.home + (g.neutral ? "-n" : "");
  }

  /* Distribution of the final margin (home minus away) as a normal curve; shaded areas are each side's win chance */
  function marginChart(spread, sd, homeName, awayName) {
    const W = 640, H = 170, padB = 30, top = 14, padX = 12;
    const lo = Math.min(spread - 3 * sd, -6), hi = Math.max(spread + 3 * sd, 6);
    const x = (v) => padX + (v - lo) / (hi - lo) * (W - 2 * padX);
    const dens = (v) => Math.exp(-0.5 * ((v - spread) / sd) ** 2);
    const y = (d) => H - padB - d * (H - padB - top);
    const area = (a, b) => {
      let p = "M" + x(a).toFixed(1) + " " + y(0);
      for (let i = 0; i <= 80; i++) { const v = a + (b - a) * i / 80; p += " L" + x(v).toFixed(1) + " " + y(dens(v)).toFixed(1); }
      return p + " L" + x(b).toFixed(1) + " " + y(0) + " Z";
    };
    const step = hi - lo > 60 ? 10 : 5, ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
    return '<div class="chart-box"><svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Range of likely final margins">' +
      ticks.map((v) => '<line class="grid" x1="' + x(v) + '" x2="' + x(v) + '" y1="' + top + '" y2="' + (H - padB) + '"/><text class="tick" x="' + x(v) + '" y="' + (H - padB + 16) + '">' +
        (v === 0 ? "0" : (v > 0 ? esc(homeName) + " +" + v : esc(awayName) + " +" + -v)) + "</text>").join("") +
      '<path class="prior" d="' + area(lo, Math.min(0, hi)) + '"/><path class="post" d="' + area(Math.max(0, lo), hi) + '"/>' +
      '<line class="axis" x1="' + padX + '" x2="' + (W - padX) + '" y1="' + (H - padB) + '" y2="' + (H - padB) + '"/>' +
      '<line class="mark-post" x1="' + x(spread) + '" x2="' + x(spread) + '" y1="' + top + '" y2="' + (H - padB) + '"/>' +
      '<line class="mark-prior" x1="' + x(0) + '" x2="' + x(0) + '" y1="' + top + '" y2="' + (H - padB) + '"/></svg></div>';
  }

  function compareRow(label, a, b, fmt, rkA, rkB, n) {
    const tag = (rk) => (rk ? '<span class="rk">' + ordinal(rk) + "</span>" : "");
    const better = rkA && rkB ? (rkA < rkB ? 0 : rkB < rkA ? 1 : -1) : -1;
    return "<tr><td class='l'>" + label + "</td><td" + (better === 0 ? " class='lead'" : "") + ">" + fmt(a) + tag(rkA) + "</td><td" + (better === 1 ? " class='lead'" : "") + ">" + fmt(b) + tag(rkB) + "</td></tr>";
  }

  /* When `off` has the ball against `def`: offense stat vs what the defense allows */
  function possessionTable(offT, defT, so, sd, L) {
    const rows = [["efg", "d_efg", "Effective FG%"], ["tov", "d_tov", "Turnover rate"], ["orb", "d_orb", "Off. rebound rate"],
      ["ftr", "d_ftr", "Free-throw rate"], ["three_rate", "d_three_rate", "Share of shots from three"], ["three_pct", "d_three_pct", "3-point %"],
      ["two_pct", "d_two_pct", "2-point %"], ["rim_rate", "d_rim_rate", "Share of shots at the rim"], ["rim_pct", "d_rim_pct", "FG% at the rim"]];
    const tag = (rk) => (rk ? '<span class="rk">' + ordinal(rk) + "</span>" : "");
    return '<div class="table-box"><table><thead><tr><th class="l">' + esc(offT.short) + " with the ball</th><th>" + esc(offT.short) + " offense</th><th>" +
      esc(defT.short) + " defense allows</th><th>" + LG.short + " average</th></tr></thead><tbody>" +
      rows.map(([o, d, label]) => "<tr><td class='l'>" + label + "</td><td>" + pctf(so[o]) + tag(so[o + "_rk"]) + "</td><td>" + pctf(sd[d]) + tag(sd[d + "_rk"]) + "</td><td>" + pctf((L[o] || {}).mean) + "</td></tr>").join("") +
      "</tbody></table></div>";
  }

  /* Plain-language edges for one side of the ball. o = how good the offense is at something,
     d = how much the defense gives it up (z-scores vs. the league, oriented so positive helps the
     offense). The sentence names whichever side actually drives the edge. */
  function edges(offT, defT, so, sd, L) {
    const z = (k, v) => (v == null || !L[k] || !L[k].sd ? 0 : (v - L[k].mean) / L[k].sd);
    const O = esc(offT.short), Df = esc(defT.short);
    const V = (one, many) => (LG.nba ? many : one);
    const items = [
      { o: z("efg", so.efg), d: z("d_efg", sd.d_efg),
        good: () => O + " " + V("shoots", "shoot") + " well (" + pctf(so.efg) + " effective FG%, " + ordinal(so.efg_rk) + ") and " + Df + " " + V("gives up", "give up") + " good looks (" + pctf(sd.d_efg) + ", " + ordinal(sd.d_efg_rk) + " in defense).",
        defStrong: () => poss(Df) + " defense holds teams to " + pctf(sd.d_efg) + " effective FG% (" + ordinal(sd.d_efg_rk) + ").",
        offWeak: () => O + " " + V("has struggled", "have struggled") + " to score efficiently: " + pctf(so.efg) + " effective FG% (" + ordinal(so.efg_rk) + ")." },
      { o: z("three_pct", so.three_pct) + 0.3 * z("three_rate", so.three_rate), d: z("d_three_pct", sd.d_three_pct),
        good: () => "Three-point line: " + O + " " + V("makes", "make") + " " + pctf(so.three_pct) + " (" + ordinal(so.three_pct_rk) + ") on " + pctf(so.three_rate, 0) + " of " + V("its", "their") + " shots; " + Df + " " + V("allows", "allow") + " " + pctf(sd.d_three_pct) + " (" + ordinal(sd.d_three_pct_rk) + ").",
        defStrong: () => Df + " " + V("defends", "defend") + " the arc: opponents make " + pctf(sd.d_three_pct) + " of threes (" + ordinal(sd.d_three_pct_rk) + ").",
        offWeak: () => O + " " + V("has been", "have been") + " cold from three: " + pctf(so.three_pct) + " (" + ordinal(so.three_pct_rk) + ")." },
      { o: z("rim_pct", so.rim_pct) + 0.3 * z("rim_rate", so.rim_rate), d: z("d_rim_pct", sd.d_rim_pct),
        good: () => "At the rim: " + O + " " + V("gets", "get") + " " + pctf(so.rim_rate, 0) + " of " + V("its", "their") + " shots there and finishes " + pctf(so.rim_pct) + " (" + ordinal(so.rim_pct_rk) + "); " + Df + " " + V("allows", "allow") + " " + pctf(sd.d_rim_pct) + " (" + ordinal(sd.d_rim_pct_rk) + ").",
        defStrong: () => Df + " " + V("protects", "protect") + " the rim: opponents finish " + pctf(sd.d_rim_pct) + " there (" + ordinal(sd.d_rim_pct_rk) + "), with a block rate " + ordinal(sd.blk_rate_rk) + " in the country.",
        offWeak: () => O + " " + V("hasn't", "haven't") + " finished well inside: " + pctf(so.rim_pct) + " at the rim (" + ordinal(so.rim_pct_rk) + ")." },
      { o: -z("tov", so.tov), d: -z("d_tov", sd.d_tov),
        good: () => "Ball security: " + O + " " + V("turns", "turn") + " it over on just " + pctf(so.tov) + " of possessions (" + ordinal(so.tov_rk) + ") and " + Df + " " + V("rarely forces", "rarely force") + " them (" + pctf(sd.d_tov) + ", " + ordinal(sd.d_tov_rk) + ").",
        defStrong: () => "Turnovers: " + Df + " " + V("forces", "force") + " them on " + pctf(sd.d_tov) + " of possessions (" + ordinal(sd.d_tov_rk) + ").",
        offWeak: () => O + " " + V("has been", "have been") + " loose with the ball: turnovers on " + pctf(so.tov) + " of possessions (" + ordinal(so.tov_rk) + ")." },
      { o: z("orb", so.orb), d: z("d_orb", sd.d_orb),
        good: () => "Second chances: " + O + " " + V("grabs", "grab") + " " + pctf(so.orb, 0) + " of " + V("its", "their") + " misses (" + ordinal(so.orb_rk) + ") and " + Df + " " + V("allows", "allow") + " " + pctf(sd.d_orb, 0) + " (" + ordinal(sd.d_orb_rk) + ").",
        defStrong: () => Df + " " + V("cleans", "clean") + " the defensive glass: opponents rebound only " + pctf(sd.d_orb, 0) + " of their misses (" + ordinal(sd.d_orb_rk) + ").",
        offWeak: () => O + " " + V("rarely gets", "rarely get") + " second chances: " + pctf(so.orb, 0) + " of " + V("its", "their") + " misses (" + ordinal(so.orb_rk) + ")." },
      { o: z("ftr", so.ftr), d: z("d_ftr", sd.d_ftr),
        good: () => "Free throws: " + O + " " + V("gets", "get") + " to the line often (" + Math.round(so.ftr * 100) + " FTA per 100 shots, " + ordinal(so.ftr_rk) + ") and " + Df + " " + V("fouls", "foul") + " a lot (" + Math.round(sd.d_ftr * 100) + ", " + ordinal(sd.d_ftr_rk) + ").",
        defStrong: () => Df + " " + V("defends", "defend") + " without fouling: " + Math.round(sd.d_ftr * 100) + " opponent FTA per 100 shots (" + ordinal(sd.d_ftr_rk) + ").",
        offWeak: () => O + " " + V("rarely gets", "rarely get") + " to the line: " + Math.round(so.ftr * 100) + " FTA per 100 shots (" + ordinal(so.ftr_rk) + ")." },
    ];
    items.forEach((i) => (i.s = (i.o + i.d) / 2));
    const ok = items.filter((i) => isFinite(i.s)).sort((a, b) => b.s - a.s);
    return {
      pros: ok.filter((i) => i.s > 0.35 && i.o > 0 && i.d > -0.3).slice(0, 2).map((i) => ({ txt: i.good() })),
      cons: ok.slice().reverse().filter((i) => i.s < -0.35).slice(0, 2).map((i) => ({ txt: i.d <= i.o ? i.defStrong() : i.offWeak() })),
    };
  }

  /* Tendencies we can only infer from the numbers */
  function tendencies(t, s, L) {
    const z = (k) => (s[k] == null || !L[k] ? 0 : (s[k] - L[k].mean) / L[k].sd);
    const out = [];
    const N = D.teams.length, top = (rk, share) => rk && rk <= Math.max(3, Math.round(share * N));  // thresholds as shares of the league
    if (top(s.d_tov_rk, 0.16) && top(s.stl_rate_rk, 0.19)) out.push("Forces turnovers on " + pctf(s.d_tov) + " of possessions (" + ordinal(s.d_tov_rk) + ") with a high steal rate: likely heavy ball pressure, possibly full-court.");
    if (z("d_three_rate") > 0.7 && z("d_rim_rate") < -0.5) out.push("Opponents take lots of threes (" + pctf(s.d_three_rate, 0) + " of shots) but few at the rim: consistent with a zone or a packed-paint defense.");
    if (top(s.blk_rate_rk, 0.14)) out.push("Rim protection: blocks " + pctf(s.blk_rate, 0) + " of opponents' twos (" + ordinal(s.blk_rate_rk) + ").");
    if (top(t.t_rank, 0.16)) out.push("Plays fast: " + f1(t.tempo) + " possessions per " + LG.minutes + " minutes (" + ordinal(t.t_rank) + ").");
    if (t.t_rank >= Math.round(0.84 * N)) out.push("Plays slow: " + f1(t.tempo) + " possessions per " + LG.minutes + " minutes (" + ordinal(t.t_rank) + " of " + D.teams.length + ").");
    if (z("ast_rate") > 1) out.push("Moves the ball: " + pctf(s.ast_rate, 0) + " of its baskets are assisted.");
    if (z("ast_rate") < -1) out.push("Creates its own shots: only " + pctf(s.ast_rate, 0) + " of baskets are assisted.");
    if (z("three_rate") > 1) out.push("Lives at the three-point line: " + pctf(s.three_rate, 0) + " of shots.");
    if (z("orb") > 1) out.push("Crashes the offensive glass (" + ordinal(s.orb_rk) + ").");
    return out;
  }

  /* Suggested five against this opponent: best total impact, nudged toward what counters the
     opponent's main strengths, with at least one guard and one forward or center */
  function suggestLineup(teamId, opp, so) {
    const pool = D.players.filter((p) => p.team === teamId && p.poss >= 20).sort((a, b) => b.poss - a.poss).slice(0, 9);
    if (pool.length < 5) return null;
    const ref = D.players.filter((p) => p.poss >= 150 && p.r40);
    const stat = (k) => { const v = ref.map((p) => p.r40[k]); const m = v.reduce((a, b) => a + b, 0) / v.length; const sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / v.length) || 1; return (p) => ((p.r40 || {})[k] - m) / sd; };
    const L = (STATS_DATA || {}).league || {}, zo = (k) => (so[k] == null || !L[k] ? 0 : (so[k] - L[k].mean) / L[k].sd);
    const needs = [];
    if (zo("orb") > 0.9) needs.push({ size: zo("orb"), why: "defensive rebounding against " + esc(opp.short) + "'s offensive glass", f: stat("dreb") });
    if (zo("d_tov") > 0.9) needs.push({ size: zo("d_tov"), why: "ball handling against " + esc(opp.short) + "'s pressure", f: (p) => -stat("tov")(p) + 0.5 * stat("ast")(p) });
    if (Math.max(zo("rim_rate"), zo("rim_pct")) > 0.9) needs.push({ size: Math.max(zo("rim_rate"), zo("rim_pct")), why: "rim protection against " + esc(opp.short) + "'s inside scoring", f: stat("blk") });
    if (Math.max(-zo("d_rim_pct"), zo("blk_rate")) > 0.9) needs.push({ size: Math.max(-zo("d_rim_pct"), zo("blk_rate")), why: "outside shooting to pull " + esc(opp.short) + "'s shot blockers away from the rim", f: stat("tpm") });
    needs.sort((a, b) => b.size - a.size);
    needs.splice(2);  // only the opponent's two biggest strengths
    const bonus = (p) => needs.reduce((a, n) => a + 0.6 * n.f(p), 0);
    let best = null;
    const n = pool.length;
    for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) for (let c = b + 1; c < n; c++) for (let d = c + 1; d < n; d++) for (let e = d + 1; e < n; e++) {
      const five = [pool[a], pool[b], pool[c], pool[d], pool[e]];
      const pos = five.map((p) => p.pos || "");
      if (pos.some(Boolean) && (!pos.includes("G") || !pos.some((x) => x === "F" || x === "C"))) continue;
      const score = five.reduce((s, p) => s + p.total + bonus(p), 0);
      if (!best || score > best.score) best = { five, score };
    }
    return best && { five: best.five, needs };
  }
  let STATS_DATA = null;

  function playerList(teamId) {
    const rows = D.players.filter((p) => p.team === teamId).sort((a, b) => b.poss - a.poss).slice(0, 8);
    return '<div class="table-box"><table><thead><tr><th class="l">Player</th><th>Ht</th><th>MPG</th><th>PPG</th><th>Impact</th></tr></thead><tbody>' +
      rows.map((p) => "<tr><td class='l name'>" + esc(p.name) + '<span class="sub">' + posLabel(p) + "</span></td><td>" + esc(p.ht || "–") + "</td><td>" + f1(p.mpg) +
        "</td><td>" + f1(p.ppg) + "</td><td class='" + cls(p.total) + "'>" + sgn(p.total, 2) + "</td></tr>").join("") + "</tbody></table></div>";
  }

  async function matchupPage(main, away, home, neutral, game) {
    const A = teamById[away], H = teamById[home];
    if (!A || !H) { main.innerHTML = '<p class="lede">That matchup isn’t available. <a href="#games">Back to games</a></p>'; return; }
    // A scheduled game carries the server's prediction, which includes any back-to-back adjustment
    const p = game && game.home_score != null ? { home_score: game.home_score, away_score: game.away_score, poss: game.poss, home_win: game.home_win } : predict(home, away, neutral);
    const tired = game && game.b2b ? [...game.b2b].map((s) => (s === "h" ? H : A).short) : [];
    const m = D.meta.model, idx = {};
    m.ids.forEach((id, i) => (idx[id] = i));
    const hi = idx[home], ai = idx[away], hf = neutral ? 0 : 1;
    const effH = D.meta.mu + m.O[hi] + m.D[ai] + hf * D.meta.hca / 2, effA = D.meta.mu + m.O[ai] + m.D[hi] - hf * D.meta.hca / 2;
    const spread = p.home_score - p.away_score, sd = D.meta.sd;
    const fav = spread >= 0 ? H : A, favWin = spread >= 0 ? p.home_win : 1 - p.home_win;
    const when = game && game.start ? new Date(game.start) : null;
    const whenTxt = when && !isNaN(when) ? when.toLocaleString(undefined, { weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    const lo80 = spread - 1.2816 * sd, hi80 = spread + 1.2816 * sd;
    const rangeTxt = (v) => (v >= 0 ? esc(H.short) + " by " + Math.abs(v).toFixed(0) : esc(A.short) + " by " + Math.abs(v).toFixed(0));

    main.innerHTML = '<div><p class="note" style="margin:0"><a href="#games">← Games</a></p><h1>' + esc(A.short) + (neutral ? " vs. " : " at ") + esc(H.short) + "</h1>" +
      '<p class="lede">' + esc(whenTxt) + (neutral ? " · neutral site" : "") + "</p></div>" +
      // Prediction
      '<section class="belief"><h2>Prediction</h2>' +
      '<dl class="kv"><div><dt>' + esc(A.short) + "</dt><dd>" + f1(p.away_score) + "</dd></div><div><dt>" + esc(H.short) + "</dt><dd>" + f1(p.home_score) +
      "</dd></div><div><dt>Spread</dt><dd>" + esc(fav.abbr || fav.short) + " −" + Math.abs(spread).toFixed(1) + "</dd></div><div><dt>Win chance</dt><dd>" + esc(fav.abbr || fav.short) + " " + pct(favWin) +
      "</dd></div><div><dt>Possessions</dt><dd>" + Math.round(p.poss) + "</dd></div></dl>" +
      '<p class="lede">The model expects ' + esc(fav.short) + " to win by about " + Math.abs(spread).toFixed(1) + ", but a single game is noisy: margins miss by about " + Math.round(sd) +
      " points on average. Eight times out of ten the final margin should land between " + rangeTxt(lo80) + " and " + rangeTxt(hi80) + ". The shaded areas below are each team's win chance.</p>" +
      (tired.length ? '<p class="note">' + esc(tired.join(" and ")) + (tired.length > 1 ? " are both" : /s$/.test(tired[0]) ? " are" : " is") + " playing the second night of a back-to-back" +
        (tired.length > 1 ? ", so the adjustments cancel." : ", which costs about " + f1(D.meta.b2b) + " points in this prediction (the effect held up across the 2025-26 season).") + "</p>" : "") +
      marginChart(spread, sd, H.short, A.short) +
      '<p class="legend"><span class="key prior"></span>' + esc(A.short) + " wins " + pct(1 - p.home_win) + ' <span class="key post"></span>' + esc(H.short) + " wins " + pct(p.home_win) + "</p>" +
      '<details class="how"><summary>How the prediction is built</summary><p>Each side’s points = possessions × expected points per 100 possessions ÷ 100.</p>' +
      '<div class="table-box"><table><tbody>' +
      "<tr><td class='l'>Possessions: average " + D.meta.tau + " + both teams’ tempo effects</td><td>" + p.poss.toFixed(1) + "</td></tr>" +
      "<tr><td class='l'>" + esc(H.short) + ": average " + D.meta.mu + " + its offense " + sgn(m.O[hi]) + " + " + esc(A.short) + "’s defense " + sgn(m.D[ai]) + (hf ? " + half of home court " + sgn(D.meta.hca / 2) : "") + "</td><td>" + effH.toFixed(1) + " per 100 → " + p.home_score.toFixed(1) + "</td></tr>" +
      "<tr><td class='l'>" + esc(A.short) + ": average " + D.meta.mu + " + its offense " + sgn(m.O[ai]) + " + " + esc(H.short) + "’s defense " + sgn(m.D[hi]) + (hf ? " − half of home court " + sgn(D.meta.hca / 2) : "") + "</td><td>" + effA.toFixed(1) + " per 100 → " + p.away_score.toFixed(1) + "</td></tr>" +
      "</tbody></table></div></details></section>" +
      // Ratings
      "<h2>Team comparison</h2>" +
      '<div class="table-box"><table><thead><tr><th class="l"></th><th>' + esc(A.short) + "</th><th>" + esc(H.short) + "</th></tr></thead><tbody>" +
      compareRow("Record", A.w + "-" + A.l, H.w + "-" + H.l, (x) => x) +
      compareRow("Net rating (rank)", A.net, H.net, (x) => sgn(x), A.rank, H.rank) +
      compareRow("Offense, pts per 100", A.o, H.o, f1, A.o_rank, H.o_rank) +
      compareRow("Defense, pts per 100 allowed", A.d, H.d, f1, A.d_rank, H.d_rank) +
      compareRow("Tempo, possessions per " + LG.minutes, A.tempo, H.tempo, f1) +
      compareRow("Preseason rating", A.pre, H.pre, (x) => (x == null ? "–" : sgn(x))) +
      "</tbody></table></div>" +
      '<div id="m-stats"><p class="lede">Loading season stats…</p></div>';

    const S = await loadStats();
    STATS_DATA = S;
    const box = $("#m-stats");
    if (!box) return;
    if (!S || !S.teams[away] || !S.teams[home]) { box.innerHTML = '<p class="lede">Season stat profiles aren’t available for this matchup yet.</p>'; return; }
    const L = S.league, sa = S.teams[away], sh = S.teams[home];
    const eA = edges(A, H, sa, sh, L), eH = edges(H, A, sh, sa, L);
    const li = (x) => "<li>" + x.txt + "</li>";
    const tA = tendencies(A, sa, L), tH = tendencies(H, sh, L);
    const sugA = suggestLineup(away, H, sh), sugH = suggestLineup(home, A, sa);
    const mostUsed = (id) => D.lineups.filter((l) => l.team === id).sort((a, b) => b.poss - a.poss)[0];
    const lineupBlock = (T, sug, mu) => '<div class="card"><h3>' + esc(T.short) + "</h3>" +
      (sug ? "<p><b>Suggested five:</b> " + sug.five.map((p) => esc(p.name) + ' <span class="sub">' + esc(p.pos || "") + "</span>").join(", ") + "</p>" +
        '<p class="note" style="margin:0">' + (sug.needs.length ? "Chosen for impact ratings plus " + sug.needs.map((n) => n.why).join(" and ") + "." : "Chosen for the highest combined impact ratings with a balanced frontcourt and backcourt.") + "</p>" : "<p class='note'>Not enough playing time yet to suggest a lineup.</p>") +
      (mu ? "<p><b>Most-used five:</b> " + mu.players.map(esc).join(", ") + ' <span class="sub">' + Math.round(mu.poss) + " poss, net " + sgn(mu.net) + "</span></p>" : "") + "</div>";

    box.innerHTML =
      "<h2>When " + esc(A.short) + (LG.nba ? " have" : " has") + " the ball</h2>" + possessionTable(A, H, sa, sh, L) +
      "<h2>When " + esc(H.short) + (LG.nba ? " have" : " has") + " the ball</h2>" + possessionTable(H, A, sh, sa, L) +
      '<section class="prose" style="max-width:none"><h2>Scouting report</h2>' +
      '<p class="note">Based on ' + sa.games + " and " + sh.games + " games. Season averages, not adjusted for opponents" + (Math.min(sa.games, sh.games) < 8 ? "; early-season numbers swing a lot from game to game" : "") + ".</p>" +
      '<div class="grid">' +
      '<div class="card"><h3>' + esc(A.short) + " on offense</h3>" + (eA.pros.length ? "<p><b>Where it can attack</b></p><ul>" + eA.pros.map(li).join("") + "</ul>" : "") +
      (eA.cons.length ? "<p><b>What could slow it down</b></p><ul>" + eA.cons.map(li).join("") + "</ul>" : "") + (eA.pros.length + eA.cons.length ? "" : "<p>No clear edges either way.</p>") + "</div>" +
      '<div class="card"><h3>' + esc(H.short) + " on offense</h3>" + (eH.pros.length ? "<p><b>Where it can attack</b></p><ul>" + eH.pros.map(li).join("") + "</ul>" : "") +
      (eH.cons.length ? "<p><b>What could slow it down</b></p><ul>" + eH.cons.map(li).join("") + "</ul>" : "") + (eH.pros.length + eH.cons.length ? "" : "<p>No clear edges either way.</p>") + "</div>" +
      "</div>" +
      "<h3>Likely tendencies</h3><p class='note'>Inferred from the stats, not observed: play-by-play doesn't record zone, man or press.</p>" +
      '<div class="grid"><div class="card"><h3>' + esc(A.short) + "</h3>" + (tA.length ? "<ul>" + tA.map((x) => "<li>" + x + "</li>").join("") + "</ul>" : "<p>No strong tendencies stand out yet.</p>") + "</div>" +
      '<div class="card"><h3>' + esc(H.short) + "</h3>" + (tH.length ? "<ul>" + tH.map((x) => "<li>" + x + "</li>").join("") + "</ul>" : "<p>No strong tendencies stand out yet.</p>") + "</div></div>" +
      "<h3>Lineups for this matchup</h3><p class='note'>A starting point for game planning, not a substitute for film: built from player impact ratings and box-score profiles, with extra weight on what counters the opponent's strengths.</p>" +
      '<div class="grid">' + lineupBlock(A, sugA, mostUsed(away)) + lineupBlock(H, sugH, mostUsed(home)) + "</div></section>" +
      "<h2>Key players</h2>" + '<div class="grid two"><div><h3>' + esc(A.short) + "</h3>" + playerList(away) + "</div><div><h3>" + esc(H.short) + "</h3>" + playerList(home) + "</div></div>";
  }

  async function gamePage(main, id) {
    let g = D.games.find((x) => x.id === id);
    if (!g) { const all = await loadSchedule(); g = all && all.find((x) => x.id === id); }
    if (!g) { main.innerHTML = '<p class="lede">That game isn’t on the schedule anymore. It may have been played already. <a href="#games">Back to games</a></p>'; return; }
    return matchupPage(main, g.away, g.home, !!g.neutral, g);
  }

  // What was tested for predictive power (tests/factors.py, tests/coach_study.py). A factor
  // "holds up" only if, fit on one part of the data, it improved predictions on the rest.
  function factorTable() {
    const rows = LG.nba ? [
      ["Missing rotation players (injuries, rest)", "Yes", "About 0.8 points per point of missing impact; biggest single gain. Needs reliable pregame injury reports, not yet wired in"],
      ["Second night of a back-to-back", "Yes", "About −1.8 points; now in the predictions"],
      ["Days of rest, travel distance, time zones", "No", "Nothing beyond the back-to-back"],
      ["Hot or cold last five games", "No", "Significant in one half of the season, reversed in the other"],
      ["Team-specific home court", "No", "One league-wide home edge predicts as well"],
      ["Style matchups (pace, threes, rebounding, turnovers)", "No", "None of six improved predictions"],
      ["Second-half “adjustment” teams", "No", "Halftime splits don't repeat (reliability 0.04). A first-half surprise is partly given back after the break, which matters only for live win chances"],
      ["Tip-off time", "No", "Too few early or late games to show anything"],
      ["Recency weighting", "Kept at 60 days", "Shorter and longer half-lives both did worse"],
      ["Betting market", "Benchmark", "The closing line beats this model (11.2 vs 11.7 points); adding the model to the line doesn't help"],
    ] : [
      ["Coaching change and the new coach's record elsewhere", "Yes", "Helped all 12 held-out seasons; now in the preseason ratings"],
      ["Missing rotation players (injuries)", "Yes", "About 0.5 points per point of missing impact when a key player sits; needs pregame injury reports, not yet wired in"],
      ["A coach's record at his current school", "No", "Already inside last season's rating"],
      ["Coach's past NCAA tournament overperformance", "No", "Helped 7 of 12 tournaments: no better than a coin flip"],
      ["Program's tournament reputation", "No", "Not reliably"],
      ["Distance from campus in the NCAA tournament", "Yes", "About 2 points for 50 vs. 1,000 miles; in the tournament odds"],
      ["Days of rest, travel distance, time zones, back-to-backs", "No", "No consistent effect in college"],
      ["Hot or cold last five games", "No", "Significant in one half of the season, reversed in the other"],
      ["Team-specific home court", "No", "One national home edge predicts as well"],
      ["Style matchups (pace, threes, rebounding, turnovers)", "No", "None of six improved predictions"],
      ["Second-half “adjustment” teams", "No", "Halftime splits don't repeat (reliability 0.07). A first-half surprise is partly given back after the break, which matters only for live win chances"],
      ["Tip-off time (early, afternoon, weekend, weekday)", "No", "No change in home edge by tip-off time"],
      ["Recency weighting", "Kept at 60 days", "Shorter and longer half-lives both did worse"],
      ["Betting market", "Benchmark", "The closing line beats this model (8.9 vs 9.1 points); adding the model to the line doesn't help"],
    ];
    return "<h2>What else was tested</h2><p>Each idea was fit on part of the " + (LG.nba ? "2025-26 season" : "data") + " and judged on games it hadn't seen. It counts only if it improved both the average miss and the win-probability score in every held-out part.</p>" +
      '<div class="table-box"><table class="findings"><thead><tr><th class="l">Factor</th><th class="l">Holds up?</th><th class="l">Finding</th></tr></thead><tbody>' +
      rows.map((r) => "<tr><td class='l'>" + esc(r[0]) + "</td><td class='l'>" + esc(r[1]) + "</td><td class='l'>" + esc(r[2]) + "</td></tr>").join("") + "</tbody></table></div>";
  }

  function route() {
    const h = location.hash.slice(1) || "rankings";
    const main = $("#main");
    const view = h.startsWith("team-") ? "rankings" : (h.startsWith("game-") || h.startsWith("vs-")) ? "games" : (VIEWS.includes(h) ? h : "rankings");
    document.querySelectorAll(".tabs a").forEach((a) => {
      if (a.getAttribute("href") === "#" + view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    if (h.startsWith("team-")) team(main, h.slice(5));
    else if (h.startsWith("game-")) gamePage(main, h.slice(5));
    else if (h.startsWith("vs-")) { const [a, b, n] = h.slice(3).split("-"); matchupPage(main, a, b, n === "n", null); }
    else ({ rankings, players, lineups, games, matchup, bracket, value, method })[view](main);
    window.scrollTo(0, 0);
  }

  load().catch((e) => {
    $("#main").innerHTML = '<p class="lede">The ratings files didn’t load (' + esc(e.message) + "). If this is the first day, the daily update may not have run yet.</p>";
  });
})();
