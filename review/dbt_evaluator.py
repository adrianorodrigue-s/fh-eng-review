"""dbt Project Evaluator local — sem BigQuery, sem o pacote dbt-labs.

Lê `target/manifest.json` (gerado por `dbt parse`, ver `_dbt_evaluator_cmd`
em steps.py) e roda 4 checks estruturais:
  1. model sem teste de unicidade (`unique` ou `unique_combination_of_columns`)
  2. model/coluna sem description (e model sem nenhuma coluna declarada)
  3. model órfão: tabela hardcoded (`` `projeto.dataset.tabela` ``) em vez de
     ref()/source() no raw_code
  4. model Gold que depende de source diretamente, sem passar por um model
     Silver

Roda como script standalone (sem importar `review.steps`, de propósito —
mesmo cwd trocado pelo build_cmd, dá pra testar os checks isolados sem
subprocess): `python dbt_evaluator.py <dbt_project_dir>`. Imprime só a lista
de achados em JSON no stdout, no schema usado por `_finding()` em
review/steps.py (as duas cópias do dict precisam ficar em sincronia).

Aceite explícito de achados: se `.dbt-evaluator-accept.yml` existir na raiz
do projeto dbt (não no fh-eng-review), achados cujo (check, model) constem
lá são marcados com `accepted: true` (continuam na saída, não somem) e não
contam pro exit code — ver `_load_accepted`/`_apply_accepted`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

Finding = dict

_UNIQUE_TEST_NAMES = {"unique", "unique_combination_of_columns"}

# literal `projeto.dataset.tabela` entre crases — usado só em linhas que não
# são comentário SQL (senão pega falso positivo em valores tipo R$1.117.217,65
# escritos em comentário, já visto testando contra o fricarne).
_HARDCODED_TABLE_RE = re.compile(r"`[a-zA-Z0-9_-]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+`")

_ACCEPT_FILENAME = ".dbt-evaluator-accept.yml"


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


def _models(manifest: dict) -> dict[str, dict]:
    return {
        uid: n for uid, n in manifest.get("nodes", {}).items() if n.get("resource_type") == "model"
    }


def _tests(manifest: dict) -> dict[str, dict]:
    return {
        uid: n for uid, n in manifest.get("nodes", {}).items() if n.get("resource_type") == "test"
    }


def check_missing_uniqueness_test(manifest: dict) -> list[Finding]:
    tested_models: set[str] = set()
    for test in _tests(manifest).values():
        name = (test.get("test_metadata") or {}).get("name")
        if name in _UNIQUE_TEST_NAMES:
            tested_models.update(test.get("depends_on", {}).get("nodes", []))

    findings = []
    for uid, model in _models(manifest).items():
        if uid in tested_models:
            continue
        name = model.get("name")
        findings.append(
            _finding(
                file=model.get("original_file_path", ""),
                model=name,
                rule="dbt-missing-uniqueness-test",
                severity="WARNING",
                message=f"Model `{name}` não tem teste `unique` nem `unique_combination_of_columns`",
                recommendation=(
                    f"Adicione um teste `unique` (se houver PK de coluna única) ou "
                    f"`dbt_utils.unique_combination_of_columns` no schema.yml de `{name}`"
                ),
                url="https://docs.getdbt.com/reference/resource-properties/tests",
            )
        )
    return findings


def check_missing_description(manifest: dict) -> list[Finding]:
    findings = []
    for uid, model in _models(manifest).items():
        name = model.get("name")
        path = model.get("original_file_path", "")

        if not (model.get("description") or "").strip():
            findings.append(
                _finding(
                    file=path,
                    model=name,
                    rule="dbt-missing-description",
                    severity="WARNING",
                    message=f"Model `{name}` não tem description",
                    recommendation=f"Preencha `description` de `{name}` no schema.yml",
                    url="https://docs.getdbt.com/reference/resource-properties/description",
                )
            )

        columns = model.get("columns") or {}
        if not columns:
            findings.append(
                _finding(
                    file=path,
                    model=name,
                    rule="dbt-no-columns-declared",
                    severity="WARNING",
                    message=f"Model `{name}` não tem nenhuma coluna declarada no schema.yml",
                    recommendation=(
                        f"Declare as colunas de `{name}` no schema.yml (mesmo sem description "
                        "ainda) — sem isso não dá nem pra detectar coluna sem documentação"
                    ),
                    url="https://docs.getdbt.com/reference/resource-properties/columns",
                )
            )
            continue

        for col_name, col in columns.items():
            if not (col.get("description") or "").strip():
                findings.append(
                    _finding(
                        file=path,
                        model=name,
                        rule="dbt-missing-description",
                        severity="WARNING",
                        message=f"Coluna `{col_name}` de `{name}` não tem description",
                        recommendation=(
                            f"Preencha `description` da coluna `{col_name}` em `{name}` no schema.yml"
                        ),
                        url="https://docs.getdbt.com/reference/resource-properties/description",
                    )
                )
    return findings


def check_orphan_hardcoded_table(manifest: dict) -> list[Finding]:
    findings = []
    for uid, model in _models(manifest).items():
        raw = model.get("raw_code") or model.get("raw_sql") or ""
        matches: list[str] = []
        for line in raw.splitlines():
            if line.strip().startswith("--"):
                continue
            matches.extend(_HARDCODED_TABLE_RE.findall(line))
        if not matches:
            continue
        name = model.get("name")
        uniq_matches = sorted(set(matches))
        findings.append(
            _finding(
                file=model.get("original_file_path", ""),
                model=name,
                rule="dbt-orphan-hardcoded-table",
                severity="ERROR",
                message=f"Model `{name}` referencia tabela hardcoded ({uniq_matches[0]}) em vez de ref()/source()",
                detail=", ".join(uniq_matches),
                recommendation=(
                    f"Substitua a referência literal em `{name}` por `{{{{ ref(...) }}}}` ou "
                    "`{{ source(...) }}`, conforme o caso"
                ),
                url="https://docs.getdbt.com/reference/dbt-jinja-functions/ref",
            )
        )
    return findings


def check_gold_skips_silver(
    manifest: dict, gold_segment: str = "gold", silver_segment: str = "silver"
) -> list[Finding]:
    models = _models(manifest)
    findings = []
    for uid, model in models.items():
        fqn = model.get("fqn") or []
        if gold_segment not in fqn:
            continue

        deps = model.get("depends_on", {}).get("nodes", [])
        source_deps = [d for d in deps if d.startswith("source.")]
        silver_deps = [
            d
            for d in deps
            if d.startswith("model.") and silver_segment in (models.get(d, {}).get("fqn") or [])
        ]
        if not source_deps or silver_deps:
            continue

        name = model.get("name")
        findings.append(
            _finding(
                file=model.get("original_file_path", ""),
                model=name,
                rule="dbt-gold-skips-silver",
                severity="WARNING",
                message=(
                    f"Model Gold `{name}` depende diretamente de source ({source_deps[0]}) "
                    "sem passar por nenhum model Silver"
                ),
                detail=", ".join(source_deps),
                recommendation=(
                    f"Crie ou reaproveite um model Silver que faça o ref()/source() da tabela "
                    f"bruta, e faça `{name}` depender do Silver em vez da source diretamente"
                ),
            )
        )
    return findings


def _short_rule(rule: str) -> str:
    """`dbt-missing-uniqueness-test` -> `missing-uniqueness-test`, o nome
    curto usado em `.dbt-evaluator-accept.yml` (evita repetir o prefixo
    `dbt-` em toda linha do arquivo de aceite)."""
    return rule.removeprefix("dbt-")


def _load_accepted(dbt_project_dir: Path) -> dict[tuple[str, str], str]:
    """Lê `.dbt-evaluator-accept.yml` da raiz do projeto dbt (se existir) —
    formato:
        accepted:
          - check: missing-uniqueness-test
            model: fct_vendas_unificado
            reason: "..."
    Retorna {(check, model): reason}. Ausente ou malformado => {} (fail
    closed: um erro no arquivo de aceite nunca esconde achado — na dúvida,
    o achado continua contando pro exit code)."""
    path = dbt_project_dir / _ACCEPT_FILENAME
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = data.get("accepted") or []
        return {(str(e["check"]), str(e["model"])): str(e.get("reason", "")) for e in entries}
    except (yaml.YAMLError, AttributeError, KeyError, TypeError) as exc:
        print(f"aviso: {path} malformado, ignorando aceites ({exc})", file=sys.stderr)
        return {}


def _apply_accepted(findings: list[Finding], accepted: dict[tuple[str, str], str]) -> None:
    """Marca in-place achados cujo (check, model) está na accept-list: ganham
    `accepted: true` + `accepted_reason` e a mensagem prefixada com
    `[ACEITO]` — continuam na saída (visíveis), só deixam de contar pro
    exit code (ver `main`)."""
    for f in findings:
        reason = accepted.get((_short_rule(f.get("rule", "")), f.get("model", "")))
        if reason is None:
            continue
        f["accepted"] = True
        f["accepted_reason"] = reason
        f["message"] = f"[ACEITO] {f.get('message', '')}"


def run_checks(manifest: dict) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_missing_uniqueness_test(manifest))
    findings.extend(check_missing_description(manifest))
    findings.extend(check_orphan_hardcoded_table(manifest))
    findings.extend(check_gold_skips_silver(manifest))
    return findings


def main(argv: list[str]) -> int:
    if not argv:
        print("uso: dbt_evaluator.py <dbt_project_dir>", file=sys.stderr)
        return 2

    project_dir = Path(argv[0])
    manifest_path = project_dir / "target" / "manifest.json"
    if not manifest_path.is_file():
        print(f"manifest não encontrado: {manifest_path}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    findings = run_checks(manifest)
    _apply_accepted(findings, _load_accepted(project_dir))
    print(json.dumps(findings))
    # exit 1 se sobrar achado não-aceito / 0 se não sobrar nenhum — mesma
    # convenção de sqlfluff/yamllint (ok_codes={0} em Step, steps.py), só que
    # achados aceitos explicitamente (accepted: true) não contam pro FAIL.
    unaccepted = [f for f in findings if not f.get("accepted")]
    return 1 if unaccepted else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
