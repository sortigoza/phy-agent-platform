import subprocess
from pathlib import Path


def version() -> str:
    """`git describe --tags --always` of the checkout this code runs from."""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()
