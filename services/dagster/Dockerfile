# One image for the three Dagster processes: code server, webserver and daemon.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/home

COPY services/dagster/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /opt/dagster/app
COPY services/dagster/dagster.yaml services/dagster/workspace.yaml ${DAGSTER_HOME}/
COPY services/dagster/llobregat_pipelines ./llobregat_pipelines

EXPOSE 3000 4000
