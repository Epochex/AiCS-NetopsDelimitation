from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from .config import Settings
from .runtime_reader import build_runtime_stream_delta, load_runtime_snapshot

settings = Settings.from_env()

app = FastAPI(
  title='Hybrid NetOps Console Gateway',
  version='0.1.0',
  docs_url='/api/docs',
  openapi_url='/api/openapi.json',
)

if settings.cors_origins:
  allow_all = '*' in settings.cors_origins
  app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'] if allow_all else list(settings.cors_origins),
    allow_credentials=not allow_all,
    allow_methods=['*'],
    allow_headers=['*'],
  )


@app.get('/api/healthz')
def healthz() -> dict[str, str]:
  return {'status': 'ok'}


@app.get('/api/runtime/snapshot')
def runtime_snapshot():
  return load_runtime_snapshot(settings)


@app.get('/api/runtime/stream')
async def runtime_stream(request: Request):
  async def event_stream():
    previous_payload: dict[str, object] | None = None
    idle_cycles = 0

    while True:
      if await request.is_disconnected():
        break

      payload = load_runtime_snapshot(settings)
      if previous_payload is None:
        envelope = {
          'type': 'snapshot',
          'emittedAt': payload['runtime']['latestSuggestionTs'],
          'snapshot': payload,
        }
        yield (
          'retry: 2000\n'
          f"event: snapshot\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"
        )
        previous_payload = payload
        idle_cycles = 0
        await asyncio.sleep(settings.stream_interval_sec)
        continue

      delta = build_runtime_stream_delta(previous_payload, payload)
      if delta:
        envelope = {
          'type': 'delta',
          'emittedAt': delta['emittedAt'],
          'snapshot': payload,
          'delta': delta,
        }
        yield (
          'retry: 2000\n'
          f"event: delta\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"
        )
        previous_payload = payload
        idle_cycles = 0
      else:
        idle_cycles += 1
        if idle_cycles * settings.stream_interval_sec >= 15:
          heartbeat = {
            'type': 'heartbeat',
            'emittedAt': payload['runtime']['latestSuggestionTs'],
          }
          yield f"event: heartbeat\ndata: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
          idle_cycles = 0

      await asyncio.sleep(settings.stream_interval_sec)

  return StreamingResponse(
    event_stream(),
    media_type='text/event-stream',
    headers={
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  )


@app.get('/', include_in_schema=False)
@app.get('/{full_path:path}', include_in_schema=False)
def serve_frontend(full_path: str = ''):
  if not settings.frontend_dist.exists():
    return PlainTextResponse(
      'Frontend dist not built yet. Run Vite on :5173 for development or build frontend/ before serving from FastAPI.',
      status_code=404,
    )

  requested_path = (settings.frontend_dist / full_path).resolve()
  dist_root = settings.frontend_dist.resolve()
  if (
    full_path
    and requested_path.is_relative_to(dist_root)
    and requested_path.is_file()
  ):
    return FileResponse(requested_path)
  return FileResponse(dist_root / 'index.html')
