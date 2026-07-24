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

RUN pip install --no-cache-dir ruff semgrep pytest yamllint

# SQLFluff com templater dbt: ele compila o projeto de verdade (resolve
# ref()/source()/Jinja) antes de lintar, então precisa do dbt-core (via
# dbt-bigquery) instalado também. Versão pinada na mesma faixa que os
# projetos dbt já usam em produção (ex.: docker/fricarne/Dockerfile usa
# dbt-bigquery==1.7.*) pra evitar incompatibilidade de compilação.
RUN pip install --no-cache-dir sqlfluff sqlfluff-templater-dbt "dbt-bigquery>=1.7,<1.8"

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
