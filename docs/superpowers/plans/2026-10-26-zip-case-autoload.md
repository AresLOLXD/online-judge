# Auto-load Test Cases from the Data Zip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uploading a data zip on the problem data page sets up the cases from a bundled `init.yml` (or from file pairs when the problem has no cases), and the page explains the upload flow and the rejudge consequences.

**Architecture:** Pure helpers in `judge/utils/problem_data.py` read and parse the zip's `init.yml` and pair file names; one DB function applies the result to a problem; `ProblemDataView.post()` calls it after the existing saves and before `ProblemDataCompiler.generate()`. `data.html` gets a help box, a rejudge notice linking to the existing Manage submissions page, and the flash messages include.

**Tech Stack:** Django (Jinja2 templates), PyYAML (`yaml.safe_load`), `zipfile`, Django `TestCase`/`SimpleTestCase`, MySQL test DB from `dmoj/local_settings.py`.

**Spec:** `docs/superpowers/specs/2026-10-26-zip-case-autoload-design.md`

## Global Constraints

- Work on branch `feat/zip-case-autoload`. Commits follow Conventional Commits, end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push; pushing to `origin` (the fork, never `upstream`) needs the user's OK.
- Code, comments and commit messages in English. `flake8` clean (120 cols, single quotes, trailing commas, pycharm import order).
- Every user-facing string goes through `gettext` (`_`, `ngettext` in Python; `_()` in Jinja2). Do not edit `locale/`.
- `yaml.safe_load` only. `init.yml` is read only from the exact zip root entry `init.yml`, rejected above `1 << 20` bytes (checked via `ZipInfo.file_size` before reading); mark the limit with a `# shortcut:` comment.
- `judge.models` imports `judge.utils.problem_data`, so import models (`ProblemTestCase`, `CHECKERS`) inside functions, as `ProblemDataCompiler.compile` does.
- Existing cases are never touched when the zip has no `init.yml`. The compiler (`make_init`, `compile`) and the generated `init.yml` format are not changed.
- Batch `dependencies` are imported as written, no renumbering (add `# shortcut:` comment).
- Tests that write files must run with `@override_settings(MEDIA_ROOT=<temp dir>)` (`DMOJ_PROBLEM_DATA_ROOT` is `None`, so `problem_data_storage` falls back to `MEDIA_ROOT`). Assert `problem_data_storage.location` equals the temp dir once; if it does not, patch `problem_data_storage._location` instead.
- Run tests with `python manage.py test <dotted.path>`.

## Review Focus

- `init.yml` that is empty, a list, or a scalar: error, no rows change (Task 1, Task 2).
- `init.yml` over 1 MiB, or only at `sub/init.yml`: oversized rejected before reading; nested ignored (Task 1).
- Zips made on macOS contain `__MACOSX/._1.in` / `._1.out`: must not become cases (Task 1).
- File names longer than 100 chars (the `input_file`/`output_file` column limit): error from the yaml, treated as unpaired for file pairing (Task 1).
- Zip with no pairs or an empty problem and no yaml: no rows, no crash, only warnings (Task 2).

---

### Task 1: Zip reading, yaml parsing and file pairing helpers

**Files:**
- Modify: `judge/utils/problem_data.py` (new module-level functions after `ProblemDataError`)
- Test: `judge/utils/tests/test_problem_data.py` (new `SimpleTestCase` classes; helper `make_zip(files: dict) -> ZipFile` building an in-memory zip)

**Interfaces:**
- Produces:
  - `INIT_YML_NAME = 'init.yml'`, `MAX_INIT_YML_SIZE = 1 << 20`
  - `ParsedInit = namedtuple('ParsedInit', 'cases settings warnings')`: `cases` is `None` or a list of dicts keyed by `ProblemTestCase` field names (`order, type, input_file, output_file, points, is_pretest, output_limit, output_prefix, checker, checker_args, generator_args, batch_dependencies`); `settings` is a dict keyed by `ProblemData` field names (`output_limit, output_prefix, unicode, nobigmath, checker, checker_args`); `warnings` is a list of strings.
  - `read_zip_init_yml(zip_file: ZipFile) -> Optional[dict]`: `None` if there is no root `init.yml`; raises `ProblemDataError` if oversized, not parseable, or not a mapping.
  - `parse_init(init: dict) -> ParsedInit`: raises `ProblemDataError` for a non-int `points`/limit/dependency, a non-mapping entry, or an `in`/`out` name over 100 chars.
  - `pair_zip_files(names: Iterable[str]) -> Tuple[List[Tuple[str, str]], List[str]]`: `(pairs, unpaired)`.

