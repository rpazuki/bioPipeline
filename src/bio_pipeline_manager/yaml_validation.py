from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import yaml


class IssueLevel(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    level: IssueLevel
    message: str
    pipeline: str | None = None
    section: str | None = None
    item: str | None = None


@dataclass(frozen=True)
class ProcessSummary:
    name: str
    package: str
    method: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class PipelineSummary:
    name: str
    inputs: list[str] = field(default_factory=list)
    processes: list[ProcessSummary] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    issues: list[ValidationIssue]
    pipelines: list[PipelineSummary]

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": [
                {
                    "level": issue.level.value,
                    "message": issue.message,
                    "pipeline": issue.pipeline,
                    "section": issue.section,
                    "item": issue.item,
                }
                for issue in self.issues
            ],
            "pipelines": [
                {
                    "name": pipeline.name,
                    "inputs": pipeline.inputs,
                    "processes": [
                        {
                            "name": process.name,
                            "package": process.package,
                            "method": process.method,
                            "parameters": process.parameters,
                        }
                        for process in pipeline.processes
                    ],
                    "outputs": pipeline.outputs,
                }
                for pipeline in self.pipelines
            ],
        }


REFERENCE_PARAMETER_NAMES = {
    "df",
    "df_parsed",
    "folders_list",
    "left_df",
    "meta_data",
    "params_df",
    "payload",
    "raw_data",
    "right_df",
}


def validate_labutils_yaml(content: str, *, validate_imports: bool = False) -> ValidationReport:
    """Validate and summarize a labUtils pipeline YAML document.

    The checks intentionally stay close to labUtils' current YAML shape. Import
    validation is optional so users can still edit YAML before all dependencies are
    installed in the active environment.
    """

    issues: list[ValidationIssue] = []
    summaries: list[PipelineSummary] = []

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return ValidationReport(
            is_valid=False,
            issues=[ValidationIssue(IssueLevel.ERROR, f"YAML parser error: {exc}")],
            pipelines=[],
        )

    if not isinstance(data, dict):
        return _invalid("YAML content must be a mapping")

    pipelines = data.get("pipelines")
    if not isinstance(pipelines, list) or not pipelines:
        return _invalid("YAML must contain a non-empty 'pipelines' list")

    seen_pipeline_names: set[str] = set()
    for pipeline_entry in pipelines:
        if not isinstance(pipeline_entry, dict) or len(pipeline_entry) != 1:
            issues.append(ValidationIssue(IssueLevel.ERROR, "Each pipeline entry must be a one-item mapping"))
            continue

        pipeline_name, pipeline_config = next(iter(pipeline_entry.items()))
        if pipeline_name in seen_pipeline_names:
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    f"Duplicate pipeline name '{pipeline_name}'",
                    pipeline=pipeline_name,
                )
            )
        seen_pipeline_names.add(pipeline_name)

        if not isinstance(pipeline_config, dict):
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "Pipeline config must be a mapping",
                    pipeline=pipeline_name,
                )
            )
            continue

        summary = _validate_pipeline(
            pipeline_name,
            pipeline_config,
            issues=issues,
            validate_imports=validate_imports,
        )
        summaries.append(summary)

    return ValidationReport(
        is_valid=not any(issue.level == IssueLevel.ERROR for issue in issues),
        issues=issues,
        pipelines=summaries,
    )


def _validate_pipeline(
    pipeline_name: str,
    pipeline_config: dict[str, Any],
    *,
    issues: list[ValidationIssue],
    validate_imports: bool,
) -> PipelineSummary:
    for section in ("Inputs", "Processes", "Outputs"):
        if section not in pipeline_config:
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    f"Pipeline config must contain '{section}'",
                    pipeline=pipeline_name,
                    section=section,
                )
            )

    inputs = _validate_inputs(pipeline_name, pipeline_config.get("Inputs"), issues, validate_imports)
    processes = _validate_processes(
        pipeline_name,
        pipeline_config.get("Processes"),
        known_payloads=set(inputs),
        issues=issues,
        validate_imports=validate_imports,
    )
    known_payloads = set(inputs) | {process.name for process in processes}
    outputs = _validate_outputs(pipeline_name, pipeline_config.get("Outputs"), known_payloads, issues)
    return PipelineSummary(name=pipeline_name, inputs=inputs, processes=processes, outputs=outputs)


def _validate_inputs(
    pipeline_name: str,
    inputs_config: Any,
    issues: list[ValidationIssue],
    validate_imports: bool,
) -> list[str]:
    if inputs_config is None:
        return []
    if not isinstance(inputs_config, list):
        issues.append(
            ValidationIssue(IssueLevel.ERROR, "Inputs must be a list", pipeline=pipeline_name, section="Inputs")
        )
        return []

    names: list[str] = []
    for entry in inputs_config:
        if not isinstance(entry, dict) or len(entry) != 1:
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "Each input must be a one-item mapping",
                    pipeline=pipeline_name,
                    section="Inputs",
                )
            )
            continue
        input_name, raw_spec = next(iter(entry.items()))
        names.append(input_name)
        spec = _coerce_input_spec(raw_spec)
        if spec is None:
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "Input spec must be a mapping or list of one-item mappings",
                    pipeline=pipeline_name,
                    section="Inputs",
                    item=input_name,
                )
            )
            continue
        for key in ("src", "package", "method"):
            if key not in spec:
                issues.append(
                    ValidationIssue(
                        IssueLevel.ERROR,
                        f"Input '{input_name}' must contain '{key}'",
                        pipeline=pipeline_name,
                        section="Inputs",
                        item=input_name,
                    )
                )
        _validate_import(
            spec.get("package"),
            spec.get("method"),
            pipeline_name=pipeline_name,
            section="Inputs",
            item=input_name,
            issues=issues,
            validate_imports=validate_imports,
        )
    return names


