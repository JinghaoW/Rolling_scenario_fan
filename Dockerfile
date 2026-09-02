FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

RUN apt-get update \
    && apt-get install --no-install-recommends -y glpk-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY c/ ./c/
COPY b_read_dataset/ ./b_read_dataset/
COPY Rolling_scenario_fan.py index.html ./

RUN mkdir -p /app/a_dataset /app/output_c \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

ENTRYPOINT ["python", "-m", "c.run"]
CMD ["0", "--solver", "glpk"]