- [ ] **Step 1: Write the failing tests** in `judge/utils/tests/test_problem_data.py` (import the new names from `judge.utils.problem_data`):
  - `test_read_returns_none_without_root_init`: zip with only `sub/init.yml` → `None`.
  - `test_read_parses_mapping`: `init.yml` = `test_cases:\n- {in: 1.in, out: 1.out, points: 10}\n` → `{'test_cases': [{'in': '1.in', 'out': '1.out', 'points': 10}]}`.
  - `test_read_rejects_oversized`: `init.yml` of `MAX_INIT_YML_SIZE + 1` bytes → `ProblemDataError`.
  - `test_read_rejects_non_mapping_and_invalid_yaml`: `'- 1\n- 2'`, `''` and `': [\n'` each → `ProblemDataError`.
  - `test_parse_normal_and_pretest_cases`: `{'pretest_test_cases': [{'in': 's.in', 'out': 's.out', 'points': 0}], 'test_cases': [{'in': '1.in', 'out': '1.out', 'points': 10}]}` → `cases[0] == {'order': 1, 'type': 'C', 'input_file': 's.in', 'output_file': 's.out', 'points': 0, 'is_pretest': True, 'output_limit': None, 'output_prefix': None, 'checker': '', 'checker_args': '', 'generator_args': '', 'batch_dependencies': ''}`; `cases[1]` has `order` 2, `is_pretest` False, `points` 10.
  - `test_parse_batch`: `{'test_cases': [{'points': 30, 'dependencies': [1, 2], 'batched': [{'in': 'a.in', 'out': 'a.out'}]}]}` → types `['S', 'C', 'E']`, S has `points` 30 and `batch_dependencies` `'1,2'`, the C row has `points` None and its files.
  - `test_parse_generator_args_and_per_case_checker`: entry with `generator_args: ['1', '2']` → `'1\n2'`; `checker: {name: floats, args: {precision: 4}}` → `checker 'floats'`, `checker_args '{"precision": 4}'`.
  - `test_parse_dataset_settings_only_for_present_keys`: `{'checker': {'name': 'floats', 'args': {'precision': 4}}, 'output_limit_length': 100, 'hints': ['unicode']}` → `cases is None`, `settings == {'checker': 'floats', 'checker_args': '{"precision": 4}', 'output_limit': 100, 'unicode': True, 'nobigmath': False}`; `parse_init({})` → `ParsedInit(None, {}, [])`.
  - `test_parse_ignored_keys_warn`: `{'archive': 'x.zip', 'checker': 'weird.py', 'test_cases': []}` → some warning contains `'archive'`, some contains `'weird.py'`, `settings` has no `checker`.
  - `test_parse_rejects_bad_values`: `points: 'abc'`, and an `in` name of 101 chars → `ProblemDataError`.
  - `test_pair_zip_files`: names `['10.in', '10.out', '2.in', '2.out', 'init.yml', 'data/', '__MACOSX/._2.in', '__MACOSX/._2.out', 'x.in', 'x.ans', 'a' * 101 + '.in']` → pairs `[('2.in', '2.out'), ('10.in', '10.out')]`, unpaired `['x.ans', 'x.in', 'a' * 101 + '.in']` (natural order; over-long names are unpaired).

- [ ] **Step 2: Run to verify failure:** `python manage.py test judge.utils.tests.test_problem_data` → ImportError / FAIL.

- [ ] **Step 3: Implement the three functions** in `judge/utils/problem_data.py`. Parsing is the inverse of `ProblemDataCompiler.make_init()` (spec mapping table): pretest list first then test list, `order` from 1; a `batched` entry yields an `S` row, one `C` row per item, an `E` row; unknown keys (top-level and entry-level) are collected into one sorted warning, and an unsupported checker name into another; a checker is valid when its name is in `judge.models.problem_data.CHECKERS`. Pairing reuses the page's rule (`re.sub(r'in(?!.*?in)', 'out', name)` when the result is in the set), skips directory entries, `init.yml`, anything under `__MACOSX/` and names over 100 chars, and sorts naturally (`re.split(r'(\d+)', name)` with digits as ints).

- [ ] **Step 4: Run to verify pass:** same command → all PASS; `flake8 judge/utils` clean.

- [ ] **Step 5: Commit**

```bash
git add judge/utils/problem_data.py judge/utils/tests/test_problem_data.py
git commit -m "feat(problem-data): parse bundled init.yml and pair zip files"
```

---

### Task 2: Apply a zip to a problem

**Files:**
- Modify: `judge/utils/problem_data.py`
- Test: `judge/utils/tests/test_problem_data.py` (new `TestCase`; helper `make_zip_path(files: dict) -> str` writing a zip to a temp file and registering cleanup)

**Interfaces:**
- Consumes: `read_zip_init_yml`, `parse_init`, `pair_zip_files`, `ParsedInit` (Task 1).
- Produces: `import_cases_from_zip(problem: Problem, data: ProblemData, zip_path: str) -> List[str]`: returns warning strings; raises `ProblemDataError` (before any DB change) when the zip's `init.yml` is unusable; all writes in one `transaction.atomic()`.

