from frontend.gateway.app.config import Settings
from frontend.gateway.app.runtime_reader import load_runtime_snapshot


def test_load_runtime_snapshot_emits_timeline_and_stage_telemetry_for_suggestions():
  settings = Settings.from_env()

  snapshot = load_runtime_snapshot(settings)

  suggestions = snapshot.get('suggestions', [])
  assert suggestions

  first = suggestions[0]
  assert first.get('timeline')
  assert first.get('stageTelemetry')

  stage_ids = [item['stageId'] for item in first['stageTelemetry']]
  assert 'correlator' in stage_ids
  assert 'aiops-agent' in stage_ids
