# Port Markdown to mistune 3, group 1: core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `markdown` filter from mistune 0.8.4 to mistune 3.4 with escaping, URL safety, strikethrough, tables, bare URLs and post-processing, proven by tests first.

**Architecture:** `judge/jinja2/markdown/__init__.py` keeps the filter and its lxml/bleach post-processing and swaps the 0.8 grammar/lexer/renderer classes for an `HTMLRenderer` subclass plus three mistune plugins. Features that belong to groups 2 and 3 (nofollow, headings, tables wrapper, code highlighting, `#Title`, math, `<latex>`) are NOT built here.

**Tech Stack:** Python 3.13/3.14, Django 5.2, mistune 3.4, lxml, bleach, uv.

**Spec:** `openspec/changes/port-markdown-to-mistune-3/design.md` and `openspec/changes/port-markdown-to-mistune-3/specs/markdown-rendering/spec.md`. This plan covers `tasks.md` group 1 (ids 1.1-1.4).

## Global Constraints

- Branch `feat/mistune-3-port`. Conventional Commits, English, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push. Stage only the files a task names.
- Code style is the repository's flake8 (120 columns, single quotes, trailing commas, pycharm import order); `uv run flake8` clean at the end of every task.
- Do not edit `judge/jinja2/markdown/math.py`, `judge/utils/mathoid.py` or `dmoj/settings.py`. After Task 2 nothing imports `math.py` (group 3 rewrites it).
- After Task 2 the filter has no math, no `<latex>`, no nofollow and no code highlighting: that is the planned state until groups 2 and 3. Remove imports, variables and options that become unused (`TexoidRenderer`, `TEXOID_ENABLED`, `highlight_code`, the math imports, `NOFOLLOW_WHITELIST`, the `nofollow`/`texoid`/`math` locals); groups 2 and 3 add them back.
- Environment (scratch only, never inside the repo; the scratchpad was wiped by a reboot and must be rebuilt): `export SCRATCH=/tmp/claude-1000/-var-home-areslolxd-Documentos-online-judge/6b1cb67e-65ce-4d10-8f6f-3a9fec626c0d/scratchpad UV_LINK_MODE=copy`. Settings for markdown-only tests: create `$SCRATCH/probe_settings.py` containing `from dmoj.settings import *  # noqa` and `STATIC_ROOT = '<SCRATCH>/static_root'` and `DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}`. Markdown tests: `export PYTHONPATH=$SCRATCH DJANGO_SETTINGS_MODULE=probe_settings UV_PROJECT_ENVIRONMENT=$SCRATCH/env313; uv sync --locked --python 3.13; uv run --no-sync python manage.py test judge.jinja2.markdown --noinput` (they are `SimpleTestCase`s: no database is created).
- The full suite needs MariaDB; the controller starts it and provides `$SCRATCH/matrix_settings.py`. Implementers never start, stop or alter database services. Never create `.venv`, `static/`, `formcheckerprob/` or `.mo` files in the repo (delete them if a command leaves any).
- The real corpus is not used in this group.

## Review Focus

- Empty input renders as an empty string without error (templates call the filter with possibly empty summaries).
- A literal entity in the text (`&amp;`) is not double-escaped, and non-BMP characters (emoji) pass through once.
- CRLF line endings do not leak a `\r` and still split paragraphs.
- A single 8192-character line without spaces or breaks renders within the same 1 s budget.
- If Task 3 adds a parser cache: an unescaped style rendered between two escaped renders must not change their output.

---

### Task 1: Baseline worktree and tests first

Covers `tasks.md` 1.1.

**Files:**
- Modify: `judge/jinja2/markdown/test_markdown.py` (append helpers and classes; add `Scenario:` docstring lines to the existing tests named below; no other change to existing tests)
- Outside the repo: baseline worktree `$SCRATCH/baseline` (unmodified `e2dd72ff`, mistune 0.8) with environment `$SCRATCH/env_baseline`

**Interfaces:**
- Produces, for groups 2 and 3, module-level helpers of `test_markdown.py`: `SAFE_STYLES: tuple[str, ...]`, `render_tree(source: str, style: str, **kwargs) -> lxml.html.HtmlElement` (the filter output parsed under a `div`), `executable_markup(tree) -> list[str]` (offending items, empty means safe).

