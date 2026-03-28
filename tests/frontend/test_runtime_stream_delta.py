from frontend.gateway.app.runtime_reader import build_runtime_stream_delta


def test_build_runtime_stream_delta_from_new_alert_feed():
  previous = {
    'feed': [{'id': 'feed-raw-1', 'kind': 'raw'}],
    'clusterWatch': [],
    'runtime': {'latestAlertTs': 'n/a', 'latestSuggestionTs': 'n/a'},
    'defaultSuggestionId': '',
  }
  current = {
    'feed': [
      {'id': 'feed-alert-1', 'kind': 'alert'},
      {'id': 'feed-raw-1', 'kind': 'raw'},
    ],
    'clusterWatch': [],
    'runtime': {
      'latestAlertTs': '2026-03-25T12:00:00+00:00',
      'latestSuggestionTs': 'n/a',
    },
    'defaultSuggestionId': '',
  }

  delta = build_runtime_stream_delta(previous, current)

  assert delta is not None
  assert delta['kind'] == 'alert'
  assert delta['reason'] == 'feed'
  assert delta['feedIds'] == ['feed-alert-1']
  assert delta['stageIds'] == ['correlator', 'alerts-topic', 'cluster-window']


def test_build_runtime_stream_delta_marks_cluster_suggestion_path():
  previous = {
    'feed': [],
    'clusterWatch': [],
    'runtime': {'latestAlertTs': 'n/a', 'latestSuggestionTs': 'n/a'},
    'defaultSuggestionId': '',
  }
  current = {
    'feed': [
      {
        'id': 'feed-suggestion-1',
        'kind': 'suggestion',
        'scope': 'cluster',
      },
    ],
    'clusterWatch': [],
    'runtime': {
      'latestAlertTs': '2026-03-25T12:00:00+00:00',
      'latestSuggestionTs': '2026-03-25T12:00:01+00:00',
    },
    'defaultSuggestionId': 'suggestion-1',
  }

  delta = build_runtime_stream_delta(previous, current)

  assert delta is not None
  assert delta['kind'] == 'cluster'
  assert delta['stageIds'] == [
    'cluster-window',
    'aiops-agent',
    'suggestions-topic',
    'remediation',
  ]


def test_build_runtime_stream_delta_returns_none_without_changes():
  snapshot = {
    'feed': [{'id': 'feed-raw-1', 'kind': 'raw'}],
    'clusterWatch': [{'key': 'a', 'progress': 1, 'target': 3}],
    'runtime': {
      'latestAlertTs': '2026-03-25T12:00:00+00:00',
      'latestSuggestionTs': '2026-03-25T12:00:01+00:00',
    },
    'defaultSuggestionId': 'suggestion-1',
  }

  assert build_runtime_stream_delta(snapshot, snapshot) is None
