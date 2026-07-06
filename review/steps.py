"""Definição dos passos da revisão e parsing das saídas em findings.

Cada passo produz findings normalizados no formato:
    {
        "file": str, "line": int | None, "end_line": int | None,
        "rule": str, "severity": str,
        "message": str,          # resumo curto
        "detail": str,           # descrição longa (quando a ferramenta fornece)
        "recommendation": str,   # como corrigir
        "url": str,              # documentação da regra/CVE
        "snippet": str,          # trecho de código (preenchido pelo runner se vazio)
        "snippet_start": int | None,
    }
que alimentam o console e o dashboard Streamlit.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent

Finding = dict


def _finding(**kwargs) -> Finding:
    base = {
        "file": "",
        "line": None,
        "end_line": None,
        "rule": "",
        "severity": "WARNING",
        "message": "",
        "detail": "",
        "recommendation": "",
        "url": "",
        "snippet": "",
        "snippet_start": None,
    }
    base.update({k: v for k, v in kwargs.items() if v is not None})
    return base


@dataclass
class Step:
    key: str
    title: str
    build_cmd: Callable[[Path], list[str]]
    parse_findings: Callable[[str, Path], list[Finding]]
    # códigos de saída considerados sucesso (pytest devolve 5 quando não há testes)
    ok_codes: set[int] = field(default_factory=lambda: {0})
    optional: bool = False  # se a ferramenta não existir, apenas pula


def _rel(file: str, target: Path) -> str:
    try:
        return str(Path(file).relative_to(target))
    except ValueError:
        return file


# --- Ruff ---------------------------------------------------------------


def _ruff_config_args(target: Path) -> list[str]:
    """Usa a config do próprio projeto se existir; senão, o default da lib."""
    if (target / "ruff.toml").exists() or (target / ".ruff.toml").exists():
        return []
    pyproject = target / "pyproject.toml"
    if pyproject.exists() and "[tool.ruff" in pyproject.read_text(encoding="utf-8"):
        return []
    return ["--config", str(LIB_DIR / "config" / "ruff-defaults.toml")]


def _ruff_check_cmd(target: Path) -> list[str]:
    return ["ruff", "check", ".", "--output-format", "json", *_ruff_config_args(target)]


def _parse_ruff_check(stdout: str, target: Path) -> list[Finding]:
    try:
        items = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return []
    findings = []
    for it in items:
        fix = it.get("fix") or {}
        recommendation = fix.get("message") or ""
        if fix:
            recommendation += " — corrigível automaticamente: `ruff check --fix`"
        findings.append(
            _finding(
                file=_rel(it.get("filename") or "", target),
                line=(it.get("location") or {}).get("row"),
                end_line=(it.get("end_location") or {}).get("row"),
                rule=it.get("code") or "syntax-error",
                severity="ERROR",
                message=it.get("message", ""),
                recommendation=recommendation.strip(" —"),
                url=it.get("url") or "",
            )
        )
    return findings


def _ruff_format_cmd(target: Path) -> list[str]:
    return ["ruff", "format", "--check", ".", *_ruff_config_args(target)]


def _parse_ruff_format(stdout: str, target: Path) -> list[Finding]:
    return [
        _finding(
            file=line.split("Would reformat:", 1)[1].strip(),
            rule="FORMAT",
            severity="WARNING",
            message="Arquivo fora do padrão de formatação",
            recommendation=(
                f"Rode `ruff format {line.split('Would reformat:', 1)[1].strip()}` "
                "no projeto para corrigir automaticamente"
            ),
            url="https://docs.astral.sh/ruff/formatter/",
        )
        for line in stdout.splitlines()
        if line.startswith("Would reformat:")
    ]


# --- Pytest -------------------------------------------------------------

_JUNIT = Path(os.environ.get("TMPDIR", "/tmp")) / "review-pytest.xml"  # noqa: S108


def _pytest_cmd(target: Path) -> list[str]:
    _JUNIT.unlink(missing_ok=True)
    return [
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",  # inclui arquivo/linha no XML
        f"--junitxml={_JUNIT}",
    ]


def _parse_pytest(stdout: str, target: Path) -> list[Finding]:
    if not _JUNIT.exists():
        return []
    try:
        # XML gerado pelo próprio pytest nesta execução, não é entrada externa
        root = ET.parse(_JUNIT).getroot()  # noqa: S314
    except ET.ParseError:
        return []
    findings = []
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        line = case.get("line")
        for kind in ("failure", "error"):
            for node in case.findall(kind):
                findings.append(
                    _finding(
                        file=case.get("file") or case.get("classname", ""),
                        line=int(line) + 1 if line else None,
                        rule=case.get("name", ""),
                        severity="ERROR",
                        message=(node.get("message") or kind)[:300],
                        detail=(node.text or "")[:3000],
                        recommendation=(
                            f"Reproduza localmente com `pytest {test_id}` e corrija o teste "
                            "ou o código que ele cobre"
                        ),
                    )
                )
    return findings


# --- Semgrep ------------------------------------------------------------


def _semgrep_cmd(target: Path) -> list[str]:
    project_rules = target / ".semgrep.yml"
    default_rules = LIB_DIR / "config" / "semgrep-defaults.yml"
    config = project_rules if project_rules.exists() else default_rules
    return [
        "semgrep",
        "scan",
        "--config",
        str(config),
        "--json",
        "--metrics=off",
        "--error",
        "--quiet",
    ]


def _parse_semgrep(stdout: str, target: Path) -> list[Finding]:
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return []
    findings = []
    for r in data.get("results", []):
        extra = r.get("extra") or {}
        metadata = extra.get("metadata") or {}
        references = metadata.get("references") or []
        start_line = (r.get("start") or {}).get("line")
        if extra.get("fix"):
            recommendation = f"Substitua pelo trecho sugerido: `{extra['fix']}`"
        else:
            recommendation = "Siga a orientação da mensagem da regra"
        findings.append(
            _finding(
                file=r.get("path", ""),
                line=start_line,
                end_line=(r.get("end") or {}).get("line"),
                rule=(r.get("check_id") or "").split(".")[-1],
                severity=extra.get("severity", "WARNING"),
                message=(extra.get("message") or "").strip()[:500],
                recommendation=recommendation,
                url=references[0] if references else "",
                # extra["lines"] vem como "requires login" sem conta semgrep;
                # o runner extrai o snippet direto do arquivo
            )
        )
    return findings


# --- Trivy --------------------------------------------------------------


def _trivy_cmd(target: Path) -> list[str]:
    return [
        "trivy",
        "fs",
        "--scanners",
        "vuln,secret,misconfig",
        "--severity",
        "HIGH,CRITICAL",
        "--exit-code",
        "1",
        "--format",
        "json",
        "--quiet",
        ".",
    ]


def _code_lines(obj: dict) -> tuple[str, int | None]:
    """Extrai o snippet do bloco CauseMetadata/Code que o Trivy devolve."""
    lines = ((obj.get("CauseMetadata") or obj).get("Code") or {}).get("Lines") or []
    if not lines:
        return "", None
    text = "\n".join(ln.get("Content", "") for ln in lines)
    return text, lines[0].get("Number")


def _parse_trivy(stdout: str, target: Path) -> list[Finding]:
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return []
    findings = []
    for res in data.get("Results") or []:
        file = res.get("Target", "")
        for v in res.get("Vulnerabilities") or []:
            pkg = v.get("PkgName", "")
            installed = v.get("InstalledVersion", "")
            fixed = v.get("FixedVersion") or ""
            findings.append(
                _finding(
                    file=file,
                    rule=v.get("VulnerabilityID", ""),
                    severity=v.get("Severity", ""),
                    message=f"{pkg} {installed}: {v.get('Title', '')}"[:300],
                    detail=(v.get("Description") or "")[:1500],
                    recommendation=(
                        f"Atualize `{pkg}` de {installed} para {fixed} "
                        f"(ex.: `poetry update {pkg}` ou fixe a versão no pyproject)"
                        if fixed
                        else f"Sem versão corrigida para `{pkg}` — avalie mitigação ou remoção"
                    ),
                    url=v.get("PrimaryURL") or "",
                )
            )
        for m in res.get("Misconfigurations") or []:
            snippet, snippet_start = _code_lines(m)
            findings.append(
                _finding(
                    file=file,
                    line=(m.get("CauseMetadata") or {}).get("StartLine"),
                    end_line=(m.get("CauseMetadata") or {}).get("EndLine"),
                    rule=m.get("ID", ""),
                    severity=m.get("Severity", ""),
                    message=m.get("Title", "")[:300],
                    detail=(m.get("Description") or "")[:1500],
                    recommendation=m.get("Resolution") or "",
                    url=m.get("PrimaryURL") or "",
                    snippet=snippet,
                    snippet_start=snippet_start,
                )
            )
        for s in res.get("Secrets") or []:
            snippet, snippet_start = _code_lines(s)
            findings.append(
                _finding(
                    file=file,
                    line=s.get("StartLine"),
                    end_line=s.get("EndLine"),
                    rule=s.get("RuleID", ""),
                    severity=s.get("Severity", ""),
                    message=s.get("Title", "")[:300],
                    recommendation=(
                        "Remova o segredo do repositório, rotacione a credencial exposta "
                        "e passe a usar variável de ambiente/gerenciador de segredos"
                    ),
                    snippet=snippet,
                    snippet_start=snippet_start,
                )
            )
    return findings


STEPS = [
    Step("ruff", "Ruff — qualidade de código", _ruff_check_cmd, _parse_ruff_check),
    Step("format", "Ruff — formatação", _ruff_format_cmd, _parse_ruff_format),
    Step(
        "pytest",
        "Pytest — testes unitários",
        _pytest_cmd,
        _parse_pytest,
        ok_codes={0, 5},
        optional=True,
    ),
    Step("semgrep", "Semgrep — segurança do código", _semgrep_cmd, _parse_semgrep),
    Step("trivy", "Trivy — dependências, segredos e infra", _trivy_cmd, _parse_trivy),
]
