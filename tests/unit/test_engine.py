"""Direct tests for the transferred pipeline engine (pipeline/engine.py)."""

import sys
import types

import pandas as pd
import pytest

from pipeline import engine
from pipeline.engine import (
    DFPipeline,
    DFProcess,
    Dict,
    IncompatibleArgsException,
    InputProcess,
    OutputProcess,
    ProcessFork,
    ProcessJoined,
    ProcessLogic,
    build_pipeline_from_yaml_string,
)


@pytest.fixture
def fake_mod():
    """A throwaway module resolvable via importlib for package:method refs."""
    mod = types.ModuleType("eng_fake")

    def head(df, n=2):
        return df.head(n)

    def needs_dir(data, output_dir=None):
        return {"data": data, "dir": str(output_dir)}

    mod.head = head
    mod.needs_dir = needs_dir
    sys.modules["eng_fake"] = mod
    engine.cache.clear()
    try:
        yield mod
    finally:
        del sys.modules["eng_fake"]
        engine.cache.clear()


# --------------------------------------------------------------------------- #
# InputProcess
# --------------------------------------------------------------------------- #
def test_input_process_loads_via_package_method(tmp_path):
    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(csv, index=False)

    out = InputProcess()(name="raw", src=str(csv), package="pandas", method="read_csv")

    assert list(out["raw"]["a"]) == [1, 2, 3]


def test_input_process_caches_by_src(tmp_path):
    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": [1]}).to_csv(csv, index=False)
    engine.cache.clear()

    first = InputProcess()(name="raw", src=str(csv), package="pandas", method="read_csv", is_cached=True)
    # Overwrite the file; a cached read must still return the original frame.
    pd.DataFrame({"a": [9, 9, 9]}).to_csv(csv, index=False)
    second = InputProcess()(name="raw", src=str(csv), package="pandas", method="read_csv", is_cached=True)

    assert list(first["raw"]["a"]) == [1]
    assert list(second["raw"]["a"]) == [1]
    engine.cache.clear()


# --------------------------------------------------------------------------- #
# DFProcess
# --------------------------------------------------------------------------- #
def test_df_process_maps_payload_reference_and_preserves_payload(fake_mod):
    payload = Dict(raw=pd.DataFrame({"x": [0, 1, 2, 3]}))

    out = DFProcess()(
        payload=payload,
        name="topped",
        package="eng_fake",
        method="head",
        parameters={"df": "raw", "n": 2},
    )

    assert len(out["topped"]) == 2  # n=2 was passed literally
    assert "raw" in out  # original payload is preserved downstream


def test_df_process_resolves_dict_of_references(fake_mod):
    """A dict-valued parameter resolves each item against the payload, keeping keys."""

    def gather(paths):
        return paths

    fake_mod.gather = gather
    payload = Dict(org_1_file="/data/org1.xml", org_2_file="/data/org2.xml")

    out = DFProcess()(
        payload=payload,
        name="gathered",
        package="eng_fake",
        method="gather",
        parameters={"paths": {"organism_1": "org_1_file", "organism_2": "org_2_file"}},
    )

    assert out["gathered"] == {"organism_1": "/data/org1.xml", "organism_2": "/data/org2.xml"}


def test_df_process_resolves_list_of_references(fake_mod):
    """A list-valued parameter resolves each item against the payload, keeping order."""

    def gather(paths):
        return paths

    fake_mod.gather = gather
    payload = Dict(org_1_file="/data/org1.xml", org_2_file="/data/org2.xml")

    out = DFProcess()(
        payload=payload,
        name="gathered",
        package="eng_fake",
        method="gather",
        parameters={"paths": ["org_1_file", "org_2_file"]},
    )

    assert out["gathered"] == ["/data/org1.xml", "/data/org2.xml"]


def test_df_process_leaves_non_reference_container_items_literal(fake_mod):
    """Items in a container that are not payload keys pass through unchanged."""

    def gather(paths):
        return paths

    fake_mod.gather = gather
    payload = Dict(org_1_file="/data/org1.xml")

    out = DFProcess()(
        payload=payload,
        name="gathered",
        package="eng_fake",
        method="gather",
        parameters={"paths": {"a": "org_1_file", "b": "not_a_key", "c": 5}},
    )

    assert out["gathered"] == {"a": "/data/org1.xml", "b": "not_a_key", "c": 5}


def test_df_process_injects_output_dir_when_supported(fake_mod):
    out = DFProcess()(
        payload=Dict(),
        name="r",
        package="eng_fake",
        method="needs_dir",
        parameters={"data": "literal"},
        output_dir="/tmp/o",
    )

    assert out["r"]["data"] == "literal"  # not in payload -> passed literally
    assert out["r"]["dir"] == "/tmp/o"


# --------------------------------------------------------------------------- #
# OutputProcess
# --------------------------------------------------------------------------- #
def test_output_process_writes_single_dataframe(tmp_path):
    OutputProcess()(payload=Dict(result=pd.DataFrame({"a": [1, 2]})), outputs={"result": str(tmp_path / "r.csv")})
    assert list(pd.read_csv(tmp_path / "r.csv")["a"]) == [1, 2]


