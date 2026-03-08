FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY edge/edge_forwarder/requirements.txt /app/edge/edge_forwarder/requirements.txt
RUN pip install --no-cache-dir -r /app/edge/edge_forwarder/requirements.txt

COPY edge/__init__.py /app/edge/__init__.py
COPY edge/edge_forwarder /app/edge/edge_forwarder
