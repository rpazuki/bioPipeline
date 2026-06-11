# Skill: Extract Pipeline Defaults into Job Definition `process_arg_mapping`

## Goal
Given a Pipeline YAML and an existing Job Definition YAML, read all scalar default parameters from each process, and surface them explicitly in the job's `process_arg_mapping`, preserving all existing comments and adding short inline comments for newly added parameters.

---

## Step-by-Step Plan

### 1. Read all relevant files first — in parallel
Request these simultaneously:
- The target Pipeline YAML (e.g. `fba_pipeline.yaml`)
- The existing Job Definition YAML (e.g. `build_FBA_input_job.yaml`)
- One or two reference Job Definitions that demonstrate the comment/formatting style (e.g. `OD600_growth_rates_ingestion.yaml`, `Multiple_OD600_growth_rates_ingestion_by_pattern.yaml`)

**Pitfall:** Large files may come back `"truncated": true`. If any file is truncated, say so immediately and ask the admin to paste the missing portion directly into chat before proceeding. Do not guess or reconstruct truncated content.

---

### 2. Classify every process parameter
For each process in the pipeline YAML, sort every parameter into one of two buckets:

| Bucket | Criterion | Destination |
|---|---|---|
| **Payload reference** | Value matches the name of an Input or an earlier Process | Skip — do not add to job |
| **Scalar default** | Value is a string literal, number, boolean, or filepath | Add to `process_arg_mapping` |

**Pitfall:** Parameters that are payload references look like plain strings (e.g. `growth_rates_df: growth_data`). Cross-check every value against the list of Input names and Process names before classifying it as a scalar.

---

### 3. Check what the job already passes
For each scalar default found in step 2, check whether the existing `process_arg_mapping` already includes it.

- **Already present** → preserve as-is, including its existing comment.
- **Missing** → add it with a short inline comment (e.g. `# pipeline default — explicit`).

**Pitfall:** Do not duplicate keys. Do not reformat or reorder existing entries.

---

### 4. Decide: scalar vs. variant-driven
For each missing scalar, ask: *does this value differ across variants?*

- **Same across all variants** → add as a plain scalar literal under the process.
- **Differs by variant** → add the field to the `variant` mapping in `variables`, give each variant its value, and reference it as `{variant.field_name}` in `process_arg_mapping`.

**Pitfall:** If the admin has not indicated which values vary, default to plain scalar (same for all variants) and note the assumption explicitly so the admin can correct it.

---

### 5. Handle processes unique to one or more variants
If a process only exists in some variant pipelines (e.g. `df_replicate_stats` only in the replicates pipeline), it is safe to name it in `process_arg_mapping` — the engine ignores it for variants whose pipeline does not include that process.

**Pitfall:** Do not omit variant-specific processes from `process_arg_mapping` out of fear of breaking other variants. Name them freely.

---

### 6. Preserve all comments and formatting
- Copy every existing `#` comment verbatim.
- For newly added parameters, append a short inline comment on the same line.
- Do not reformat indentation, blank lines, or section separators that already exist.

**Pitfall:** YAML editors and LLMs tend to strip comments. Treat comment preservation as a hard requirement, not a nice-to-have.

---

### 7. Show the result — do not save yet
Present the full updated Job Definition in a code block. Summarise only what changed in a small table:

| Process | Parameter | Action | Reason |
|---|---|---|---|
| `mapping_df` | `halt_on_error` | Added | Pipeline default `false`, now explicit |
| `mapping_df` | `verbose` | Added | Pipeline default `true`, now explicit |

Ask the admin to confirm before saving.

---

## What to Tell the Admin Up Front (Prompt Template)

> "Please share or confirm:
> 1. The exact Pipeline YAML name in the store.
> 2. The exact Job Definition YAML name to update.
> 3. Any reference job(s) whose comment/formatting style to follow.
> 4. Whether any of the pipeline's scalar defaults should vary by variant (if unsure, I will default to plain scalars and flag them).
> 5. If any file comes back truncated, paste the missing section here before I proceed."

---

## Known Pitfalls Summary

| Pitfall | Mitigation |
|---|---|
| Truncated tool response | Detect `"truncated": true`, stop, ask admin to paste missing content |
| Payload refs misclassified as scalars | Cross-check every value against Input + Process name list |
| Duplicate keys in `process_arg_mapping` | Diff existing keys before adding |
| Stripping existing comments | Treat comments as required content, not optional |
| Assuming scalar when value varies by variant | Flag assumption explicitly, let admin correct |
| Guessing `output_dir` when truncated | Ask admin to confirm path rather than invent one |
| Saving before admin confirms | Always show full result first; save only on explicit go-ahead |