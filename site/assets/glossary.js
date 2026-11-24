/* Hover definitions for column headers (desktop). Matches header text, upper-cased, and adds a title attribute. */
(function () {
  const football = /\/(football|nfl)\//.test(location.pathname);
  const unit = football ? "points per game" : "points per 100 possessions";
  const COMMON = {
    "RK": "Rank by net rating.", "W-L": "Wins and losses this season.", "±": "Uncertainty (one standard error) in the net rating. Smaller means the rating is firmer.",
    "NET": "Net rating: how many " + unit + " better than an average team, against an average opponent" + (football ? "." : " on a neutral floor. Offense minus defense."),
    "OFF": "Offense: " + unit + " scored against an average defense.", "DEF": "Defense: " + unit + " allowed against an average offense. Lower is better.",
    "PRE": "Preseason rating: the model's net rating before the season, from last season and this year's roster" + (football ? " (last season's rating)." : "."),
    "RET": "Returning minutes: share of the roster's expected minutes from players who played for this team last year.",
    "TEMPO": "Pace: possessions per game against an average-tempo opponent.",
    "PLAYER": "Player name.", "HT": "Height.", "MPG": "Minutes per game.", "PPG": "Points per game.", "TS%": "True shooting: points per shot attempt, counting threes and free throws.",
    "IMPACT": "Points per 100 possessions this player adds over an average player, offense and defense combined.",
    "PRIOR": "Where the player's rating started this season: last season's rating carried forward, or a box-score estimate for newcomers.",
    "POSS": "Possessions played.", "LINEUP": "The five players on the floor.",
    "SEC/POSS": "Seconds per possession on offense. Lower is faster.", "3PA": "Share of shots that are three-pointers.", "RIM": "Share of shots at the rim (dunks, layups, tips).",
    "AST’D": "Share of made baskets that were assisted.", "TO/100": "Turnovers per 100 possessions.", "FTA/100": "Free-throw attempts per 100 possessions.",
    "OPP 3PA": "Share of opponents' shots that are threes.", "OPP FTA/100": "Opponent free-throw attempts per 100 possessions.", "OPP TO/100": "Opponent turnovers forced per 100 possessions.",
    "SEED": "Projected NCAA tournament seed.", "REGION": "Projected tournament region.", "FIRST WEEKEND": "Projected first-weekend site and distance from campus.",
    "LAST 4": "Record in the last four tournaments, and average points above (+) or below (−) what the ratings expected.",
    "R64": "Chance to reach the Round of 64.", "R32": "Chance to reach the Round of 32.", "SWEET 16": "Chance to reach the Sweet 16.", "ELITE 8": "Chance to reach the Elite Eight.",
    "FINAL 4": "Chance to reach the Final Four.", "FINAL": "Chance to reach the title game.", "CHAMPION": "Chance to win the title.",
    "SALARY": "Current-season salary.", "WINS ADDED (82-GAME PACE)": "Wins above a replacement-level player, scaled to an 82-game season.", "WINS ADDED (PACE)": "Wins above replacement-level players, scaled to an 82-game season.",
    "SURPLUS VALUE": "Value of the wins added minus what the player is paid.", "PAYROLL": "Total current-season salary.", "COST PER WIN": "Payroll divided by wins added.", "NET RATING": "Points per 100 possessions better than average, while on the floor.",
    "MINUTES": "Share of the team's minutes this position group plays.", "ADDS, PER 100": "Points per 100 possessions the group adds over an average player, minutes-weighted.",
    "OFFENSE": "Offensive part of the rating.", "DEFENSE": "Defensive part of the rating.",
    "PTS/DRIVE": "Points scored per drive (not opponent-adjusted).", "ALLOWED": "Points allowed per drive (not opponent-adjusted).",
    "CFP": "College Football Playoff.", "AVG. FINAL RECORD": "Average final record across the simulated seasons.", "WIN CONF.": "Chance to win the conference.", "MAKE CFP": "Chance to make the 12-team Playoff.",
    "BYE": "Chance to earn a first-round bye.", "SEMIS": "Chance to reach the semifinals.", "TITLE GAME": "Chance to reach the title game.",
    "UNIT": "A part of the team: run game, pass game, and so on.", "MEASURE": "The statistic used for that unit.", "CONF. RANK": "Rank among teams in the same conference.", "NATIONAL": "National rank.",
    "VS. CONF.": "Gap to the conference average, in standard deviations of the national spread. Positive is better than the conference.",
    "PLAYERS": "Players on the roster in this group.", "SENIORS": "Seniors (including graduate students), likely to leave.", "AVG LBS": "Average weight, in pounds.",
    "PRODUCTION MEASURE": "How the group's output is measured, with its conference rank.", "TOP PRODUCERS": "The group's three most productive players this season.",
    "PLAYS": "Plays in this situation.", "PASS": "Share of plays that were passes.", "SUCCESS": "Share of plays that gained enough: half the yards to go on 1st down, 70% on 2nd, all of them on 3rd or 4th.",
    "EDGE": "Own success rate plus the opponent's allowed success rate, each against the league average. Positive favors this offense.", "SITUATION": "The down, distance, score or field-position situation.",
    "LEAGUE": "League average.", "GO-FOR-IT RATE ON 4TH DOWN": "How often the offense goes for it instead of punting or kicking.",
    "GAMES": "Games.", "SAID": "The model's average stated confidence in the group.", "HAPPENED": "How often the pick was actually right.", "WEEK OF": "Week beginning.", "RIGHT": "Picks that were right.", "%": "Share right.",
    "CHANCE (HOME)": "The model's chance that the home team wins.", "PREDICTED MARGIN": "Predicted home margin (home minus visitor), in points.", "ACTUAL": "Actual home margin.",
    "PICKS RIGHT": "Games where the team was on the side the model favored and won.", "AVG. RESULT VS. PREDICTION": "Average points better (+) or worse (−) than the model expected, shrunk toward zero for luck.", "SWING": "How much that gap varies game to game.",
    "CORRECT": "Share of games predicted correctly.", "LOG LOSS": "Penalty for confident wrong picks. Lower is better.", "BRIER": "Average squared gap between stated chance and what happened. Lower is better.",
    "FACTOR": "What was tested.", "HOLDS UP?": "Whether the effect held up when tested on games it hadn't seen.", "FINDING": "What the test found.", "GROUP": "Position group.", "RANK": "Rank among conference teams.", "LEADERS": "Highest-impact players in the group.",
  };
  const PATTERN = [[/ WITH THE BALL$/, "How this team performs when it has the ball in this situation."], [/ DEFENSE ALLOWS$| ALLOWS$/, "What this defense allows in the same situation."],
                   [/ OFFENSE$/, "This offense in the same situation."], [/ DEFENSE$/, "This defense in the same situation."], [/ (AVG|AVERAGE)$/, "Average for the group."],
                   [/^VS\. /, "Gap to the group's average."], [/^AT THE .*…$/, "The situation being analyzed."]];
  function tag(root) {
    (root || document).querySelectorAll("th:not([data-tip])").forEach((th) => {
      const key = th.textContent.trim().replace(/\s+/g, " ").toUpperCase();
      let tip = COMMON[key];
      if (!tip) for (const [re, t] of PATTERN) if (re.test(key)) { tip = t; break; }
      th.setAttribute("data-tip", "1");
      if (tip && !th.title) th.title = tip;
    });
  }
  new MutationObserver(() => tag()).observe(document.documentElement, { childList: true, subtree: true });
  tag();
})();
