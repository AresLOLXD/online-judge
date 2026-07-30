# Custom Python Checker Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a problem editor upload a custom Python checker script (`checker.py`) through the "problem data" admin page, statically reject files containing obviously dangerous patterns, and wire the uploaded file into the generated `init.yml`.

**Architecture:** Add a `checker_file` `FileField` to `ProblemData` (mirroring the existing `generator` field exactly — same storage, same `upload_to`, same rename-on-problem-rename handling). Add a `'custom'` option to the dataset-level checker dropdown (form-only, not model-level, so the per-testcase checker dropdown is unaffected). A new pure-function AST scanner rejects uploads containing blacklisted imports/calls. `ProblemDataCompiler.make_init()` writes the checker file's relative filename into `init['checker']` when `checker == 'custom'`.

**Tech Stack:** Django 4.2 (forms, models, migrations), Python `ast` module (static analysis, never executes the uploaded file), Django `TestCase`/`SimpleTestCase`.

## Global Constraints

- Design doc: `docs/superpowers/specs/2026-07-29-custom-checker-upload-design.md` — follow it exactly; do not reintroduce the "import init.yml from zip" feature (explicitly out of scope) or per-testcase custom checkers (explicitly out of scope).
- `checker_file` is dataset-level only — `ProblemTestCase` and `ProblemCaseForm` are never touched by this plan.
- flake8 config: 120 col limit, pycharm import order, `flake8-commas`, `flake8-quotes` — run `flake8` on every file you touch before committing.
- Dangerous-pattern scan is static-only (`ast.parse`, never `exec`/`eval`/`import` of the uploaded content) and is a hard rejection (`ValidationError`), not a warning.

---

### Task 1: `checker_file` model field, migration, and rename handling

**Files:**
- Modify: `judge/models/problem_data.py:34-75` (`ProblemData` class)
- Create: `judge/migrations/0153_problemdata_checker_file.py`
- Test: `judge/models/tests/test_problem_data.py` (new file)

**Interfaces:**
- Produces: `ProblemData.checker_file` — a `django.db.models.FileField` (same shape as `ProblemData.generator`), usable by later tasks as `self.data.checker_file` / `data.checker_file.name`.

- [ ] **Step 1: Write the failing test**

Create `judge/models/tests/test_problem_data.py`:

```python
from django.test import TestCase

from judge.models.tests.util import create_problem, create_problem_type, create_user


class ProblemDataModelTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='author')
        create_problem_type(name='type')
        cls.problem = create_problem(code='checkerprob', types=('type',), authors=('author',))

    def test_checker_file_field_exists_and_defaults_empty(self):
        from judge.models import ProblemData
        data = ProblemData.objects.create(problem=self.problem)
        self.assertFalse(data.checker_file)

    def test_update_code_relocates_checker_file(self):
        from judge.models import ProblemData
        data = ProblemData.objects.create(problem=self.problem)
        data.checker_file.name = 'checkerprob/checker.py'
        data.save()

        data._update_code('checkerprob', 'renamedprob')

        self.assertEqual(data.checker_file.name, 'renamedprob/checker.py')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test judge.models.tests.test_problem_data -v 2`
Expected: FAIL — `ProblemData` has no field `checker_file` (`AttributeError` or `FieldError`).

- [ ] **Step 3: Add the field to the model**

In `judge/models/problem_data.py`, add the new field right after `generator` (currently lines 39-40):

```python
    generator = models.FileField(verbose_name=_('generator file'), storage=problem_data_storage, null=True, blank=True,
                                 upload_to=problem_directory_file)
    checker_file = models.FileField(verbose_name=_('custom checker file'), storage=problem_data_storage, null=True,
                                    blank=True, upload_to=problem_directory_file)
```

Update `_update_code` (currently lines 64-75) to relocate `checker_file` alongside `generator`:

```python
    def _update_code(self, original, new):
        try:
            problem_data_storage.rename(original, new)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
        if self.zipfile:
            self.zipfile.name = _problem_directory_file(new, self.zipfile.name)
        if self.generator:
            self.generator.name = _problem_directory_file(new, self.generator.name)
        if self.checker_file:
            self.checker_file.name = _problem_directory_file(new, self.checker_file.name)
        self.save()
    _update_code.alters_data = True
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `python manage.py makemigrations judge --name problemdata_checker_file`

Verify the generated file matches this shape (rename/adjust only if Django names it differently), following the style of `judge/migrations/0151_submission_is_archived.py`:

```python
# Generated by Django 4.2.27 on 2026-07-29 00:00

