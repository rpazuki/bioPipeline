from bio_pipeline_manager.templates import get_template, list_templates
from bio_pipeline_manager.yaml_validation import validate_labutils_yaml


def test_templates_are_valid_labutils_yaml():
    for template in list_templates():
        report = validate_labutils_yaml(template.content)
        assert report.is_valid, template.name


def test_get_template_by_name():
    template = get_template("empty")

    assert template.name == "empty"
    assert "new_pipeline" in template.content

