"""Daily snapshot of the Bracket Matrix (bracketmatrix.com), a consensus of published bracket
projections. The page is saved as-is; parsing happens in the bracket model.

    python -m basketball.bracketmatrix
"""
from __future__ import annotations

from datetime import date

from . import config
from .fetch import session

URL = "http://www.bracketmatrix.com/"
OUT = config.DATA_DIR / "bracketmatrix"


def snapshot() -> None:
    try:
        r = session.get(URL, timeout=60)
        r.raise_for_status()
    except Exception as e:  # never let an outside site break the daily update
        print(f"Bracket Matrix not fetched: {e}")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.html").write_bytes(r.content)
    print(f"Bracket Matrix saved ({len(r.content):,} bytes) on {date.today()}")


if __name__ == "__main__":
    snapshot()
