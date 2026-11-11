"""Display names for ESPN's conference codes (both sports)."""

NAMES = {
    "acc": "ACC", "aeast": "America East", "american": "American", "asun": "ASUN", "atl10": "Atlantic 10",
    "belt": "Sun Belt", "big10": "Big Ten", "big12": "Big 12", "bige": "Big East", "bigw": "Big West",
    "bsky": "Big Sky", "bsou": "Big South", "caa": "CAA", "col": "CAA", "hor": "Horizon", "ind": "Independent",
    "indaa": "Independent", "ivy": "Ivy League", "land": "Southland", "maac": "MAAC", "metro": "MAAC",
    "meac": "MEAC", "midam": "MAC", "mvc": "Missouri Valley", "mvfc": "Missouri Valley", "mwest": "Mountain West",
    "neast": "NEC", "ovc": "OVC", "pac12": "Pac-12", "pat": "Patriot", "pfl": "Pioneer", "sec": "SEC",
    "south": "SoCon", "summ": "Summit", "swac": "SWAC", "uac": "UAC", "usa": "Conference USA", "wac": "WAC",
    "wcc": "WCC",
}


def name(code) -> str:
    if not isinstance(code, str) or not code:
        return ""
    return NAMES.get(code.strip().lower(), code)
