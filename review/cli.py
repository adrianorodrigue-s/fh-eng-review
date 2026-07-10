"""Ponto de entrada: python -m review --target /caminho/da/engenharia."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .runner import run_review
from .steps import STEPS


def main(argv: list[str] | None = None) -> int:
    keys = [s.key for s in STEPS]
    parser = argparse.ArgumentParser(
        prog="review",
        description="Revisão de código para engenharias de dados (Ruff + Semgrep + Trivy).",
    )
    parser.add_argument("--target", default=".", help="raiz do projeto a revisar")
    parser.add_argument(
        "--project",
        default=os.environ.get("PROJECT_NAME") or None,
        help="nome da engenharia (default: nome da pasta alvo)",
    )
    parser.add_argument(
        "--only", nargs="+", choices=keys, help="roda apenas os passos indicados"
    )
    parser.add_argument(
        "--skip", nargs="+", choices=keys, default=[], help="pula os passos indicados"
    )
    parser.add_argument(
        "--fail-fast", action="store_true", help="interrompe na primeira falha"
    )
    parser.add_argument(
        "--reports-dir", default=None, help="pasta onde salvar os relatórios"
    )
    parser.add_argument(
        "--no-report", action="store_true", help="não salva o relatório JSON"
    )
    parser.add_argument(
        "--ignore-dir",
        action="append",
        help="diretórios a serem ignorados pelas ferramentas (default: ['code_review'])",
    )
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"Alvo não encontrado: {target}", file=sys.stderr)
        return 2

    ignore_dirs = args.ignore_dir if args.ignore_dir is not None else ["code_review"]

    report = run_review(
        target=target,
        project=args.project or target.name,
        only=args.only,
        skip=args.skip,
        fail_fast=args.fail_fast,
        reports_dir=Path(args.reports_dir) if args.reports_dir else None,
        save=not args.no_report,
        ignore_dirs=ignore_dirs,
    )
    return 0 if report["passed"] else 1