Behavior (spec "Behavior"): with a root `init.yml`: if `parsed.cases is not None`, delete `problem.cases` and `bulk_create` the new rows (`dataset=problem`); set each key of `parsed.settings` on `data` and `data.save()`; return `parsed.warnings`. Without `init.yml`: if `problem.cases` exists, add nothing and return a warning with the count of zip files no case uses (`ngettext`); if it is empty and `data.generator` is falsy, create `C` rows from `pair_zip_files` (`order` from 1, `points` None, `is_pretest` False) and return a warning with the unpaired count when non-zero; if a generator is set, do nothing.

- [ ] **Step 1: Write the failing tests** (`create_user`, `create_problem_type`, `create_problem` from `judge.models.tests.util`; `data = ProblemData.objects.create(problem=problem)`):
  - `test_round_trip`: create rows (pretest `C` first; then `S` points 30, two `C` with one `checker='floats'`/`checker_args='{"precision": 4}'`, `E`; then `S` with `batch_dependencies='1'`, `C`, `E`; then a plain `C` with `output_limit=5`), run `ProblemDataCompiler(problem, data, problem.cases.order_by('order'), files).make_init()`, `yaml.safe_dump` it into a zip's `init.yml` together with the case files, import it into a second problem, and assert both problems' rows are equal on all fields except `id`/`dataset`.
  - `test_init_yml_replaces_cases`: existing row with `input_file='old.in'`; zip `init.yml` has one case `1.in/1.out/points 7` → exactly one row, `input_file == '1.in'`.
  - `test_absent_dataset_keys_keep_values`: `data.output_limit = 9` and `checker='standard'` saved; `init.yml` only has `test_cases` → both unchanged.
  - `test_init_yml_without_cases_keeps_rows`: `init.yml` = `output_limit_length: 3` → rows unchanged, `data.output_limit == 3`.
  - `test_no_yaml_empty_problem_registers_pairs`: files `2.in 2.out 10.in 10.out` → rows `(order 1, '2.in', '2.out')`, `(2, '10.in', '10.out')`, all `type 'C'`, `points None`, `is_pretest False`; empty zip → no rows, no exception.
  - `test_no_yaml_with_cases_adds_nothing`: row using `1.in/1.out`, zip also has `2.in/2.out` → still one row, returned warnings contain `'2'` (count of unused files = 2).
  - `test_unpaired_files_warn`: files `1.in 1.out x.ans` on an empty problem → one row and a warning mentioning `1` unpaired file.
  - `test_generator_skips_registration`: `data.generator.name = 'code/gen.py'` saved, empty problem, pair files in zip → no rows.
  - `test_invalid_yaml_changes_nothing`: existing row, zip `init.yml` = `'- 1'` → `ProblemDataError`, row unchanged.

- [ ] **Step 2: Run to verify failure:** `python manage.py test judge.utils.tests.test_problem_data` → new tests FAIL (name not defined).

- [ ] **Step 3: Implement `import_cases_from_zip`** in `judge/utils/problem_data.py` as specified above (open the zip with `ZipFile(zip_path)`).

- [ ] **Step 4: Run to verify pass:** same command → all PASS; `flake8 judge/utils` clean.

- [ ] **Step 5: Commit**

```bash
git add judge/utils/problem_data.py judge/utils/tests/test_problem_data.py
git commit -m "feat(problem-data): apply zip contents to a problem's cases"
```

---

### Task 3: Hook into the data view

**Files:**
- Modify: `judge/views/problem_data.py` (`ProblemDataView.post`, lines ~247-268), `templates/problem/data.html` (add `{% include "messages.html" %}` as the first line inside `{% block body %}`)
- Test: `judge/views/tests/test_problem_data_view.py` (new)

**Interfaces:**
- Consumes: `import_cases_from_zip`, `ProblemDataError` (Task 2).

In `post()`, after the existing case saves/deletes and before `ProblemDataCompiler.generate(...)`: when `'problem-data-zipfile' in request.FILES`, call `import_cases_from_zip(problem, data, data.zipfile.path)`; on success send each returned warning through `messages.warning(request, w)`; on `ProblemDataError` remember `e.message`. After `generate(...)`, if an error was remembered, set `data.feedback` to it and `data.save(update_fields=['feedback'])` (so the existing feedback box shows it). A POST without a new zip never calls the import.

