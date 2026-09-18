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
import re
import shlex
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pathspec
import yaml

LIB_DIR = Path(__file__).resolve().parent.parent

Finding = dict

# Pastas que nunca fazem sentido escanear em NENHUM projeto dbt — embutido na
# lib pra funcionar sem exigir .yamllint/.sqlfluffignore/--ignore-dir
# configurado no projeto analisado. Fonte única: cli.py usa isso pro default
# de --ignore-dir (ruff/semgrep/trivy/pytest); _yamllint_effective_config e
# _sqlfluff_sql_files usam pra montar o ignore de yamllint/sqlfluff.
UNIVERSAL_IGNORE_DIRS = ["dbt_packages", "target", "logs", ".dbt_venv", "code_review"]
UNIVERSAL_IGNORE_GLOBS = [f"{d}/" for d in UNIVERSAL_IGNORE_DIRS]


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
    build_cmd: Callable[[Path, list[str] | None], list[str]]
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


def _ruff_check_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    cmd = ["ruff", "check", ".", "--output-format", "json", *_ruff_config_args(target)]
    if ignore_dirs:
        for d in ignore_dirs:
            cmd.extend(["--exclude", d])
    return cmd


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


def _ruff_format_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    cmd = ["ruff", "format", "--check", ".", *_ruff_config_args(target)]
    if ignore_dirs:
        for d in ignore_dirs:
            cmd.extend(["--exclude", d])
    return cmd


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


def _pytest_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    _JUNIT.unlink(missing_ok=True)
    cmd = [
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",  # inclui arquivo/linha no XML
        f"--junitxml={_JUNIT}",
        "--ignore-glob=*/dbt_packages/*",
    ]
    if ignore_dirs:
        for d in ignore_dirs:
            cmd.append(f"--ignore={d}")
    return cmd


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


def _semgrep_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    project_rules = target / ".semgrep.yml"
    default_rules = LIB_DIR / "config" / "semgrep-defaults.yml"
    config = project_rules if project_rules.exists() else default_rules
    cmd = [
        "semgrep",
        "scan",
        "--config",
        str(config),
        "--json",
        "--metrics=off",
        "--error",
        "--quiet",
    ]
    if ignore_dirs:
        for d in ignore_dirs:
            cmd.extend(["--exclude", d])
    return cmd


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


def _trivy_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    cmd = [
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
    ]
    if ignore_dirs:
        for d in ignore_dirs:
            cmd.extend(["--skip-dirs", d])
    cmd.append(".")
    return cmd


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


# --- Yamllint -------------------------------------------------------------

_YAMLLINT_PROJECT_NAMES = (".yamllint", ".yamllint.yaml", ".yamllint.yml")
_YAMLLINT_MERGED = Path(os.environ.get("TMPDIR", "/tmp")) / "review-yamllint-merged.yml"  # noqa: S108


def _find_project_yamllint(target: Path) -> Path | None:
    for name in _YAMLLINT_PROJECT_NAMES:
        candidate = target / name
        if candidate.exists():
            return candidate
    return None


