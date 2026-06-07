"""Pipeline execution engine for bio-pipeline-manager.

This is the project-native process/YAML engine. It was transferred out of the
external ``labUtils`` package so the manager owns pipeline orchestration; the
science process functions still live in ``labUtils`` and are referenced from
YAML as ``package: labUtils.*`` and resolved by import at runtime.

The engine resolves each process's ``package``/``method`` via ``importlib``, so
any importable package works: ``labUtils.*`` (science), ``pipeline.helpers``
(project), ``pandas``, etc.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

import yaml
from addict import Dict as DefaultDict
from pandas import DataFrame

_Self = TypeVar("_Self", bound="AbstractPipeline")

log = logging.getLogger(__name__)

# Shared input/output cache keyed by (package, method, identifier).
cache: dict = {}


class Dict(DefaultDict):
    def __missing__(self, key) -> None:
        # Unassigned properties return None instead of raising KeyError.
        return None


class IncompatibleArgsException(Exception):
    """Raised when the arguments passed to a process are incompatible."""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class AbstractPipeline(ABC):
    """An abstract pipeline class."""

    def __init__(self, processes=None):
        self.processes = processes if processes is not None else []

    def append_process(self, process) -> None:
        """Append a process to the pipeline."""
        self.processes.append(process)

    def __call__(self, /, **kwargs) -> Dict:
        return self.process(**kwargs)

    @abstractmethod
    def process(self, /, **kwargs) -> Dict:
        """Process and return the pipeline."""

    @abstractmethod
    def __rshift__(self: _Self, other) -> _Self:
        pass

    @abstractmethod
    def __mul__(self, other) -> "ProcessFork":
        pass


class AbstractProcess(ABC):
    @abstractmethod
    def __call__(self, **kwargs) -> Dict:
        """The operation of the process must happen here.

        It can define any number of arguments it likes and must have one
        ``**kwargs`` at the end. The returns are named payload as a Dict object
        and passed to the down-stream process or returned to the caller.
        """

    def __rshift__(self, other) -> AbstractPipeline:
        """Append the process to the end of a Process or DFPipeline (immutable)."""
        if issubclass(type(other), AbstractProcess):
            if isinstance(other, ProcessFork):
                other = ProcessJoined(other)
            return DFPipeline([self, other])
        elif issubclass(type(other), AbstractPipeline):
            return DFPipeline([self] + other.processes)
        else:
            raise ValueError(f"The '{type(other)}' must be a AbstractProcess or DFPipeline.")

    def __mul__(self, other):
        """Fork two or more processes (immutable)."""
        if isinstance(other, int):
            if isinstance(self, ProcessFork):
                raise ValueError("The 'ProcessFork' has already forked (cannot be multiplied).")
            else:
                return ProcessFork([self] * other)
        if isinstance(other, ProcessFork):
            if isinstance(self, ProcessFork):
                return ProcessFork(self.processes + other.processes)
            else:
                return ProcessFork([self] + other.processes)
        if issubclass(type(other), AbstractProcess):
            return ProcessFork([self, other])
        if issubclass(type(other), DFPipeline):
            return ProcessFork([self, other])
        else:
            raise ValueError(f"The '{type(other)}' must be an int, a AbstractProcess, DFPipeline or tuples of both.")


class Process(AbstractProcess):
    """A singleton object for instantiable processes."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Process, cls).__new__(cls)
        return cls._instance


class ProcessPassThrough(Process):
    def __call__(self, **kwargs) -> Dict:
        """Payload is simply passed to the next process."""
        return Dict(**kwargs)


class ProcessJoined(AbstractProcess):
    def __init__(self, forkedProcess: AbstractProcess, kwargs_mapping: Mapping[int, list[tuple[str, str]]] = None):
        """Join all the forked processes and return them as a single Mapping.

        Parameters
        ----------
        forkedProcess : Process
            The process that has been forked.
        kwargs_mapping : Mapping[int, list[tuple[str, str]]], optional
            Renaming of the processes' outputs. The key is the index of the
            process in the forked process; the value is a list of
            ``(old_key, new_key)`` tuples.
        """
        self.forkedProcess = forkedProcess
        self.kwargs_mapping = kwargs_mapping if kwargs_mapping is not None else {}

    def __call__(self, **kwargs) -> Dict:
        tuple_return = self.forkedProcess(**kwargs)
        for index, names in self.kwargs_mapping.items():
            ret = tuple_return[index]
            for old_key, new_key in names:
                ret[new_key] = ret.pop(old_key)
        # Union all returned payloads; names from higher-rank returns have precedence.
        new_kwargs = tuple_return[0]
        for d in tuple_return[1:]:
            new_kwargs |= d
        return new_kwargs


