from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from bio_pipeline_manager.job_queue import JobQueue
from bio_pipeline_manager.models import JobSpec, as_utc
from bio_pipeline_manager.storage import JobStore
from bio_pipeline_manager.templates import get_template, list_templates
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
    yaml_validate = yaml_sub.add_parser("validate")
    yaml_validate.add_argument("name")
    yaml_validate.add_argument("--imports", action="store_true", help="Validate package imports and methods")

    template_parser = subparsers.add_parser("template")
    template_sub = template_parser.add_subparsers(dest="template_command", required=True)
    template_sub.add_parser("list")
    template_show = template_sub.add_parser("show")
    template_show.add_argument("name")

    submit = subparsers.add_parser("submit")
    submit.add_argument("yaml_name")
    submit.add_argument("pipeline_name")
    submit.add_argument("--output-dir", type=Path, required=True)
    submit.add_argument("--backend", default="local")
    submit.add_argument("--at", dest="scheduled_at")
    submit.add_argument("-i", "--input", action="append", default=[])
    submit.add_argument(
        "-p",
        "--process-arg",
        action="append",
        default=[],
        metavar="PROCESS.KEY=VALUE",
        help="Per-process parameter override. Repeatable.",
    )

    run_due = subparsers.add_parser("run-due")
    run_due.add_argument("--parallel", type=int, default=1)

    subparsers.add_parser("jobs")
    cancel = subparsers.add_parser("cancel")
    cancel.add_argument("job_id")

    job_parser = subparsers.add_parser("job", help="Job Definition (multi-task) operations")
    job_sub = job_parser.add_subparsers(dest="job_command", required=True)
    job_preview = job_sub.add_parser("preview", help="Expand a Job Definition without running it")
    job_preview.add_argument("definition", type=Path)
    job_submit = job_sub.add_parser("submit", help="Expand and queue a Job Definition")
    job_submit.add_argument("definition", type=Path)
    job_submit.add_argument("--at", dest="scheduled_at")
    job_status = job_sub.add_parser("status", help="Show rollup status of a submitted Job Definition")
    job_status.add_argument("parent_job_id")

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
        if args.yaml_command == "validate":
            report = yaml_store.validate(args.name, validate_imports=args.imports)
            print("valid" if report.is_valid else "invalid")
            for issue in report.issues:
                location = "/".join(part for part in [issue.pipeline, issue.section, issue.item] if part)
                suffix = f" [{location}]" if location else ""
                print(f"{issue.level}: {issue.message}{suffix}")
            return 0

    if args.command == "template":
        if args.template_command == "list":
            for template in list_templates():
                print(f"{template.name}\t{template.description}")
            return 0
        if args.template_command == "show":
            print(get_template(args.name).content)
            return 0

    if args.command == "submit":
        input_sources = _parse_inputs(args.input)
        process_arg_mapping = _parse_process_args(args.process_arg)
        scheduled_at = as_utc(datetime.fromisoformat(args.scheduled_at)) if args.scheduled_at else None
        spec = JobSpec(
            yaml_path=yaml_store.resolve_name(args.yaml_name),
            pipeline_name=args.pipeline_name,
            output_dir=args.output_dir,
            input_sources=input_sources,
            process_arg_mapping=process_arg_mapping,
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

    if args.command == "cancel":
        job = queue.cancel(args.job_id)
        print(f"{job.id} {job.status}")
        return 0

    if args.command == "job":
        return _handle_job_command(args, queue, yaml_store)

    raise AssertionError(f"Unhandled command: {args.command}")


def _format_matrix_key(matrix_key: dict[str, str]) -> str:
    return ",".join(f"{k}={v}" for k, v in matrix_key.items()) or "-"


def _handle_job_command(args, queue: JobQueue, yaml_store: YamlStore) -> int:
    from bio_pipeline_manager.job_definition import expand

    if args.job_command == "preview":
        text = args.definition.read_text(encoding="utf-8")
        tasks = expand(text)
        print(f"{len(tasks)} task(s):")
        for task in tasks:
            print(
                f"  [{task.stage}] {_format_matrix_key(task.matrix_key)} "
                f"-> {task.pipeline_name} (yaml={task.pipeline_yaml})"
            )
            print(f"      output_dir: {task.output_dir}")
            if task.input_sources:
                print(f"      inputs: {task.input_sources}")
            if task.process_arg_mapping:
                print(f"      process_args: {task.process_arg_mapping}")
        return 0

    if args.job_command == "submit":
        text = args.definition.read_text(encoding="utf-8")
        scheduled_at = as_utc(datetime.fromisoformat(args.scheduled_at)) if args.scheduled_at else None
        parent_id, records = queue.submit_definition(
            text, yaml_resolver=yaml_store.resolve_name, scheduled_at=scheduled_at
        )
        print(f"{parent_id} ({len(records)} tasks queued)")
        return 0

    if args.job_command == "status":
        summary = queue.group_status(args.parent_job_id)
        print(f"{summary['parent_job_id']} {summary['job_name']} {summary['status']} "
              f"({summary['total']} tasks)")
        for status_name, count in sorted(summary["counts"].items()):
            print(f"  {status_name}: {count}")
        for task in summary["tasks"]:
            print(f"  {task.id} [{task.spec.stage}] {_format_matrix_key(task.spec.matrix_key)} {task.status}")
        return 0

    raise AssertionError(f"Unhandled job command: {args.job_command}")


def _parse_inputs(values: list[str]) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Input override must be NAME=PATH: {value}")
        name, path = value.split("=", 1)
        inputs[name.strip()] = path.strip()
    return inputs


def _parse_process_args(values: list[str]) -> dict[str, dict[str, str]]:
    """Parse repeated PROCESS.KEY=VALUE overrides into a nested mapping."""
    mapping: dict[str, dict[str, str]] = {}
    for value in values:
        if "=" not in value or "." not in value.split("=", 1)[0]:
            raise ValueError(f"Process arg override must be PROCESS.KEY=VALUE: {value}")
        target, raw_value = value.split("=", 1)
        process, key = target.split(".", 1)
        mapping.setdefault(process.strip(), {})[key.strip()] = raw_value.strip()
    return mapping


if __name__ == "__main__":
    raise SystemExit(main())
