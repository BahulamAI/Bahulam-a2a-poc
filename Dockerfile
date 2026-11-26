FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY bahulam_poc ./bahulam_poc
COPY README.md ARCHITECTURE.md NOTICE.txt ./
RUN pip install --no-deps .

RUN mkdir -p /app/workspaces /app/state

EXPOSE 9101 9102

CMD ["python", "-m", "bahulam_poc.agents.builder_server"]
