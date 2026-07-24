# Imagem da lib de revisão de código: Ruff + Semgrep + Trivy + Pytest + Yamllint + SQLFluff.
# O código da lib e o projeto alvo são montados como volumes (docker-compose.yml),
# então a imagem só precisa ser construída uma vez.
# O dashboard (Next.js) tem imagem própria em dashboard/Dockerfile.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        git \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# pathspec: usado direto por review/steps.py (merge de ignore do yamllint/
# sqlfluff) — declarado explícito em vez de depender da instalação
# transitiva que já vem via yamllint.
RUN pip install --no-cache-dir ruff semgrep pytest yamllint pathspec

# SQLFluff com templater dbt: ele compila o projeto de verdade (resolve
# ref()/source()/Jinja) antes de lintar, então precisa do dbt-core (via
# dbt-bigquery) instalado também. A lib roda contra QUALQUER projeto dbt
# colado em code_review, não só o primeiro que foi testado — por isso a
# versão não fica presa à faixa de um projeto específico (era 1.7.*, travado
# olhando só pro fricarne). dbt-core 1.7.19 não lê o package-lock.yml de
# projetos gerados com dbt-core mais novo (schema de lock mudou entre as
# séries: campo `name` por pacote passou a ser aceito/obrigatório de um jeito
# que o validador do 1.7 rejeita — reproduzido isolando package-lock.yml do
# Caronly). >=1.8 já resolve esse schema; testado manualmente e confirmado
# OK com dbt-core 1.11.9 (~/dbt-env). Teto em <1.12 pra não puxar a versão
# mais nova (1.12, lançada recentemente) sem antes testar contra os projetos
# reais. dbt-core precisa de teto EXPLÍCITO à parte: a partir da arquitetura
# de adapters desacoplados (dbt-adapters), fixar só dbt-bigquery não prende
# mais a versão do dbt-core — sem esse segundo pin, o resolvedor do pip
# instala dbt-core 1.12.0 (não testado) mesmo com dbt-bigquery<1.12.
RUN pip install --no-cache-dir sqlfluff sqlfluff-templater-dbt "dbt-bigquery>=1.8,<1.12" "dbt-core>=1.8,<1.12"

# Trivy não é distribuído via pip — instala o binário oficial
RUN curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \
    | sh -s -- -b /usr/local/bin

# roda como usuário não-root (o cache do Trivy vive no home dele)
RUN useradd --create-home reviewer \
    && mkdir -p /home/reviewer/.cache/trivy \
    && chown -R reviewer:reviewer /home/reviewer
USER reviewer
ENV HOME=/home/reviewer

WORKDIR /review

ENTRYPOINT ["python", "-m", "review"]
