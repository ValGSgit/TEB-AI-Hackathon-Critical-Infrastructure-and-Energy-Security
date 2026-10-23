# Orchestrator image for the judged run: python -m greenops.live with credentials from the environment.
# Runs unprivileged with a read-only root filesystem; only /tmp is written (decision log, status samples).
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 HOME=/tmp GREENOPS_OUT=/tmp/greenops-run
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin greenops
COPY challenge ./challenge
COPY greenops ./greenops
USER 10001
ENTRYPOINT ["python", "-m", "greenops.live"]
