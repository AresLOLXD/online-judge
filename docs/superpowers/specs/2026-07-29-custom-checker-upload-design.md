# Custom Python Checker Upload

## Problem

The "problem data" admin page (`templates/problem/data.html`, backed by
`judge/views/problem_data.py`) lets a problem editor pick a checker from a
fixed list of built-ins (`CHECKERS` in `judge/models/problem_data.py`:
`standard`, `floats`, `floatsabs`, `floatsrel`, `rstripped`, `sorted`,
`identical`, `linecount`). There is no way to use a problem-specific custom
checker script: the form has no field for it, and if a custom checker
script is bundled inside the uploaded test-data zip, it is silently
ignored — the site never inspects zip contents beyond matching test case
filenames.

This forces editors of problems needing custom grading logic (e.g.
non-strict output comparison, multiple valid answers) to manage
`init.yml` by hand outside the web UI, defeating the purpose of the admin
page.

## Design

### Data model

Add a `checker_file` field to `ProblemData`
(`judge/models/problem_data.py`), mirroring the existing `generator`
field exactly:

```python
checker_file = models.FileField(verbose_name=_('custom checker file'), storage=problem_data_storage,
                                null=True, blank=True, upload_to=problem_directory_file)
```

- Same storage (`problem_data_storage`) and `upload_to` convention as
  `generator` and `zipfile` — lives at `<problem.code>/<basename>`.
- Included in `ProblemData._update_code()` alongside `generator`, so
  renaming a problem's code also relocates the checker file.
- New migration `0153_problemdata_checker_file.py`, following the
  existing `AddField` pattern used for single-field additions
  (see `0151_submission_is_archived.py` for style).
- **Dataset-level only.** `ProblemTestCase` (per-case checker override)
  is untouched — no `checker_file` there, and the per-case checker
  dropdown does not gain a "custom" option (see Form section).

### Form and validation (`judge/views/problem_data.py`)

`ProblemDataForm` (dataset-level form) changes:

- The `checker` field is overridden with an explicit
  `forms.ChoiceField(choices=CHECKERS + CUSTOM_CHECKER_CHOICE)` where
  `CUSTOM_CHECKER_CHOICE = (('custom', _('Custom (Python script)')),)`.
  This is a form-level override, not a model-level change to `CHECKERS`,
  so `ProblemCaseForm` (which renders the per-case checker field straight
  from the model's `choices`) never offers "custom".
- `checker_file` is added to `Meta.fields`.
- `clean_checker_file()`:
  - Rejects the filename `init.yml` (same rule as `clean_generator`).
  - Requires a `.py` extension.
  - Runs the dangerous-pattern scan (below); raises `ValidationError`
    listing the offending names if any are found.
- `clean()` (form-level): if the resolved `checker` is `'custom'`, a
  `checker_file` must be present (either newly uploaded or already
  attached to the instance) — else `ValidationError`. If `checker` is
  anything else, any uploaded `checker_file` is cleared/ignored (matches
  how `checker_args` is discarded when `checker` is empty in
  `ProblemDataCompiler.make_init`).

### Dangerous-pattern scan

A new helper, e.g. `judge/utils/problem_data.py::scan_checker_source(source: bytes) -> list[str]`:

- Parses the uploaded file with `ast.parse()` — the file is **never
  executed or imported** by the Django app, only statically parsed.
- Walks the AST and collects (does not execute) any occurrence of:
  - `import` / `from ... import` of: `os`, `subprocess`, `sys`,
    `socket`, `shutil`, `ctypes`, `importlib`, `multiprocessing`,
    `threading`, `requests`, `urllib`, `http`, `ftplib`, `telnetlib`,
    `pty`, `pickle`, `marshal`, `code`.
  - Calls to the builtins `eval`, `exec`, `compile`, `__import__`.
- If the list is non-empty, `clean_checker_file()` raises a
  `ValidationError` naming each match (module/builtin name), rejecting
  the upload outright — no override path.
- A `SyntaxError` from `ast.parse()` (invalid Python) is also surfaced as
  a `ValidationError` (the file isn't a valid checker anyway).

**Known limitation (documented, not solved by this design):** this is
static, best-effort detection, not a sandbox. It can be defeated by
obfuscation (e.g. building a module name from string concatenation before
calling `__import__`). Its purpose is to catch obvious/copy-pasted
malicious code, not to provide a real security boundary. The actual trust
boundary is unchanged by this feature: only users passing
`Problem.is_editable_by()` (superusers, users with
`edit_all_problem`/`edit_public_problem`, problem authors/curators, or
org admins for org-private problems) can reach this form at all — the
same population that can already upload an unscanned `generator` script
today, which runs judge-side with no restriction whatsoever. This feature
does not change that existing trust model or retroactively add scanning
to `generator`.

### init.yml generation (`judge/utils/problem_data.py`)

In `ProblemDataCompiler.make_init()`, the dataset-level checker block
(current lines ~205-208) changes: when `self.data.checker == 'custom'`,
instead of writing the literal string `'custom'`, resolve
`self.data.checker_file`'s path the same way `self.generator` is resolved
(`split_path_first`, existing lines ~175-179) and write that relative
filename as the checker value — i.e. `init['checker'] = '<filename>.py'`
(optionally wrapped with `checker_args` via the existing `make_checker()`
helper, unchanged). This matches the documented `init.yml` format where a
checker's `name` is either a built-in identifier or a filename resolved
relative to the problem's data directory (same resolution judge-server
already applies to `archive`/`generator`).

### UI (`templates/problem/data.html`)

- `checker_file` renders next to the dataset-level `checker` dropdown
  (table row, same as other `data_form` fields via `as_table()` —
  no bespoke markup needed for the raw input).
- Extend the existing inline JS `checker_precision($checker)` (lines
  ~65-96) with the same show/hide pattern already used for the `floats`
  precision field: when the dataset-level checker `<select>` value is
  `custom`, reveal the `checker_file` upload row; otherwise hide it.

### Tests

No test coverage exists today for this view/form/compiler. Add
`judge/utils/tests/test_problem_data.py` covering:

- `scan_checker_source()`: returns `[]` for a clean checker; returns
  matches for each blacklisted import and each blacklisted builtin call;
  raises/reports on invalid Python syntax.
- `ProblemDataForm`: `checker='custom'` without `checker_file` fails
  validation; `checker='custom'` with a clean `.py` file passes; a file
  containing a blacklisted import is rejected with a `ValidationError`.
- `ProblemDataCompiler.make_init()`: with `checker='custom'` and a
  `checker_file` set, the generated `init['checker']` is the checker
  file's relative filename.

## Out of scope

- Reading/importing an `init.yml` bundled inside the uploaded test-data
  zip. The compiler continues to always regenerate `init.yml` from the
  form; any `init.yml` inside the zip is ignored, same as today. (This
  was considered and explicitly deferred — the checker pain point is
  fully addressed by the separate `checker_file` upload field above.)
- Per-test-case custom checker override (`ProblemTestCase` is untouched).
- Sandboxing or scanning of the existing `generator` script field, or any
  runtime/execution-time protection on the judge-server side — both are
  unchanged by this design.
- Supporting non-Python (e.g. compiled/`bridged`) custom checkers.
- File size limits on `checker_file` beyond whatever Django/the web
  server already enforce globally (no precedent for per-field size limits
  exists elsewhere in this codebase either).