class ProcessFork(AbstractProcess):
    def __init__(self, processes: list):
        assert len(processes) > 1, "The processes must be more than one."
        self.processes = processes

    def __getitem__(self, key: int) -> AbstractProcess | AbstractPipeline:
        return self.processes[key]

    def __setitem__(self, key: int, process) -> None:
        self.processes[key] = process

    def __call__(self, **kwargs) -> tuple[Dict, ...]:
        """Call each sub-process of the fork and return their payloads as a tuple."""
        return tuple(p(**kwargs) for p in self.processes)

    def __rshift__(self, other) -> ProcessJoined:
        return ProcessJoined(self) >> other

    def __itruediv__(self, other) -> ProcessJoined:
        return self.__truediv__(other)

    def __truediv__(self, other: Mapping[int, list[tuple[str, str]]]) -> ProcessJoined:
        """Combine the output of a forked process via a renaming mapping."""
        if isinstance(other, Mapping):
            error_msg = "The number of renaming must be less than or equal to the number of processes."
            assert len(other) <= len(self.processes), error_msg
            return ProcessJoined(self, kwargs_mapping=other)
        else:
            raise ValueError(f"The {type(other)=} must be a Mapping[str, int] ")


class DFPipeline(AbstractPipeline):
    def __rshift__(self, other) -> AbstractPipeline:
        """Append the process to the end of this pipeline (immutable)."""
        if issubclass(type(other), AbstractProcess):
            if isinstance(other, ProcessFork):
                other = ProcessJoined(other)
            return DFPipeline(self.processes + [other])
        elif isinstance(other, DFPipeline):
            return DFPipeline(self.processes + other.processes)
        else:
            raise ValueError(f"The '{type(other)}' must be a Process or DFPipeline.")

    def __mul__(self, other) -> ProcessFork:
        """Fork two or more pipelines (immutable)."""
        if isinstance(other, int):
            return ProcessFork([self] * other)
        if isinstance(other, ProcessFork):
            raise ValueError(f"The {type(other)=} cannot be multiplied from LHS of a DFPipeline.")
        if issubclass(type(other), AbstractProcess):
            return ProcessFork([self, other])
        if issubclass(type(other), DFPipeline):
            return ProcessFork([self, other])
        else:
            raise ValueError(f"The {type(other)=} must be an int, a Process, DFPipeline or tuples of both.")

    def process(self, /, **kwargs) -> Dict:
        """Process and return the pipeline.

        All kwargs are default values for any down-stream processes; process
        returned parameters have precedence.
        """
        index = 0
        try:
            payload_kwargs = Dict(**kwargs)
            for index, process in enumerate(self.processes):
                ret: Dict = process(**payload_kwargs)
                # Union the returned payload with previous ones:
                #  1- Process parameters have precedence over the kwargs.
                #  2- The latest process parameters have precedence over the former.
                payload_kwargs |= ret
        except TypeError as e:

            def name(obj) -> str:
                return type(obj).__name__

            if len(e.args) > 0 and (
                "missing 1 required keyword-only argument" in e.args[0]
                or "missing 1 required positional argument" in e.args[0]
            ):
                if index > 0:
                    previous_process = name(self.processes[index - 1])
                else:
                    previous_process = "(input of the pipeline)"
                raise IncompatibleArgsException(
                    f"The process '{name(process)}' received incompatible payload from "
                    f"the previous process '{previous_process}'\n"
                    f"provided arguments: {list(payload_kwargs.keys())}\n"
                    f"e.args={e.args}\n"
                ) from e
            else:
                raise e
        return payload_kwargs


class ProcessLogic(AbstractProcess):
    def __init__(self, logic_callback: Callable[..., Dict]):
        self.logic_callback = logic_callback

    def __call__(self, **kwargs) -> Dict:
        return self.logic_callback(**kwargs)


class ProcessLogicProperty(AbstractProcess):
    def __init__(self, logic_callback: Callable[..., Dict]):
        self.logic_callback = logic_callback
        self.caller_class = None

    def __call__(self, **kwargs) -> Dict:
        return self.logic_callback(self.caller_class, **kwargs)


class ProcessFactory:
    def __init__(self, factory_callback: Callable[..., AbstractProcess]):
        self.factory_callback = factory_callback

    def __call__(self, *args: Any, **kwargs) -> AbstractProcess:
        return self.create(*args, **kwargs)

    def create(self, *args: Any, **kwargs) -> AbstractProcess:
        """Create a parametrised process to be attached and called later."""
        process = self.factory_callback(*args, **kwargs)
        return process