def _load_yaml_mapping(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _ignore_lines(value) -> list[str]:
    if isinstance(value, str):
        return [ln for ln in value.splitlines() if ln.strip()]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _merge_yamllint_rules(base: dict, override: dict) -> dict:
    merged = dict(base)
    for rule, val in override.items():
        if isinstance(val, dict) and isinstance(merged.get(rule), dict):
            combined = dict(merged[rule])
            combined.update(val)
            merged[rule] = combined
        else:
            merged[rule] = val
    return merged


def _yamllint_effective_config(target: Path) -> Path:
    """Gera um config efetivo = ignore universal da lib (UNIVERSAL_IGNORE_DIRS)
    + regras/ignore do .yamllint do próprio projeto (se existir) por cima —
    sempre escrito num arquivo temporário e passado via --config-file.

    Não dá pra confiar no `extends:` nativo do yamllint pra fazer esse merge:
    lendo o pacote instalado (yamllint/config.py:extend()), quando o config
    filho estende uma base que tem `ignore`, o valor da BASE substitui o do
    filho inteiro — não concatena. Isso faria o ignore universal da lib
    desaparecer silenciosamente sempre que o projeto alvo já tivesse o seu
    próprio `ignore:` (ex.: fricarne). Por isso o merge é feito aqui, em
    Python, e o resultado final tem `extends: default` apontando só pro
    ruleset embutido do próprio yamllint (esse sim seguro: não define
    `ignore`, então não sofre do mesmo problema).
    """
    lib_conf = _load_yaml_mapping(LIB_DIR / "config" / "yamllint-defaults.yml")
    merged_rules = dict(lib_conf.get("rules") or {})
    merged_ignore = list(UNIVERSAL_IGNORE_GLOBS)

    project_file = _find_project_yamllint(target)
    if project_file is not None:
        project_conf = _load_yaml_mapping(project_file)
        merged_rules = _merge_yamllint_rules(merged_rules, project_conf.get("rules") or {})
        merged_ignore += _ignore_lines(project_conf.get("ignore"))

    merged = {
        "extends": "default",
        "rules": merged_rules,
        "ignore": "\n".join(dict.fromkeys(merged_ignore)),
    }
    _YAMLLINT_MERGED.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    return _YAMLLINT_MERGED


def _yamllint_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    # yamllint não tem flag de exclusão de diretório (diferente das outras
    # etapas, que usam --exclude/--ignore/--skip-dirs) — quem ignora
    # diretório é a chave `ignore:` do config, por isso o merge acontece na
    # geração do config efetivo (_yamllint_effective_config), não aqui.
    # --strict: sem isso, warnings sozinhos não derrubam o exit code (só
    # erros), o que quebraria a regra "qualquer achado reprova" das outras etapas.
    return [
        "yamllint",
        "--format",
        "parsable",
        "--strict",
        "--config-file",
        str(_yamllint_effective_config(target)),
        ".",
    ]


# saída de `yamllint --format parsable`: "<file>:<line>:<col>: [<level>] <desc> (<rule>)"
_YAMLLINT_LINE = re.compile(
    r"^(?P<file>.+):(?P<line>\d+):(?P<col>\d+): \[(?P<level>error|warning)\] (?P<message>.*)$"
)
_YAMLLINT_RULE_SUFFIX = re.compile(r"^(?P<desc>.*) \((?P<rule>[a-z][a-z-]*)\)$")


def _parse_yamllint(stdout: str, target: Path) -> list[Finding]:
    findings = []
    for line in stdout.splitlines():
        m = _YAMLLINT_LINE.match(line)
        if not m:
            continue
        rule_match = _YAMLLINT_RULE_SUFFIX.match(m.group("message"))
        desc, rule = (
            (rule_match.group("desc"), rule_match.group("rule"))
            if rule_match
            else (m.group("message"), "syntax-error")
        )
        findings.append(
            _finding(
                file=_rel(m.group("file").removeprefix("./"), target),
                line=int(m.group("line")),
                rule=rule,
                severity=m.group("level").upper(),
                message=desc,
            )
        )
    return findings


# --- SQLFluff (dbt) --------------------------------------------------------

# Credencial de BigQuery pro templater dbt: nunca fica na imagem nem no repo.
# google.auth.default() (usado pelo `method: oauth` do dbt-bigquery) resolve
# a credencial a partir da env var abaixo, então basta apontá-la pro arquivo
# certo antes de invocar dbt/sqlfluff — o profiles.yml do projeto analisado
# não precisa mudar nada em nenhum dos dois casos abaixo.
#
# Prioridade:
#   1. --keyfile explícito (review.sh monta em /secrets/keyfile.json)
#   2. ADC default do gcloud local — ~/.config/gcloud/application_default_
#      credentials.json do HOST, detectado por review.sh e montado em
#      /secrets/adc-default.json quando existir (arquivo gerado por
#      `gcloud auth application-default login`; convenção padrão do gcloud,
#      não é específica de nenhum projeto — funciona em qualquer máquina que
#      já tenha rodado esse login alguma vez).
#   3. nenhum dos dois: falha com mensagem clara (mesmo comportamento de
#      antes, só que agora cobrindo os dois caminhos).
_SQLFLUFF_KEYFILE_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
_ADC_DEFAULT_PATH = Path("/secrets/adc-default.json")


def _valid_credential_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _sqlfluff_credential_path() -> Path | None:
    explicit = Path(os.environ.get(_SQLFLUFF_KEYFILE_ENV, ""))
    if _valid_credential_file(explicit):
        return explicit
    if _valid_credential_file(_ADC_DEFAULT_PATH):
        return _ADC_DEFAULT_PATH
    return None


def _sqlfluff_error_cmd(message: str) -> list[str]:
    """Comando "falso" que só imprime uma mensagem clara e falha — usado
    quando falta pré-requisito (credencial, dbt_project.yml), pra não deixar
    um stack trace cru do dbt/sqlfluff estourar no dashboard."""
    return ["sh", "-c", f"echo {shlex.quote(message)} >&2; exit 1"]


def _sqlfluff_sql_files(dbt_project_dir: Path) -> list[str]:
    """Lista explícita de .sql (caminhos relativos a dbt_project_dir) pra
    passar como argumento posicional do sqlfluff, no lugar de ".".

    SQLFluff não tem flag de ignore-path customizado (`sqlfluff lint --help`
    só tem `-i/--ignore` pra família de erro — parsing/templating — e
    `--disregard-sqlfluffignores` pra desativar o .sqlfluffignore nativo;
    nada equivalente a um --ignore-path — confirmado na versão instalada).
    Por isso a filtragem é feita aqui, em Python: exclui os universais da lib
    (UNIVERSAL_IGNORE_DIRS) + o que o .sqlfluffignore do próprio projeto
    listar (se existir) — mesmo princípio de merge do yamllint
    (_yamllint_effective_config).
    """
    patterns = list(UNIVERSAL_IGNORE_GLOBS)
    project_ignore = dbt_project_dir / ".sqlfluffignore"
    if project_ignore.exists():
        patterns += [
            ln for ln in project_ignore.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
    spec = pathspec.GitIgnoreSpec.from_lines(patterns)
    files = []
    for p in dbt_project_dir.rglob("*.sql"):
        # .as_posix(): pathspec/gitignore casam por "/", independente do SO
        rel = p.relative_to(dbt_project_dir).as_posix()
        if not spec.match_file(rel):
            files.append(rel)
    return sorted(files)


def _find_dbt_project_dir(target: Path) -> Path | None:
    """Acha a raiz do projeto dbt dentro de `target`: o próprio `target` ou,
    no máximo, um nível de subpasta (ex.: a engenharia é a raiz do repo, mas
    o projeto dbt fica em <target>/<algum_nome>/). Não assume nome de
    projeto — se achar 0 ou mais de 1 candidato, devolve None."""
    if (target / "dbt_project.yml").exists():
        return target
    matches = [d for d in target.iterdir() if d.is_dir() and (d / "dbt_project.yml").exists()]
    return matches[0] if len(matches) == 1 else None


def _sqlfluff_config_args(dbt_project_dir: Path) -> list[str]:
    """Usa o .sqlfluff do próprio projeto se existir; senão, o default da lib.

    Sempre passa --config explícito (não deixa o sqlfluff descobrir sozinho
    a partir do cwd): a descoberta nativa por nesting é o que causa o warning
    "Attempt to set templater to dbt failed... cannot be set in a .sqlfluff
    file in a subdirectory of the current working directory" quando há
    qualquer ambiguidade de onde o cwd "raiz" está — apontar o arquivo direto
    remove essa ambiguidade.
    """
    project_config = dbt_project_dir / ".sqlfluff"
    config = project_config if project_config.exists() else LIB_DIR / "config" / "sqlfluff-defaults.cfg"
    return ["--config", str(config)]


def _sqlfluff_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    # ignore_dirs (--ignore-dir/UNIVERSAL_IGNORE_DIRS) não chega aqui como
    # flag de CLI (SQLFluff não tem uma) — é aplicado via _sqlfluff_sql_files,
    # que já embute UNIVERSAL_IGNORE_DIRS diretamente.
    credential = _sqlfluff_credential_path()
    if credential is None:
        return _sqlfluff_error_cmd(
            "SQLFluff requer credencial do BigQuery: use --keyfile <caminho> ou "
            "rode `gcloud auth application-default login` na máquina host "
            "(detectado automaticamente)"
        )

    dbt_project_dir = _find_dbt_project_dir(target)
    if dbt_project_dir is None:
        return _sqlfluff_error_cmd(
            f"SQLFluff: não encontrei dbt_project.yml em {target} nem em um "
            "subdiretório direto — aponte --target pra raiz do projeto dbt "
            "(ou pra pasta que contém o projeto dbt)"
        )

    sql_files = _sqlfluff_sql_files(dbt_project_dir)
    if not sql_files:
        return _sqlfluff_error_cmd(
            f"SQLFluff: nenhum .sql em {dbt_project_dir} fora dos diretórios "
            "ignorados (UNIVERSAL_IGNORE_DIRS + .sqlfluffignore do projeto)"
        )

    project_dir_q = shlex.quote(str(dbt_project_dir))
    config_args = " ".join(shlex.quote(a) for a in _sqlfluff_config_args(dbt_project_dir))
    files_q = " ".join(shlex.quote(f) for f in sql_files)
    cmd_str = (
        f"cd {project_dir_q} && "
        f"export {_SQLFLUFF_KEYFILE_ENV}={shlex.quote(str(credential))} && "
        # dbt deps escreve logs no stdout; sem isso esse texto fica
        # concatenado ANTES do JSON que o sqlfluff escreve no stdout,
        # quebrando o json.loads em _parse_sqlfluff (que exige stdout
        # inteiro como JSON válido, igual ao _parse_ruff_check).
        f"dbt deps --project-dir {project_dir_q} --profiles-dir {project_dir_q} 1>&2 && "
        f"sqlfluff lint --templater dbt --dialect bigquery --format json {config_args} {files_q}"
    )
    return ["sh", "-c", cmd_str]


def _dbt_evaluator_cmd(target: Path, ignore_dirs: list[str] | None = None) -> list[str]:
    # ignore_dirs não se aplica: os 4 checks rodam sobre o manifest.json
    # inteiro (todos os models declarados no projeto dbt), não sobre uma
    # varredura de arquivos soltos do repo.
    dbt_project_dir = _find_dbt_project_dir(target)
    if dbt_project_dir is None:
        return _sqlfluff_error_cmd(
            f"dbt Project Evaluator: não encontrei dbt_project.yml em {target} nem em um "
            "subdiretório direto — aponte --target pra raiz do projeto dbt "
            "(ou pra pasta que contém o projeto dbt)"
        )

    project_dir_q = shlex.quote(str(dbt_project_dir))
    evaluator_script_q = shlex.quote(str(LIB_DIR / "review" / "dbt_evaluator.py"))
    cmd_str = (
        f"cd {project_dir_q} && "
        # dbt deps é necessário mesmo só pra gerar o manifest via `dbt parse`:
        # se packages.yml lista dependências (dbt_utils/dbt_expectations no
        # fricarne, por ex.) e dbt_packages/ não está instalado, `dbt parse`
        # falha com "Compilation Error: ... found N package(s) ... but only 0
        # installed" antes de sequer tentar escrever manifest.json — testado
        # contra o fricarne removendo dbt_packages/.
        # Ambos os comandos escrevem log no stdout; sem 1>&2 esse texto
        # contamina o JSON que dbt_evaluator.py espera ler puro do stdout —
        # mesmo bug já corrigido no dbt deps da etapa sqlfluff (_sqlfluff_cmd
        # acima).
        f"dbt deps --project-dir {project_dir_q} --profiles-dir {project_dir_q} 1>&2 && "
        f"dbt parse --project-dir {project_dir_q} --profiles-dir {project_dir_q} 1>&2 && "
        # invocado pelo caminho absoluto do arquivo, não `-m review.dbt_evaluator`:
        # aqui o cwd é o projeto dbt alvo, não o repo do fh-eng-review, e não
        # há PYTHONPATH configurado em lugar nenhum (Dockerfile/docker-compose)
        # — `-m review.dbt_evaluator` falharia com ModuleNotFoundError, testado.
        f"python3 {evaluator_script_q} {project_dir_q}"
    )
    return ["sh", "-c", cmd_str]


def _parse_dbt_evaluator(stdout: str, target: Path) -> list[Finding]:
    try:
        items = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return []
    # os caminhos que dbt_evaluator.py devolve são relativos ao dbt_project_dir
    # (original_file_path do manifest), não a `target` — mesmo recálculo já
    # feito em _parse_sqlfluff, pro caso do projeto dbt ficar em <target>/fricarne/.
    dbt_project_dir = _find_dbt_project_dir(target) or target
    findings = []
    for it in items:
        it = dict(it)
        if it.get("file"):
            it["file"] = _rel(str(dbt_project_dir / it["file"]), target)
        findings.append(_finding(**it))
    return findings


def _parse_sqlfluff(stdout: str, target: Path) -> list[Finding]:
    try:
        data = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return []
    # o path que o sqlfluff devolve é relativo ao dbt_project_dir (onde
    # rodou), não a `target` — recalcula pra bater com o resto do dashboard
    # (ex.: quando o projeto dbt fica em <target>/fricarne/).
    dbt_project_dir = _find_dbt_project_dir(target) or target
    findings = []
    for file_result in data:
        abs_file = dbt_project_dir / file_result.get("filepath", "")
        for v in file_result.get("violations", []):
            findings.append(
                _finding(
                    file=_rel(str(abs_file), target),
                    line=v.get("start_line_no"),
                    end_line=v.get("end_line_no"),
                    rule=v.get("code", ""),
                    severity="WARNING" if v.get("warning") else "ERROR",
                    message=v.get("description", ""),
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
    Step("yamllint", "Yamllint — lint de YAML", _yamllint_cmd, _parse_yamllint),
    Step("sqlfluff", "SQLFluff — lint de SQL (dbt)", _sqlfluff_cmd, _parse_sqlfluff),
    Step("dbt-evaluator", "dbt Project Evaluator (local)", _dbt_evaluator_cmd, _parse_dbt_evaluator),
]
