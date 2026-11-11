# Port Markdown to mistune 3, group 2: site presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the site's link, heading, table and code presentation, and the `#Title` compatibility rule, on the mistune 3 renderer built by group 1.

**Architecture:** `AwesomeRenderer` (in `judge/jinja2/markdown/__init__.py`) gains `link`, `heading` and `block_code` overrides and a registered table hook; a `BlockParser` subclass relaxes only the `atx_heading` rule. The `table`, `strikethrough` and `url` plugins and the post-processing stay as they are.

**Tech Stack:** Python 3.13/3.14, Django 5.2, mistune 3.4 (`HTMLRenderer`, `BlockParser`), pygments through `judge.highlight_code.highlight_code`, uv.

**Spec:** `openspec/changes/port-markdown-to-mistune-3/design.md` (decisions 6-9, 12, 13) and `openspec/changes/port-markdown-to-mistune-3/specs/markdown-rendering/spec.md`. This plan covers `tasks.md` group 2 (ids 2.1-2.3).

## Global Constraints

- Branch `feat/mistune-3-port`. Conventional Commits, English, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push. Stage only the files a task names.
- Style: 120 columns, single quotes, trailing commas, pycharm import order. Run `uv run --no-sync flake8 judge/jinja2/markdown` (plain `flake8` also scans the untracked `.claude/worktrees/`, which is not ours).
- Do not edit `judge/jinja2/markdown/math.py`, `judge/utils/mathoid.py` or `dmoj/settings.py`. Math, `<latex>` and `TEXOID_ENABLED`/`TexoidRenderer` belong to group 3.
- Do not weaken any test or payload from group 1; the 243-payload battery, `executable_markup` and the timing tests must stay green with the new renderer code.
- Environment (scratch only, never in the repo): `export SCRATCH=/tmp/claude-1000/-var-home-areslolxd-Documentos-online-judge/6b1cb67e-65ce-4d10-8f6f-3a9fec626c0d/scratchpad UV_LINK_MODE=copy`. Markdown tests: `export PYTHONPATH=$SCRATCH DJANGO_SETTINGS_MODULE=probe_settings UV_PROJECT_ENVIRONMENT=$SCRATCH/env313; uv sync --locked --python 3.13; uv run --no-sync python manage.py test judge.jinja2.markdown --noinput` (`$SCRATCH/probe_settings.py` has SQLite in memory and locmem caches; recreate it from the group 1 plan text if the scratchpad was wiped: `from dmoj.settings import *`, `STATIC_ROOT`, `DATABASES` SQLite `:memory:`, `CACHES` locmem). Always set `UV_PROJECT_ENVIRONMENT`; never create `.venv`, `static/`, `formcheckerprob/` or `.mo` in the repo (check `git status`).
- Full suite (Task 3 only): the controller keeps a scratch MariaDB on `127.0.0.1:3307` (user and password `dmoj`) and `$SCRATCH/matrix_settings.py`; use `DJANGO_SETTINGS_MODULE=matrix_settings`, run `manage.py compilejsi18n` first. Never start, stop or alter database services; if it is unreachable, report BLOCKED.
- Baseline (Task 1 only): `git worktree add --detach $SCRATCH/baseline e2dd72ff`, environment `UV_PROJECT_ENVIRONMENT=$SCRATCH/env_baseline uv sync --locked --python 3.13` (mistune 0.8). Remove the worktree when done (`git worktree remove --force --force`, `git worktree prune`).

## Review Focus

