"""Backup (export) and restore (import) of admin-authored project content.

Bundles the admin-authored artifacts of a project — pipeline YAMLs, reusable Job
Definitions, published jobs, the project type library, and a ``requirements.txt``
of the *extra* packages installed through the app — into a single portable zip,
and applies such a zip onto another server. Runs, queues, logs, users, sessions,
saved values, and recurring schedules are deliberately **not** part of a backup.

This is pure domain logic over the existing stores (no FastAPI): the route layer
streams the bytes out (:func:`build_backup`) and feeds an uploaded body back in
(:func:`import_backup`). Import is governed by a single ``overwrite`` flag (off =>
existing items are skipped; on => replaced) plus an ``install_packages`` flag that
reuses the package-install mechanism so imported pipelines/jobs become runnable.

Security note: every stored path comes from a zip entry, but the underlying stores
(:class:`~bio_pipeline_manager.yaml_store.YamlStore`,
:class:`~bio_pipeline_manager.job_definition_store.JobDefinitionStore`) containment
-check each name in ``save()``, so a crafted ``pipelines/../evil`` entry is rejected
(recorded as a per-item error) rather than escaping the store.
"""

from __future__ import annotations

import importlib.metadata
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from bio_pipeline_manager.job_definition_store import JobDefinitionStore
from bio_pipeline_manager.models import utc_now
from bio_pipeline_manager.packages import (
    PackageBusyError,
    PackageError,
    PackageManager,
    distribution_name,
)
from bio_pipeline_manager.published_jobs import (
    PublishedJobError,
    PublishedJobRecord,
    PublishedJobStore,
)
from bio_pipeline_manager.type_library_store import TypeLibraryStore
from bio_pipeline_manager.type_schema import TypeSchemaError
from bio_pipeline_manager.yaml_store import YamlStore

FORMAT_VERSION = 1

# Zip directory prefixes / filenames.
_PIPELINES = "pipelines/"
_JOB_DEFS = "job_definitions/"
_PUBLISHED = "published_jobs/"
_TYPE_LIBRARY = "type_library.yaml"
_REQUIREMENTS = "requirements.txt"
_MANIFEST = "manifest.json"


class BackupError(ValueError):
    """The uploaded archive is not a valid Bio Pipeline Manager backup."""


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class CategoryResult:
    """Per-category import outcome (one of pipelines / job defs / published / types)."""

    created: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "overwritten": self.overwritten,
            "skipped": self.skipped,
            "errors": self.errors,
        }


@dataclass
class ImportReport:
    pipelines: CategoryResult = field(default_factory=CategoryResult)
    job_definitions: CategoryResult = field(default_factory=CategoryResult)
    published_jobs: CategoryResult = field(default_factory=CategoryResult)
    type_library: CategoryResult = field(default_factory=CategoryResult)
    packages: dict[str, Any] = field(
        default_factory=lambda: {"attempted": False, "ok": None, "exit_code": None, "detail": ""}
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipelines": self.pipelines.as_dict(),
            "job_definitions": self.job_definitions.as_dict(),
            "published_jobs": self.published_jobs.as_dict(),
            "type_library": self.type_library.as_dict(),
            "packages": self.packages,
        }


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def build_backup(
    *,
    yaml_store: YamlStore,
    definition_store: JobDefinitionStore,
    published_jobs: PublishedJobStore,
    packages: PackageManager,
    type_library: TypeLibraryStore,
    created_by: str,
) -> bytes:
    """Build an in-memory backup zip of all admin-authored content. Returns the bytes."""
    buffer = io.BytesIO()
    pipelines: list[str] = []
    job_defs: list[str] = []
    published: list[dict[str, str]] = []
    has_type_library = False

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in yaml_store.list():
            rel = yaml_store.relative_name(path)
            archive.writestr(f"{_PIPELINES}{rel}", path.read_text(encoding="utf-8"))
            pipelines.append(rel)

        for path in definition_store.list():
            rel = definition_store.relative_name(path)
            archive.writestr(f"{_JOB_DEFS}{rel}", path.read_text(encoding="utf-8"))
            job_defs.append(rel)

        for record in published_jobs.list():
            archive.writestr(
                f"{_PUBLISHED}{record.id}.json",
                json.dumps(_published_job_to_dict(record), indent=2, sort_keys=True),
            )
            published.append({"id": record.id, "name": record.name})

        library = type_library.all()
        if library:
            archive.writestr(_TYPE_LIBRARY, yaml.safe_dump(library, sort_keys=True))
            has_type_library = True

        archive.writestr(_REQUIREMENTS, build_requirements(packages))

        manifest = {
            "format_version": FORMAT_VERSION,
            "app_version": _app_version(),
            "created_at": utc_now().isoformat(),
            "created_by": created_by,
            "contents": {
                "pipelines": pipelines,
                "job_definitions": job_defs,
                "published_jobs": published,
                "type_library": has_type_library,
                "requirements": True,
            },
        }
        archive.writestr(_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True))

    return buffer.getvalue()


