# Port Markdown to mistune 3, group 4: integration checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the finished port with the repository's checks and with the maintainer's real documents, and produce the evidence the verify step needs, without changing the renderer.

**Architecture:** Four verification tasks. Task 1 runs the repository gates (plus two cheap tests deferred from earlier groups). Tasks 2 and 3 build a throwaway harness OUTSIDE the repository that renders every document of the private corpus with the old code (`master` at `e2dd72ff`, mistune 0.8) and the new code (the branch), then compare. Task 4 checks the downstream consumers and lists every Scenario with its test. Any defect found is reported, not fixed here: a fix becomes its own round with a test.

**Tech Stack:** Python 3.13/3.14, Django 5.2, lxml, uv; the corpus file `~/Documentos/online-judge-corpus/corpus.jsonl` (182 records with keys `code`, `kind` (`problem` 179, `blog` 3), `markdown`, `name`).

**Spec:** `openspec/changes/port-markdown-to-mistune-3/design.md` (decisions 11, 13) and `openspec/changes/port-markdown-to-mistune-3/specs/markdown-rendering/spec.md`. This plan covers `tasks.md` group 4 (ids 4.1-4.4).

## Global Constraints

- Branch `feat/mistune-3-port`. Conventional Commits, English, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push. The only commit of this group is Task 1's small test commit; stage only `judge/jinja2/markdown/test_markdown.py`.
- **The corpus is private.** It is read only; never copy it, a record or an excerpt into the repository, into a commit, into a report file under the repository (`.superpowers/` is inside the repository directory), into the final reply or into a subagent prompt. Everything derived from it (dumps, diffs, excerpts) lives under `$SCRATCH/corpus/`. Reports and replies name documents by `code` and `kind` only and give counts and categories; an excerpt, when a person must judge a difference, stays in a file under `$SCRATCH/corpus/` that the report names by path.
- Do not change production code. If a check reveals a defect, write it in the report with the document `code`, the check and the smallest reproducing input you can make that contains nothing from the corpus.
- Environment (scratch only, never in the repo): `export SCRATCH=/tmp/claude-1000/-var-home-areslolxd-Documentos-online-judge/6b1cb67e-65ce-4d10-8f6f-3a9fec626c0d/scratchpad UV_LINK_MODE=copy` and set `UV_PROJECT_ENVIRONMENT` in EVERY command (shell variables do not persist between calls; a missing one creates a stray `.venv` in the repo: delete it and check `git status`). New code: `PYTHONPATH=$SCRATCH DJANGO_SETTINGS_MODULE=probe_settings UV_PROJECT_ENVIRONMENT=$SCRATCH/env313`. Old code: `git worktree add --detach $SCRATCH/baseline e2dd72ff`, run from inside it with `UV_PROJECT_ENVIRONMENT=$SCRATCH/env_baseline` (mistune 0.8; verify with an import). Remove the worktree at the end (`git worktree remove --force --force`, `git worktree prune`). `probe_settings.py` (SQLite in memory, locmem caches) and the scratch MariaDB on `127.0.0.1:3307` (user and password `dmoj`, `DJANGO_SETTINGS_MODULE=matrix_settings`) exist; never start, stop or alter database services (report BLOCKED if unreachable).
- Never connect to remote servers other than the package index used by `uv audit`. The harness must not call Mathoid, Texoid or camo: math and LaTeX go through recording stand-ins.

## Review Focus

- A document that renders in more than 0.2 s (the budget is 1 s per call), or raises, in any style.
- Math spans that change: a `~` used as a plain character in a sentence (`~5 minutes`) that 0.8 and the new code treat differently, or a formula with `<`, `&`, `\\` or a line break.
- A table, list, heading or image present in the old output and missing in the new one (tag-count drop), which signals lost content rather than a style change.
- A link or image that became `#harmful-link` because of the new scheme allowlist.
- Raw HTML in staff styles: a tag that survived bleach in the old output and is gone in the new one.

---

### Task 1: Repository gates and two deferred tests

Covers `tasks.md` 4.1.

**Files:**
- Modify: `judge/jinja2/markdown/test_markdown.py` (two small additions only)

**Interfaces:**
- Consumes: the finished branch.
- Produces: gate results in the report; one commit.

- [ ] **Step 1: Add two tests from the earlier reviews.** In `TestPathologicalInput` extend the math timing test (`test_unterminated_math_openers_are_fast`) with the slow shapes `'\\[a ' * 2048` and `'\\(a ' * 2730`; in `TestAutolinkInjection` add the mirror assertion that `<java&Tab;script:alert(1)>` produces no `a` element (the old `&amp;Tab;` assertion was dropped in group 1). Run them; commit `test(markdown): cover the slow math openers and the Tab entity autolink`.
- [ ] **Step 2: Run the gates and record each result.** The full suite on Python 3.13 (`matrix_settings`, `env313`, after `manage.py compilejsi18n`) and on 3.14 (`env314`, build it with `uv sync --locked --python 3.14` if needed); `uv run --no-sync flake8 $(git ls-files '*.py')` (CI lints tracked files; plain `flake8` also scans the untracked `.claude/worktrees/`); `uv run --no-sync python manage.py makemigrations --check --dry-run` (only the known pending `judge` 0154 may appear); `uv lock --check`; `uv audit --frozen`. Expected: all pass, `mistune` absent from the audit; anything else is reported with its output.

### Task 2: Corpus math-span equality

Covers `tasks.md` 4.2.

**Files:**
- Create (outside the repo): `$SCRATCH/corpus/dump.py`, `$SCRATCH/corpus/compare_math.py`, outputs `$SCRATCH/corpus/math_old.jsonl`, `math_new.jsonl`, `math_diff.txt`