- `urlparse` raises `ValueError` for a target such as `http://[::1`: the link must still render (the old code answered `rel="nofollow"`), never raise.
- A protocol-relative target `//example.com/x` has a host: it gets `rel="nofollow"`.
- Link text keeps its inline markup: `[**b**](https://example.com/)` has a `strong` inside the anchor.
- Headings: `## Sub ##` has no trailing `#` in its text; `#######x` (seven hashes) is a paragraph; a bare `#` line does not raise.
- Code: an unknown or hostile language (`` ```notalang ``, `` ```<script>alert(1)</script> ``) falls back to escaped `<pre><code>` with no markup injected; extra words after the language (`` ```python title="x" ``) use the first word only; a code span `` `a &amp; b` `` shows the literal `&amp;` (the group 1 `text()` override must not touch code).
- Table cells keep inline markup and an escaped pipe (`a \| b`) stays one cell.

---

### Task 1: Tests first, run against the baseline

Covers `tasks.md` 2.1.

**Files:**
- Modify: `judge/jinja2/markdown/test_markdown.py` (append test classes; no change to existing tests)
- Outside the repo: baseline worktree and environment described in Global Constraints

**Interfaces:**
- Consumes: group 1 helpers `render_tree(source, style, **kwargs)`, `executable_markup(tree)`, `SAFE_STYLES`.
- Produces: classes `TestLinks`, `TestHeadings`, `TestHeadingWithoutSpace`, `TestTables`, `TestCode`; each test named as the snake_case of its Scenario (for example `test_nofollow_by_host`) with the docstring `Scenario: <exact scenario name from the spec>`; tests with no Scenario say so in their docstring.

- [ ] **Step 1: Write `TestLinks`** (all use `render_tree(..., 'comment')` unless noted):
  - `test_nofollow_by_host`: with `mock.patch('judge.jinja2.markdown.NOFOLLOW_WHITELIST', {'excluded.example'})`, render `[a](https://example.com/)`, `[b](https://excluded.example/)`, `[c](/problem/a)`, a bare `https://example.org/x`, `<a@b.c>` and `<https://example.net/auto>` (one per paragraph); `a`, the bare URL and the angle-bracket autolink have `rel == 'nofollow'`, the others have no `rel` attribute (the email anchor included).
  - `test_style_without_nofollow`: `override_settings(MARKDOWN_STYLES={'plain': {'safe_mode': True, 'nofollow': False}})`, render `[a](https://example.com/)` with style `'plain'`: the anchor has no `rel`.
  - `test_allowed_and_replaced_schemes`: links to `https://example.com/`, `mailto:a@b.c`, `tel:+123`, `ftp://example.com/`, `/relative` and an image `![i](data:image/png;base64,AA)` keep their URL (`href` or `src`); links to `steam://run/1`, `sms:+1`, `file:///etc/passwd` and an image `![i](data:image/svg+xml,AA)` have `#harmful-link` as `href` or `src`.
  - `test_unparsable_host_does_not_raise` (no Scenario): `[x](http://[::1)` returns a string and `executable_markup` is empty; `test_protocol_relative_link_is_nofollow` (no Scenario): `[x](//example.com/p)` has `rel='nofollow'`; `test_link_text_keeps_markup` (no Scenario): `[**b**](https://example.com/)` has `a/strong`; `test_entity_scheme_autolink_is_text` (no Scenario): `<java&Tab;script:alert(1)>` yields no `a`.
- [ ] **Step 2: Write `TestHeadings.test_heading_levels`**: `# a`, `### b`, `###### c` give `h3` 'a', `h5` 'b', `h6` 'c' and no `h7` or `h8`. Add `test_trailing_hashes_are_not_text` (no Scenario): `## Sub ##` gives `h4` with text `Sub`.
- [ ] **Step 3: Write `TestHeadingWithoutSpace`**: `test_heading_without_a_space` (`#Title`, `##Sub` give `h3` 'Title' and `h4` 'Sub', no `#` in the text); `test_fenced_code_is_untouched` (a fenced block containing `#include <stdio.h>` gives that text inside `pre` and no `h1`-`h6`); `test_raw_html_blocks_are_untouched` (style `problem-full`; `<style>\n#a { color: red }\n</style>` and `<pre>\n#include <x>\n\n#b\n</pre>`, the lines appear unchanged inside their elements and no heading exists); no-Scenario extras `test_seven_hashes_is_a_paragraph` (`#######x`) and `test_lone_hash_does_not_raise` (`#`).
- [ ] **Step 4: Write `TestTables.test_table_wrapper`** (pipe table, header row and two body rows, `comment`): exactly one `div.h-scrollable-table` containing `table.table` with one `thead` row and two `tbody` rows. Add no-Scenario `test_table_cells_keep_markup_and_escaped_pipe`: a cell `**b**` has a `strong`, a cell `a \| b` is one cell with text `a | b`.
- [ ] **Step 5: Write `TestCode`**: `test_code_blocks` (a ```` ```python ```` block gives an element with class `codehilite`; an untagged block containing `<b>&</b>` gives `<pre><code>` whose text is `<b>&</b>` with the raw string `&lt;b&gt;&amp;&lt;/b&gt;` in the output); no-Scenario `test_unknown_language_falls_back` (`` ```notalang `` and `` ```<script>alert(1)</script> `` give escaped `pre/code`, no `script`, `executable_markup` empty), `test_info_string_uses_the_first_word` (`` ```python title="x" `` is highlighted), `test_code_span_keeps_a_literal_entity` (`` `a &amp; b` `` output contains `<code>a &amp;amp; b</code>`).
- [ ] **Step 6: Run the new classes in the baseline.** Copy the test file into `$SCRATCH/baseline/judge/jinja2/markdown/` and run only `TestLinks TestHeadings TestHeadingWithoutSpace TestTables TestCode` with the scratch settings. Expected pass (kept behavior): nofollow tests, the table and code tests, `test_heading_without_a_space`. Expected fail (new): `test_allowed_and_replaced_schemes`, `test_heading_levels`, `test_raw_html_blocks_are_untouched` (confirm, do not force). Record every test as pass, fail or error. Then run the same classes on the branch (mistune 3, group 1 code): every test that passes on the baseline and fails here is expected (they are the work of Tasks 2 and 3); note them.
- [ ] **Step 7: Commit** `test(markdown): add the link, heading, table and code tests`. The body holds the baseline pass/fail table and the list of tests red on the branch until Tasks 2 and 3. `uv run --no-sync flake8 judge/jinja2/markdown` is clean.

### Task 2: Links, headings, tables and code

Covers `tasks.md` 2.2.

**Files:**
- Modify: `judge/jinja2/markdown/__init__.py`

**Interfaces:**
- Consumes: Task 1 tests; group 1's `AwesomeRenderer`, `_create_markdown`, `markdown()`.
- Produces: module-level `NOFOLLOW_WHITELIST = settings.NOFOLLOW_EXCLUDED` (read at call time, tests patch it); `AwesomeRenderer.__init__(self, escape: bool = True, nofollow: bool = True)`; `_create_markdown(escape: bool, nofollow: bool = True) -> mistune.Markdown`; `markdown()` reads `nofollow = styles.get('nofollow', True)`.

- [ ] **Step 1: `link`.** Override `AwesomeRenderer.link(self, text, url, title=None)`: same output as `HTMLRenderer.link`, plus `rel="nofollow"` when `self.nofollow` and `urlparse` of the sanitized URL has a `netloc` not in `NOFOLLOW_WHITELIST`; a `ValueError` from `urlparse` counts as nofollow, as in the old code (`judge/jinja2/markdown/__init__.py` at `e2dd72ff`, `_link_rel`). Autolinks and the `url` plugin go through `link`, so this one hook covers them; relative, `mailto:` and `#harmful-link` targets have no host and get no `rel`.
- [ ] **Step 2: `heading`.** Override `heading(self, text, level, **attrs)` to call the parent with `min(level + 2, 6)`.
- [ ] **Step 3: tables.** After the plugins run in `_create_markdown`, register a table hook with `markdown.renderer.register('table', render_table)` where `render_table(renderer, text)` returns `'<div class="h-scrollable-table">\n<table class="table">\n' + text + '</table>\n</div>\n'` (the plugin's `table_head`/`table_body` already emit `thead` and `tbody`).
- [ ] **Step 4: code.** Override `block_code(self, code, info=None)`: take the first word of the info string (decode and strip it like the parent does); with a language return `highlight_code(code, lang)` (`judge.highlight_code`; it falls back to escaped `<pre><code>` for an unknown language); without one call the parent. Pass `nofollow` from `markdown()` into `_create_markdown` and the renderer.
- [ ] **Step 5: Verify.** All Task 1 tests pass except `TestHeadingWithoutSpace.test_heading_without_a_space` and the two `#`-extras if they still fail (Task 3 owns them); the group 1 suite (battery, timing, malformed input, edge cases) still passes; flake8 clean; `git status` clean of stray files.
- [ ] **Step 6: Commit** `feat(markdown): restore links, headings, tables and code highlighting on mistune 3`, staging only `__init__.py`.

### Task 3: Headings without a space

Covers `tasks.md` 2.3.

**Files:**
- Modify: `judge/jinja2/markdown/__init__.py`

**Interfaces:**
- Consumes: Task 2's `_create_markdown(escape, nofollow)`.
- Produces: `class AwesomeBlockParser(mistune.BlockParser)` in `__init__.py`, used by `_create_markdown` (`mistune.Markdown(..., block=AwesomeBlockParser(), ...)`).

- [ ] **Step 1: Implement `AwesomeBlockParser`.** Its class attribute `SPECIFICATION` is a copy of `mistune.BlockParser.SPECIFICATION` with `atx_heading` replaced by `r'^ {0,3}(?P<atx_1>#{1,6})(?!#+)(?P<atx_2>[ \t]*|[ \t]*[^#\s].*?)$'` (design decision 9; mistune's own pattern requires whitespace after the hashes). Add a one-line comment saying why. Do not scan or rewrite the source text: context (fences, `<pre>`, `<style>`, lists, quotes) stays the parser's job. Check that the subclass's pattern is the one actually compiled and used (including for headings inside lists and quotes); if mistune compiles the base pattern anyway, report it.
- [ ] **Step 2: Verify.** All of `TestHeadingWithoutSpace` and the rest of the module pass on Python 3.13 and 3.14 (`UV_PROJECT_ENVIRONMENT=$SCRATCH/env314`, `--python 3.14`); the full suite (`matrix_settings`) is OK with no fewer tests than group 1's 224 plus the new ones; flake8 clean.
- [ ] **Step 3: Commit** `feat(markdown): keep headings written without a space after the hashes`, staging only `__init__.py`.