def build_requirements(packages: PackageManager) -> str:
    """Reconstruct, as a pip requirements file, the *extra* packages an admin installed
    through the Environment page.

    Walks the install audit log oldest→newest, keeping a net set (a successful
    ``install`` adds, a successful ``uninstall`` removes), then emits one line per
    surviving package: a pinned ``name==version`` for PyPI installs (preferring the
    *currently* installed version), the original spec for git installs, and a comment
    for editable / requirements-file installs (their paths are source-machine-local
    and can't be reproduced on the target).
    """
    net: dict[str, dict[str, Any]] = {}
    for op in packages.store.all_operations():
        if not op.get("ok"):
            continue
        name = distribution_name(op["spec"], op["source_type"])
        key = (name or op["spec"]).lower()
        if op["action"] == "install":
            net[key] = {
                "spec": op["spec"],
                "source_type": op["source_type"],
                "resolved_version": op.get("resolved_version"),
                "name": name,
            }
        elif op["action"] == "uninstall":
            net.pop(key, None)

    body: list[str] = []
    for entry in sorted(net.values(), key=lambda e: (e.get("name") or e["spec"]).lower()):
        spec, source_type, name = entry["spec"], entry["source_type"], entry.get("name")
        if source_type == "git":
            body.append(spec)
        elif source_type in {"editable", "requirements"}:
            body.append(
                f"# {source_type} install (not portable — re-install on the target manually): {spec}"
            )
        else:  # pypi
            version = (packages.installed_version(name) if name else None) or entry.get("resolved_version")
            if name and version:
                body.append(f"{name}=={version}")
            elif name:
                body.append(name)
            else:
                body.append(spec)

    header = [
        f"# Generated by Bio Pipeline Manager backup on {date.today().isoformat()}.",
        "# Extra packages installed through the Environment page.",
        "",
    ]
    return "\n".join(header + body) + "\n"


def _published_job_to_dict(record: PublishedJobRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "status": record.status,
        "version": record.version,
        "definition_name": record.definition_name,
        "definition_content": record.definition_content,
        "fields": record.fields,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
    }