def test_output_process_writes_list_of_dataframes(tmp_path):
    payload = Dict(pair=[pd.DataFrame({"a": [1]}), pd.DataFrame({"b": [2]})])
    OutputProcess()(payload=payload, outputs={"pair": [str(tmp_path / "p0.csv"), str(tmp_path / "p1.csv")]})
    assert (tmp_path / "p0.csv").exists()
    assert (tmp_path / "p1.csv").exists()


def test_output_process_skips_missing_payload_key(tmp_path):
    OutputProcess()(payload=Dict(), outputs={"absent": str(tmp_path / "x.csv")})
    assert not (tmp_path / "x.csv").exists()


def test_output_process_rejects_unsupported_type():
    with pytest.raises(IncompatibleArgsException):
        OutputProcess()(payload=Dict(result=123), outputs={"result": "x.csv"})


def test_output_process_writes_text(tmp_path):
    OutputProcess()(payload=Dict(message="Generated numbers: [1, 2, 3]"), outputs={"message": str(tmp_path / "message.txt")})
    assert (tmp_path / "message.txt").read_text(encoding="utf-8") == "Generated numbers: [1, 2, 3]"


# --------------------------------------------------------------------------- #
# build_pipeline_from_yaml_string — validation
# --------------------------------------------------------------------------- #
def test_build_requires_pipelines_key():
    with pytest.raises(ValueError, match="pipelines"):
        build_pipeline_from_yaml_string("foo: bar\n", "p")


def test_build_pipeline_not_found():
    text = "pipelines:\n  - a:\n      Inputs: []\n      Processes: []\n      Outputs: []\n"
    with pytest.raises(ValueError, match="not found"):
        build_pipeline_from_yaml_string(text, "missing")


def test_build_requires_inputs_section():
    text = "pipelines:\n  - a:\n      Processes: []\n      Outputs: []\n"
    with pytest.raises(ValueError, match="Inputs"):
        build_pipeline_from_yaml_string(text, "a")


def test_build_requires_input_src():
    text = (
        "pipelines:\n"
        "  - a:\n"
        "      Inputs:\n"
        "        - raw:\n"
        "            - package: pandas\n"
        "            - method: read_csv\n"
        "      Processes: []\n"
        "      Outputs: []\n"
    )
    with pytest.raises(ValueError, match="src"):
        build_pipeline_from_yaml_string(text, "a")


# --------------------------------------------------------------------------- #
# Full build + run (input -> process -> output, with output_dir prepend)
# --------------------------------------------------------------------------- #
def test_build_and_run_full_pipeline(tmp_path, fake_mod):
    csv = tmp_path / "in.csv"
    pd.DataFrame({"x": [0, 1, 2, 3]}).to_csv(csv, index=False)
    text = f"""
pipelines:
  - p:
      Inputs:
        - raw:
            - src: {csv.as_posix()}
            - package: pandas
            - method: read_csv
      Processes:
        - topped:
            package: eng_fake
            method: head
            parameters:
              df: raw
              n: 2
      Outputs:
        - topped: out.csv
"""
    pipe, _config = build_pipeline_from_yaml_string(text, "p", output_dir=str(tmp_path))
    result = pipe()

    assert "topped" in result
    written = tmp_path / "out.csv"  # output_dir prepended to "out.csv"
    assert written.exists()
    assert len(pd.read_csv(written)) == 2


def test_incompatible_args_raises_helpful_error(fake_mod):
    # `head` needs `df`, but no parameters are supplied.
    text = """
pipelines:
  - p:
      Inputs: []
      Processes:
        - topped:
            package: eng_fake
            method: head
            parameters: {}
      Outputs: []
"""
    pipe, _ = build_pipeline_from_yaml_string(text, "p")
    with pytest.raises(IncompatibleArgsException):
        pipe()


# --------------------------------------------------------------------------- #
# Fork / join / composition operators
# --------------------------------------------------------------------------- #
def test_rshift_builds_pipeline_and_runs():
    p1 = ProcessLogic(lambda **k: Dict(a=1))
    p2 = ProcessLogic(lambda **k: Dict(b=2))
    pipe = p1 >> p2
    assert isinstance(pipe, DFPipeline)
    result = pipe()
    assert result["a"] == 1 and result["b"] == 2


def test_fork_returns_tuple_and_join_unions():
    p1 = ProcessLogic(lambda **k: Dict(a=1))
    p2 = ProcessLogic(lambda **k: Dict(b=2))
    fork = p1 * p2
    assert isinstance(fork, ProcessFork)

    parts = fork()
    assert parts[0]["a"] == 1 and parts[1]["b"] == 2

    merged = ProcessJoined(fork)()
    assert merged["a"] == 1 and merged["b"] == 2


def test_multiply_by_int_replicates():
    p1 = ProcessLogic(lambda **k: Dict(a=1))
    fork = p1 * 3
    assert isinstance(fork, ProcessFork)
    assert len(fork.processes) == 3
