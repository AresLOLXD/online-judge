# Auto-load test cases from the uploaded data zip

## Problem

On the problem data page (`templates/problem/data.html`, backed by
`ProblemDataView` in `judge/views/problem_data.py`) a problem editor uploads a
zip of test data. Today the zip is only used to fill the file `<select>`s:
`get_valid_files()` reads `ZipFile.namelist()` and nothing else. The editor
then has to add every case by hand (type, input file, output file, points),
one row at a time, even when the zip already lists every file or even carries
its own `init.yml`.

Two further frictions:

- Editors upload the whole zip again every time anything changes. The new zip
  replaces the old one entirely (`ProblemData.save()` deletes the original
  file), but nothing on the page says so, so editors do not know whether they
  must re-upload every case or only the new ones.
- Nothing on the page explains how to upload cases, that an `init.yml` in the
  zip is the fast path, or that the checker and the rest of the dataset
  settings are configured on the same page.

DMOJ is used by many groups and each uses its own file naming, so the site must
not assume a naming convention. The `init.yml` is the one format-neutral way to
describe the cases.

## Goals

- Uploading a zip that contains an `init.yml` at its root sets up the cases and
  dataset settings from that file, in one step, with no manual row entry.
- Uploading a zip without `init.yml` to a problem that has no cases yet
  pre-registers one row per detectable input/output pair, with the points left
  empty for the editor to fill.
- Re-uploading a zip never makes the editor retype case configuration that was
  not meant to change.
- The page tells the editor, in a short box: how to upload cases, that
  including an `init.yml` is faster, that a new zip replaces the previous one
  (so all cases must be in it, not only the new ones), and that the checker and
  the other settings are configured below.

- The page says that changing cases does not rejudge existing submissions,
  explains what a rejudge involves, and offers a button to go and rejudge
  (see "Rejudge notice").

## Non-goals (what we deliberately do not build)

- New rejudge logic or a one-click rejudge on the data page. Rejudging stays
  in the existing "Manage submissions" page.
- Rejudging automatically when cases change. Nothing in the codebase does
  that today (no signal on `ProblemData` / `ProblemTestCase`), and a yaml that
  replaces every case could trigger a mass rejudge by accident.
- Merging a partial zip into the existing one. The new zip always replaces the
  old one; the help text says so.
- Editing the `init.yml` in the browser.
- Any change to the `init.yml` the site generates for the judge, to the
  judge-server, or to the bridge.
- A configurable naming convention or a per-site setting for file pairing.
- Importing a custom checker or a generator script out of the zip (those keep
  their own upload fields).

## Reversal of an earlier decision

`docs/superpowers/specs/2026-07-29-custom-checker-upload-design.md` listed
"reading an `init.yml` bundled inside the uploaded zip" as out of scope and
said any such file is ignored. This design supersedes that for the cases and
settings the form can represent. The compiler still always regenerates the
`init.yml` the judge uses from the form data; the zip's `init.yml` is only an
input to populate the form data.

## Behavior

### When it runs

Only in `ProblemDataView.post()`, only when the POST carries a new zip
(`'problem-data-zipfile' in request.FILES`) and the data form and case formset
are valid and saved as they are today. It runs after those saves and before
`ProblemDataCompiler.generate()`, so the generated `init.yml` and the feedback
box reflect the result. A plain page load, or a POST that does not upload a
zip, never triggers it.

### Zip contains `init.yml` at its root: the yaml replaces

- All existing cases of the problem are deleted and recreated from the yaml.
  Manual edits to cases are lost; the help text warns about this.
- Dataset-level settings are applied only for keys present in the yaml; keys
  that are absent leave the current value alone. This keeps, for example, a
  custom checker selected on the page when the yaml says nothing about the
  checker.
- If the yaml defines neither `test_cases` nor `pretest_test_cases`, cases are
  left alone.
- If the yaml cannot be parsed or is not a mapping, nothing is changed and an
  error is shown in the existing feedback box. The zip itself is still saved.

### Zip has no `init.yml`: register only when the problem has no cases

- If the problem already has cases, nothing is added and existing cases are
  never touched. This is deliberate: the compiler deletes the working
  `init.yml` on any error (`ProblemDataCompiler.compile()`), and new cases
  without points raise one, so auto-adding to a live problem would stop it
  from being judged until the points are filled. The new files still appear in
  the file selects, and the page reports how many zip files no case uses.
- If the problem has no cases, the files in the zip are paired and one normal
  case (`type='C'`) is created per pair, `order` from 1, with `points` empty and
  `is_pretest=False`.