**Interfaces:**
- Produces: `dump.py --corpus PATH --mode math|render --out PATH`, runnable from the old worktree (0.8) and from the repo (new code); the output is one JSON line per record with `code`, `kind` and the mode's data. Task 3 reuses it with `--mode render`.

- [ ] **Step 1: Write `dump.py` math mode.** It calls `django.setup()`, then for each record renders `markdown(record['markdown'], style, math_engine='svg')` with `style` = `problem` for `kind == 'problem'` and `blog` for `kind == 'blog'`, under `override_settings(MATHOID_URL='http://mathoid.invalid')` and a recording stand-in for the math parser (`inline_math(f)` and `display_math(f)` append `('inline'|'display', f)` and return `<span></span>`). The patch target is `judge.jinja2.markdown.math.MathoidMathParser` on the old code and `judge.jinja2.markdown.MathoidMathParser` on the new one: detect which module has the attribute. Output the ordered `(kind, formula)` list per record.
- [ ] **Step 2: Run it on both trees and compare** with `compare_math.py` (record-by-record equality of the lists). Expected: identical for every record, or each difference explained.
- [ ] **Step 3: Explain every difference.** For each differing record write in `math_diff.txt` the old and new list for that record (this file stays under `$SCRATCH/corpus/`) and classify it: `new works, old did not` (`\(` and `\[` were never math on 0.8: expected), `tilde edge` (`~a~~b~`, a lone `~`), `anywhere vs start`, or `unexplained`. The report lists counts per class and the `code` of every record that is not `new works, old did not`.

### Task 3: Corpus render check and change report

Covers `tasks.md` 4.3.

**Files:**
- Create (outside the repo): `$SCRATCH/corpus/check_render.py`, outputs `render_old.jsonl`, `render_new.jsonl`, `render_report.txt`

**Interfaces:**
- Consumes: Task 2's `dump.py` (render mode: for each record and each style of `settings.MARKDOWN_STYLES`, the output HTML, the elapsed time, or the exception text) and the repository helpers `executable_markup` and `parse_fragment` of `judge/jinja2/markdown/test_markdown.py` (import them in the script; do not copy them).

- [ ] **Step 1: Render mode.** Render every record with every style (15 styles), in both trees, with the math and Texoid stand-ins as in Task 2 and `lazy_load=False`. Record time and any exception.
- [ ] **Step 2: Hard checks on the new code.** No exception; every call under 1 s (list any over 0.2 s); for the safe-mode styles (`default`, `comment`, `self-description`, `organization-about`, `ticket`) `executable_markup(parse_fragment(output))` is empty for every record. Any failure is a defect to report with the record `code` and style.
- [ ] **Step 3: Visible-change report.** For each record and style compare old and new with a tag histogram (count of `h1`-`h6`, `p`, `a`, `img`, `ul`, `ol`, `li`, `pre`, `code`, `table`, `tr`, `blockquote`, `strong`, `em`, `del`, `span`, `div`, plus the number of `href`/`src` equal to `#harmful-link` and of `rel="nofollow"`), after removing whitespace-only text. A record changes visibly when a histogram differs. Group the changed records by category: raw HTML in the source, `_x_` emphasis, nested lists or quotes, setext headings, tables (source has pipe-table lines and the table count differs, including tables inside lists or quotes), links or images turned into `#harmful-link`, heading counts, `nofollow` counts, other. Write counts per category and the `code` list per category to `render_report.txt`, and for each category put 1 to 3 old/new fragment pairs in `$SCRATCH/corpus/examples/<category>.txt` so a person can judge them.
- [ ] **Step 4: Classify.** Mark each category `expected` (the accepted differences of `proposal.md`: Markdown inside raw HTML, `_x_`, list and quote edge cases) or `needs a decision` (anything that loses content: a table, image or heading that disappears, a `#harmful-link` on a link the maintainer would want, bleach dropping a tag). Report the `needs a decision` ones first.

### Task 4: Consumers and Scenario-to-test list

Covers `tasks.md` 4.4.

**Files:**
- Create (outside the repo): `$SCRATCH/corpus/consumers.py`, `$SCRATCH/corpus/scenario_map.txt`

**Interfaces:**
- Consumes: `judge.jinja2.reference.reference`, `judge.utils.opengraph.generate_opengraph`, `judge/feed.py`.

- [ ] **Step 1: Consumer tests and a live pass.** Run `judge.jinja2.test_reference` and every test that touches `judge/feed.py` or `judge/utils/opengraph.py` (find them with grep; the full suite of Task 1 already covers them, say which tests they are). With a script, pass the new HTML of five corpus records (including one with a table, one with math stand-in spans and one with an image) through `reference(...)` and `generate_opengraph` (the latter takes the same `markdown(data, style)` input as `judge/utils/opengraph.py:12`; read it for the exact call, use a stub `cache_key`/request as needed or call the inner steps) and verify there is no exception and the output is non-empty; compare the old output of the same five records for the text content.
- [ ] **Step 2: Scenario map.** Extract every `#### Scenario:` name from the spec delta and every `Scenario:` docstring line of `judge/jinja2/markdown/test_markdown.py` (grep), and write to `$SCRATCH/corpus/scenario_map.txt` one line per Scenario with its test (class and method), then a list of tests added by this change that carry no Scenario line (the no-Scenario extras, the oracle self-test, the edge cases). Verify every Scenario has at least one test; a Scenario with no test or a test naming a Scenario that does not exist is a defect to report. The report holds the counts and any mismatch; the controller prints the full map in the final summary.
