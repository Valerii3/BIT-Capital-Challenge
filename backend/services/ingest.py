import subprocess
import sys
from pathlib import Path


def run_ingest() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "sync_markets.py"
    subprocess.run([sys.executable, str(script)], check=True)
