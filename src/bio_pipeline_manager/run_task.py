"""In-process Task runner.

Builds and runs a single pipeline Task through the project-native engine
(:mod:`pipeline.engine`), instead of shelling out to the external
``labUtils.scripts.run_a_pipeline`` CLI. Running the builder in-process is what
lets a Task carry ``process_arg_mapping`` (which the CLI never exposed).

Invoked by the runner as an isolated subprocess::

    python -m bio_pipeline_manager.run_task TASK_JSON

where ``TASK_JSON`` is a file holding a single object::

    {
      "yaml_path": "...",
      "pipeline_name": "...",
      "output_dir": "...",
      "input_sources": {"raw_data": "...", "meta_data": "..."},
      "input_arg_mapping": {"raw_data": {"value_column_name": "od600"}},
      "process_arg_mapping": {"proc": {"key": "value"}},
      "output_path_mapping": {"result": "custom.csv"}
    }
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import sys
from pathlib import Path

from pipeline.engine import build_pipeline_from_yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("bio_pipeline_manager.run_task")


def _pin_multiprocessing_executable() -> None:
    """Force any multiprocessing child to use THIS interpreter.

    Pipeline processes can use multiprocessing (e.g. cobra's ProcessPool during
    FBA). On Windows, "spawn" launches a fresh interpreter; when this venv was
    created from a different base (e.g. an Anaconda install), the spawned child
    can resolve to that base interpreter instead of the venv. The base lacks the
    venv's packages, so the child wedges and the parent blocks on it forever.
    Pinning the spawn executable to ``sys.executable`` keeps children inside this
    venv. See bio_pipeline_manager.run_task hang investigation.
    """
    try:
        multiprocessing.set_executable(sys.executable)
    except Exception:  # noqa: BLE001 - never let this stop a task from running
        log.warning("Could not pin multiprocessing executable to %s", sys.executable)


def run_task(task: dict) -> dict:
    """Build the pipeline described by ``task`` and execute it.

    Returns the pipeline result payload. Raises on any build/execution error.
    """
    yaml_path = Path(task["yaml_path"])
    pipeline_name = task["pipeline_name"]
    output_dir = Path(task["output_dir"]) if task.get("output_dir") else None
    input_sources = task.get("input_sources") or None
    input_arg_mapping = task.get("input_arg_mapping") or None
    process_arg_mapping = task.get("process_arg_mapping") or None
    output_path_mapping = task.get("output_path_mapping") or None

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    pipeline, _config = build_pipeline_from_yaml(
        yaml_path,
        pipeline_name,
        output_dir=output_dir,
        input_sources=input_sources,
        input_arg_mapping=input_arg_mapping,
        process_arg_mapping=process_arg_mapping,
        output_path_mapping=output_path_mapping,
    )
    return pipeline()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        log.error("usage: python -m bio_pipeline_manager.run_task TASK_JSON")
        return 2

    _pin_multiprocessing_executable()

    task_path = Path(argv[0])
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("Could not read task file %s: %s", task_path, exc)
        return 2

    log.info("Running pipeline '%s' from %s", task.get("pipeline_name"), task.get("yaml_path"))
    try:
        result = run_task(task)
    except Exception as exc:  # noqa: BLE001 - surface any failure as a non-zero exit
        log.error("Task failed: %s", exc, exc_info=True)
        return 1

    print("=" * 60)
    print(f"Pipeline: {task.get('pipeline_name')}")
    print(f"Output directory: {task.get('output_dir')}")
    print(f"Result payload contains {len(result)} items:")
    for key in result.keys():
        print(f"  - {key}: {type(result[key]).__name__}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
