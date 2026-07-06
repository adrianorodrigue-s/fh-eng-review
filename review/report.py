"""Persistência dos relatórios de revisão (JSON lidos pelo dashboard)."""

from __future__ import annotations

import json
from pathlib import Path

from .steps import LIB_DIR

DEFAULT_REPORTS_DIR = LIB_DIR / "reports"


def save_report(report: dict, reports_dir: Path | None = None) -> Path:
    project_dir = (reports_dir or DEFAULT_REPORTS_DIR) / report["project"]
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{report['run_id']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
