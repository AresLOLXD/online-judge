# Port Markdown to mistune 3, group 3: math and LaTeX blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the four math delimiters (`~x~`, `\(x\)`, `$$x$$`, `\[x\]`) rendered through Mathoid, and `<latex>` blocks rendered through Texoid, on the mistune 3 filter built by groups 1 and 2.

**Architecture:** `judge/jinja2/markdown/math.py` is rewritten as two small mistune plugins that only parse syntax (`math` registers four inline rules ahead of mistune's backslash `escape` rule; `latex` registers one block rule); rendering and the service clients stay in `AwesomeRenderer` (`judge/jinja2/markdown/__init__.py`), which keeps the names the tests patch. A prototype on mistune 3.4.0 (controller probe, not in the repo) already shows the inline approach reproducing every delimiter case of the spec; the placeholder pre-pass of design decision 4 is NOT needed unless a test of Task 1 proves otherwise.

**Tech Stack:** Python 3.13/3.14, Django 5.2, mistune 3.4 (`InlineParser.register`, `BlockParser.register`), `judge.utils.mathoid.MathoidMathParser`, `judge.utils.texoid.TexoidRenderer`, uv.

**Spec:** `openspec/changes/port-markdown-to-mistune-3/design.md` (decisions 4, 5, 12, 13) and `openspec/changes/port-markdown-to-mistune-3/specs/markdown-rendering/spec.md`. This plan covers `tasks.md` group 3 (ids 3.1-3.3).

## Global Constraints

- Branch `feat/mistune-3-port`. Conventional Commits, English, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push. Stage only the files a task names.
- Style: 120 columns, single quotes, trailing commas, pycharm import order. Lint with `uv run --no-sync flake8 judge/jinja2/markdown judge/utils/mathoid.py`.
- Do not weaken any test or payload of groups 1 and 2. Do not edit `dmoj/settings.py`, `judge/utils/texoid.py`, the bleach allowlists, or the post-processing in `markdown()`.
- Names that tests patch must stay importable from `judge.jinja2.markdown`: `MathoidMathParser`, `TexoidRenderer`, `TEXOID_ENABLED`, `NOFOLLOW_WHITELIST`, `camo_client`.
- Environment (scratch only, never in the repo): `export SCRATCH=/tmp/claude-1000/-var-home-areslolxd-Documentos-online-judge/6b1cb67e-65ce-4d10-8f6f-3a9fec626c0d/scratchpad UV_LINK_MODE=copy PYTHONPATH=$SCRATCH DJANGO_SETTINGS_MODULE=probe_settings UV_PROJECT_ENVIRONMENT=$SCRATCH/env313; uv run --no-sync python manage.py test judge.jinja2.markdown --noinput` (`probe_settings.py`: SQLite in memory, locmem caches; recreate it from the group 1 plan text if the scratchpad was wiped). Always set `UV_PROJECT_ENVIRONMENT`; never create `.venv`, `static/`, `formcheckerprob/` or `.mo` in the repo (check `git status`).
- Full suite (Task 3 only): scratch MariaDB on `127.0.0.1:3307` (user and password `dmoj`) with `DJANGO_SETTINGS_MODULE=matrix_settings`; run `manage.py compilejsi18n` first. Never start, stop or alter database services; if unreachable report BLOCKED.
- Baseline (Task 1 only): `git worktree add --detach $SCRATCH/baseline e2dd72ff`, environment `UV_PROJECT_ENVIRONMENT=$SCRATCH/env_baseline` (mistune 0.8). Remove the worktree when done. On the baseline the math parser name lives in `judge.jinja2.markdown.math`, not in `judge.jinja2.markdown`: for the baseline run only, use a copy of the test file in which `mock.patch('judge.jinja2.markdown.MathoidMathParser', ...)` targets `judge.jinja2.markdown.math.MathoidMathParser`, and say so in the report.

## Review Focus

- Entities in a formula: `~a &lt; b~` with no math engine renders `\(a &lt; b\)` (shown as `a < b`), not `&amp;lt;`; with an engine the service receives the raw `a &lt; b` (the service cleans it with `format_math`).
- Repeated unterminated openers (`\(` x4096, `\[` x4096, `$$a ` x2048, `~a ` x2730, `$` x8192, `~ ` x4096) render within the 1 s budget with the math rules active.
- Math inside link text, a heading and a table cell reaches the service once each (`[~a~](http://x.y)`, `## ~a~`, a pipe-table cell `\(c\)`).
- Single or unpaired delimiters stay literal text: `a ~ b`, `$$a$`, `\~a\~` (escaped tildes), and `~a~~b~` does not raise.
- `<latex>`: two blocks in one document stay two images; an unterminated `<latex>` does not swallow the rest of the document and does not raise; a block with blank lines inside is one block.
- Known limit, not tested: a multi-line `$$ ... $$` whose inner line starts with `#` is cut by the `#Title` heading rule (group 2). Leave a `shortcut:` comment on the math rules saying so.

---

### Task 1: Tests first, run against the baseline

Covers `tasks.md` 3.1.

**Files:**
- Modify: `judge/jinja2/markdown/test_markdown.py` (append test classes and a stub; no change to existing tests)
- Outside the repo: baseline worktree and environment described in Global Constraints

**Interfaces:**
- Consumes: group 1 helpers `render_tree`, `executable_markup`, `assert_fast`; group 2's `NOFOLLOW_WHITELIST`.
- Produces: classes `TestMath`, `TestLatexBlocks`, a module-level stub class `RecordingMath` (`__init__(self, type)`, `calls: list` shared at class level, `inline_math(self, formula) -> str` returning `<span class="m-inline">{formula}</span>` and `display_math(self, formula) -> str` returning `<span class="m-display">{formula}</span>`, each appending `('inline'|'display', formula)` to `calls`), and a stub `RecordingTexoid` (`get_result(self, latex)` returning a configurable result). Tests are named as the snake_case of their Scenario with the docstring `Scenario: <exact name>`; no-Scenario tests say so.

- [ ] **Step 1: Write the shared setup.** A helper `render_math(source, style='comment', **kwargs)` that clears `RecordingMath.calls`, applies `override_settings(MATHOID_URL='http://mathoid.invalid')` and `mock.patch('judge.jinja2.markdown.MathoidMathParser', RecordingMath)`, calls `markdown(source, style, math_engine='svg', **kwargs)` and returns the lxml tree via `fragments_to_tree`. The `comment` style has `math` enabled in `MARKDOWN_STYLES`.
- [ ] **Step 2: Write `TestMath`:**
  - `test_all_four_delimiters`: `~a+b~ \(a+b\) $$a+b$$ \[a+b\]` gives `calls == [('inline','a+b'), ('inline','a+b'), ('display','a+b'), ('display','a+b')]` and the output contains the stub's `m-inline` and `m-display` spans, two of each.
  - `test_math_keeps_its_own_characters`: sources `\(a_b\)`, `$$x_1*y_2$$`, `~a_b~`, `\[a\\b\]` (the last is `\[a\\b\]` as written in Markdown, i.e. backslash backslash) give formulas `a_b`, `x_1*y_2`, `a_b`, `a\\b` exactly, with no `em`, `strong` or stray `\` processing.
  - `test_tilde_math_next_to_strikethrough`: `~a~ and ~~b~~` gives `calls == [('inline','a')]` and a `del` with text `b`.
  - `test_math_delimiters_inside_code`: `` `~a~` `` and a fenced block containing `$$a$$` give no calls and the text inside `code`.
  - `test_math_without_a_math_engine`: with no engine (plain `markdown('~a<b~ $$a<b$$', 'comment')` and `MATHOID_URL` false) the output contains `\(a&lt;b\)` and `\[a&lt;b\]`.
  - No-Scenario extras: `test_entity_in_a_fallback_formula` (`~a &lt; b~` with no engine contains `\(a &lt; b\)` and not `&amp;lt;`; with the stub the formula is the raw `a &lt; b`), `test_math_in_link_heading_and_table` (the three sources of the Review Focus give one call each, with the span inside `a`, `h3` and `td`), `test_unpaired_delimiters_stay_literal` (`a ~ b`, `$$a$`, `\~a\~` give no calls; `~a~~b~` does not raise), `test_unterminated_math_openers_are_fast` (each source of the Review Focus through `assert_fast` with the stub active).
- [ ] **Step 3: Write `TestLatexBlocks`** with `override_settings(MARKDOWN_STYLES={'latex': {'safe_mode': False, 'texoid': True}})` and `mock.patch('judge.jinja2.markdown.TEXOID_ENABLED', True)` and `mock.patch('judge.jinja2.markdown.TexoidRenderer', RecordingTexoid)`:
  - `test_successful_latex_block`: a stub result `{'svg': '/s.svg', 'png': '/s.png', 'meta': {'width': '10px', 'height': '5px'}}` for `<latex>x^2</latex>` gives one `img` with `width` `10px` and `height` `5px` inside a `div` (and inside a `span` for `<latex inline>x^2</latex>`); the stub received `x^2`.
  - `test_latex_service_error`: result `{'error': 'bad <tex>'}` gives `pre` with text `bad <tex>` (escaped in the raw output); result `None` gives `pre` with the source `x^2`.
  - No-Scenario extras: `test_latex_block_with_blank_lines` (source `<latex>\na\n\nb\n</latex>` is one stub call with `a\n\nb`), `test_two_latex_blocks_stay_separate`, `test_unterminated_latex_does_not_swallow_the_rest` (`<latex>x\n\nafter *me*` returns a string containing `<em>me</em>`, no exception), `test_latex_is_plain_text_in_a_style_without_texoid` (`comment` style: output shows `&lt;latex&gt;`, stub never called).
- [ ] **Step 4: Run in the baseline.** Copy the (adjusted, see Global Constraints) test file into `$SCRATCH/baseline/judge/jinja2/markdown/` and run only `TestMath TestLatexBlocks` with the scratch settings. Expected pass (kept behavior): the four delimiters, `keeps_its_own_characters`, `inside_code`, `without_a_math_engine`, the latex success/error/blank-line tests, the unpaired-delimiter test. Record each as pass, fail or error; anything surprising (for example `test_tilde_math_next_to_strikethrough`, `test_unterminated_math_openers_are_fast`) is reported, not forced. Then run the same classes on the branch: every test red there is expected (math and latex are not built yet).
- [ ] **Step 5: Commit** `test(markdown): add the math and LaTeX block tests`. The body holds the baseline pass/fail table and the list of tests red on the branch until Tasks 2 and 3. `uv run --no-sync flake8 judge/jinja2/markdown` is clean.

### Task 2: Math

Covers `tasks.md` 3.2.

**Files:**
- Modify: `judge/jinja2/markdown/math.py` (rewrite), `judge/jinja2/markdown/__init__.py`, `judge/utils/mathoid.py`

**Interfaces:**
- Consumes: Task 1 tests; groups 1-2 `AwesomeRenderer`, `_create_markdown(escape, nofollow)`, `markdown()`.
- Produces: `judge/jinja2/markdown/math.py` exports `def math(md: mistune.Markdown) -> None`; it registers four inline rules and produces tokens `{'type': 'inline_math', 'raw': formula}` and `{'type': 'display_math', 'raw': formula}`. `AwesomeRenderer.__init__(self, escape: bool = True, nofollow: bool = True, math: bool = False, math_engine: str | None = None)`; `inline_math(self, formula: str) -> str` and `display_math(self, formula: str) -> str`. `_create_markdown(escape: bool, nofollow: bool = True, math: bool = False, math_engine: str | None = None) -> mistune.Markdown`. Importable from the package: `MathoidMathParser`.

- [ ] **Step 1: Rewrite `math.py`** as the `math` plugin. Start from the prototype that the controller verified on mistune 3.4.0 (`$SCRATCH/proto_math.py`, read it if the scratchpad still has it; the four patterns below are enough otherwise): four rules registered with `md.inline.register(name, pattern, func, before='escape', start_chars=...)` so they win over the backslash `escape` rule: `\$\$(?P<math_dollar>[\s\S]+?)\$\$` (display), `\\\[(?P<math_bracket>[\s\S]+?)\\\]` (display), `\\\((?P<math_paren>[\s\S]+?)\\\)` (inline), `(?<!~)~(?!~)(?P<math_tilde>[^~]+?)~(?!~)` (inline). Each rule needs its OWN named group (mistune combines all inline rules into one regex; a repeated group name raises `re.PatternError`), and a parse function `(inline, m, state)` that appends the token and returns `m.end()`. Tune a pattern only if a test requires it. Delete the 0.8 grammar, lexer and renderer classes and the `mistune._pre_tags` line. Add the `shortcut:` comment of the Review Focus.
- [ ] **Step 2: Renderer.** In `__init__.py` import `MathoidMathParser` (from `judge.utils.mathoid`) and `math` (from `.math`, name it so it does not shadow the stdlib in the module, for example `from .math import math as math_plugin`); `AwesomeRenderer.__init__` sets `self.mathoid = MathoidMathParser(math_engine or 'svg') if math else None`; `inline_math` and `display_math` return `self.mathoid.inline_math(formula)` / `display_math(formula)` when the parser exists and the formula is non-empty, otherwise `\(` + safe_entity(formula) + `\)` (display: `\[`..`\]`), where `safe_entity` is `mistune.util.safe_entity` (decode then escape, as group 1's `text()`: it keeps an author-typed `&lt;` from becoming `&amp;lt;`). Add the plugin to the plugin list in `_create_markdown` (always on: the fallback text is part of the spec) and pass `math` and `math_engine` through. In `markdown()` compute `math = bool(settings.MATHOID_URL) and styles.get('math', False)` and pass `math and math_engine is not None` (read `settings.MATHOID_URL` at call time).
- [ ] **Step 3: `mathoid.py`.** Replace `from mistune import escape` with `from mistune.util import safe_entity` and use `safe_entity` at its two call sites (`display_math` and `inline_math` fallback, lines 157 and 161), for the same reason (0.8 did not double-escape an existing entity). No other change.
- [ ] **Step 4: Verify.** All `TestMath` tests pass; every group 1 and 2 test still passes (battery, timing, headings, links, tables, code); `git grep -n "_pre_tags\|InlineGrammar\|InlineLexer" judge/` is empty; flake8 clean on `judge/jinja2/markdown judge/utils/mathoid.py`; `git status` clean of stray files.
- [ ] **Step 5: Commit** `feat(markdown): restore math rendering on mistune 3`, staging `math.py`, `__init__.py` and `mathoid.py`.

### Task 3: LaTeX blocks and integration run

Covers `tasks.md` 3.3.

**Files:**
- Modify: `judge/jinja2/markdown/math.py`, `judge/jinja2/markdown/__init__.py`

**Interfaces:**
- Consumes: Task 2's `_create_markdown(escape, nofollow, math, math_engine)`.
- Produces: `math.py` exports `def latex(md: mistune.Markdown) -> None` (a block rule `<latex ...>...</latex>` registered ahead of the HTML block rules, producing `{'type': 'latex', 'raw': source, 'attrs': {'inline': bool}}`, case-sensitive tag, lazy match so two blocks stay separate; an unterminated tag does not match). `AwesomeRenderer.__init__` gains `texoid: bool = False` and sets `self.texoid = TexoidRenderer() if texoid else None`; `latex(self, source: str, inline: bool = False) -> str`; `_create_markdown(..., texoid: bool = False)` adds the plugin only when `texoid` is true, so styles without Texoid keep the normal raw-HTML path. `__init__.py` imports `TEXOID_ENABLED` and `TexoidRenderer` from `judge.utils.texoid`; `markdown()` computes `texoid = TEXOID_ENABLED and styles.get('texoid', False)`.

- [ ] **Step 1: Block rule and renderer.** Implement as described. The output must match what the 0.8 code produced (`git show e2dd72ff:judge/jinja2/markdown/__init__.py`, `block_html`): the source is `html.unescape`d before it is sent to Texoid; no result gives `<pre>` plus the escaped source; an `error` key gives `<pre>` plus the escaped error; success gives the `img` (svg with png `onerror` fallback, `class="tex-full"`, width and height) inside a `span` for the `inline` attribute or a centered `div` otherwise, with the same inline `style` values. Check which block rule name (`block_html` or `raw_html`) is active in `BlockParser.DEFAULT_RULES` and register ahead of it.
- [ ] **Step 2: Verify.** All of `TestLatexBlocks` and the whole module pass on Python 3.13 and 3.14 (`UV_PROJECT_ENVIRONMENT=$SCRATCH/env314`, `--python 3.14`); the full suite (`matrix_settings`) is OK with no fewer than 244 tests plus the new ones; flake8 clean.
- [ ] **Step 3: Commit** `feat(markdown): render LaTeX blocks through Texoid on mistune 3`, staging `math.py` and `__init__.py`.