- [ ] **Step 1: Build the baseline.** `git worktree add --detach $SCRATCH/baseline e2dd72ff`; in it run `UV_PROJECT_ENVIRONMENT=$SCRATCH/env_baseline uv sync --locked --python 3.13`. Run the existing markdown tests there with the scratch settings. Expected: 11 tests OK and `uv pip list` shows mistune 0.8.4.
- [ ] **Step 2: Write the helpers.** `SAFE_STYLES = ('default', 'comment', 'self-description', 'organization-about', 'ticket')`. `executable_markup` reports: any element whose tag is `script`, `iframe` or `object`; any attribute whose name starts with `on`; any `href` or `src` that, after removing every character in `\x00-\x20` and lowercasing, starts with `javascript:` or `vbscript:`. It decodes nothing beyond what lxml already decoded (browsers decode attributes once).
- [ ] **Step 3: Write the tests.** Each test name is the snake_case form of the spec scenario it covers (for example `test_raw_html_is_shown_as_text` covers "Raw HTML is shown as text"), and its docstring is `Scenario: <exact scenario name from the spec>`:
  - `TestPathologicalInput` (helper `assert_fast(source, style='comment')` asserts the call takes under 1.0 s with `time.perf_counter`): `test_repeated_unterminated_autolink_openers` (`'<http://' * 1024`); `test_repeated_quadratic_prone_constructs` with `subTest` for `'[a](' * 2048`, `'<!--' * 2048`, `'**' * 4096`, `'~~' * 4096`, `'*a ' * 2730`, `'_a ' * 2730`.
  - `TestMalformedInput.test_deep_nesting_and_unterminated_constructs`: for styles `comment` and `problem` and each of `'>' * 1000`, 1000 nested list levels (`' ' * (2 * i) + '- x'` per line), `'[' * 5000`, an unterminated fence ```` ```python\nx ````, `'<div'`, `'a\x00b'`: the result is a `str` and the call takes under 1.0 s.
  - `TestSafeModeStyles` for every style in `SAFE_STYLES`: `test_raw_html_is_shown_as_text` (`<script>alert(1)</script>` gives output containing `&lt;script&gt;` and no `script` element; `<img src=x onerror=alert(1)>` gives no `img` element); `test_dangerous_schemes_in_links_images_and_autolinks` (the scenario's sources: `[x](javascript:alert(1))`, mixed case, leading spaces, tab and newline inside the scheme, a `\x01` before it, `vbscript:`, an entity-encoded scheme, `![x](javascript:alert(1))`, `<javascript:alert(1)>`; `executable_markup(...) == []`); `test_payload_battery` (`PAYLOADS` has at least 40 entries and `executable_markup(render_tree(p, style)) == []` for each).
  - `PAYLOADS`: a module-level tuple seeded with every source string of the existing `TestAutolinkInjection` tests, plus several variants for each category of the spec: scheme tricks (case, whitespace, control characters, entities, percent-encoding, `data:text/html`, `livescript:`), attribute breaking (quotes, `>` and `<` in link targets and titles, reference-style links), raw HTML (event handlers, `svg`/`iframe`/`object`/`form`, comments, CDATA), entity tricks, nested constructs (links in images in quotes in lists), and math/code delimiters around markup (`~<img onerror=x>~`, `$$<script>$$`, backticks around `<b onclick=x>`).
  - `TestPostProcessing`: `test_image_proxy` (a stub object with `update_tree(tree)` that prefixes every `img` `src` with `https://camo.invalid/`; with `mock.patch('judge.jinja2.markdown.camo_client', stub)` rendering `![x](https://a.invalid/i.png)` with `comment` gives that prefixed `src`; with the patch value `None` the `src` is unchanged); `test_paragraph_stripping` (`markdown('proudly powered by **DMOJ**', 'default', strip_paragraphs=True)` contains `<strong>DMOJ</strong>` and no `<p>`).
  - `TestInlineExtras.test_bare_url_and_strikethrough`: `render_tree('see https://example.com/a and ~~gone~~', 'comment')` has one `a` whose `href` and text are `https://example.com/a`, and a `del` with text `gone`.
  - Docstring lines only on existing tests: `TestMarkdown.test_bleach` and `test_bleach_mathml` get `Scenario: Staff style removes scripts and keeps allowed markup`; `test_no_bleach` gets `Scenario: Unbleached staff style keeps raw HTML`; `test_post_process` gets `Scenario: Lazy loading`; `TestAutolinkInjection.test_no_event_handler_attributes`, `test_href_is_the_escaped_url` and `test_single_quote_in_url` get `Scenario: Quotes cannot break out of a link attribute`.
- [ ] **Step 4: Run the new tests in the baseline.** Copy the test file into `$SCRATCH/baseline/judge/jinja2/markdown/` and run with the scratch settings from that directory. Expected: kept-behavior tests (`test_raw_html_is_shown_as_text`, `test_bare_url_and_strikethrough`, `test_image_proxy`, `test_paragraph_stripping`, the dangerous-scheme tests) pass; `test_repeated_unterminated_autolink_openers` fails after about 22 s. Record every test as pass, fail or error with its time.
- [ ] **Step 5: Run the same file on the branch** (still mistune 0.8): the results must match the baseline's. `uv run flake8 judge/jinja2/markdown/test_markdown.py` is clean.
- [ ] **Step 6: Commit** `test(markdown): add the safety, timing and post-processing tests for the mistune 3 port`. The body contains the pass/fail table of Step 4 and states that the failing tests are the new guarantees and are expected to fail until the port commit.

### Task 2: Pin mistune 3 and rewrite the filter

Covers `tasks.md` 1.2 and 1.3.

**Files:**
- Modify: `pyproject.toml:18`, `uv.lock`, `judge/jinja2/markdown/__init__.py`, `judge/jinja2/markdown/test_markdown.py` (adapt existing expectations, add `TestInputEdgeCases`)

