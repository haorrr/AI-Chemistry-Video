"""Centralized filesystem paths. No other module should hardcode artifact paths."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = BASE_DIR / "artifacts"
SAMPLE_OUTPUTS_DIR = BASE_DIR / "sample_outputs"

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
