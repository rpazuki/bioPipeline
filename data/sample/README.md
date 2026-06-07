# Sample data for Job Definition templates

This folder holds **dummy fixtures** so the Job Definitions page can validate and
preview the fan-out templates (`mapping_fanout`, `preprocess_collate`,
`folders_fanout`) without errors as you edit them.

- `mapping.yaml` — a 2-entry `raw_data_file: metadata_file` mapping read by
  `mapping_file` fan-out. Only this file is read at preview time; the data files
  it names need not exist.
- `processed/group_a`, `processed/group_b` — two empty sub-folders so `folders`
  fan-out has something to enumerate.

These are **placeholders only**. For a real run, point each stage's `mapping:`
and `data_dir:` at your own data folder and submit. Paths in the templates are
relative to where the backend process runs (the repository root).
