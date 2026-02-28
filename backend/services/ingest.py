import subprocess
import sys
from pathlib import Path


def _script_path(script_name: str) -> Path:
    """Resolve backend/scripts/<script_name> relative to this file."""
    script = Path(__file__).resolve().parent.parent / "scripts" / script_name
    if not script.exists():
        raise RuntimeError(f"Could not find scripts/{script_name}")
    return script


def run_ingest() -> None:
    script = _script_path("sync_markets.py")
    subprocess.run([sys.executable, str(script)], check=True)