import judge.models.problem_data
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0152_deactivate_user_permission'),
    ]

    operations = [
        migrations.AddField(
            model_name='problemdata',
            name='checker_file',
            field=models.FileField(blank=True, null=True, upload_to=judge.models.problem_data.problem_directory_file,
                                   verbose_name='custom checker file'),
        ),
    ]
```

If the file isn't named `0153_problemdata_checker_file.py`, rename it to match.

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test judge.models.tests.test_problem_data -v 2`
Expected: PASS (2 tests)

- [ ] **Step 6: Lint and commit**

Run: `flake8 judge/models/problem_data.py judge/migrations/0153_problemdata_checker_file.py judge/models/tests/test_problem_data.py`

```bash
git add judge/models/problem_data.py judge/migrations/0153_problemdata_checker_file.py judge/models/tests/test_problem_data.py
git commit -m "$(cat <<'EOF'
Add checker_file field to ProblemData

Lets a custom checker script be attached to a problem's data set,
mirroring the existing generator FileField, so a later change can
offer it as a checker option in the problem data admin form.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Dangerous-pattern scanner for checker source

**Files:**
- Modify: `judge/utils/problem_data.py` (add function near the top, after imports)
- Test: `judge/utils/tests/test_problem_data.py` (new file)

**Interfaces:**
- Produces: `judge.utils.problem_data.scan_checker_source(source: bytes) -> list[str]` — returns a list of human-readable violation strings (e.g. `"import 'os'"`, `"call to 'eval'"`, `"invalid Python syntax: <msg>"`); empty list means clean. Later tasks (Task 3) call this from `clean_checker_file()`.

- [ ] **Step 1: Write the failing tests**

Create `judge/utils/tests/test_problem_data.py`:

```python
from django.test import SimpleTestCase

from judge.utils.problem_data import scan_checker_source


