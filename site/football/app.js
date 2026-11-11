/* Sports by Numbers — football views (college and NFL share this script). Reads the JSON the daily job writes. */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const poss = (name) => (/s$/.test(name) ? name + "\u2019" : name + "\u2019s");  // Giants' / Duke's
  const f1 = (x) => (x == null ? "–" : Number(x).toFixed(1));
  const f2 = (x) => (x == null ? "–" : Number(x).toFixed(2));
  const sgn = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
  const cls = (x) => (x > 0.05 ? "pos" : x < -0.05 ? "neg" : "");
  const pct = (p) => (p >= 0.995 ? ">99%" : p <= 0.005 ? "<1%" : Math.round(p * 100) + "%");
  const VIEWS = ["rankings", "games", "matchup", "playoff", "method"];
  let D = {};
  let LG = { nfl: false, level: "Division I", short: "D-I" };  // replaced by meta.league on load
  const teamById = {};

  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
  function recall(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  async function load() {
    const names = ["meta", "teams", "games"];
    const res = await Promise.all(names.map((n) => fetch("data/" + n + ".json").then((r) => { if (!r.ok) throw new Error(n); return r.json(); })));
    names.forEach((n, i) => (D[n] = res[i]));
    D.playoff = await fetch("data/playoff.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    D.teams.forEach((t) => (teamById[t.id] = t));
    if (D.meta.league) LG = D.meta.league;
    $("#stamp").textContent = D.meta.season + " season · updated " + new Date(D.meta.updated).toLocaleDateString(undefined, { month: "short", day: "numeric" });
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
    return '<span class="dot" style="background:#' + esc(t.color) + '"></span>' + esc(t.short || t.name) +
      (withConf ? '<span class="sub">' + esc([t.conf, LG.nfl ? "" : t.div].filter(Boolean).join(" · ")) + "</span>" : "");
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
    main.innerHTML = '<div><h1>Team Ratings</h1><p class="lede">Expected margin, in points, against an average ' + LG.level + ' team on a neutral field. Offense is points scored and defense points allowed against average opposition.</p></div>' +
      '<div class="controls"><div class="field"><label for="r-q">Search</label><input type="search" id="r-q" placeholder="Team name"></div>' +
      (LG.nfl ? "" : '<div class="field"><label for="r-v">Division</label><select id="r-v">' + options(["FBS", "FCS"], recall("sbnf-div") || "FBS", "All Division I") + "</select></div>") +
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
      const q = $("#r-q").value.trim().toLowerCase(), v = $("#r-v") ? $("#r-v").value : "", c = $("#r-c").value;
      if ($("#r-v")) store("sbnf-div", v);
      table($("#r-t"), cols, D.teams.filter((t) => (!v || t.div === v) && (!c || t.conf === c) && (!q || (t.name + " " + t.abbr).toLowerCase().includes(q))), "net");
    };
    ["#r-q", "#r-v", "#r-c"].forEach((s) => $(s) && $(s).addEventListener("input", draw));
    draw();
  }

  function gameCard(g) {
    const when = g.start ? new Date(g.start) : null;
    const whenTxt = when && !isNaN(when) ? when.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    const spread = g.home_score - g.away_score;
    const fav = spread >= 0 ? g.home : g.away;
    return '<article class="card game" data-href="' + gameHref(g) + '"><div class="when">' + esc(whenTxt) + (g.neutral ? " · neutral site" : "") + (g.note ? " · " + esc(g.note) : "") + "</div>" +
      '<div class="row"><span class="t">' + teamLink(g.away) + '</span><span class="s">' + f1(g.away_score) + "</span></div>" +
      '<div class="row"><span class="t">' + (g.neutral ? "" : "@ ") + teamLink(g.home) + '</span><span class="s">' + f1(g.home_score) + "</span></div>" +
      '<div class="prob" role="img" aria-label="Home win probability ' + pct(g.home_win) + '"><span class="a" style="width:' + (100 - g.home_win * 100) + '%"></span><span class="h" style="width:' + g.home_win * 100 + '%"></span></div>' +
      '<div class="probtxt"><span>' + pct(1 - g.home_win) + "</span><span>" + esc((teamById[fav] || {}).abbr || "") + " by " + Math.abs(spread).toFixed(1) + "</span><span>" + pct(g.home_win) + "</span></div>" +
      '<a class="more-link" href="' + gameHref(g) + '">Matchup details →</a></article>';
  }

  function games(main) {
    const known = D.games.filter((g) => teamById[g.home] || teamById[g.away]);
    main.innerHTML = '<div><h1>Upcoming Games</h1><p class="lede">Projected scores, spreads and win chances for the next week.</p></div>' +
      '<div class="controls"><div class="field"><label for="g-q">Team</label><input type="search" id="g-q" placeholder="Filter by team"></div></div><div id="g-l"></div>';
    const draw = () => {
      const q = $("#g-q").value.trim().toLowerCase();
      const rows = known.filter((g) => !q || ((g.home_name || "") + " " + (g.away_name || "")).toLowerCase().includes(q));
      $("#g-l").innerHTML = rows.length ? '<div class="grid">' + rows.map(gameCard).join("") + "</div>" : '<p class="lede">No ' + LG.level + ' games in the next week match.</p>';
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
    main.innerHTML = '<div><h1>Matchup</h1><p class="lede">Pick any two ' + LG.level + ' teams to project a score, spread and win chance.</p></div>' +
      '<div class="controls"><div class="field"><label for="m-a">Away</label><select id="m-a">' + teamOptions(a0) + "</select></div>" +
      '<div class="field"><label for="m-h">Home</label><select id="m-h">' + teamOptions(h0) + "</select></div>" +
      '<div class="field"><label for="m-v">Site</label><select id="m-v"><option value="0">Home field</option><option value="1">Neutral</option></select></div></div><div id="m-out"></div>';
    const draw = () => {
      const a = $("#m-a").value, h = $("#m-h").value, n = $("#m-v").value === "1";
      store("sbnf-away", a); store("sbnf-home", h);
      if (a === h) { $("#m-out").innerHTML = '<p class="lede">Choose two different teams.</p>'; return; }
      const p = predict(h, a, n);
      $("#m-out").innerHTML = p ? '<div class="grid">' + gameCard(Object.assign({ home: h, away: a, neutral: n }, p)) + "</div>" +
        '<p class="lede">Typical miss: about ' + Math.round(D.meta.sd) + ' points either way. <a href="' + gameHref({ away: a, home: h, neutral: n }) + '">Full matchup report →</a></p>' : "";
    };
    ["#m-a", "#m-h", "#m-v"].forEach((s) => $(s).addEventListener("change", draw));
    draw();
  }

  function playoff(main) {
    const P = D.playoff;
    if (LG.nfl || !P) { main.innerHTML = '<div><h1>Playoff Odds</h1><p class="lede">Playoff odds will appear after the next daily update.</p></div>'; return; }
    const poll = P.polls || {};
    main.innerHTML = '<div><h1>Playoff Odds</h1><p class="lede">Chances of making the 12-team College Football Playoff and advancing, from ' + P.sims.toLocaleString() +
      " simulations of the rest of the season. Each one plays out the remaining schedule and conference title games, ranks teams by strength of record (how surprising their record would be for a top-25-caliber team against the same schedule) with a small credit for rating, then builds the field by the 2026 rules and plays the bracket.</p></div>" +
      '<p class="note">An approximation of the committee, not a copy of it. ' + (poll.name ? "The " + esc(poll.name) + " rank is shown for comparison." : "") +
      " Automatic bids go to the ACC, Big Ten, Big 12 and SEC champions, the highest-ranked team from the American, Conference USA, MAC, Mountain West, Pac-12 and Sun Belt, and Notre Dame if it ranks in the top 12; the top four get byes.</p><div id='po-t'></div>";
    const p100 = (v) => (v >= 0.995 ? "✓" : v < 0.001 ? "–" : (v * 100).toFixed(v < 0.1 ? 1 : 0));
    const cols = [
      { key: "poll", label: poll.name && /playoff|cfp/i.test(poll.name) ? "CFP" : "AP", asc: true, val: (t) => (poll.ranks || {})[t.id] || null, html: (t) => (poll.ranks || {})[t.id] || "–" },
      { key: "team", label: "Team", left: true, cls: "name", html: (t) => teamLink(t.id, true), val: (t) => (teamById[t.id] || {}).short, asc: true },
      { key: "rec", label: "Avg. final record", html: (t) => t.wins.toFixed(1) + "–" + t.losses.toFixed(1), val: (t) => t.wins - t.losses },
      { key: "conf_champ", label: "Win conf.", html: (t) => p100(t.conf_champ) },
      { key: "playoff", label: "Make CFP", html: (t) => "<b>" + p100(t.playoff) + "</b>" },
      { key: "bye", label: "Bye", html: (t) => p100(t.bye) },
      { key: "semi", label: "Semis", html: (t) => p100(t.semi) },
      { key: "final", label: "Title game", html: (t) => p100(t.final) },
      { key: "title", label: "Champion", html: (t) => p100(t.title) },
    ];
    table($("#po-t"), cols, P.teams, "playoff");
  }

  function method(main) {
    const m = D.meta;
    if (LG.nfl) {
      main.innerHTML = '<div class="prose"><h1>How It Works</h1>' +
        "<p>Ratings come from one regression over every NFL game this season, refit each morning. The current fit uses " + m.games.toLocaleString() + " games.</p>" +
        "<h2>Team ratings</h2><p>Each game gives two observations, one per offense:</p>" +
        '<span class="eq">points scored = μ + O[offense] + D[defense] + h·H/2 + ε</span>' +
        "<p>μ is the average score (" + m.mu + " this season). h is +1 for the home offense, −1 for the road offense and 0 at a neutral site (London, Mexico City and other international games), so H is the full home-field edge, currently " + m.hfa + " points. Net = O − D is the expected margin against an average NFL team on a neutral field.</p>" +
        "<p>The fit is Bayesian ridge regression. Each team starts from last season's final rating, with " + Math.round(m.prior_keep * 100) + "% carried over and worth about " + m.prior_games + " games of evidence. NFL rosters turn over more than college programs' reputations suggest, so less of last season carries forward than in college football.</p>" +
        "<h2>Predictions</h2><p>Each side's projected points are μ plus its offense, the opponent's defense and its share of home field. The win chance treats the actual margin as normal around the projected spread with a standard deviation of " + m.sd + " points.</p>" +
        "<h2>Coming next</h2><p>Player value and salary-cap efficiency: which teams get the most performance per cap dollar.</p></div>";
      return;
    }
    main.innerHTML = '<div class="prose"><h1>How It Works</h1>' +
      "<p>Ratings come from one regression over every Division I game this season (FBS and FCS on one scale, since they play each other), refit each morning. The current fit uses " + m.games.toLocaleString() + " games.</p>" +
      "<h2>Team ratings</h2><p>Each game gives two observations, one per offense:</p>" +
      '<span class="eq">points scored = μ + O[offense] + D[defense] + h·H/2 + ε</span>' +
      "<p>μ is the average score (" + m.mu + " this season). h is +1 for the home offense, −1 for the road offense and 0 at a neutral site, so H is the full home-field edge, currently " + m.hfa + " points. Net = O − D is the expected margin against an average Division I team on a neutral field. Teams from outside Division I are pooled into one opponent so wins over them count for what they are.</p>" +
      "<p>The fit is Bayesian ridge regression. Each team starts from last season's final rating, with " + Math.round(m.prior_keep * 100) + "% carried over and worth about " + m.prior_games + " games of evidence, so September ratings are sensible and this season's results take over within a few weeks. Both settings were chosen by replaying the 2025 season week by week. Damping lopsided scores (counting a 63-0 win as something less) made those replayed predictions worse, so every score counts as played. Non-conference games are the only ones linking conferences, so they set how the conferences compare. Delen, Cogdell and Kasap (2012) found non-conference results and average margin were the two strongest predictors of bowl outcomes.</p>" +
      "<h2>Predictions</h2><p>Each side's projected points are μ plus its offense, the opponent's defense and its share of home field. The win chance treats the actual margin as normal around the projected spread with a standard deviation of " + m.sd + " points, measured from how far this season's games landed from their fitted margins.</p>" +
      "<h2>Points per drive</h2><p>The Teams table also shows raw points per drive for and against, from ESPN's drive charts. They aren't adjusted for opponents; they show how efficiently each side of the ball turns possessions into points.</p>" +
      "<h2>Playoff odds</h2><p>The Playoff tab simulates the rest of the season 10,000 times with these ratings, ranks teams by strength of record with a small credit for rating, builds the 12-team field by the 2026 rules (Power 4 champions, the top Group of Six team, Notre Dame if it ranks in the top 12, the rest at-large; byes for the top four) and plays the bracket. The committee is people, not a formula, so treat the selection step as an informed approximation.</p>" +
      "<h2>Bowl games: a study</h2><p>Following Delen, Cogdell and Kasap (2012, <i>International Journal of Forecasting</i> 28(2), 543–552), we compared ways of predicting bowl winners on every FBS postseason game from 2018 to 2025 (319 games), training each season's model only on earlier seasons. Features were measured at the end of the regular season: these ratings, win percentage, non-conference and conference records, average margin, points for and against, schedule strength, last-three-games form, conference strength, games played and days off.</p>" +
      '<div class="table-box"><table><thead><tr><th class="l">Method</th><th>Correct</th><th>Log loss</th><th>Brier</th></tr></thead><tbody>' +
      "<tr><td class='l'>Random forest, all features</td><td>61.4%</td><td>0.658</td><td>0.233</td></tr>" +
      "<tr><td class='l'>Logistic regression, rating gap only</td><td>60.2%</td><td>0.664</td><td>0.236</td></tr>" +
      "<tr><td class='l'>This site's rating model</td><td>59.6%</td><td>0.666</td><td>0.237</td></tr>" +
      "<tr><td class='l'>Gradient boosting, all features</td><td>61.1%</td><td>0.674</td><td>0.240</td></tr>" +
      "<tr><td class='l'>Logistic regression, all features</td><td>59.2%</td><td>0.687</td><td>0.245</td></tr>" +
      "<tr><td class='l'>Decision tree (as in the paper)</td><td>56.7%</td><td>0.739</td><td>0.258</td></tr></tbody></table></div>" +
      "<p>Bowls are hard: every method lands near 60%, and the differences among the top four are within the noise of 319 games. The decision tree that led the paper's cross-validated results did worst when predicting future seasons, a reminder that cross-validation which mixes seasons can flatter a flexible model. On their own, the paper's two most important variables picked the winner 54% (non-conference record) and 57% (average margin) of the time, against 59% for the rating gap. Bowl predictions here use the rating model; the gain from the forest isn't large enough yet to trust.</p>" +
      "<h2>Coming next</h2><p>Efficiency ratings built on expected points per play.</p></div>";
  }

  /* ===================== Matchup page ===================== */
  let STATS = null;
  const loadStats = () => (STATS = STATS || fetch("data/teamstats.json").then((r) => (r.ok ? r.json() : null)).catch(() => null));
  const ordinal = (n) => (n ? n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th") : "");
  const pc = (x, d = 0) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
  const n1 = (x) => (x == null ? "–" : Number(x).toFixed(1));
  const n2 = (x) => (x == null ? "–" : Number(x).toFixed(2));
  const gameHref = (g) => (g.id ? "#game-" + g.id : "#vs-" + g.away + "-" + g.home + (g.neutral ? "-n" : ""));

  function marginChart(spread, sd, homeName, awayName) {
    const W = 640, H = 170, padB = 30, top = 14, padX = 12;
    const lo = Math.min(spread - 3 * sd, -7), hi = Math.max(spread + 3 * sd, 7);
    const x = (v) => padX + (v - lo) / (hi - lo) * (W - 2 * padX);
    const dens = (v) => Math.exp(-0.5 * ((v - spread) / sd) ** 2);
    const y = (d) => H - padB - d * (H - padB - top);
    const area = (a, b) => {
      let p = "M" + x(a).toFixed(1) + " " + y(0);
      for (let i = 0; i <= 80; i++) { const v = a + (b - a) * i / 80; p += " L" + x(v).toFixed(1) + " " + y(dens(v)).toFixed(1); }
      return p + " L" + x(b).toFixed(1) + " " + y(0) + " Z";
    };
    const step = hi - lo > 70 ? 14 : 7, ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
    return '<div class="chart-box"><svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Range of likely final margins">' +
      ticks.map((v) => '<line class="grid" x1="' + x(v) + '" x2="' + x(v) + '" y1="' + top + '" y2="' + (H - padB) + '"/><text class="tick" x="' + x(v) + '" y="' + (H - padB + 16) + '">' +
        (v === 0 ? "0" : (v > 0 ? esc(homeName) + " +" + v : esc(awayName) + " +" + -v)) + "</text>").join("") +
      (lo < 0 ? '<path class="prior" d="' + area(lo, Math.min(0, hi)) + '"/>' : "") + (hi > 0 ? '<path class="post" d="' + area(Math.max(0, lo), hi) + '"/>' : "") +
      '<line class="axis" x1="' + padX + '" x2="' + (W - padX) + '" y1="' + (H - padB) + '" y2="' + (H - padB) + '"/>' +
      '<line class="mark-post" x1="' + x(spread) + '" x2="' + x(spread) + '" y1="' + top + '" y2="' + (H - padB) + '"/>' +
      '<line class="mark-prior" x1="' + x(0) + '" x2="' + x(0) + '" y1="' + top + '" y2="' + (H - padB) + '"/></svg></div>';
  }

  const UNIT_ROWS = [["ypp", "d_ypp", "Yards per play", n2], ["success", "d_success", "Success rate", pc], ["explosive", "d_explosive", "Explosive play rate", pc],
    ["rush_ypc", "d_rush_ypc", "Yards per rush", n2], ["rush_success", "d_rush_success", "Rush success rate", pc],
    ["pass_ypa", "d_pass_ypa", "Yards per dropback", n2], ["pass_success", "d_pass_success", "Pass success rate", pc],
    ["third_conv", "d_third_conv", "3rd-down conversion", pc], ["sack_rate", "d_sack_rate", "Sack rate", (x) => pc(x, 1)],
    ["rz_td", "d_rz_td", "Red-zone TD rate", pc], ["ppd", "d_ppd", "Points per drive", n2], ["to_drive", "d_to_drive", "Turnovers per drive", (x) => pc(x, 1)]];

  function unitTable(offT, defT, so, sd, L) {
    const tag = (rk) => (rk ? '<span class="rk">' + ordinal(rk) + "</span>" : "");
    return '<div class="table-box"><table><thead><tr><th class="l">' + esc(offT.short) + " with the ball</th><th>" + esc(offT.short) + " offense</th><th>" +
      esc(defT.short) + " defense allows</th><th>" + LG.short + " average</th></tr></thead><tbody>" +
      UNIT_ROWS.map(([o, d, label, f]) => "<tr><td class='l'>" + label + "</td><td>" + f(so[o]) + tag(so[o + "_rk"]) + "</td><td>" + f(sd[d]) + tag(sd[d + "_rk"]) +
        "</td><td>" + f((L[o] || {}).mean) + "</td></tr>").join("") + "</tbody></table></div>";
  }

  /* Plain-language edges for one side of the ball. o = how good the offense is at something,
     d = how much the defense gives it up (both z-scores vs. the league, oriented so positive
     helps the offense). The sentence names whichever side actually drives the edge. */
  function edges(offT, defT, so, sd, L) {
    const z = (k, v) => (v == null || !L[k] || !L[k].sd ? 0 : (v - L[k].mean) / L[k].sd);
    const O = esc(offT.short), Df = esc(defT.short);
    const V = (one, many) => (LG.nfl ? many : one);
    const items = [
      { o: z("rush_success", so.rush_success), d: z("d_rush_success", sd.d_rush_success),
        good: () => "Run game: " + O + " " + V("stays", "stay") + " on schedule on " + pc(so.rush_success) + " of runs (" + ordinal(so.rush_success_rk) + ", " + n1(so.rush_ypc) + " a carry) and " + Df + " " + V("allows", "allow") + " " + pc(sd.d_rush_success) + " (" + ordinal(sd.d_rush_success_rk) + ").",
        defStrong: () => Df + " " + V("stuffs", "stuff") + " the run: opponents succeed on " + pc(sd.d_rush_success) + " of runs (" + ordinal(sd.d_rush_success_rk) + "), " + n1(sd.d_rush_ypc) + " a carry.",
        offWeak: () => poss(O) + " run game has struggled: " + pc(so.rush_success) + " success (" + ordinal(so.rush_success_rk) + "), " + n1(so.rush_ypc) + " a carry." },
      { o: z("pass_ypa", so.pass_ypa), d: z("d_pass_ypa", sd.d_pass_ypa),
        good: () => "Passing game: " + O + " " + V("averages", "average") + " " + n1(so.pass_ypa) + " yards per dropback (" + ordinal(so.pass_ypa_rk) + ") and " + Df + " " + V("allows", "allow") + " " + n1(sd.d_pass_ypa) + " (" + ordinal(sd.d_pass_ypa_rk) + ").",
        defStrong: () => poss(Df) + " pass defense allows just " + n1(sd.d_pass_ypa) + " yards per dropback (" + ordinal(sd.d_pass_ypa_rk) + ").",
        offWeak: () => poss(O) + " passing game has sputtered: " + n1(so.pass_ypa) + " yards per dropback (" + ordinal(so.pass_ypa_rk) + ")." },
      { o: z("explosive", so.explosive), d: z("d_explosive", sd.d_explosive),
        good: () => "Big plays: " + pc(so.explosive) + " of " + poss(O) + " snaps go for 12+ on the ground or 16+ through the air (" + ordinal(so.explosive_rk) + "); " + Df + " " + V("allows", "allow") + " " + pc(sd.d_explosive) + ".",
        defStrong: () => Df + " " + V("rarely gives up", "rarely give up") + " big plays (" + pc(sd.d_explosive) + " of snaps, " + ordinal(sd.d_explosive_rk) + ").",
        offWeak: () => O + " " + V("doesn't", "don't") + " generate many big plays (" + pc(so.explosive) + " of snaps, " + ordinal(so.explosive_rk) + ")." },
      { o: z("third_conv", so.third_conv), d: z("d_third_conv", sd.d_third_conv),
        good: () => "Third downs: " + O + " " + V("converts", "convert") + " " + pc(so.third_conv) + " (" + ordinal(so.third_conv_rk) + ") and " + Df + " " + V("allows", "allow") + " " + pc(sd.d_third_conv) + " (" + ordinal(sd.d_third_conv_rk) + ").",
        defStrong: () => Df + " " + V("gets", "get") + " off the field on third down: opponents convert " + pc(sd.d_third_conv) + " (" + ordinal(sd.d_third_conv_rk) + ").",
        offWeak: () => O + " " + V("has struggled", "have struggled") + " on third down: " + pc(so.third_conv) + " conversions (" + ordinal(so.third_conv_rk) + ")." },
      { o: -z("sack_rate", so.sack_rate), d: -z("d_sack_rate", sd.d_sack_rate),
        good: () => "Protection: " + O + " " + V("gives up", "give up") + " a sack on just " + pc(so.sack_rate, 1) + " of dropbacks (" + ordinal(so.sack_rate_rk) + ") and " + poss(Df) + " pass rush is quiet (" + pc(sd.d_sack_rate, 1) + ", " + ordinal(sd.d_sack_rate_rk) + ").",
        defStrong: () => "Pass rush: " + Df + " " + V("sacks", "sack") + " the quarterback on " + pc(sd.d_sack_rate, 1) + " of dropbacks (" + ordinal(sd.d_sack_rate_rk) + ").",
        offWeak: () => poss(O) + " line has leaked sacks: " + pc(so.sack_rate, 1) + " of dropbacks (" + ordinal(so.sack_rate_rk) + ")." },
      { o: -z("to_drive", so.to_drive), d: -z("d_to_drive", sd.d_to_drive),
        good: () => "Ball security: " + O + " " + V("turns", "turn") + " it over on " + pc(so.to_drive, 1) + " of drives (" + ordinal(so.to_drive_rk) + ") and " + Df + " " + V("forces", "force") + " few (" + pc(sd.d_to_drive, 1) + ", " + ordinal(sd.d_to_drive_rk) + ").",
        defStrong: () => "Takeaways: " + Df + " " + V("forces", "force") + " a turnover on " + pc(sd.d_to_drive, 1) + " of drives (" + ordinal(sd.d_to_drive_rk) + ").",
        offWeak: () => O + " " + V("has been", "have been") + " loose with the ball: a turnover on " + pc(so.to_drive, 1) + " of drives (" + ordinal(so.to_drive_rk) + ")." },
      { o: z("rz_td", so.rz_td), d: z("d_rz_td", sd.d_rz_td),
        good: () => "Red zone: " + O + " " + V("scores", "score") + " touchdowns on " + pc(so.rz_td) + " of trips inside the 20 (" + ordinal(so.rz_td_rk) + ") and " + Df + " " + V("allows", "allow") + " " + pc(sd.d_rz_td) + " (" + ordinal(sd.d_rz_td_rk) + ").",
        defStrong: () => Df + " " + V("stiffens", "stiffen") + " in the red zone: touchdowns on " + pc(sd.d_rz_td) + " of opponents' trips (" + ordinal(sd.d_rz_td_rk) + ").",
        offWeak: () => O + " " + V("settles", "settle") + " for field goals: touchdowns on " + pc(so.rz_td) + " of red-zone trips (" + ordinal(so.rz_td_rk) + ")." },
    ];
    return rankEdges(items);
  }

  function rankEdges(items) {
    items.forEach((i) => (i.s = (i.o + i.d) / 2));
    const ok = items.filter((i) => isFinite(i.s)).sort((a, b) => b.s - a.s);
    return {
      pros: ok.filter((i) => i.s > 0.35 && i.o > 0 && i.d > -0.3).slice(0, 2).map((i) => i.good()),
      cons: ok.slice().reverse().filter((i) => i.s < -0.35).slice(0, 2).map((i) => (i.d <= i.o ? i.defStrong() : i.offWeak())),
    };
  }

  function tendencies(s, L) {
    const z = (k) => (s[k] == null || !L[k] ? 0 : (s[k] - L[k].mean) / L[k].sd);
    const out = [];
    if (z("pass_rate") > 1) out.push("Pass-first: throws on " + pc(s.pass_rate) + " of plays (" + pc(s.early_pass_rate) + " on early downs).");
    if (z("pass_rate") < -1) out.push("Run-first: runs on " + pc(1 - s.pass_rate) + " of plays.");
    if (z("plays_pg") > 1) out.push("Up-tempo: " + n1(s.plays_pg) + " offensive plays per game.");
    if (z("plays_pg") < -1) out.push("Slows the game down: " + n1(s.plays_pg) + " offensive plays per game.");
    if (z("fourth_go") > 1) out.push("Aggressive on fourth down: goes for it on " + pc(s.fourth_go) + " of 4th downs.");
    if (z("d_sack_rate") > 1) out.push("Gets after the quarterback: sacks on " + pc(s.d_sack_rate, 1) + " of opponents' dropbacks, consistent with frequent pressure or blitzing.");
    if (z("d_explosive") < -1) out.push("Keeps everything in front: allows few explosive plays (" + pc(s.d_explosive) + ").");
    if (z("d_to_drive") > 1) out.push("Opportunistic defense: a takeaway on " + pc(s.d_to_drive, 1) + " of drives.");
    return out;
  }

  async function matchupPage(main, away, home, neutral, game) {
    const A = teamById[away], H = teamById[home];
    if (!A || !H) { main.innerHTML = '<p class="lede">That matchup isn’t available. <a href="#games">Back to games</a></p>'; return; }
    const p = predict(home, away, neutral);
    const m = D.meta.model, idx = {};
    m.ids.forEach((id, i) => (idx[id] = i));
    const hi = idx[home], ai = idx[away], hf = neutral ? 0 : 1, sd = D.meta.sd;
    const spread = p.home_score - p.away_score, fav = spread >= 0 ? H : A, favWin = spread >= 0 ? p.home_win : 1 - p.home_win;
    const when = game && game.start ? new Date(game.start) : null;
    const whenTxt = when && !isNaN(when) ? when.toLocaleString(undefined, { weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    const lo80 = spread - 1.2816 * sd, hi80 = spread + 1.2816 * sd;
    const rng = (v) => (v >= 0 ? esc(H.short) + " by " + Math.abs(v).toFixed(0) : esc(A.short) + " by " + Math.abs(v).toFixed(0));
    const row = (label, a, b, f, ra, rb) => { const tag = (r) => (r ? '<span class="rk">' + ordinal(r) + "</span>" : ""); const w = ra && rb ? (ra < rb ? 0 : rb < ra ? 1 : -1) : -1;
      return "<tr><td class='l'>" + label + "</td><td" + (w === 0 ? " class='lead'" : "") + ">" + f(a) + tag(ra) + "</td><td" + (w === 1 ? " class='lead'" : "") + ">" + f(b) + tag(rb) + "</td></tr>"; };
    main.innerHTML = '<div><p class="note" style="margin:0"><a href="#games">← Games</a></p><h1>' + esc(A.short) + (neutral ? " vs. " : " at ") + esc(H.short) + "</h1>" +
      '<p class="lede">' + esc(whenTxt) + (neutral ? " · neutral site" : "") + (game && game.note ? " · " + esc(game.note) : "") + "</p></div>" +
      '<section class="belief"><h2>Prediction</h2><dl class="kv"><div><dt>' + esc(A.short) + "</dt><dd>" + f1(p.away_score) + "</dd></div><div><dt>" + esc(H.short) + "</dt><dd>" + f1(p.home_score) +
      "</dd></div><div><dt>Spread</dt><dd>" + esc(fav.abbr || fav.short) + " −" + Math.abs(spread).toFixed(1) + "</dd></div><div><dt>Win chance</dt><dd>" + esc(fav.abbr || fav.short) + " " + pct(favWin) + "</dd></div></dl>" +
      '<p class="lede">The model expects ' + esc(fav.short) + " to win by about " + Math.abs(spread).toFixed(1) + ". Football margins are noisy: games miss the projection by about " + Math.round(sd) +
      " points on average, so eight times out of ten the final margin should land between " + rng(lo80) + " and " + rng(hi80) + ". The shaded areas are each team's win chance.</p>" +
      marginChart(spread, sd, H.short, A.short) +
      '<p class="legend"><span class="key prior"></span>' + esc(A.short) + " wins " + pct(1 - p.home_win) + ' <span class="key post"></span>' + esc(H.short) + " wins " + pct(p.home_win) + "</p>" +
      '<details class="how"><summary>How the prediction is built</summary><div class="table-box"><table><tbody>' +
      "<tr><td class='l'>" + esc(H.short) + ": average score " + D.meta.mu + " + its offense " + sgn(m.O[hi]) + " + " + esc(A.short) + "’s defense " + sgn(m.D[ai]) + (hf ? " + half of home field " + sgn(D.meta.hfa / 2) : "") + "</td><td>" + p.home_score.toFixed(1) + "</td></tr>" +
      "<tr><td class='l'>" + esc(A.short) + ": average score " + D.meta.mu + " + its offense " + sgn(m.O[ai]) + " + " + esc(H.short) + "’s defense " + sgn(m.D[hi]) + (hf ? " − half of home field " + sgn(D.meta.hfa / 2) : "") + "</td><td>" + p.away_score.toFixed(1) + "</td></tr>" +
      "</tbody></table></div></details></section>" +
      "<h2>Team comparison</h2><div class='table-box'><table><thead><tr><th class='l'></th><th>" + esc(A.short) + "</th><th>" + esc(H.short) + "</th></tr></thead><tbody>" +
      row("Record", A.w + "-" + A.l, H.w + "-" + H.l, (x) => x) + row("Net rating (rank)", A.net, H.net, (x) => sgn(x), A.rank, H.rank) +
      row("Offense, points vs. average defense", A.o, H.o, f1, A.o_rank, H.o_rank) + row("Defense, points allowed vs. average offense", A.d, H.d, f1, A.d_rank, H.d_rank) +
      row("Preseason rating", A.pre, H.pre, (x) => (x == null ? "–" : sgn(x))) + "</tbody></table></div><div id='m-stats'><p class='lede'>Loading season stats…</p></div>";

    const S = await loadStats();
    const box = $("#m-stats");
    if (!box) return;
    if (!S || !S.teams[away] || !S.teams[home]) { box.innerHTML = '<p class="lede">Season stat profiles aren’t available for this matchup yet.</p>'; return; }
    const L = S.league, sa = S.teams[away], sh = S.teams[home];
    const eA = edges(A, H, sa, sh, L), eH = edges(H, A, sh, sa, L), tA = tendencies(sa, L), tH = tendencies(sh, L);
    const sideCard = (T, e) => '<div class="card"><h3>' + esc(T.short) + " on offense</h3>" +
      (e.pros.length ? "<p><b>Where it can attack</b></p><ul>" + e.pros.map((x) => "<li>" + x + "</li>").join("") + "</ul>" : "") +
      (e.cons.length ? "<p><b>What could slow it down</b></p><ul>" + e.cons.map((x) => "<li>" + x + "</li>").join("") + "</ul>" : "") +
      (e.pros.length + e.cons.length ? "" : "<p>No clear edges either way.</p>") + "</div>";
    const tendCard = (T, t) => '<div class="card"><h3>' + esc(T.short) + "</h3>" + (t.length ? "<ul>" + t.map((x) => "<li>" + x + "</li>").join("") + "</ul>" : "<p>No strong tendencies stand out.</p>") + "</div>";
    box.innerHTML = "<h2>When " + esc(A.short) + (LG.nfl ? " have" : " has") + " the ball</h2>" + unitTable(A, H, sa, sh, L) +
      "<h2>When " + esc(H.short) + (LG.nfl ? " have" : " has") + " the ball</h2>" + unitTable(H, A, sh, sa, L) +
      "<h2>Scouting report</h2><p class='note'>Season averages from " + sa.games + " and " + sh.games + " games, not adjusted for opponents. A play is a success if it gains half the needed yards on 1st down, 70% on 2nd, or all of them on 3rd or 4th.</p>" +
      '<div class="grid">' + sideCard(A, eA) + sideCard(H, eH) + "</div>" +
      "<h3>Likely tendencies</h3><p class='note'>Inferred from the stats, not observed.</p><div class='grid'>" + tendCard(A, tA) + tendCard(H, tH) + "</div>";
  }

  async function gamePage(main, id) {
    const g = D.games.find((x) => x.id === id);
    if (!g) { main.innerHTML = '<p class="lede">That game isn’t on the schedule anymore. It may have been played already. <a href="#games">Back to games</a></p>'; return; }
    return matchupPage(main, g.away, g.home, !!g.neutral, g);
  }

  function route() {
    const h = location.hash.slice(1) || "rankings";
    const view = (h.startsWith("game-") || h.startsWith("vs-")) ? "games" : VIEWS.includes(h) ? h : "rankings";
    document.querySelectorAll(".tabs a").forEach((a) => {
      if (a.getAttribute("href") === "#" + view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    if (h.startsWith("game-")) gamePage($("#main"), h.slice(5));
    else if (h.startsWith("vs-")) { const [a, b, n] = h.slice(3).split("-"); matchupPage($("#main"), a, b, n === "n", null); }
    else ({ rankings, games, matchup, playoff, method })[view]($("#main"));
    window.scrollTo(0, 0);
  }

  load().catch((e) => {
    $("#main").innerHTML = '<p class="lede">The ratings files didn’t load (' + esc(e.message) + "). The first football update may not have run yet.</p>";
  });
})();