def _app_version() -> str:
    try:
        return importlib.metadata.version("bio-pipeline-manager")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def import_backup(
    zip_bytes: bytes,
    *,
    yaml_store: YamlStore,
    definition_store: JobDefinitionStore,
    published_jobs: PublishedJobStore,
    packages: PackageManager,
    type_library: TypeLibraryStore,
    overwrite: bool,
    install_packages: bool,
    actor: str,
) -> ImportReport:
    """Apply a backup zip. Content is imported first (so it lands even if pip is
    refused), then — if requested — the requirements file is installed."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise BackupError("Uploaded file is not a valid zip archive") from exc

    with archive:
        names = set(archive.namelist())
        if _MANIFEST not in names:
            raise BackupError("Backup is missing manifest.json")
        try:
            manifest = json.loads(archive.read(_MANIFEST))
        except ValueError as exc:
            raise BackupError("Backup manifest.json is unreadable") from exc
        version = manifest.get("format_version")
        if version != FORMAT_VERSION:
            raise BackupError(
                f"Unsupported backup format_version: {version!r} (expected {FORMAT_VERSION})"
            )

        report = ImportReport()
        _import_yaml_entries(archive, names, _PIPELINES, yaml_store, overwrite, report.pipelines)
        _import_yaml_entries(archive, names, _JOB_DEFS, definition_store, overwrite, report.job_definitions)
        _import_published_jobs(archive, names, published_jobs, overwrite, actor, report.published_jobs)
        if _TYPE_LIBRARY in names:
            _import_type_library(archive, type_library, overwrite, report.type_library)
        if install_packages and _REQUIREMENTS in names:
            _install_requirements(archive, packages, actor, report)

    return report


def _import_yaml_entries(
    archive: zipfile.ZipFile,
    names: set[str],
    prefix: str,
    store: YamlStore | JobDefinitionStore,
    overwrite: bool,
    result: CategoryResult,
) -> None:
    existing = {store.relative_name(path) for path in store.list()}
    for name in sorted(n for n in names if n.startswith(prefix) and not n.endswith("/")):
        rel = name[len(prefix):]
        if not rel:
            continue
        existed = rel in existing
        if existed and not overwrite:
            result.skipped.append(rel)
            continue
        content = archive.read(name).decode("utf-8")
        try:
            store.save(rel, content, overwrite=overwrite)
        except FileExistsError:
            result.skipped.append(rel)
        except ValueError as exc:  # bad path or invalid YAML content
            result.errors.append({"name": rel, "error": str(exc)})
        else:
            (result.overwritten if existed else result.created).append(rel)


def _import_published_jobs(
    archive: zipfile.ZipFile,
    names: set[str],
    store: PublishedJobStore,
    overwrite: bool,
    actor: str,
    result: CategoryResult,
) -> None:
    # Match by NAME: ids are per-server UUIDs that never collide across machines, so
    # name is the meaningful identity for skip/overwrite.
    existing = {record.name: record for record in store.list()}
    for name in sorted(n for n in names if n.startswith(_PUBLISHED) and n.endswith(".json")):
        try:
            data = json.loads(archive.read(name))
        except ValueError as exc:
            result.errors.append({"name": name, "error": f"invalid JSON: {exc}"})
            continue
        job_name = data.get("name")
        if not job_name:
            result.errors.append({"name": name, "error": "published job is missing 'name'"})
            continue
        if "definition_content" not in data:
            result.errors.append({"name": job_name, "error": "published job is missing 'definition_content'"})
            continue
        current = existing.get(job_name)
        try:
            if current is None:
                store.create(
                    name=job_name,
                    description=data.get("description", ""),
                    definition_name=data.get("definition_name", ""),
                    definition_content=data["definition_content"],
                    fields=data.get("fields", []),
                    actor=actor,
                    status=data.get("status", "draft"),
                )
                result.created.append(job_name)
            elif overwrite:
                store.update(
                    current.id,
                    name=job_name,
                    description=data.get("description", ""),
                    definition_name=data.get("definition_name", ""),
                    definition_content=data["definition_content"],
                    fields=data.get("fields", []),
                    actor=actor,
                )
                desired_status = data.get("status", current.status)
                if desired_status != current.status:
                    store.set_status(current.id, desired_status, actor=actor)
                result.overwritten.append(job_name)
            else:
                result.skipped.append(job_name)
        except PublishedJobError as exc:
            result.errors.append({"name": job_name, "error": str(exc)})


def _import_type_library(
    archive: zipfile.ZipFile,
    type_library: TypeLibraryStore,
    overwrite: bool,
    result: CategoryResult,
) -> None:
    try:
        incoming = yaml.safe_load(archive.read(_TYPE_LIBRARY).decode("utf-8")) or {}
    except yaml.YAMLError as exc:
        result.errors.append({"name": _TYPE_LIBRARY, "error": f"invalid YAML: {exc}"})
        return
    if not isinstance(incoming, dict):
        result.errors.append({"name": _TYPE_LIBRARY, "error": "type library must be a mapping"})
        return
    try:
        current = type_library.all()
    except TypeSchemaError as exc:
        result.errors.append({"name": _TYPE_LIBRARY, "error": str(exc)})
        return

    merged = dict(current)
    created, overwritten, skipped = [], [], []
    for type_name, type_def in incoming.items():
        if type_name in current:
            if overwrite:
                merged[type_name] = type_def
                overwritten.append(type_name)
            else:
                skipped.append(type_name)
        else:
            merged[type_name] = type_def
            created.append(type_name)

    if created or overwritten:
        try:
            # Validates the whole merged library (cross-type refs / cycles) before writing.
            type_library.replace(merged)
        except TypeSchemaError as exc:
            result.errors.append({"name": _TYPE_LIBRARY, "error": str(exc)})
            return
    result.created.extend(sorted(created))
    result.overwritten.extend(sorted(overwritten))
    result.skipped.extend(sorted(skipped))


def _install_requirements(
    archive: zipfile.ZipFile,
    packages: PackageManager,
    actor: str,
    report: ImportReport,
) -> None:
    content = archive.read(_REQUIREMENTS).decode("utf-8")
    has_specs = any(
        line.strip() and not line.strip().startswith("#") for line in content.splitlines()
    )
    if not has_specs:
        report.packages = {
            "attempted": False,
            "ok": None,
            "exit_code": None,
            "detail": "No extra packages to install.",
        }
        return

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(content)
            tmp_path = handle.name
        op = packages.install(tmp_path, source_type="requirements", actor=actor)
        detail = (op.stderr or op.stdout or "").strip()
        report.packages = {
            "attempted": True,
            "ok": op.ok,
            "exit_code": op.exit_code,
            "detail": detail[-4000:],
        }
    except (PackageBusyError, PackageError) as exc:
        report.packages = {"attempted": True, "ok": False, "exit_code": None, "detail": str(exc)}
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
