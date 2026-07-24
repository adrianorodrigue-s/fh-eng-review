# 🔍 code_review — revisão de código para engenharias de dados

Ferramenta de revisão **pré-commit**: roda **Ruff** (qualidade), **Semgrep**
(segurança do código), **Trivy** (dependências, segredos e infra), **Yamllint**
(lint de YAML), **SQLFluff** (lint de SQL/dbt) e o **dbt Project Evaluator**
(auditoria de estrutura do projeto dbt) em qualquer engenharia, e mostra tudo
em um **dashboard web** com o trecho de código, a explicação e como corrigir
cada achado.

**Zero-config**: `./review.sh` sem nenhuma flag já funciona em qualquer
projeto — a credencial de BigQuery (necessária só para o SQLFluff, quando o
projeto revisado for um projeto dbt) é detectada automaticamente via ADC do
`gcloud`, sem precisar de `--keyfile`.

A regra é simples: **só commita quando o review passar.** ✅

---

## Pré-requisitos

- **Docker Desktop** instalado e rodando (`docker --version` deve responder).
- Nada mais. Ruff, Semgrep, Trivy, Yamllint, SQLFluff, o dbt Project
  Evaluator e o dashboard rodam dentro de containers — você não instala
  nenhuma ferramenta na sua máquina.
- Opcional, só se o projeto for dbt: uma credencial de BigQuery para o
  SQLFluff (templater dbt). Se você já rodou
  `gcloud auth application-default login` alguma vez nesta máquina, não
  precisa fazer nada — é detectada automaticamente. Senão, use `--keyfile`.

---

## Passo a passo

### 1. Tenha a pasta `code_review/` na engenharia

Se ela já existe no repositório do projeto, pule este passo. Senão, copie a
pasta para dentro da engenharia que você quer revisar:

```
minha-engenharia/
├── code_review/      ← esta pasta
├── pyproject.toml
├── Dockerfile
└── src/ ...
```

### 2. Rode a revisão

```bash
cd minha-engenharia/code_review
./review.sh
```

`./review.sh` **sem nenhuma flag já funciona out-of-the-box** em qualquer
projeto: a credencial de BigQuery que o SQLFluff precisa (só quando o
projeto for dbt) é detectada automaticamente via ADC do gcloud, e pastas
como `dbt_packages/`, `target/`, `logs/`, `.dbt_venv/`, `code_review/` já
vêm ignoradas por padrão, sem configurar nada no projeto. Use
`--keyfile <caminho>` só se quiser apontar uma credencial **específica**
(ex.: outra service account) no lugar da ADC automática.

O que acontece (a primeira execução demora alguns minutos — baixa as imagens
e o banco de vulnerabilidades; as próximas levam segundos):

1. Roda **Ruff → formatação → Pytest → Semgrep → Trivy → Yamllint →
   SQLFluff → dbt Project Evaluator** na engenharia
2. Imprime cada achado no terminal e um resumo no final
3. Salva o relatório em `reports/<engenharia>/<data-hora>.json`
4. **Sobe o dashboard e informa a porta**

Saída esperada:

```
============================================================
RESUMO
============================================================
  Ruff — qualidade de código                    OK    (0.1s)
  Ruff — formatação                             OK    (0.0s)
  Pytest — testes unitários                     OK    (0.3s)
  Semgrep — segurança do código                 OK    (1.5s)
  Trivy — dependências, segredos e infra        FAIL  (0.7s) 15 achado(s)
  Yamllint — lint de YAML                        OK    (0.2s)
  SQLFluff — lint de SQL (dbt)                   OK    (3.1s)
  dbt Project Evaluator (local)                  OK    (0.4s)

Relatório salvo em: /review/reports/minha-engenharia/2026-07-06_14-12-43.json

Revisão reprovada — corrija os problemas antes de commitar.

📊 Dashboard no ar:  http://localhost:3000
   Quando terminar a análise:  ./review.sh down
```

### 3. Abra o dashboard e encontre os erros

Abra **http://localhost:3000** no navegador:

