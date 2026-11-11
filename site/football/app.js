/* Sports by Numbers — college football views. Reads the JSON the daily job writes. */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const f1 = (x) => (x == null ? "–" : Number(x).toFixed(1));
  const f2 = (x) => (x == null ? "–" : Number(x).toFixed(2));
  const sgn = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
  const cls = (x) => (x > 0.05 ? "pos" : x < -0.05 ? "neg" : "");
  const pct = (p) => Math.round(p * 100) + "%";
  const VIEWS = ["rankings", "games", "matchup", "method"];
  let D = {};
  const teamById = {};

  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
  function recall(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  async function load() {
    const names = ["meta", "teams", "games"];
    const res = await Promise.all(names.map((n) => fetch("data/" + n + ".json").then((r) => { if (!r.ok) throw new Error(n); return r.json(); })));
    names.forEach((n, i) => (D[n] = res[i]));
    D.teams.forEach((t) => (teamById[t.id] = t));
    $("#stamp").textContent = D.meta.season + " season · updated " + new Date(D.meta.updated).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    window.addEventListener("hashchange", route);
    route();
  }

  function teamLink(id, withConf) {
    const t = teamById[id];
    if (!t) return esc(id);
    return '<span class="dot" style="background:#' + esc(t.color) + '"></span>' + esc(t.short || t.name) +
      (withConf ? '<span class="sub">' + esc([t.conf, t.div].filter(Boolean).join(" · ")) + "</span>" : "");
  }
  function netBar(x, max) {
    const w = Math.min(Math.abs(x) / max, 1) * 50;
    const style = x >= 0 ? "left:50%;width:" + w + "%;background:var(--pos)" : "right:50%;width:" + w + "%;background:var(--neg)";
    return '<span class="bar"><span class="' + cls(x) + '">' + sgn(x) + '</span><i><b style="' + style + '"></b></i></span>';
  }

  function table(el, cols, rows, sortKey) {
    let key = sortKey, asc = !!(cols.find((c) => c.key === sortKey) || {}).asc, shown = 150;
    function draw() {
      const col = cols.find((c) => c.key === key), v = col.val || ((r) => r[key]);
      const sorted = rows.slice().sort((a, b) => {
        const x = v(a), y = v(b);
        if (x == null) return 1; if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
      });
      el.innerHTML = '<div class="table-box"><table><thead><tr>' +
        cols.map((c) => '<th scope="col" data-k="' + c.key + '" class="' + (c.left ? "l " : "") + (c.key === key ? "sorted" + (asc ? " asc" : "") : "") + '">' + c.label + "</th>").join("") +
        "</tr></thead><tbody>" +
        (sorted.slice(0, shown).map((r) => "<tr>" + cols.map((c) => '<td class="' + (c.left ? "l " : "") + (c.cls || "") + '">' + (c.html ? c.html(r) : esc(r[c.key])) + "</td>").join("") + "</tr>").join("") ||
          '<tr><td class="l" colspan="' + cols.length + '">Nothing matches these filters.</td></tr>') +
        "</tbody></table></div>" +
        (sorted.length > shown ? '<div class="more"><button type="button" data-more>Show ' + Math.min(150, sorted.length - shown) + " more of " + sorted.length + "</button></div>" : "");
      el.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
        const c = cols.find((x) => x.key === th.dataset.k);
        if (key === c.key) asc = !asc; else { key = c.key; asc = !!c.asc; }
        draw();
      }));
      const more = el.querySelector("[data-more]");
      if (more) more.addEventListener("click", () => { shown += 150; draw(); });
    }
    draw();
  }

  function options(list, sel, blank) {
    return (blank ? '<option value="">' + blank + "</option>" : "") + list.map((x) => "<option" + (x === sel ? " selected" : "") + ">" + esc(x) + "</option>").join("");
  }
  function teamOptions(sel) {
    return D.teams.slice().sort((a, b) => (a.short || a.name).localeCompare(b.short || b.name))
      .map((t) => '<option value="' + t.id + '"' + (t.id === sel ? " selected" : "") + ">" + esc(t.short || t.name) + "</option>").join("");
  }

  function rankings(main) {
    const confs = [...new Set(D.teams.map((t) => t.conf).filter(Boolean))].sort();
    main.innerHTML = '<div><h1>Team Ratings</h1><p class="lede">Expected margin, in points, against an average Division I team on a neutral field. Offense is points scored and defense points allowed against average opposition.</p></div>' +
      '<div class="controls"><div class="field"><label for="r-q">Search</label><input type="search" id="r-q" placeholder="Team name"></div>' +
      '<div class="field"><label for="r-v">Division</label><select id="r-v">' + options(["FBS", "FCS"], recall("sbnf-div") || "FBS", "All Division I") + "</select></div>" +
      '<div class="field"><label for="r-c">Conference</label><select id="r-c">' + options(confs, "", "All conferences") + "</select></div></div><div id='r-t'></div>";
    const max = Math.max(...D.teams.map((t) => Math.abs(t.net)), 1);
    const cols = [
      { key: "rank", label: "Rk", asc: true },
      { key: "name", label: "Team", left: true, cls: "name", html: (t) => teamLink(t.id, true), val: (t) => t.short, asc: true },
      { key: "rec", label: "W-L", html: (t) => t.w + "-" + t.l, val: (t) => t.w - t.l },
      { key: "net", label: "Net", html: (t) => netBar(t.net, max) },
      { key: "net_se", label: "±", asc: true, html: (t) => f1(t.net_se) },
      { key: "o", label: "Off", html: (t) => f1(t.o) + '<span class="rk">' + t.o_rank + "</span>" },
      { key: "d", label: "Def", asc: true, html: (t) => f1(t.d) + '<span class="rk">' + t.d_rank + "</span>" },
      { key: "ppd_o", label: "Pts/drive", html: (t) => f2(t.ppd_o) },
      { key: "ppd_d", label: "Allowed", asc: true, html: (t) => f2(t.ppd_d) },
      { key: "pre", label: "Pre", html: (t) => (t.pre == null ? "–" : '<span class="' + cls(t.pre) + '">' + sgn(t.pre) + "</span>") },
    ];
    const draw = () => {
      const q = $("#r-q").value.trim().toLowerCase(), v = $("#r-v").value, c = $("#r-c").value;
      store("sbnf-div", v);
      table($("#r-t"), cols, D.teams.filter((t) => (!v || t.div === v) && (!c || t.conf === c) && (!q || (t.name + " " + t.abbr).toLowerCase().includes(q))), "net");
    };
    ["#r-q", "#r-v", "#r-c"].forEach((s) => $(s).addEventListener("input", draw));
    draw();
  }

  function gameCard(g) {
    const when = g.start ? new Date(g.start) : null;
    const whenTxt = when && !isNaN(when) ? when.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    const spread = g.home_score - g.away_score;
    const fav = spread >= 0 ? g.home : g.away;
    return '<article class="card"><div class="when">' + esc(whenTxt) + (g.neutral ? " · neutral site" : "") + (g.note ? " · " + esc(g.note) : "") + "</div>" +
      '<div class="row"><span class="t">' + teamLink(g.away) + '</span><span class="s">' + f1(g.away_score) + "</span></div>" +
      '<div class="row"><span class="t">' + (g.neutral ? "" : "@ ") + teamLink(g.home) + '</span><span class="s">' + f1(g.home_score) + "</span></div>" +
      '<div class="prob" role="img" aria-label="Home win probability ' + pct(g.home_win) + '"><span class="a" style="width:' + (100 - g.home_win * 100) + '%"></span><span class="h" style="width:' + g.home_win * 100 + '%"></span></div>' +
      '<div class="probtxt"><span>' + pct(1 - g.home_win) + "</span><span>" + esc((teamById[fav] || {}).abbr || "") + " by " + Math.abs(spread).toFixed(1) + "</span><span>" + pct(g.home_win) + "</span></div></article>";
  }

  function games(main) {
    const known = D.games.filter((g) => teamById[g.home] || teamById[g.away]);
    main.innerHTML = '<div><h1>Upcoming Games</h1><p class="lede">Projected scores, spreads and win chances for the next week.</p></div>' +
      '<div class="controls"><div class="field"><label for="g-q">Team</label><input type="search" id="g-q" placeholder="Filter by team"></div></div><div id="g-l"></div>';
    const draw = () => {
      const q = $("#g-q").value.trim().toLowerCase();
      const rows = known.filter((g) => !q || ((g.home_name || "") + " " + (g.away_name || "")).toLowerCase().includes(q));
      $("#g-l").innerHTML = rows.length ? '<div class="grid">' + rows.map(gameCard).join("") + "</div>" : '<p class="lede">No Division I games in the next week match.</p>';
    };
    $("#g-q").addEventListener("input", draw);
    draw();
  }

  function normCdf(z) {
    const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2);
    const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
    return z > 0 ? 1 - p : p;
  }
  function predict(h, a, neutral) {
    const m = D.meta.model, idx = {};
    m.ids.forEach((id, i) => (idx[id] = i));
    const hi = idx[h], ai = idx[a];
    if (hi == null || ai == null) return null;
    const hf = neutral ? 0 : 1, mu = D.meta.mu, H = D.meta.hfa;
    const hs = mu + m.O[hi] + m.D[ai] + hf * H / 2, as = mu + m.O[ai] + m.D[hi] - hf * H / 2;
    return { home_score: hs, away_score: as, home_win: normCdf((hs - as) / D.meta.sd) };
  }

  function matchup(main) {
    const a0 = recall("sbnf-away") || D.teams[1].id, h0 = recall("sbnf-home") || D.teams[0].id;
    main.innerHTML = '<div><h1>Matchup</h1><p class="lede">Pick any two Division I teams to project a score, spread and win chance.</p></div>' +
      '<div class="controls"><div class="field"><label for="m-a">Away</label><select id="m-a">' + teamOptions(a0) + "</select></div>" +
      '<div class="field"><label for="m-h">Home</label><select id="m-h">' + teamOptions(h0) + "</select></div>" +
      '<div class="field"><label for="m-v">Site</label><select id="m-v"><option value="0">Home field</option><option value="1">Neutral</option></select></div></div><div id="m-out"></div>';
    const draw = () => {
      const a = $("#m-a").value, h = $("#m-h").value, n = $("#m-v").value === "1";
      store("sbnf-away", a); store("sbnf-home", h);
      if (a === h) { $("#m-out").innerHTML = '<p class="lede">Choose two different teams.</p>'; return; }
      const p = predict(h, a, n);
      $("#m-out").innerHTML = p ? '<div class="grid">' + gameCard(Object.assign({ home: h, away: a, neutral: n }, p)) + "</div>" +
        '<p class="lede">Typical miss: about ' + Math.round(D.meta.sd) + " points either way.</p>" : "";
    };
    ["#m-a", "#m-h", "#m-v"].forEach((s) => $(s).addEventListener("change", draw));
    draw();
  }

  function method(main) {
    const m = D.meta;
    main.innerHTML = '<div class="prose"><h1>How It Works</h1>' +
      "<p>Ratings come from one regression over every Division I game this season (FBS and FCS on one scale, since they play each other), refit each morning. The current fit uses " + m.games.toLocaleString() + " games.</p>" +
      "<h2>Team ratings</h2><p>Each game gives two observations, one per offense:</p>" +
      '<span class="eq">points scored = μ + O[offense] + D[defense] + h·H/2 + ε</span>' +
      "<p>μ is the average score (" + m.mu + " this season). h is +1 for the home offense, −1 for the road offense and 0 at a neutral site, so H is the full home-field edge, currently " + m.hfa + " points. Net = O − D is the expected margin against an average Division I team on a neutral field. Teams from outside Division I are pooled into one opponent so wins over them count for what they are.</p>" +
      "<p>The fit is Bayesian ridge regression. Each team starts from last season's final rating, with " + Math.round(m.prior_keep * 100) + "% carried over and worth about " + m.prior_games + " games of evidence, so September ratings are sensible and this season's results take over within a few weeks. Both settings were chosen by replaying the 2025 season week by week. Damping lopsided scores (counting a 63-0 win as something less) made those replayed predictions worse, so every score counts as played. Non-conference games are the only ones linking conferences, so they set how the conferences compare. Delen, Cogdell and Kasap (2012) found non-conference results and average margin were the two strongest predictors of bowl outcomes.</p>" +
      "<h2>Predictions</h2><p>Each side's projected points are μ plus its offense, the opponent's defense and its share of home field. The win chance treats the actual margin as normal around the projected spread with a standard deviation of " + m.sd + " points, measured from how far this season's games landed from their fitted margins.</p>" +
      "<h2>Points per drive</h2><p>The Teams table also shows raw points per drive for and against, from ESPN's drive charts. They aren't adjusted for opponents; they show how efficiently each side of the ball turns possessions into points.</p>" +
      "<h2>Coming next</h2><p>Bowl and College Football Playoff projections, a bowl-specific model following Delen, Cogdell and Kasap, and efficiency ratings built on expected points per play.</p></div>";
  }

  function route() {
    const h = location.hash.slice(1) || "rankings";
    const view = VIEWS.includes(h) ? h : "rankings";
    document.querySelectorAll(".tabs a").forEach((a) => {
      if (a.getAttribute("href") === "#" + view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    ({ rankings, games, matchup, method })[view]($("#main"));
    window.scrollTo(0, 0);
  }

  load().catch((e) => {
    $("#main").innerHTML = '<p class="lede">The ratings files didn’t load (' + esc(e.message) + "). The first football update may not have run yet.</p>";
  });
})();
