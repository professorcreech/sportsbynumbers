/* Record tab, shared by all four sports: how the day-of predictions have done (tools/ledger.py -> data/record.json). */
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const sgn = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
  const cls = (x) => (x > 0.05 ? "pos" : x < -0.05 ? "neg" : "");
  const pc = (x, d = 0) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
  const dateStr = (s) => { const d = new Date(s); return isNaN(d) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" }); };

  window.SBN_record = async function (main, teamById) {
    main.innerHTML = '<p class="lede">Loading the track record…</p>';
    const R = await fetch("data/record.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (!R) { main.innerHTML = "<h1>Track record</h1><p class='lede'>No graded predictions yet. They appear after the first saved games are played.</p>"; return; }
    const name = (id) => (teamById[id] ? teamById[id].short || teamById[id].name : id);
    const tms = Object.entries(R.teams).map(([id, t]) => ({ id, ...t })).filter((t) => teamById[t.id]);
    const min = R.n >= 400 ? 5 : 3;
    const tbl = (rows) => '<div class="table-box"><table class="findings"><thead><tr><th class="l">Team</th><th>Games</th><th>Picks right</th><th>Avg. result vs. prediction</th><th>Swing</th><th>vs. top-' + R.big_top + " teams</th></tr></thead><tbody>" +
      rows.map((t) => "<tr><td class='l'><a href='#team-" + esc(t.id) + "'>" + esc(name(t.id)) + "</a></td><td>" + t.n + "</td><td>" + t.hit + "/" + t.n + "</td><td class='" + cls(t.res) + "'>" + sgn(t.res) +
        (t.se != null ? " <span class='note'>±" + t.se.toFixed(1) + "</span>" : "") + "</td><td>" + (t.sd != null ? t.sd.toFixed(1) : "–") + "</td><td>" + (t.big_n ? sgn(t.big_res) + " <span class='note'>(" + t.big_n + ")</span>" : "–") + "</td></tr>").join("") + "</tbody></table></div>";
    const SORTS = {
      beat: ["Beat the prediction most", (a, b) => b.res - a.res, () => true],
      short: ["Fell short of the prediction most", (a, b) => a.res - b.res, () => true],
      swing: ["Most inconsistent (biggest swings)", (a, b) => (b.sd || 0) - (a.sd || 0), (t) => t.sd != null],
      steady: ["Most consistent", (a, b) => (a.sd || 99) - (b.sd || 99), (t) => t.sd != null],
      big: ["Best against top teams", (a, b) => (b.big_res ?? -99) - (a.big_res ?? -99), (t) => t.big_n >= 2],
      bigw: ["Worst against top teams", (a, b) => (a.big_res ?? 99) - (b.big_res ?? 99), (t) => t.big_n >= 2],
    };

    const P = R.replay;
    let yoy = "";
    if (P && P.same) {
      const a = { n: R.n, hit: R.hit, brier: R.brier, mae: R.mae, market: R.market }, b = P.same, f = P.full;
      const row = (lab, fn, fmt) => "<tr><td class='l'>" + lab + "</td><td>" + fmt(fn(a)) + "</td><td>" + fmt(fn(b)) + "</td><td>" + fmt(fn(f)) + "</td></tr>";
      const rate = (x) => x.hit / x.n;
      const se = Math.sqrt(((a.hit + b.hit) / (a.n + b.n)) * (1 - (a.hit + b.hit) / (a.n + b.n)) * (1 / a.n + 1 / b.n));
      const diff = rate(a) - rate(b);
      const verdict = Math.abs(diff) < 2 * se ? "That gap is within normal game-to-game luck for samples this size (about ±" + Math.round(2 * se * 100) + " points)." :
        "That gap is bigger than luck alone usually explains (about ±" + Math.round(2 * se * 100) + " points).";
      yoy = "<h2>This season vs. last season</h2><p class='lede'>Last season replayed game by game: for each game, the model is refit on only the games before it, starting from the same kind of preseason prior. " +
        "The replay uses past results only, with no rosters, injuries or coaching changes, so differences partly reflect those added inputs. Compare the same dates, because early-season slates are lopsided.</p>" +
        "<div class='table-box'><table class='findings'><thead><tr><th class='l'></th><th>This season<br><span class='note'>" + dateStr(R.first) + " – now</span></th><th>Last season, same dates<br><span class='note'>" + dateStr(P.from + "T12:00") + " – " + dateStr(P.to + "T12:00") + "</span></th><th>Last season, full</th></tr></thead><tbody>" +
        row("Games", (x) => x.n, (v) => v.toLocaleString()) +
        row("Picks right", rate, (v) => pc(v, 1)) +
        row("Brier score", (x) => x.brier, (v) => v.toFixed(3)) +
        row("Avg. miss (points)", (x) => x.mae, (v) => v.toFixed(1)) +
        (R.market && b.market ? row("Model miss minus line’s miss", (x) => (x.market ? x.market.model_mae - x.market.market_mae : null), (v) => (v == null ? "–" : sgn(v))) : "") +
        "</tbody></table></div><p class='note'>On the same dates the hit rate is " + pc(rate(a), 1) + " now against " + pc(rate(b), 1) + " then. " + verdict + " Lower is better for Brier score and for misses.</p>";
    }
    const pickRate = R.hit / R.n, mk = R.market;
    main.innerHTML = "<h1>Track record</h1><p class='lede'>Every prediction is saved before the game starts and graded once the final score is in, so this is the model’s real record, not a re-fit after the fact. " +
      esc(R.name) + " since " + dateStr(R.first) + ": " + R.n + " games graded so far.</p>" +
      '<dl class="kv"><div><dt>Picks right</dt><dd>' + R.hit + "/" + R.n + '<span class="rk">' + pc(pickRate, 1) + "</span></dd></div>" +
      "<div><dt>Favorites ≥70%</dt><dd>" + R.fav_hit + "/" + R.fav_n + '<span class="rk">' + (R.fav_n ? pc(R.fav_hit / R.fav_n, 0) : "–") + "</span></dd></div>" +
      "<div><dt>Avg. miss</dt><dd>" + R.mae.toFixed(1) + '<span class="rk">points</span></dd></div>' +
      "<div><dt>Brier score</dt><dd>" + R.brier.toFixed(3) + '<span class="rk">coin flip ' + R.brier_coin.toFixed(2) + "</span></dd></div></dl>" +
      (mk ? "<p class='lede'>On the " + mk.n + " games that also had a betting line, the model picked " + mk.model_hit + " winners and the line’s favorite picked " + mk.market_hit + "; the average miss was " + mk.model_mae.toFixed(1) + " points for the model and " + mk.market_mae.toFixed(1) + " for the line.</p>" : "") +
      "<p class='note'>Brier score is the average squared gap between the stated chance and what happened (0 is perfect, 0.25 is always saying 50%). The home team won " + pc(R.home_rate) + " of these games, so that is what blind “pick the home team” would score.</p>" +
      yoy + "<h2>Do the percentages mean what they say?</h2><div class='table-box'><table class='findings'><thead><tr><th class='l'>Model’s confidence in its pick</th><th>Games</th><th>Said</th><th>Happened</th></tr></thead><tbody>" +
      R.bins.map((b) => "<tr><td class='l'>" + Math.round(b.lo * 100) + "–" + (b.hi >= 1 ? "100" : Math.round(b.hi * 100)) + "%</td><td>" + b.n + "</td><td>" + pc(b.pred) + "</td><td>" + pc(b.hit) + "</td></tr>").join("") + "</tbody></table></div>" +
      "<p class='note'>If the model is honest, the last two columns match. Small groups wander: with 30 games, 10 points either way is ordinary luck.</p>" +
      "<h2>By week</h2><div class='table-box'><table class='findings'><thead><tr><th class='l'>Week of</th><th>Games</th><th>Right</th><th>%</th></tr></thead><tbody>" +
      R.weekly.slice().reverse().map((w) => "<tr><td class='l'>" + dateStr(w.week + "T12:00") + "</td><td>" + w.n + "</td><td>" + w.hit + "</td><td>" + pc(w.hit / w.n) + "</td></tr>").join("") + "</tbody></table></div>" +
      "<h2>Teams</h2><p class='lede'>“Avg. result vs. prediction” is how many points better (+) or worse (−) the team has finished than the model expected, on average; the ± is its margin of noise. Swing is how much that gap varies game to game. A team needs a lot of games before any of this is more than luck, so lists start at " + min + " games and the ± matters.</p>" +
      '<p><label>Show: <select id="rec-sort">' + Object.entries(SORTS).map(([k, v]) => '<option value="' + k + '">' + v[0] + "</option>").join("") + '</select></label></p><div id="rec-teams"></div>' +
      "<h2>Latest results</h2><div class='table-box'><table class='findings'><thead><tr><th class='l'>Game</th><th>Chance (home)</th><th>Predicted margin</th><th>Actual</th><th></th></tr></thead><tbody>" +
      R.recent.map((g) => "<tr><td class='l'>" + dateStr(g.start) + " · " + esc(g.away) + (g.neutral ? " vs " : " @ ") + esc(g.home) + "</td><td>" + pc(g.p) + "</td><td>" + sgn(g.pred) + "</td><td>" + sgn(g.actual, 0) + "</td><td class='" + (g.hit ? "pos" : "neg") + "'>" + (g.hit ? "✓" : "✗") + "</td></tr>").join("") + "</tbody></table></div>" +
      "<p class='note'>Margins are home team minus visitor. Predictions before " + dateStr(R.first) + " were not saved.</p>";
    const show = () => {
      const [, cmp, ok] = SORTS[$("#rec-sort").value];
      const rows = tms.filter((t) => t.n >= min && ok(t)).sort(cmp).slice(0, 25);
      $("#rec-teams").innerHTML = rows.length ? tbl(rows) : "<p class='note'>Not enough games yet for this view.</p>";
    };
    const $ = (s) => main.querySelector(s);
    $("#rec-sort").addEventListener("change", show);
    show();
  };
})();
