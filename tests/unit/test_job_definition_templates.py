import os
from pathlib import Path

import pytest

from bio_pipeline_manager.job_definition import expand, parse_job_definition
from bio_pipeline_manager.job_definition_templates import get_template, list_templates

# Repo root = parents[2] of this file (tests/unit/<file>); fan-out templates
# reference ./data/sample relative to where the backend process runs (repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_templates_are_valid_job_definitions():
    for template in list_templates():
        definition = parse_job_definition(template.content)
        assert definition.name, template.name


def test_templates_preview_without_filesystem_errors(monkeypatch):
    """Every starter template must expand in preview mode (lenient) from the repo
    root — including fan-out templates, whose sample data ships in data/sample."""
    monkeypatch.chdir(_REPO_ROOT)
    for template in list_templates():
        tasks = expand(template.content, lenient=True)
        assert tasks, template.name


def test_fanout_templates_resolve_sample_data(monkeypatch):
    monkeypatch.chdir(_REPO_ROOT)
    # mapping.yaml has 2 raw->meta pairs; processed/ has 2 sub-folders.
    assert len(expand(get_template("mapping_fanout").content, lenient=True)) == 2
    assert len(expand(get_template("folders_fanout").content, lenient=True)) == 2


def test_get_template_by_name():
    template = get_template("empty")

    assert template.name == "empty"
    assert "new_job" in template.content


def test_get_unknown_template_raises():
    with pytest.raises(KeyError):
        get_template("does_not_exist")