class InputProcess(Process):
    def __call__(self, *, name: str, src: str, package: str, method: str, is_cached: bool = False, **kwargs) -> Dict:
        """Input process to load data from different sources."""
        pkg = importlib.import_module(package)
        func = getattr(pkg, method)
        if is_cached:
            cache_key = (package, method, src)
            if cache_key in cache:
                data = cache[cache_key]
            else:
                data = func(Path(src), **kwargs)
                cache[cache_key] = data
        else:
            data = func(Path(src), **kwargs)
        return Dict({f"{name}": data})


class DFProcess(Process):
    def __call__(
        self,
        *,
        payload: Dict,
        name: str,
        package: str,
        method: str,
        parameters: dict,
        output_dir: str | Path | None = None,
        is_cached: bool = False,
        **kwargs,
    ) -> Dict:
        """DataFrame process that calls ``package.method`` with mapped parameters."""

        def is_hashable(obj):
            try:
                hash(obj)
                return True
            except TypeError:
                return False

        pkg = importlib.import_module(package)
        func = getattr(pkg, method)
        arguments = {}
        for key, value in parameters.items():
            if is_hashable(value) and value in payload:
                arguments[key] = payload[value]
            else:
                arguments[key] = value
        signature = inspect.signature(func)
        if output_dir is not None:
            if "output_dir" in signature.parameters:
                arguments["output_dir"] = output_dir
        if is_cached:
            cache_key = (package, method, name)
            if cache_key in cache:
                data = cache[cache_key]
            else:
                data = func(**arguments)
                cache[cache_key] = data
        else:
            data = func(**arguments)

        return Dict({**{f"{name}": data}, **payload})


class OutputProcess(Process):
    def __call__(self, *, payload: Dict, outputs: dict, **kwargs) -> Dict:
        """Output process to save payload items to their destinations."""
        for name, output_path in outputs.items():
            if isinstance(output_path, list):
                payload_item = payload.get(name)
                if payload_item is None:
                    continue
                for i, output_spec in enumerate(output_path):
                    if isinstance(payload_item[i], DataFrame):
                        payload_item[i].to_csv(output_spec, index=False)
                        continue

                    if isinstance(payload_item, tuple):
                        inner_item = payload_item[i]
                        if isinstance(inner_item, DataFrame):
                            inner_item.to_csv(output_spec, index=False)
                        else:
                            import json

                            class SetEncoder(json.JSONEncoder):
                                def default(self, obj):
                                    if isinstance(obj, set):
                                        return list(obj)
                                    return super().default(obj)

                            if os.path.exists(output_spec):
                                os.remove(output_spec)
                            with open(output_spec, "w") as file:
                                json.dump(inner_item, file, indent=4, cls=SetEncoder)

                        continue

                    raise IncompatibleArgsException(
                        f"OutputProcess cannot handle the type of '{type(payload_item)}' for '{name}'"
                    )

            else:
                payload_item = payload.get(name)
                if payload_item is None:
                    continue

                if isinstance(payload_item, DataFrame):
                    payload_item.to_csv(output_path, index=False)
                    continue

                raise IncompatibleArgsException(
                    f"OutputProcess cannot handle the type of '{type(payload_item)}' for '{name}'"
                )

        return payload