def _validate_processes(
    pipeline_name: str,
    processes_config: Any,
    known_payloads: set[str],
    issues: list[ValidationIssue],
    validate_imports: bool,
) -> list[ProcessSummary]:
    if processes_config is None:
        return []
    if not isinstance(processes_config, list):
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR,
                "Processes must be a list",
                pipeline=pipeline_name,
                section="Processes",
            )
        )
        return []

    summaries: list[ProcessSummary] = []
    for entry in processes_config:
        if not isinstance(entry, dict) or len(entry) != 1:
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "Each process must be a one-item mapping",
                    pipeline=pipeline_name,
                    section="Processes",
                )
            )
            continue

        process_name, spec = next(iter(entry.items()))
        if not isinstance(spec, dict):
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    f"Process '{process_name}' spec must be a mapping",
                    pipeline=pipeline_name,
                    section="Processes",
                    item=process_name,
                )
            )
            continue

        for key in ("package", "method", "parameters"):
            if key not in spec:
                issues.append(
                    ValidationIssue(
                        IssueLevel.ERROR,
                        f"Process '{process_name}' must contain '{key}'",
                        pipeline=pipeline_name,
                        section="Processes",
                        item=process_name,
                    )
                )

        parameters = spec.get("parameters")
        if not isinstance(parameters, dict):
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    f"Process '{process_name}' parameters must be a mapping",
                    pipeline=pipeline_name,
                    section="Processes",
                    item=process_name,
                )
            )
            parameters = {}

        _warn_unknown_payload_references(pipeline_name, process_name, parameters, known_payloads, issues)
        _validate_import(
            spec.get("package"),
            spec.get("method"),
            pipeline_name=pipeline_name,
            section="Processes",
            item=process_name,
            issues=issues,
            validate_imports=validate_imports,
        )
        summaries.append(
            ProcessSummary(
                name=process_name,
                package=str(spec.get("package", "")),
                method=str(spec.get("method", "")),
                parameters=parameters,
            )
        )
        known_payloads.add(process_name)
    return summaries


def _validate_outputs(
    pipeline_name: str,
    outputs_config: Any,
    known_payloads: set[str],
    issues: list[ValidationIssue],
) -> list[str]:
    if outputs_config is None:
        return []
    if not isinstance(outputs_config, list):
        issues.append(
            ValidationIssue(IssueLevel.ERROR, "Outputs must be a list", pipeline=pipeline_name, section="Outputs")
        )
        return []

    outputs: list[str] = []
    for entry in outputs_config:
        if not isinstance(entry, dict) or len(entry) != 1:
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "Each output must be a one-item mapping",
                    pipeline=pipeline_name,
                    section="Outputs",
                )
            )
            continue
        output_name, output_path = next(iter(entry.items()))
        outputs.append(output_name)
        if output_name not in known_payloads:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    f"Output '{output_name}' is not produced by an input or process",
                    pipeline=pipeline_name,
                    section="Outputs",
                    item=output_name,
                )
            )
        if not isinstance(output_path, str | list):
            issues.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    f"Output '{output_name}' path must be a string or list",
                    pipeline=pipeline_name,
                    section="Outputs",
                    item=output_name,
                )
            )
    return outputs


def _coerce_input_spec(raw_spec: Any) -> dict[str, Any] | None:
    if isinstance(raw_spec, dict):
        return raw_spec
    if isinstance(raw_spec, list):
        spec: dict[str, Any] = {}
        for item in raw_spec:
            if not isinstance(item, dict):
                return None
            spec.update(item)
        return spec
    return None


def _validate_import(
    package: Any,
    method: Any,
    *,
    pipeline_name: str,
    section: str,
    item: str,
    issues: list[ValidationIssue],
    validate_imports: bool,
) -> None:
    if not validate_imports or not isinstance(package, str) or not isinstance(method, str):
        return
    try:
        module = importlib.import_module(package)
    except ImportError as exc:
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR,
                f"Cannot import package '{package}': {exc}",
                pipeline=pipeline_name,
                section=section,
                item=item,
            )
        )
        return
    if not hasattr(module, method):
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR,
                f"Package '{package}' has no method '{method}'",
                pipeline=pipeline_name,
                section=section,
                item=item,
            )
        )


def _warn_unknown_payload_references(
    pipeline_name: str,
    process_name: str,
    parameters: dict[str, Any],
    known_payloads: set[str],
    issues: list[ValidationIssue],
) -> None:
    for key, value in parameters.items():
        if not isinstance(value, str):
            continue
        key_suggests_payload = key in REFERENCE_PARAMETER_NAMES or key.endswith("_df")
        if key_suggests_payload and value not in known_payloads:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    f"Parameter '{key}' references '{value}', which is not yet produced",
                    pipeline=pipeline_name,
                    section="Processes",
                    item=process_name,
                )
            )


def _invalid(message: str) -> ValidationReport:
    return ValidationReport(
        is_valid=False,
        issues=[ValidationIssue(IssueLevel.ERROR, message)],
        pipelines=[],
    )

