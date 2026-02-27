import subprocess
import sys
from pathlib import Path


def _resolve_script(script_name: str) -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "scripts" / script_name,
        here.parents[1] / "scripts" / script_name,
        here.parents[3] / "scripts" / script_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        f"Could not find scripts/{script_name}. Deploy with repo root context or include scripts directory."
    )


def run_filter() -> None:
    script = _resolve_script("filter_pipeline.py")
    subprocess.run([sys.executable, str(script)], check=True)