def build_pipeline_from_yaml_string(
    yaml_string: str,
    pipeline_name: str,
    output_dir: str | Path | None = None,
    input_sources: dict[str, str] | None = None,
    input_arg_mapping: dict[str, dict[str, Any]] | None = None,
    process_arg_mapping: dict[str, dict[str, Any]] | None = None,
    output_path_mapping: dict[str, Any] | None = None,
) -> tuple[DFPipeline, dict]:
    """Build a DFPipeline from a YAML configuration string.

    Parameters
    ----------
    yaml_string : str
        YAML configuration as a string.
    pipeline_name : str
        Name of the pipeline to build from the YAML.
    output_dir : str | Path, optional
        Output directory to prepend to all output file paths from YAML.
    input_sources : dict[str, str], optional
        Overrides the ``src`` field in the YAML for the named inputs.
    input_arg_mapping : dict[str, dict[str, Any]], optional
        Per-input parameter overrides, keyed by input name.
    process_arg_mapping : dict[str, dict[str, Any]], optional
        Per-process parameter overrides, keyed by process name.
    output_path_mapping : dict[str, Any], optional
        Per-output path overrides, keyed by output payload name.
    """
    if output_dir is not None:
        output_dir = Path(output_dir)

    config = yaml.safe_load(yaml_string)

    if "pipelines" not in config:
        raise ValueError("YAML must contain 'pipelines' key")

    pipelines = config["pipelines"]

    pipeline_config = None
    for pipeline_dict in pipelines:
        if pipeline_name in pipeline_dict:
            pipeline_config = pipeline_dict[pipeline_name]
            break

    if pipeline_config is None:
        available = [list(p.keys())[0] for p in pipelines]
        raise ValueError(f"Pipeline '{pipeline_name}' not found. Available pipelines: {available}")

    if "Inputs" not in pipeline_config:
        raise ValueError(f"Pipeline '{pipeline_name}' must contain 'Inputs' section")
    if "Processes" not in pipeline_config:
        raise ValueError(f"Pipeline '{pipeline_name}' must contain 'Processes' section")
    if "Outputs" not in pipeline_config:
        raise ValueError(f"Pipeline '{pipeline_name}' must contain 'Outputs' section")

    processes = []

    inputs_config = pipeline_config["Inputs"]
    for input_dict in inputs_config:
        for input_name, input_spec in input_dict.items():
            input_params = {}
            for item in input_spec:
                input_params.update(item)

            if input_sources and input_name in input_sources:
                input_params["src"] = input_sources[input_name]
            if input_arg_mapping and input_name in input_arg_mapping:
                input_params.update(input_arg_mapping[input_name])

            if "src" not in input_params:
                raise ValueError(
                    f"Input '{input_name}' must have 'src' field in YAML or provided via input_sources parameter"
                )
            if "package" not in input_params:
                raise ValueError(f"Input '{input_name}' must have 'package' field")
            if "method" not in input_params:
                raise ValueError(f"Input '{input_name}' must have 'method' field")
            if "is_cached" not in input_params:
                input_params["is_cached"] = False

            def make_input_process(name, params):
                def input_logic(**_kwargs):
                    input_proc = InputProcess()
                    return input_proc(
                        name=name,
                        src=params["src"],
                        package=params["package"],
                        method=params["method"],
                        is_cached=params["is_cached"],
                        **{k: v for k, v in params.items() if k not in ["src", "package", "method", "is_cached"]},
                    )

                return input_logic

            processes.append(ProcessLogic(make_input_process(input_name, input_params)))

    processes_config = pipeline_config["Processes"]
    for process_dict in processes_config:
        for process_name, process_spec in process_dict.items():
            if "package" not in process_spec:
                raise ValueError(f"Process '{process_name}' must have 'package' field")
            if "method" not in process_spec:
                raise ValueError(f"Process '{process_name}' must have 'method' field")
            if "parameters" not in process_spec:
                raise ValueError(f"Process '{process_name}' must have 'parameters' field")

            if process_arg_mapping and process_name in process_arg_mapping:
                arg_overrides = process_arg_mapping[process_name]
                for param_key, override_value in arg_overrides.items():
                    process_spec["parameters"][param_key] = override_value

            def make_df_process(name, spec):
                def df_logic(**kwargs):
                    df_proc = DFProcess()
                    return df_proc(
                        payload=Dict(**kwargs),
                        name=name,
                        package=spec["package"],
                        method=spec["method"],
                        parameters=spec["parameters"],
                        is_cached=spec.get("is_cached", False),
                        output_dir=output_dir,
                    )

                return df_logic

            processes.append(ProcessLogic(make_df_process(process_name, process_spec)))

    outputs_config = pipeline_config["Outputs"]
    outputs_dict = {}
    for output_dict in outputs_config:
        outputs_dict.update(output_dict)
    if output_path_mapping:
        outputs_dict.update(output_path_mapping)

    if output_dir is not None:
        processed_outputs = {}
        for key, value in outputs_dict.items():
            if isinstance(value, list):
                processed_outputs[key] = [str(output_dir / v) for v in value]
            else:
                processed_outputs[key] = str(output_dir / value)
        outputs_dict = processed_outputs

    def output_logic(**kwargs):
        output_proc = OutputProcess()
        return output_proc(payload=Dict(**kwargs), outputs=outputs_dict)

    processes.append(ProcessLogic(output_logic))

    return DFPipeline(processes), pipeline_config


def build_pipeline_from_yaml(
    yaml_path: str | Path,
    pipeline_name: str,
    output_dir: str | Path | None = None,
    input_sources: dict[str, str] | None = None,
    input_arg_mapping: dict[str, dict[str, Any]] | None = None,
    process_arg_mapping: dict[str, dict[str, Any]] | None = None,
    output_path_mapping: dict[str, Any] | None = None,
) -> tuple[DFPipeline, dict]:
    """Build a DFPipeline from a YAML configuration file.

    Thin wrapper over :func:`build_pipeline_from_yaml_string` that reads the
    file at ``yaml_path``.
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"YAML file not found: {yaml_path}")

    with open(yaml_path, encoding="utf-8") as f:
        yaml_string = f.read()

    return build_pipeline_from_yaml_string(
        yaml_string=yaml_string,
        pipeline_name=pipeline_name,
        output_dir=output_dir,
        input_sources=input_sources,
        input_arg_mapping=input_arg_mapping,
        process_arg_mapping=process_arg_mapping,
        output_path_mapping=output_path_mapping,
    )