- [ ] **Step 1: Write the failing tests** in `judge/views/tests/test_problem_data_view.py`: `TestCase` decorated with `@override_settings(MEDIA_ROOT=<tempdir>)`; a superuser (`create_user(username='admin', is_superuser=True, is_staff=True)`) logged in with `self.client.force_login`; POST to `reverse('problem_data', args=[problem.code])` with `SimpleUploadedFile('data.zip', <zip bytes>)` as `problem-data-zipfile`, plus `problem-data-output_limit`, `problem-data-output_prefix`, `problem-data-checker`, `problem-data-checker_args` all `''`, and the formset management form `cases-TOTAL_FORMS='0'`, `cases-INITIAL_FORMS='0'`, `cases-MIN_NUM_FORMS='0'`, `cases-MAX_NUM_FORMS='1000'`; use `follow=True`.
  - `test_yaml_zip_creates_cases_and_init`: zip with `init.yml` (one case, points 10) plus `1.in`/`1.out` → one `ProblemTestCase`, `problem_data_storage.exists('<code>/init.yml')` is true, `ProblemData.feedback == ''`.
  - `test_zip_without_yaml_registers_pairs_and_asks_for_points`: `1.in/1.out` → one row with `points is None`; `ProblemData.feedback` contains `'Points must be defined'`.
  - `test_invalid_yaml_shows_error_and_keeps_cases`: existing row, zip `init.yml` = `'- 1'` → row unchanged, `ProblemData.feedback` non-empty, the zip file exists on disk.
  - `test_warnings_are_shown`: zip with `1.in 1.out x.ans` → the followed response contains `x.ans`'s unpaired warning text (assert on the count wording via `assertContains(response, 'not paired')` or whichever literal Task 2 used; keep them in sync).
  - `test_post_without_zip_applies_nothing`: first POST uploads a zip with `init.yml` (2 cases); delete one row; second POST without a file → one row remains.

- [ ] **Step 2: Run to verify failure:** `python manage.py test judge.views.tests.test_problem_data_view` → FAIL.

- [ ] **Step 3: Implement the `post()` change and the messages include** as specified. Import `messages` from `django.contrib` and the new names from `judge.utils.problem_data` (keep import order).

- [ ] **Step 4: Run to verify pass:** the new module plus `judge.views.tests.test_problem_data_form` → PASS; `flake8 judge/views` clean.

- [ ] **Step 5: Commit**

```bash
git add judge/views/problem_data.py templates/problem/data.html judge/views/tests/test_problem_data_view.py
git commit -m "feat(problem-data): import cases from the uploaded zip on save"
```

---

### Task 4: Help box and rejudge notice

**Files:**
- Modify: `templates/problem/data.html` (new block at the top of `{% block body %}`, below the messages include and above the feedback box)
- Test: `judge/views/tests/test_problem_data_view.py` (add)

**Interfaces:**
- Produces: two elements in the page, `<div id="data-help">` and `<div id="rejudge-notice">`; inside the latter, `<a id="rejudge-link" href="{{ url('problem_manage_submissions', problem.code) }}">` rendered only under `{% if problem.is_subs_manageable_by(request.user) %}`.

Copy (all through `_()`; wording and styling are the builder's, in the style of the page): `data-help` explains how to upload the cases, that including an `init.yml` in the zip is faster and replaces the current cases, that a new zip replaces the previous one so it must contain all cases, and that the checker and the other settings are configured below. `rejudge-notice` states that changing cases does not rejudge existing submissions and lists what a rejudge does (spec "Rejudge notice": queue at batch priority, verdict/points/per-case results overwritten with the revision recorded, user points/problem stats/contest scores recalculated, submissions locked by a finished contest archived instead).

- [ ] **Step 1: Write the failing tests** (same fixtures as Task 3, GET `reverse('problem_data', args=[code])`):
  - `test_page_has_help_and_rejudge_text`: superuser response contains `id="data-help"` and `id="rejudge-notice"`.
  - `test_rejudge_link_for_subs_manager`: superuser response contains `id="rejudge-link"` and `reverse('problem_manage_submissions', args=[code])`.
  - `test_no_rejudge_link_without_permission`: a non-staff author (`create_user(username='author', user_permissions=['edit_own_problem'])`, listed in the problem's `authors`) gets 200, the `rejudge-notice` text, and no `id="rejudge-link"`.

- [ ] **Step 2: Run to verify failure:** `python manage.py test judge.views.tests.test_problem_data_view` → new tests FAIL.

- [ ] **Step 3: Implement the two blocks in `data.html`** as specified.

- [ ] **Step 4: Run to verify pass, then the whole check:** `python manage.py test judge.views.tests judge.utils.tests` → PASS; `flake8` → clean.

- [ ] **Step 5: Look at the page.** Start `python manage.py runserver`, open the data page of a problem as a superuser, upload a zip with an `init.yml` and one without, and confirm: the cases appear, the help and rejudge boxes render, the rejudge button opens Manage submissions, and the browser console shows no errors. Report what was and was not checked.

- [ ] **Step 6: Commit**

```bash
git add templates/problem/data.html judge/views/tests/test_problem_data_view.py
git commit -m "feat(problem-data): explain case upload and rejudge consequences"
```
