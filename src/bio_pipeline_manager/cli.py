from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.yaml_store import YamlStore


DEFAULT_HOME = Path(".bio_pipeline")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bio-pipeline")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")

    yaml_parser = subparsers.add_parser("yaml")
    yaml_sub = yaml_parser.add_subparsers(dest="yaml_command", required=True)
    yaml_save = yaml_sub.add_parser("save")
    yaml_save.add_argument("name")
    yaml_save.add_argument("source", type=Path)
    yaml_save.add_argument("--overwrite", action="store_true")
    yaml_sub.add_parser("list")
    yaml_show = yaml_sub.add_parser("show")
    yaml_show.add_argument("name")

    submit = subparsers.add_parser("submit")
    submit.add_argument("yaml_name")
    submit.add_argument("pipeline_name")
    submit.add_argument("--output-dir", type=Path, required=True)
    submit.add_argument("--backend", default="local")
    submit.add_argument("--at", dest="scheduled_at")
    submit.add_argument("-i", "--input", action="append", default=[])

    run_due = subparsers.add_parser("run-due")
    run_due.add_argument("--parallel", type=int, default=1)

    subparsers.add_parser("jobs")

    args = parser.parse_args(argv)
    home = args.home
    yaml_store = YamlStore(home / "yamls")
    store = JobStore(home / "state.sqlite")
    queue = JobQueue(store, home / "logs")

    if args.command == "init":
        home.mkdir(parents=True, exist_ok=True)
        print(f"Initialized {home}")
        return 0

    if args.command == "yaml":
        if args.yaml_command == "save":
            content = args.source.read_text(encoding="utf-8")
            path = yaml_store.save(args.name, content, overwrite=args.overwrite)
            print(path)
            return 0
        if args.yaml_command == "list":
            for path in yaml_store.list():
                print(path.name)
            return 0
        if args.yaml_command == "show":
            print(yaml_store.load(args.name))
            return 0

    if args.command == "submit":
        input_sources = _parse_inputs(args.input)
        scheduled_at = datetime.fromisoformat(args.scheduled_at) if args.scheduled_at else None
        spec = JobSpec(
            yaml_path=yaml_store.resolve_name(args.yaml_name),
            pipeline_name=args.pipeline_name,
            output_dir=args.output_dir,
            input_sources=input_sources,
            backend=args.backend,
            scheduled_at=scheduled_at,
        )
        job = queue.submit(spec)
        print(job.id)
        return 0

    if args.command == "run-due":
        results = queue.run_due(parallel=args.parallel)
        for job in results:
            print(f"{job.id} {job.status}")
        return 0

    if args.command == "jobs":
        for job in store.list_jobs():
            print(f"{job.id} {job.status} {job.spec.pipeline_name} {job.log_path}")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


def _parse_inputs(values: list[str]) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Input override must be NAME=PATH: {value}")
        name, path = value.split("=", 1)
        inputs[name.strip()] = path.strip()
    return inputs


if __name__ == "__main__":
    raise SystemExit(main())

