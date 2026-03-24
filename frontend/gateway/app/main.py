from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from .config import Settings
from .runtime_reader import load_runtime_snapshot

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
    while True:
      if await request.is_disconnected():
        break
      payload = load_runtime_snapshot(settings)
      yield f"retry: 5000\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
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

