import subprocess
import sys
from pathlib import Path


def run_filter() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "filter_pipeline.py"
    subprocess.run([sys.executable, str(script)], check=True)