1. Confira o **quality gate** no topo: ✅ APROVADO ou ❌ REPROVADO
2. Clique no **card da etapa** que falhou (borda vermelha) ou na aba dela
3. Use os **chips de severidade** e a **busca** para filtrar
4. **Clique em um achado** para expandir. Cada card mostra:
   - o **trecho do código** com a linha do problema destacada
   - a explicação do problema
   - 🛠️ **Como corrigir** — a ação concreta (ex.: `poetry update urllib3`,
     `ruff check --fix`, remover o segredo e rotacionar a credencial)
   - 📖 link para a documentação da regra ou página do CVE
5. O botão ⧉ ao lado de `arquivo:linha` copia a localização — cole no editor
   ou compartilhe a URL da página (ela guarda engenharia/execução/aba)

### 4. Corrija e rode de novo

```bash
# corrija os arquivos apontados, depois:
./review.sh
```

Clique em **🔄 Atualizar** no dashboard para ver a nova execução. No painel
**Histórico** (Visão geral) dá para ver os achados caindo a cada rodada —
clique em um ponto do gráfico para abrir aquela execução.

Repita até o resumo terminar com:

```
Todas as validações passaram. Pronto para commit! ✅
```

### 5. Commite e encerre

```bash
git add -A && git commit -m "..."
./review.sh down     # derruba dashboard e containers
```

---

## Comandos úteis

| Comando | O que faz |
|---|---|
| `./review.sh` | revisa a engenharia onde a lib está (pasta acima) + sobe o dashboard |
| `./review.sh /caminho/da/engenharia` | revisa qualquer outra engenharia |
| `./review.sh . --only ruff semgrep` | roda só alguns passos (`ruff`, `format`, `pytest`, `semgrep`, `trivy`, `yamllint`, `sqlfluff`, `dbt-evaluator`) |
| `./review.sh . --skip trivy` | pula um passo |
| `./review.sh . --fail-fast` | para na primeira falha |
| `./review.sh dashboard` | sobe só o dashboard (sem rodar revisão) |
| `./review.sh down` | encerra tudo |
| `DASHBOARD_PORT=9000 ./review.sh` | muda a porta do dashboard |

---

## O que cada etapa verifica

| Etapa | Ferramenta | O que verifica | Falha quando |
|---|---|---|---|
| 1 | Ruff | estilo, imports, bugs prováveis, segurança básica, pandas | qualquer violação |
| 2 | Ruff format | formatação consistente | arquivo fora do padrão |
| 3 | Pytest | testes unitários (pulado se não houver testes) | teste falhando |
| 4 | Semgrep | SQL Injection, segredos fixos, `eval`, `shell=True` + regras do time | qualquer achado |
| 5 | Trivy | CVEs em dependências, segredos no repo, misconfig Docker/IaC | HIGH ou CRITICAL |
| 6 | Yamllint | sintaxe/estrutura de YAML (schema.yml do dbt, docker-compose, GitHub Actions etc.) | qualquer erro ou warning (roda com `--strict`) |
| 7 | SQLFluff | estilo/sintaxe de SQL dos models dbt (compila via templater dbt, dialect bigquery) | violação de lint classificada como erro (regras marcadas como warning na config `.sqlfluff` não derrubam o exit code) |
| 8 | dbt Project Evaluator | estrutura do projeto dbt via `manifest.json`: model sem teste de unicidade, model/coluna sem description, tabela hardcoded (sem `ref()`/`source()`), model Gold que pula Silver | achado dos 4 checks não coberto pela accept-list (`.dbt-evaluator-accept.yml`) |

---

## Problemas comuns

**"docker: command not found" ou erro de conexão com o Docker**
→ Instale/abra o Docker Desktop e espere o ícone ficar verde.

**Primeira execução muito lenta**
→ Normal: baixa as imagens e o banco de CVEs do Trivy (~fica em cache num
volume; as próximas execuções do Trivy levam <1s).

**Porta 3000 ocupada**
→ `DASHBOARD_PORT=9000 ./review.sh` e abra `http://localhost:9000`.

**O passo Pytest falha com erro de import**
→ O container da lib não tem as dependências da sua engenharia. Rode a suíte
no ambiente do projeto e aqui use `./review.sh . --skip pytest`.

**"Nenhum relatório encontrado" no dashboard**
→ Rode uma revisão primeiro (`./review.sh`) — o dashboard só lê `reports/`.

