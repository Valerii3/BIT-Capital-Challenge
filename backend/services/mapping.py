import subprocess
import sys
from pathlib import Path
from typing import Optional


def _script_path(script_name: str) -> Path:
    """Resolve backend/scripts/<script_name> relative to this file."""
    script = Path(__file__).resolve().parent.parent / "scripts" / script_name
    if not script.exists():
        raise RuntimeError(f"Could not find scripts/{script_name}")
    return script


def run_mapping(stock_id: Optional[str] = None) -> None:
    script = _script_path("assign_event_stocks.py")

    cmd = [sys.executable, str(script)]
    if stock_id:
        cmd.extend(["--stock-id", stock_id])

    subprocess.run(cmd, check=True)