class ScanCheckerSourceTestCase(SimpleTestCase):
    def test_clean_checker_passes(self):
        source = b'''
def check(process_output, judge_output, **kwargs):
    return process_output.strip() == judge_output.strip()
'''
        self.assertEqual(scan_checker_source(source), [])

    def test_flags_blacklisted_import(self):
        source = b'''
import os

def check(process_output, judge_output, **kwargs):
    return True
'''
        violations = scan_checker_source(source)
        self.assertIn("import 'os'", violations)

    def test_flags_blacklisted_from_import(self):
        source = b'''
from subprocess import run

def check(process_output, judge_output, **kwargs):
    return True
'''
        violations = scan_checker_source(source)
        self.assertIn("import 'subprocess'", violations)

    def test_flags_blacklisted_call(self):
        source = b'''
def check(process_output, judge_output, **kwargs):
    return eval(process_output) == judge_output
'''
        violations = scan_checker_source(source)
        self.assertIn("call to 'eval'", violations)

    def test_flags_multiple_violations(self):
        source = b'''
import socket
import ctypes

def check(process_output, judge_output, **kwargs):
    return __import__('os').system('echo hi')
'''
        violations = scan_checker_source(source)
        self.assertIn("import 'socket'", violations)
        self.assertIn("import 'ctypes'", violations)
        self.assertIn("call to '__import__'", violations)

    def test_flags_syntax_error(self):
        source = b'def check(process_output, judge_output, **kwargs:\n    return True'
        violations = scan_checker_source(source)
        self.assertEqual(len(violations), 1)
        self.assertIn('invalid Python syntax', violations[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test judge.utils.tests.test_problem_data -v 2`
Expected: FAIL — `ImportError: cannot import name 'scan_checker_source'`

- [ ] **Step 3: Implement the scanner**

In `judge/utils/problem_data.py`, add `ast` to the imports (currently `import json`, `import os`, `import re` on lines 1-3) and add the scanner near the top of the file, after the existing `split_path_first` helpers (currently ending around line 17) and before `ProblemDataStorage`:

```python
import ast
import json
import os
import re
```

```python
DANGEROUS_CHECKER_IMPORTS = frozenset((
    'os', 'subprocess', 'sys', 'socket', 'shutil', 'ctypes', 'importlib',
    'multiprocessing', 'threading', 'requests', 'urllib', 'http', 'ftplib',
    'telnetlib', 'pty', 'pickle', 'marshal', 'code',
))

DANGEROUS_CHECKER_CALLS = frozenset(('eval', 'exec', 'compile', '__import__'))


def scan_checker_source(source):
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ['invalid Python syntax: %s' % e]

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split('.')[0]
                if root in DANGEROUS_CHECKER_IMPORTS:
                    violations.append("import '%s'" % root)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or '').split('.')[0]
            if root in DANGEROUS_CHECKER_IMPORTS:
                violations.append("import '%s'" % root)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_CHECKER_CALLS:
                violations.append("call to '%s'" % node.func.id)

    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test judge.utils.tests.test_problem_data -v 2`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint and commit**

Run: `flake8 judge/utils/problem_data.py judge/utils/tests/test_problem_data.py`

```bash
git add judge/utils/problem_data.py judge/utils/tests/test_problem_data.py
git commit -m "$(cat <<'EOF'
Add static dangerous-pattern scanner for checker scripts

scan_checker_source() statically parses (never executes) an uploaded
checker's source with ast and flags blacklisted imports/builtin calls,
for use as a hard-reject gate before a custom checker script is
accepted.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Wire `checker_file` into `ProblemDataForm`

**Files:**
- Modify: `judge/views/problem_data.py:1-70` (imports, `ProblemDataForm`)
- Test: `judge/views/tests/test_problem_data_form.py` (new file)

**Interfaces:**
- Consumes: `ProblemData.checker_file` (Task 1), `scan_checker_source` (Task 2).
- Produces: `ProblemDataForm` now has a `checker_file` field and a `'custom'` choice on `checker`. Task 4 relies on `ProblemData.checker == 'custom'` and `ProblemData.checker_file` being populated together after a valid form save.

- [ ] **Step 1: Write the failing tests**

Create `judge/views/tests/test_problem_data_form.py` (create the `judge/views/tests/` package with an empty `__init__.py` if it doesn't already exist):

```python
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from judge.models import ProblemData
from judge.models.tests.util import create_problem, create_problem_type, create_user
from judge.views.problem_data import ProblemDataForm


class ProblemDataFormTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='author')
        create_problem_type(name='type')
        cls.problem = create_problem(code='formcheckerprob', types=('type',), authors=('author',))

    def _base_post_data(self, checker=''):
        return {
            'problem-data-output_limit': '',
            'problem-data-output_prefix': '',
            'problem-data-checker': checker,
            'problem-data-checker_args': '',
        }

    def test_custom_checker_without_file_is_invalid(self):
        instance = ProblemData.objects.create(problem=self.problem)
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files={}, prefix='problem-data',
                               instance=instance)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_custom_checker_with_clean_file_is_valid(self):
        instance = ProblemData.objects.create(problem=self.problem)
        checker_file = SimpleUploadedFile('checker.py', b'''
def check(process_output, judge_output, **kwargs):
    return process_output == judge_output
''')
        files = {'problem-data-checker_file': checker_file}
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files=files, prefix='problem-data',
                               instance=instance)
        self.assertTrue(form.is_valid(), form.errors)

    def test_custom_checker_with_dangerous_file_is_rejected(self):
        instance = ProblemData.objects.create(problem=self.problem)
        checker_file = SimpleUploadedFile('checker.py', b'''
import subprocess

def check(process_output, judge_output, **kwargs):
    return True
''')
        files = {'problem-data-checker_file': checker_file}
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files=files, prefix='problem-data',
                               instance=instance)
        self.assertFalse(form.is_valid())
        self.assertIn('checker_file', form.errors)
        self.assertIn('subprocess', form.errors['checker_file'][0])

    def test_non_custom_checker_ignores_uploaded_file_requirement(self):
        instance = ProblemData.objects.create(problem=self.problem)
        form = ProblemDataForm(data=self._base_post_data(checker='standard'), files={}, prefix='problem-data',
                               instance=instance)
        self.assertTrue(form.is_valid(), form.errors)

    def test_checker_file_must_be_python(self):
        instance = ProblemData.objects.create(problem=self.problem)
        checker_file = SimpleUploadedFile('checker.txt', b'not python')
        files = {'problem-data-checker_file': checker_file}
        form = ProblemDataForm(data=self._base_post_data(checker='custom'), files=files, prefix='problem-data',
                               instance=instance)
        self.assertFalse(form.is_valid())
        self.assertIn('checker_file', form.errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test judge.views.tests.test_problem_data_form -v 2`
Expected: FAIL — `checker='custom'` is rejected as "not a valid choice" (no `'custom'` option yet), and there's no `checker_file` field.

- [ ] **Step 3: Implement the form changes**

In `judge/views/problem_data.py`, update the imports (currently lines 1-26) to add `ast` is not needed here (scanning lives in `judge/utils/problem_data.py`), but add `forms` and the scanner import. Change:

```python
from django.forms import BaseModelFormSet, HiddenInput, ModelForm, NumberInput, Select, formset_factory
```

to:

```python
from django import forms
from django.forms import BaseModelFormSet, HiddenInput, ModelForm, NumberInput, Select, formset_factory
```

and add to the `judge.utils.problem_data` import (currently `from judge.utils.problem_data import ProblemDataCompiler`):

```python
from judge.utils.problem_data import ProblemDataCompiler, scan_checker_source
```

and add `CHECKERS` to the existing `judge.models` import (currently
`from judge.models import Problem, ProblemData, ProblemTestCase, Submission, problem_data_storage`):

```python
from judge.models import CHECKERS, Problem, ProblemData, ProblemTestCase, Submission, problem_data_storage
```

Add a module-level constant near the top (after `mimetypes.add_type(...)`, currently line 29):

```python
CUSTOM_CHECKER_CHOICE = ('custom', _('Custom (Python script)'))
```

Replace `ProblemDataForm` (currently lines 44-70) with:

Note: the model's `checker` field has `blank=True`, so Django's default
`ModelForm` machinery would normally prepend a `('', '---------')` blank
choice automatically. Overriding the field explicitly below means that
blank choice must be added back by hand, or `checker=''` (no checker
selected — a valid, commonly-used state) would be rejected as "not a
valid choice".

```python
class ProblemDataForm(ModelForm):
    checker = forms.ChoiceField(choices=(('', '---------'),) + CHECKERS + (CUSTOM_CHECKER_CHOICE,),
                                required=False)

    def clean_zipfile(self):
        if hasattr(self, 'zip_valid') and not self.zip_valid:
            raise ValidationError(_('Your zip file is invalid!'))

        zipfile = self.cleaned_data['zipfile']
        if zipfile and not zipfile.name.endswith('.zip'):
            raise ValidationError(_("Zip files must end in '.zip'"))

        return zipfile

    def clean_generator(self):
        generator = self.cleaned_data['generator']
        if generator and generator.name == 'init.yml':
            raise ValidationError(_('Generators must not be named init.yml.'))

        return generator

    def clean_checker_file(self):
        checker_file = self.cleaned_data['checker_file']
        if not checker_file:
            return checker_file

        if checker_file.name == 'init.yml':
            raise ValidationError(_('Checker file must not be named init.yml.'))
        if not checker_file.name.endswith('.py'):
            raise ValidationError(_('Checker file must be a Python (.py) script.'))

        violations = scan_checker_source(checker_file.read())
        checker_file.seek(0)
        if violations:
            raise ValidationError(
                _('Checker script contains disallowed constructs: %s') % ', '.join(violations),
            )

        return checker_file

    def clean(self):
        cleaned_data = super().clean()
        checker = cleaned_data.get('checker')
        checker_file = cleaned_data.get('checker_file')
        clear_checkbox_name = self.add_prefix('checker_file-clear')
        has_existing_file = bool(self.instance.checker_file) and clear_checkbox_name not in self.data
        if checker == 'custom' and not checker_file and not has_existing_file:
            raise ValidationError(_('A checker script must be uploaded when using a custom checker.'))
        return cleaned_data

    clean_checker_args = checker_args_cleaner

    class Meta:
        model = ProblemData
        fields = ['zipfile', 'generator', 'unicode', 'nobigmath', 'output_limit', 'output_prefix',
                  'checker', 'checker_args', 'checker_file']
        widgets = {
            'checker_args': HiddenInput,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test judge.views.tests.test_problem_data_form -v 2`
Expected: PASS (5 tests)

Also re-run Tasks 1 and 2's suites to confirm nothing regressed:
Run: `python manage.py test judge.models.tests.test_problem_data judge.utils.tests.test_problem_data -v 2`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `flake8 judge/views/problem_data.py judge/views/tests/test_problem_data_form.py`

```bash
git add judge/views/problem_data.py judge/views/tests/test_problem_data_form.py
git commit -m "$(cat <<'EOF'
Add custom checker option and file upload to ProblemDataForm

Adds a 'custom' choice to the dataset-level checker dropdown (form
scoped, so per-testcase checkers are unaffected) backed by a new
checker_file upload, validated to be a .py file free of the
dangerous patterns flagged by scan_checker_source().

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Emit the custom checker filename in generated `init.yml`

**Files:**
- Modify: `judge/utils/problem_data.py` (`ProblemDataCompiler.make_init`, currently lines 57-213)
- Test: `judge/utils/tests/test_problem_data.py` (extend, from Task 2)

**Interfaces:**
- Consumes: `ProblemData.checker` / `ProblemData.checker_file` (Task 1), `split_path_first` (existing helper, same file).
- Produces: when `self.data.checker == 'custom'`, `ProblemDataCompiler.make_init()['checker']` is the checker file's relative filename (a plain string, or `{'name': ..., 'args': {...}}` if `checker_args` is set — same shape `make_checker()` already produces for built-in checkers).

- [ ] **Step 1: Write the failing tests**

Append to `judge/utils/tests/test_problem_data.py`:

```python
from django.test import TestCase

from judge.models import ProblemData
from judge.models.tests.util import create_problem, create_problem_type, create_user
from judge.utils.problem_data import ProblemDataCompiler


class MakeInitCustomCheckerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_user(username='author')
        create_problem_type(name='type')
        cls.problem = create_problem(code='initcheckerprob', types=('type',), authors=('author',))

    def test_custom_checker_writes_filename(self):
        data = ProblemData.objects.create(problem=self.problem, checker='custom')
        data.checker_file.name = 'initcheckerprob/checker.py'
        data.save()

        compiler = ProblemDataCompiler(self.problem, data, cases=[], files=[])
        init = compiler.make_init()

        self.assertEqual(init['checker'], 'checker.py')

    def test_custom_checker_with_args_writes_name_and_args(self):
        data = ProblemData.objects.create(problem=self.problem, checker='custom', checker_args='{"precision": 4}')
        data.checker_file.name = 'initcheckerprob/checker.py'
        data.save()

        compiler = ProblemDataCompiler(self.problem, data, cases=[], files=[])
        init = compiler.make_init()

        self.assertEqual(init['checker'], {'name': 'checker.py', 'args': {'precision': 4}})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test judge.utils.tests.test_problem_data -v 2`
Expected: FAIL — `init['checker']` is currently the literal string `'custom'`, not `'checker.py'`.

- [ ] **Step 3: Implement the checker resolution**

In `judge/utils/problem_data.py`, inside `ProblemDataCompiler`, add a helper method and use it from `make_init()`. Add the method right before `make_init` (currently line 57):

```python
    def resolve_checker_name(self, checker_field):
        if checker_field != 'custom':
            return checker_field
        checker_path = split_path_first(self.data.checker_file.name)
        if len(checker_path) != 2:
            raise ProblemDataError(_('How did you corrupt the checker file path?'))
        return checker_path[1]
```

Update `make_checker` (currently lines 67-73) to resolve the name through this helper:

```python
        def make_checker(case):
            checker_name = self.resolve_checker_name(case.checker)
            if case.checker_args:
                return {
                    'name': checker_name,
                    'args': json.loads(case.checker_args),
                }
            return checker_name
```

`make_checker` is called both for per-case checkers (`case.checker`, never `'custom'` since `ProblemCaseForm` doesn't offer that choice — Task 3 only changed `ProblemDataForm`) and for `self.data` at the bottom of `make_init` (currently lines 205-206: `init['checker'] = make_checker(self.data)`), which is unchanged since `make_checker` now takes any object with `.checker`/`.checker_args` — confirm this still reads `case.checker`/`case.checker_args` correctly when called as `make_checker(self.data)` (it does, since `self.data` also has `.checker` and `.checker_args`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test judge.utils.tests.test_problem_data -v 2`
Expected: PASS (all tests in this module, including Task 2's)

Also re-run the full suite for this feature so far:
Run: `python manage.py test judge.models.tests.test_problem_data judge.utils.tests.test_problem_data judge.views.tests.test_problem_data_form -v 2`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `flake8 judge/utils/problem_data.py judge/utils/tests/test_problem_data.py`

```bash
git add judge/utils/problem_data.py judge/utils/tests/test_problem_data.py
git commit -m "$(cat <<'EOF'
Resolve custom checker file into generated init.yml

When checker is 'custom', ProblemDataCompiler now writes the
uploaded checker script's relative filename into init.yml instead
of the literal string 'custom', matching how generator/archive
paths are already resolved.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Show/hide the checker file field in the admin UI

**Files:**
- Modify: `templates/problem/data.html`

**Interfaces:**
- Consumes: the `checker_file` field now rendered by `data_form.as_table()` (Task 3) as an ordinary `<tr>` (Django renders every `Meta.fields` entry as a table row when using `as_table()`, no template change needed for the row itself to exist).
- Produces: nothing consumed by other tasks — this is the last task in the plan.

- [ ] **Step 1: Locate the row Django renders for `checker_file`**

Run the dev server and open a problem's data page (`/problem/<code>/data`) to confirm `data_form.as_table()` already renders a `<tr>` containing an `<input id="id_problem-data-checker_file" ...>` for the new field (no code change needed for this — `Meta.fields` from Task 3 already includes it). This step is a manual check, not a code change.

- [ ] **Step 2: Extend `checker_precision` to also toggle the checker file row**

In `templates/problem/data.html`, the dataset-level checker's row-toggle logic lives in `checker_precision($checker)` (around lines 65-82) and is invoked once for the dataset form at `checker_precision($('#id_problem-data-checker'));` (around line 96). Add a sibling function right after `checker_precision`'s closing brace:

```javascript
            function toggle_checker_file($checker) {
                var $row = $('#id_problem-data-checker_file').closest('tr');
                $checker.change(function () {
                    $row.toggle($checker.val() === 'custom');
                }).change();
            }
```

Call it alongside the existing dataset-level invocation:

```javascript
            checker_precision($('#id_problem-data-checker'));
            toggle_checker_file($('#id_problem-data-checker'));
```

Note: `toggle_checker_file` is only ever called for the dataset-level `#id_problem-data-checker` select (never per-case, since `checker_file` doesn't exist on case rows) — do not add a call inside the `add-row`/per-case block (around line 165) that already calls `checker_precision($tr.find('select[id$=checker]'))` for case rows.

- [ ] **Step 3: Manually verify in the browser**

Run: `python manage.py runserver`, log in as a superuser, open `/problem/<any-code>/data`.
Expected:
- The checker file row is hidden by default (assuming a built-in checker is selected).
- Selecting "Custom (Python script)" in the dataset-level checker dropdown reveals the checker file row.
- Switching back to a built-in checker hides it again.
- Uploading a `.py` file with e.g. `import subprocess` and submitting shows the `ValidationError` message from Task 3 inline next to the field.
- Uploading a clean `.py` checker with `checker` set to `custom` and submitting succeeds, and `/problem/<code>/data/init.yml`-style "View YAML" link (top of page) shows `checker: checker.py` (or similar).

- [ ] **Step 4: Lint and commit**

Run: `flake8` (template has no Python to lint, but re-run the full flake8 pass across everything touched this plan to be safe):
Run: `flake8 judge/models/problem_data.py judge/utils/problem_data.py judge/views/problem_data.py judge/migrations/0153_problemdata_checker_file.py judge/models/tests/test_problem_data.py judge/utils/tests/test_problem_data.py judge/views/tests/test_problem_data_form.py`

```bash
git add templates/problem/data.html
git commit -m "$(cat <<'EOF'
Show checker file upload only when custom checker is selected

Extends the existing per-field show/hide pattern (checker_precision)
so the new checker_file row is only visible when the dataset-level
checker dropdown is set to 'custom'.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

Run the full judge test suite to confirm no regressions:

Run: `python manage.py test judge -v 2`
Expected: PASS, including all new tests added in Tasks 1-4.

Run: `flake8`
Expected: no output (clean).
