from bio_pipeline_manager.yaml_validation import IssueLevel, validate_labutils_yaml


VALID_YAML = """
pipelines:
  - demo:
      Inputs:
        - raw_data:
            - src: ./raw.csv
            - package: pandas
            - method: read_csv
      Processes:
        - df_processed:
            package: labUtils.utils
            method: smart_join_drop_right
            parameters:
              left_df: raw_data
              right_df: raw_data
              on_cols:
                - id
      Outputs:
        - df_processed: processed.csv
"""


def test_validation_summarizes_pipeline():
    report = validate_labutils_yaml(VALID_YAML)

    assert report.is_valid is True
    assert report.pipelines[0].name == "demo"
    assert report.pipelines[0].inputs == ["raw_data"]
    assert report.pipelines[0].processes[0].name == "df_processed"
    assert report.pipelines[0].outputs == ["df_processed"]


def test_validation_warns_about_unknown_payload_reference():
    report = validate_labutils_yaml(
        """
pipelines:
  - demo:
      Inputs: []
      Processes:
        - df_processed:
            package: labUtils.utils
            method: smart_join_drop_right
            parameters:
              left_df: missing_df
      Outputs: []
"""
    )

    assert report.is_valid is True
    assert report.issues[0].level == IssueLevel.WARNING
    assert "missing_df" in report.issues[0].message


def test_import_validation_checks_method_existence():
    report = validate_labutils_yaml(
        """
pipelines:
  - demo:
      Inputs:
        - raw_data:
            - src: ./raw.csv
            - package: pathlib
            - method: missing_method
      Processes: []
      Outputs: []
""",
        validate_imports=True,
    )

    assert report.is_valid is False
    assert any("missing_method" in issue.message for issue in report.issues)