**Interfaces:**
- Consumes: Task 1's helpers.
- Produces, for groups 2 and 3, in `judge/jinja2/markdown/__init__.py`: `class AwesomeRenderer(mistune.HTMLRenderer)` with `__init__(self, escape: bool = True)`; `def _create_markdown(escape: bool) -> mistune.Markdown` (builds `mistune.Markdown(renderer=AwesomeRenderer(escape=escape), plugins=[strikethrough, table, url])` with the plugins imported from `mistune.plugins.formatting`, `mistune.plugins.table` and `mistune.plugins.url`); the filter `markdown(value, style, math_engine=None, lazy_load=False, strip_paragraphs=False)` with its signature unchanged and `math_engine` accepted but unused until group 3; `camo_client` importable from the module.

- [ ] **Step 1: Pin.** Replace `"mistune<2"` with `"mistune>=3.4,<4"`; run `uv lock`. Verify `uv lock --check` passes, `uv.lock` pins mistune 3.4 or later, and `git diff --stat` shows only `pyproject.toml` and `uv.lock`; sync `env313` with `uv sync --locked --python 3.13`.
- [ ] **Step 2: Rewrite** `__init__.py`: delete the 0.8 classes (`CodeSafeInlineGrammar`, `AwesomeInlineGrammar`, `AwesomeInlineLexer`) and the bodies of the old renderer; implement `AwesomeRenderer`, `_create_markdown`, and make `markdown()` call `_create_markdown(escape)(value)` where `escape = styles.get('safe_mode', True)`. Keep `cleaner_cache`, `get_cleaner`, `fragments_to_tree`, `strip_paragraphs_tags`, `fragment_tree_to_str`, the camo/lazy-load/strip-paragraphs/bleach sequence and the logger exactly as they are. Remove the imports and locals listed in Global Constraints.
- [ ] **Step 3: Run the module tests.** Expected failures are only the ones the output change explains; adapt `test_post_process` and `test_bleach` (a line that is only `<img ...>` is an HTML block with no `<p>`), and in `TestAutolinkInjection` rewrite `test_href_is_the_escaped_url` and `test_single_quote_in_url` for the percent-encoded hrefs (`%22`, `%27`) while the link text keeps the raw URL, and delete the two `rel="nofollow"` assertions (group 2's `TestLinks` owns them). Security assertions stay. Every other failure is a bug in the rewrite, not in the test.
- [ ] **Step 4: Add `TestInputEdgeCases`** (Review Focus; these map to no Scenario by design): `test_empty_input` (`markdown('', 'comment') == ''`); `test_entities_and_unicode` (`'a &amp; b <3 \U0001F600'` renders containing `a &amp; b`, `&lt;3` and the emoji once, and never `&amp;amp;`); `test_crlf_line_endings` (`'a\r\n\r\nb'` gives two `p` elements and no `\r`); `test_long_single_line` (`'a' * 8192` renders in under 1.0 s).
- [ ] **Step 5: Verify.** Markdown tests all pass on Python 3.13 and on 3.14 (`UV_PROJECT_ENVIRONMENT=$SCRATCH/env314`, built with `--python 3.14`); `uv run flake8` clean; the full suite (`uv run --no-sync python manage.py test judge --noinput` with the controller's `matrix_settings` and database, after `manage.py compilejsi18n` into the scratch `STATIC_ROOT`) reports OK with at least 209 tests. A failure outside `judge.jinja2.markdown` is reported with its traceback, not worked around.
- [ ] **Step 6: Commit** `refactor(markdown): port the renderer to mistune 3`, staging `pyproject.toml`, `uv.lock`, `judge/jinja2/markdown/__init__.py` and `judge/jinja2/markdown/test_markdown.py`. The body lists what is temporarily absent until groups 2 and 3.

### Task 3: Measure the parser build cost

Covers `tasks.md` 1.4.

**Files:**
- Modify only if the cost is over 5 ms: `judge/jinja2/markdown/__init__.py`, `judge/jinja2/markdown/test_markdown.py`

**Interfaces:**
- Consumes: `_create_markdown(escape: bool) -> mistune.Markdown` from Task 2.
- Produces: unchanged `_create_markdown` signature; if a cache is added it is keyed by `escape` only and the cached `Markdown` object is never mutated per call.

- [ ] **Step 1: Measure.** With a throwaway script outside the repo, time 1000 calls of `_create_markdown(True)` and of `_create_markdown(False)` (after one warm-up call) and report milliseconds per call.
- [ ] **Step 2: Decide.** At or under 5 ms per call: change nothing, report the number, no commit. Over 5 ms: cache the two instances in a module-level dict and add `test_cache_does_not_leak_between_styles` to `TestInputEdgeCases` (render `<script>x</script>` with `comment`, then with `problem-full`, then with `comment` again: escaped, raw, escaped).
- [ ] **Step 3: If code changed**, markdown tests and `uv run flake8` pass, then commit `perf(markdown): reuse the parser instances` with the measured numbers in the body.
