/* Sports by Numbers — men's college basketball views. Reads the JSON the daily job writes. */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const f1 = (x) => (x == null ? "–" : Number(x).toFixed(1));
  const sgn = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
  const cls = (x) => (x > 0.05 ? "pos" : x < -0.05 ? "neg" : "");
  const pct = (p) => Math.round(p * 100) + "%";
  const VIEWS = ["rankings", "players", "lineups", "games", "matchup", "bracket", "method"];

  let D = {};
  const teamById = {};

  function store(k, v) { try { v === undefined ? localStorage.getItem(k) : localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
  function recall(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  async function load() {
    const names = ["meta", "teams", "players", "lineups", "games"];
    const res = await Promise.all(names.map((n) => fetch("data/" + n + ".json").then((r) => { if (!r.ok) throw new Error(n); return r.json(); })));
    names.forEach((n, i) => (D[n] = res[i]));
    D.bracket = await fetch("data/bracket.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    D.teams.forEach((t) => (teamById[t.id] = t));
    $("#stamp").textContent = D.meta.season + " · updated " + new Date(D.meta.updated).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    if (/simulat/i.test(D.meta.season)) {
      $("#banner").hidden = false;
    }
    window.addEventListener("hashchange", route);
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
      { key: "prior", label: "Box est.", html: (p) => sgn(p.prior, 2) },
      { key: "poss", label: "Poss" },
      { key: "mpg", label: "MPG", html: (p) => f1(p.mpg) },
      { key: "ppg", label: "PPG", html: (p) => f1(p.ppg) },
      { key: "ts", label: "TS%", html: (p) => (p.ts == null ? "–" : (p.ts * 100).toFixed(1)) },
    ]);
  }

  function players(main) {
    const minDefault = recall("sbn-minposs") || 150;
    main.innerHTML = '<div><h1>Player Impact</h1><p class="lede">Estimated points per 100 possessions a player adds over an average player, at both ends, from who was on the floor when points were scored. Box est. is what the box score alone suggests.</p></div>' +
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
    return '<article class="card"><div class="when">' + esc(whenTxt) + (g.neutral ? " · neutral site" : "") + "</div>" +
      '<div class="row"><span class="t">' + teamLink(g.away) + '</span><span class="s">' + f1(g.away_score) + "</span></div>" +
      '<div class="row"><span class="t">' + (g.neutral ? "" : "@ ") + teamLink(g.home) + '</span><span class="s">' + f1(g.home_score) + "</span></div>" +
      '<div class="prob" role="img" aria-label="Win probability: ' + esc((teamById[g.home] || {}).short) + " " + pct(g.home_win) + '"><span class="a" style="width:' + (100 - g.home_win * 100) + '%"></span><span class="h" style="width:' + g.home_win * 100 + '%"></span></div>' +
      '<div class="probtxt"><span>' + pct(1 - g.home_win) + "</span><span>" + Math.round(g.poss) + " poss</span><span>" + pct(g.home_win) + "</span></div></article>";
  }

  function games(main) {
    main.innerHTML = '<div><h1>Upcoming Games</h1><p class="lede">Projected scores and win chances for the next three days, from the current team ratings.</p></div>' +
      (D.games.length ? '<div class="grid">' + D.games.map(gameCard).join("") + "</div>" : '<p class="lede">No Division I games are scheduled in the next three days.</p>');
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
        '<p class="lede">Projected margin ' + sgn(p.home_score - p.away_score) + " for " + esc(teamById[h].short) + ". Typical miss: about " + Math.round(D.meta.sd) + " points.</p>" : "";
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

  function method(main) {
    const m = D.meta;
    main.innerHTML = '<div class="prose"><h1>How It Works</h1>' +
      "<p>Every rating here comes from a regression fit to every game this season, refit each morning. The current fit uses " + m.games.toLocaleString() + " games and " + m.stints.toLocaleString() + " lineup stints.</p>" +
      "<h2>Team ratings</h2><p>Each game gives two observations, one per offense. For offense <i>o</i> facing defense <i>d</i>:</p>" +
      '<span class="eq">100 × points / possessions = μ + O[o] + D[d] + h·H/2 + ε</span>' +
      "<p>μ is the league average (" + m.mu + " this season). h is +1 for the home offense, −1 for the road offense and 0 at a neutral site, so H is the full home-court swing, currently estimated at " + m.hca + " points per 100 possessions. Possessions come from the box score: FGA − OREB + TO + 0.475 × FTA, averaged over both teams.</p>" +
      "<p>The fit is Bayesian ridge regression. Games are weighted by possessions and by recency, with a 60-day half-life, and home court starts from the long-run college average until the data can pin it down. Tempo is fit the same way on possessions per game.</p>" +
      "<h2>Preseason ratings</h2><p>Each team's O and D start from a preseason estimate built from two ingredients:</p>" +
      "<p><b>Program.</b> Last season's full-season rating. Weighting last season toward its final weeks, or using only its last 15 games, predicted this season's early games worse: the full season is a bigger sample, and late-season form is mostly noise.</p>" +
      "<p><b>Roster.</b> Every player on this season's roster carries his own impact rating from last season, wherever he played it, so transfers bring their value with them. A returning rating is projected forward with a rule learned from consecutive seasons (players who stay and players who transfer are fit separately). Freshmen and players new to Division I get the average newcomer rating. The team's projection weights each player by expected minutes.</p>" +
      '<span class="eq">preseason = ' + ((m.preseason || {}).w_program || 0.69) + " × program + " + ((m.preseason || {}).w_roster || 0.5) + " × roster</span>" +
      "<p>The weights come from regressing 2025-26 full-season ratings on both ingredients and from replaying this season's games. The preseason estimate counts as about " + ((m.preseason || {}).games || 2.7) + " games of evidence, so by January it carries little weight beside 15 or more real games. It doesn't fade beyond that: forcing it to zero by mid-season made January–March predictions slightly worse. The Teams table shows each team's preseason rating (Pre) and the share of its projected minutes going to players who were on last season's team (Ret).</p>" +
      "<h2>Predictions</h2><p>Projected possessions are the two teams' tempo effects added to the average. Each side's points are possessions × its expected efficiency. The win chance treats the actual margin as normal around the projection with a standard deviation of " + m.sd + " points, measured from how far past games landed from their fitted margins.</p>" +
      "<h2>Player impact</h2><p>Play-by-play is cut into stints, stretches with the same ten players on the floor. Each stint again gives two rows:</p>" +
      '<span class="eq">100 × points / possessions − μ = Σ Off[5 on offense] + Σ Def[5 on defense] + h·H/2 + ε</span>' +
      "<p>Teammates who always play together are hard to separate, so each player gets a normal prior centered on a box-score estimate. That box-score model is itself learned from the data: a first, heavily shrunk pass of the regression is regressed on per-40-minute box stats (points, shot attempts, free throws, threes, assists, turnovers and offensive rebounds for offense; steals, blocks, defensive rebounds and fouls for defense). The final rating is the posterior mean</p>" +
      '<span class="eq">β = prior + (XᵀWX + λI)⁻¹ XᵀW (y − X·prior)</span>' +
      "<p>with W the stint possessions. λ" + (m.lambda ? " (currently " + Math.round(m.lambda).toLocaleString() + " possessions)" : "") + " sets how much on-court evidence it takes to move a player off the box-score estimate. It is chosen by cross-validation: hold out every fifth game, fit on the rest, and keep the λ that best predicts scoring in the held-out stints. Defense is reported with the sign flipped so higher is better on both ends.</p>" +
      "<h2>Tournament odds</h2><p>The Bracket tab simulates the projected field (the Bracket Matrix consensus until Selection Sunday) 20,000 times. Each simulation draws every team's true strength around its rating, with a spread measured from how much ratings moved between December and March in 2025-26, then plays each game by the prediction formula above at its announced site. Tests on every tournament from 2012 to 2026 decided what else counts. Distance from campus to arena does: margins shift about 0.75 points per unit of log(1 + miles). A team's road and neutral-court form during the season doesn't, beyond its overall rating. A program's record against expectations in recent tournaments showed a small effect that didn't hold up when each tournament was predicted from the others, so it's shown only as context.</p>" +
      "<h2>Lineups</h2><p>Lineup numbers are raw on-court results per 100 possessions, not adjusted for opponents. Use them to see how a coach deploys a roster, and lean on the player ratings for talent.</p>" +
      "<h2>Data</h2><p>Box scores and play-by-play come from ESPN's public scoreboard feed, pulled after each day's games. Stints with lineup gaps (a missed substitution in the feed) are dropped rather than guessed.</p></div>";
  }

  function route() {
    const h = location.hash.slice(1) || "rankings";
    const main = $("#main");
    const view = h.startsWith("team-") ? "rankings" : (VIEWS.includes(h) ? h : "rankings");
    document.querySelectorAll(".tabs a").forEach((a) => {
      if (a.getAttribute("href") === "#" + view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    if (h.startsWith("team-")) team(main, h.slice(5));
    else ({ rankings, players, lineups, games, matchup, bracket, method })[view](main);
    window.scrollTo(0, 0);
  }

  load().catch((e) => {
    $("#main").innerHTML = '<p class="lede">The ratings files didn’t load (' + esc(e.message) + "). If this is the first day, the daily update may not have run yet.</p>";
  });
})();
