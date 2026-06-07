from __future__ import annotations

from bio_pipeline_manager.job_definition import expand

JOB_WITH_SCALAR_SOURCES = """
job: t
stages:
  - name: run
    pipeline_yaml: x.yaml
    pipeline: p
    fanout: {type: none}
    input_sources:
      start: 1
      end: 10
      path: /data/in.csv
    output_dir: /tmp/out
"""


def test_expand_coerces_input_sources_to_strings():
    # Numbers slipping into input_sources must be stored as strings so the job
    # record never breaks JobResponse serialization on the read path.
    tasks = expand(JOB_WITH_SCALAR_SOURCES, lenient=True)
    assert tasks[0].input_sources == {"start": "1", "end": "10", "path": "/data/in.csv"}
    assert all(isinstance(value, str) for value in tasks[0].input_sources.values())
