from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "tournament_predictions.json"
WEB_DATA = ROOT / "web" / "data.js"
DIST_DIR = ROOT / "dist"


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_tournament.py")], check=True, cwd=ROOT)

    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    data["refreshed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    WEB_DATA.write_text(
        "window.__TOURNAMENT_DATA__ = " + json.dumps(data, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    if DIST_DIR.exists():
        (DIST_DIR / "tournament_predictions.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (DIST_DIR / "data.js").write_text(
            "window.__TOURNAMENT_DATA__ = " + json.dumps(data, indent=2, ensure_ascii=False) + ";\n",
            encoding="utf-8",
        )

    print(f"refreshed {OUTPUT}")


if __name__ == "__main__":
    main()
