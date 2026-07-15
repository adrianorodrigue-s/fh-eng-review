"""Executa os passos da revisão e monta o relatório da execução."""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .report import save_report
from .steps import STEPS, Step

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

_PREVIEW_LIMIT = 20
_SNIPPET_CONTEXT = 4  # linhas de contexto antes/depois da linha do achado


def _enrich_snippets(findings: list[dict], target: Path) -> None:
    """Anexa o trecho de código ao achado quando a ferramenta não o forneceu."""
    cache: dict[str, list[str] | None] = {}
    for f in findings:
        if f.get("snippet") or not f.get("file") or not f.get("line"):
            continue
        file = f["file"]
        if file not in cache:
            path = target / file
            try:
                cache[file] = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                cache[file] = None
        lines = cache[file]
        if not lines:
            continue
        line = f["line"]
        start = max(1, line - _SNIPPET_CONTEXT)
        end = min(len(lines), (f.get("end_line") or line) + _SNIPPET_CONTEXT)
        f["snippet"] = "\n".join(lines[start - 1 : end])
        f["snippet_start"] = start


def _banner(text: str) -> None:
    line = "=" * 60
    print(f"\n{BOLD}{line}\n{text}\n{line}{RESET}")


def _print_findings(findings: list[dict]) -> None:
    for f in findings[:_PREVIEW_LIMIT]:
        loc = f["file"] + (f":{f['line']}" if f.get("line") else "")
        print(f"  {f['severity']:<9} {f['rule']:<20} {loc}")
        if f.get("message"):
            print(f"            {f['message'][:110]}")
    if len(findings) > _PREVIEW_LIMIT:
        rest = len(findings) - _PREVIEW_LIMIT
        print(f"  ... e mais {rest} achado(s) — veja os detalhes no dashboard")


def _run_step(step: Step, target: Path, ignore_dirs: list[str] | None = None) -> dict:
    _banner(step.title)
    cmd = step.build_cmd(target, ignore_dirs)

    result = {
        "key": step.key,
        "title": step.title,
        "status": "OK",
        "duration_s": 0.0,
        "findings": [],
        "error_output": "",
    }

    if shutil.which(cmd[0]) is None:
        if step.optional:
            print(f"{YELLOW}'{cmd[0]}' não instalado — passo ignorado.{RESET}")
            result["status"] = "SKIP"
            return result
        print(
            f"{RED}'{cmd[0]}' não está instalado.{RESET}\n"
            f"Rode dentro do container (não exige instalar nada): ./review.sh"
        )
        result["status"] = "FAIL"
        result["error_output"] = f"ferramenta '{cmd[0]}' não encontrada"
        return result

    start = time.perf_counter()
    # comandos vêm da lista fixa STEPS, nunca de entrada do usuário
    proc = subprocess.run(cmd, cwd=target, capture_output=True, text=True)  # noqa: S603
    result["duration_s"] = round(time.perf_counter() - start, 2)

    result["findings"] = step.parse_findings(proc.stdout, target)
    _enrich_snippets(result["findings"], target)

    if proc.returncode in step.ok_codes:
        print(f"{GREEN}✔ OK{RESET} ({result['duration_s']}s)")
        return result

    result["status"] = "FAIL"
    if result["findings"]:
        print(f"{RED}✘ {len(result['findings'])} achado(s):{RESET}")
        _print_findings(result["findings"])
    else:
        # falhou sem findings estruturados: provavelmente erro da própria ferramenta
        result["error_output"] = (proc.stderr or proc.stdout)[:5000]
        print(f"{RED}✘ Falha na execução (exit {proc.returncode}):{RESET}")
        print(result["error_output"][:1500])
    return result


def run_review(
    target: Path,
    project: str,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    fail_fast: bool = False,
    reports_dir: Path | None = None,
    save: bool = True,
    ignore_dirs: list[str] | None = None,
) -> dict:
    started = datetime.now()
    selected = [s for s in STEPS if (not only or s.key in only) and s.key not in (skip or [])]

    step_results: list[dict] = []
    for step in selected:
        step_results.append(_run_step(step, target, ignore_dirs))
        if step_results[-1]["status"] == "FAIL" and fail_fast:
            break

    passed = all(r["status"] != "FAIL" for r in step_results)
    report = {
        "run_id": started.strftime("%Y-%m-%d_%H-%M-%S"),
        "project": project,
        "target": str(target),
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round((datetime.now() - started).total_seconds(), 2),
        "passed": passed,
        "steps": step_results,
    }

    _banner("RESUMO")
    color = {"OK": GREEN, "FAIL": RED, "SKIP": YELLOW}
    for r in step_results:
        n = len(r["findings"])
        extra = f"{n} achado(s)" if n else ""
        print(
            f"  {r['title']:<45} {color[r['status']]}{r['status']}{RESET}"
            f"  ({r['duration_s']}s) {extra}"
        )

    if save:
        path = save_report(report, reports_dir)
        print(f"\nRelatório salvo em: {path}")

    if passed:
        print(f"\n{GREEN}{BOLD}Todas as validações passaram. Pronto para commit! ✅{RESET}")
    else:
        print(f"\n{RED}{BOLD}Revisão reprovada — corrija os problemas antes de commitar.{RESET}")
    return report
