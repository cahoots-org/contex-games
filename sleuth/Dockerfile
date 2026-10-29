# The Sleuth web game. Build from the repo root:
#   docker build -f sleuth/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SLEUTH_WEB_HOST=0.0.0.0

RUN useradd --create-home sleuth
WORKDIR /app

COPY sleuth/requirements.txt sleuth/requirements.txt
RUN pip install --no-cache-dir -r sleuth/requirements.txt

COPY sleuth sleuth
# Without a volume the game saves its village and need baselines in the working directory.
RUN chown sleuth /app

# The entrypoint runs as root to take the volume, then drops to sleuth.
ENTRYPOINT ["sleuth/entrypoint.sh"]
CMD ["python", "-m", "sleuth", "--web"]