- Pairing rule **[Claude's call]**: reuse the rule the page's JavaScript
  already uses to autofill the output select (`templates/problem/data.html`):
  for a file `f`, the candidate output is `f` with its last occurrence of `in`
  replaced by `out`; if that name is in the zip, `(f, candidate)` is a pair.
  Natural sort order (so `2` comes before `10`). Files that pair with nothing
  (for example `.ans` outputs) are not registered; the editor adds those by
  hand, and the page reports how many files were left unpaired.
- Skipped entirely when the dataset has a generator (`data.generator` is set),
  because generator-driven cases have no input/output files.
- Never registered as case files: directory entries and `init.yml`.
- Because the new cases have no points, the compiler's existing check
  ("Points must be defined for non-batch case #N") fires and the feedback box
  tells the editor what is left to fill. No new message is needed.

### How `init.yml` keys map to the form

The mapping is the inverse of `ProblemDataCompiler.make_init()`.

| `init.yml` | Stored as |
|---|---|
| `pretest_test_cases[]`, then `test_cases[]` | `ProblemTestCase` rows in that order (`order` 1..n); rows from the pretest list get `is_pretest=True` |
| entry with `in` / `out` / `points` | `type='C'`; `input_file`, `output_file`, `points` |
| entry with `batched` | `type='S'` row (`points`, `is_pretest`, `batch_dependencies` = dependencies joined by `,`), one `C` row per batched item, then an `E` row |
| `generator_args` (list) | `generator_args` = items joined by newlines (inverse of `splitlines()`) |
| `output_limit_length`, `output_prefix_length` on an entry | `output_limit`, `output_prefix` of that row; top-level ones go to `ProblemData.output_limit` / `output_prefix` |
| `checker` as a name in `CHECKERS`, or `{name, args}` | row `checker` and `checker_args` (JSON string); top-level one goes to `ProblemData.checker` / `checker_args` |
| `hints` containing `unicode` / `nobigmath` | `ProblemData.unicode` / `nobigmath` |
| `archive`, `generator`, a checker name not in `CHECKERS`, any other key | ignored, reported as a warning |

Batch `dependencies` are imported as written, with no renumbering **[Claude's
call]**. The compiler numbers batches by row order and validates dependencies
against that count, while export splits pretests and tests into two lists. A
yaml that mixes pretest batches with dependencies can therefore be imported
in a different batch order than it was exported. The compiler's existing
"Dependencies must depend on previous batches" error reports any invalid
result, nothing is silently wrong, and a `shortcut:` comment records the
limit. The round-trip test (Testing, #1) does not combine pretest batches
with dependencies.

A file named by `in`/`out` that is not in the zip is not special-cased: the
compiler's existing "Input file for case N does not exist" error reports it.

### Warnings

Ignored keys and unpaired files are reported to the editor on the page after
the redirect. They never block saving. The channel (the existing feedback box,
Django messages, or a small notice) is left to the builder.

### Help box

A short box at the top of the page body, above the data form, in `data.html`,
using `_()` for every string, covering the four points in Goals. Wording and
styling are left to the builder; it must be visible without any click.

### Rejudge notice

A second box on the data page, below the help box, always visible **[Claude's
call]** (not only after a save, so it works for a zip uploaded earlier). It
states, with `_()` strings:

- Changing the cases does not rejudge existing submissions; they keep their
  previous verdict and points until rejudged.
- What a rejudge does: every selected submission goes back to the judge queue
  at batch priority (below normal submissions), so it takes time proportional
  to the count; verdict, points and per-case results are overwritten, with the
  change recorded in the revision history ("Rejudged"); when each submission
  finishes, the user's points, the problem statistics and contest scores are
  recalculated; submissions already locked by a finished contest are archived
  instead of rejudged.

Below the text, a button linking to `problem_manage_submissions` (the existing
"Manage submissions" page, where the editor picks filters, sees the count and
confirms). The button is rendered only when
`problem.is_subs_manageable_by(request.user)`; users without it see the text
only. The mass-rejudge action there additionally requires the
`judge.rejudge_submission_lot` permission; that is enforced by the existing
view and is not changed.

## Components

- `judge/utils/problem_data.py`: two pure helpers next to
  `ProblemDataCompiler`, one that reads and validates the zip's `init.yml` and
  returns case dicts, dataset settings and warnings, and one that pairs
  unused files. `yaml` is already imported there.
- `judge/views/problem_data.py`: `ProblemDataView.post()` calls them after the
  saves and writes the rows.
- `templates/problem/data.html`: the help box, the rejudge notice and button,
  and the warnings display.
- Locale files are not edited; strings are picked up by the existing
  `makemessages` / Crowdin flow.

## Safety

The zip comes from an authenticated editor but is still untrusted input.

- Parse with `yaml.safe_load` only.
- Check `ZipInfo.file_size` of `init.yml` before reading it and reject it above
  1 MiB with an error in the feedback box. **[Claude's call]** on the limit;
  a `shortcut:` comment marks it.
- Only the exact root entry `init.yml` counts; nested paths do not.
- Coerce `points`, dependency numbers and limits to integers and treat a value
  that does not coerce as a parse error for that yaml.
- File names written to `input_file` / `output_file` must be names that exist
  in the zip (the compiler already enforces this at generation time).

## Testing

Extend `judge/utils/tests/test_problem_data.py` and add a view test next to
`judge/views/tests/test_problem_data_form.py`. One test per behavior, each
verifiable:

1. Round trip: build a problem with normal, pretest and batch cases, take the
   `init.yml` the compiler writes, put it in a zip, upload it to an empty
   problem, and get the same rows back.
2. Zip with `init.yml` over a problem that already has cases: the old rows are
   gone, the yaml's rows are present.
3. Dataset keys absent from the yaml leave the existing `ProblemData` values
   untouched.
4. Zip without yaml, empty problem, files `1.in 1.out 2.in 2.out`: two rows,
   `points` empty, feedback contains the points message.
5. Zip without yaml over a problem that already has cases (using `1.in`/`1.out`)
   and a zip that also has `2.in`/`2.out`: no rows are added or changed, the
   working `init.yml` is still present, and the page reports the unused files.
6. Invalid yaml: no rows change, an error is shown, the zip is saved.
7. A POST without a new zip applies nothing.
8. Unpaired files and ignored yaml keys produce warnings and do not block.
9. The data page contains the link to `problem_manage_submissions` for a user
   for whom `is_subs_manageable_by` is true, and does not for one for whom it
   is false (the explanatory text is present for both).

## Left to the builder

- Where exactly the warnings are shown and the final wording and styling of
  the help box.
- How to delete-and-recreate the rows (single transaction is expected) and how
  to interact with the posted case formset in the same request.
- Extra input/output extension pairs (for example `.ans`) are a possible
  follow-up, not part of this change.