**SQLFluff / dbt Project Evaluator não encontram `dbt_project.yml`**
→ Aponte `--target` pra raiz do projeto dbt (ou pra pasta que a contém
diretamente) — a lib procura `dbt_project.yml` só no próprio `--target` ou
em um nível de subpasta abaixo dele. Se a engenharia não for um projeto dbt,
pule as duas etapas: `./review.sh . --skip sqlfluff dbt-evaluator`.

**SQLFluff requer keyfile**
→ Nem `--keyfile` foi passado nem existe ADC do gcloud detectada
(`~/.config/gcloud/application_default_credentials.json` no host). Rode
`gcloud auth application-default login` uma vez na máquina, ou passe
`--keyfile <caminho>` explicitamente.

**Falso positivo**
→ Ruff: `# noqa: <regra>` na linha, com justificativa. Semgrep:
`# nosemgrep: <id-da-regra>`. Trivy: arquivo `.trivyignore` na raiz do projeto
com o ID do CVE.

---

## Configuração por engenharia (para o time)

A lib usa a config **do projeto alvo** quando existe, senão cai nos defaults:

- **Ruff** → `[tool.ruff]` no `pyproject.toml` (ou `ruff.toml`) do projeto;
  senão `config/ruff-defaults.toml`
- **Semgrep** → `.semgrep.yml` na raiz do projeto (regras customizadas do
  time — SQL injection, `read_csv` sem encoding etc.); senão
  `config/semgrep-defaults.yml`
- **Yamllint** → sempre aplica o ignore universal da lib +
  `config/yamllint-defaults.yml`; se existir `.yamllint` / `.yamllint.yaml` /
  `.yamllint.yml` na raiz do projeto, as regras e o `ignore` de lá são
  **mesclados por cima** (não substituem os defaults)
- **SQLFluff** → `.sqlfluff` na raiz do projeto dbt; senão
  `config/sqlfluff-defaults.cfg`. Um `.sqlfluffignore` do projeto **soma**
  (não substitui) ao ignore universal da lib
- **dbt Project Evaluator** → não tem arquivo de config de regras (os 4
  checks são fixos); aceite explícito de achados via
  `.dbt-evaluator-accept.yml` na raiz do projeto dbt — ver nota abaixo
- **Trivy / etapas / severidade mínima** → `review/steps.py` (também é onde
  se adiciona uma nova etapa, ex.: coverage)

**Accept-list do dbt Project Evaluator**: para aceitar formalmente uma
dívida técnica já conhecida (ex.: um model legado sem teste de unicidade)
sem bloquear o commit, crie `.dbt-evaluator-accept.yml` na raiz do **projeto
dbt** analisado (não na pasta `code_review/`):

```yaml
accepted:
  - check: missing-uniqueness-test
    model: fct_vendas_unificado
    reason: "Legado pré-dbt; unicidade garantida na origem, migração prevista"
```

O achado continua aparecendo no dashboard (prefixado com `[ACEITO]`), só
deixa de contar para o exit code / quality gate. Um arquivo ausente ou
malformado nunca esconde achados — nesse caso nada é aceito (fail closed).

## Arquitetura (para quem for manter)

A análise roda em **Python** e o dashboard é um app **Next.js + TypeScript**;
o contrato entre os dois é o JSON em `reports/`.

```
code_review/
├── review.sh              ← comando único do engenheiro
├── Dockerfile             ← imagem python (ruff+semgrep+trivy+pytest+yamllint+sqlfluff+dbt-core)
├── docker-compose.yml     ← serviços: review (python) + dashboard (next.js)
├── config/                ← defaults de Ruff/Semgrep/Yamllint/SQLFluff
├── review/                ← pacote python (runner, parsers, relatório JSON)
├── dashboard/             ← app Next.js + TypeScript (Dockerfile próprio)
│   ├── app/api/           ← GET /api/projects · GET /api/report?project=&run=
│   └── app/page.tsx       ← UI (quality gate, cards, filtros, snippets)
└── reports/<engenharia>/<execução>.json   ← contrato entre python e o front
```

Sem Docker (requer `pip install ruff semgrep pytest yamllint sqlfluff
sqlfluff-templater-dbt dbt-bigquery` + Trivy; Node 20+ para o front):

```bash
python -m review --target /caminho/da/engenharia   # de dentro da pasta code_review
cd dashboard && npm install && npm run dev         # front em modo dev (porta 3000)
```
