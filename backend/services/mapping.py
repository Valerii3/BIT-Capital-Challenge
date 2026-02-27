import subprocess
import sys
from pathlib import Path
from typing import Optional


def run_mapping(stock_id: Optional[str] = None) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "assign_event_stocks.py"

    cmd = [sys.executable, str(script)]
    if stock_id:
        cmd.extend(["--stock-id", stock_id])

    subprocess.run(cmd, check=True)
