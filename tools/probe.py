"""Save the structure of a few ESPN responses so their formats can be checked before writing parsers.

    python -m tools.probe          (run by the daily job when its 'probe' input is set)

Writes data/probe/<name>.txt: an outline of keys, list lengths, and the first item of each list,
with long strings cut short. No full responses are stored.
"""
from __future__ import annotations

import json
from pathlib import Path

from basketball.fetch import get

OUT = Path(__file__).resolve().parent.parent / "data" / "probe"
NBA = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
NFL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CORE = "https://sports.core.api.espn.com/v2/sports"


def outline(x, depth=0, max_depth=6, width=3):
    pad = "  " * depth
    if depth > max_depth:
        return pad + "...\n"
    if isinstance(x, dict):
        s = ""
        for k, v in list(x.items())[:60]:
            if isinstance(v, (dict, list)):
                s += f"{pad}{k}: {type(v).__name__}{'[' + str(len(v)) + ']' if isinstance(v, list) else ''}\n" + outline(v, depth + 1, max_depth, width)
            else:
                s += f"{pad}{k}: {str(v)[:90]!r}\n"
        return s
    if isinstance(x, list):
        return "".join(outline(v, depth, max_depth, width) + (pad + "--\n") for v in x[:width]) if x else ""
    return pad + repr(x)[:90] + "\n"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sb = get(f"{NBA}/scoreboard", {"dates": "20261109"}) or {}
    ev = (sb.get("events") or [{}])[0].get("id", "401909952")
    nfl_sb = get(f"{NFL}/scoreboard", {"week": 10, "seasontype": 2, "dates": 2026}) or {}
    nfl_ev = (nfl_sb.get("events") or [{}])[0].get("id")
    probes = {
        "nba_scoreboard": sb,
        "nba_summary": get(f"{NBA}/summary", {"event": ev}),
        "nba_core_plays": get(f"{CORE}/basketball/leagues/nba/events/{ev}/competitions/{ev}/plays", {"limit": 10}),
        "nba_teams": get(f"{NBA}/teams"),
        "nba_roster": get(f"{NBA}/teams/1/roster"),
        "nfl_scoreboard": nfl_sb,
        "nfl_summary": get(f"{NFL}/summary", {"event": nfl_ev}) if nfl_ev else None,
        "nfl_teams": get(f"{NFL}/teams"),
    }
    for name, data in probes.items():
        text = outline(data) if data is not None else "NO RESPONSE\n"
        if name.endswith("summary") and isinstance(data, dict):
            # Summaries are big: show top-level keys, then the first plays/drives in detail
            text = "TOP KEYS: " + ", ".join(data.keys()) + "\n"
            bx = data.get("boxscore") or {}
            text += "BOXSCORE KEYS: " + ", ".join(bx.keys()) + "\n"
            for p in (bx.get("players") or [])[:1]:
                for st in (p.get("statistics") or [])[:2]:
                    text += "STAT NAMES: " + json.dumps(st.get("names") or st.get("labels")) + "\n"
                    text += "FIRST ATHLETE: " + json.dumps((st.get("athletes") or [{}])[0])[:600] + "\n"
            plays = data.get("plays") or []
            text += f"PLAYS: {len(plays)}\n"
            subs = [p for p in plays if "sub" in json.dumps(p.get("type", {})).lower() or "enters" in (p.get("text") or "").lower()]
            for p in plays[:3] + subs[:3]:
                text += "PLAY: " + json.dumps(p)[:700] + "\n"
            drives = (data.get("drives") or {}).get("previous") or []
            text += f"DRIVES: {len(drives)}\n"
            for dr in drives[:1]:
                text += "DRIVE: " + json.dumps({k: v for k, v in dr.items() if k != "plays"})[:800] + "\n"
                for p in (dr.get("plays") or [])[:2]:
                    text += "DRIVE PLAY: " + json.dumps(p)[:800] + "\n"
        (OUT / f"{name}.txt").write_text(text[:60000])
        print(f"probe {name}: {len(text)} chars")


if __name__ == "__main__":
    main()
