# Design

## Context

See `proposal.md` for the motivation and `specs/markdown-rendering/spec.md` for the required behavior.

Current state, observed in the code:

- `judge/jinja2/markdown/__init__.py` (198 lines) subclasses the 0.8 `Renderer`, `InlineGrammar` and
  `InlineLexer`, builds one `Markdown` object per call, then post-processes the HTML string with lxml (camo,
  lazy loading, paragraph stripping) and bleach. `math.py` (65 lines) adds the math rules and pushes `latex`
  into the 0.8 private list `_pre_tags`. `judge/utils/mathoid.py` only imports `escape` from `mistune`.
  Nothing else imports `mistune` (`dmoj/settings.py` does not).
- The only code that depends on the HTML shape is downstream of the filter: the `reference` filter
  (`judge/jinja2/reference.py`, walks an lxml tree), `judge/utils/camo.py`, `judge/feed.py` and
  `judge/utils/opengraph.py`. They keep working as long as the output is well-formed HTML.
- Existing tests: `judge/jinja2/markdown/test_markdown.py` (11 tests, `SimpleTestCase`, no database).
- Throwaway check on mistune 3.4.0 (scratch venv, not in the repo) with escaping on and the table, strikethrough
  and url plugins: links to `javascript:`, `data:text/html`, `livescript:` and `file:` become `#harmful-link`;
  `data:image/{gif,png,jpeg,webp}` stays allowed for images; raw `<script>` / `<img onerror>` come out escaped;
  `~a~ and ~~b~~` gives literal `~a~` plus `<del>`; `#Title` stays literal; the 7 pathological inputs of the spec
  (up to 5000 repetitions) render in at most 0.042 s.

## Goals / Non-Goals

**Goals:**
- Move to `mistune>=3.4,<4` using only its documented extension points (renderer subclass, `md.inline.register`,
  `md.block.register`, plugins), so that a later 3.x minor does not break us.
- Keep the filter's signature, the style settings and the downstream consumers unchanged.
- Make the guarantees of the spec (bounded time, no executable markup, no exceptions) true by tests, not by
  review.

**Non-Goals:**
- Reproducing 0.8 behavior beyond the spec: the maintainer accepts CommonMark differences (for example `_x_`
  becomes emphasis, Markdown is no longer parsed inside HTML blocks, list and quote edge cases).
- Footnotes, definition lists and other plugins; custom URL-scheme logic.
- Changing the bleach allowlists, Mathoid, Texoid, camo or the `reference` filter.

## Decisions

1. **Pin `mistune>=3.4,<4`.** The advisories that matter are fixed from 3.3.0 (quadratic parsing, protocol
   filtering), but the code is written and measured against 3.4.0 and uses its renderer helpers
   (`render_attrs`, `sanitize_url`, `escape_attribute`); `uv.lock` resolves to 3.4.x, so 3.3 would never be
   tested. Alternative: `>=3.3`; rejected, it promises a version nobody runs. Alternative: `==3.4.0`;
   rejected, it blocks security patches.

2. **Renderer subclass plus small plugins, built per call as today.** An `HTMLRenderer` subclass carries the
   site rendering (links, headings, code, `<latex>`, math output); the `strikethrough`, `table` and `url`
   plugins of mistune provide the syntax; two small local plugins add math (inline rules) and the `<latex>`
   block rule. The `Markdown` object is built per call like the current code. Task 1.2 measures the build
   cost; only if it is over 5 ms is a cache keyed by (escape, nofollow, texoid, math, math_engine) added.
   Alternative: always cache; rejected, state (the Mathoid parser, Texoid client) lives in the renderer and a
   cache is only worth its complexity if measurement says so.

3. **Escaping and URL safety come from mistune.** `escape=True` for safe-mode styles; raw HTML is escaped by
   the library. URL filtering uses `HTMLRenderer`'s built-in policy, which in 3.4 is an allowlist
   (`SAFE_PROTOCOLS`: `http`, `https`, `mailto`, `tel`, `ftp`, `ftps`, `irc`, `ircs`, relative URLs, plus
   `GOOD_DATA_PROTOCOLS`: `data:` images of gif, png, jpeg and webp); everything else becomes
   `#harmful-link`, for links and images, in every style. We keep the default lists, with no per-style
   exception: staff styles already get only `http`, `https` and `mailto` from bleach's defaults, so the
   visible change is in the user styles and the unbleached admin styles, and the corpus report (task 4.3)
   counts the affected documents. This replaces our `escape_link` hotfix. `TestAutolinkInjection` stays as the
   regression guard, but `test_href_is_the_escaped_url` and `test_single_quote_in_url` must be rewritten, not
   only re-stringed: mistune percent-encodes `"` as `%22` and `'` as `%27` in the href, while the visible
   link text keeps the raw URL. Alternative: our own scheme list; rejected, a second place to get it wrong.

4. **Math as inline rules registered ahead of `escape`, emphasis and code.** Patterns: `~x~` (guarded with
   `(?!~)` so it never matches `~~`), `\(x\)`, `$$x$$` and `\[x\]`, all multi-line, calling the existing
   `MathoidMathParser` (`inline_math` / `display_math`) or the escaped `\(..\)` / `\[..\]` fallback when there
   is no engine. A rule signature is `(inline, m, state)`. The rule must come before mistune's own backslash
   escape rule: checked on 3.4.0, `\(a_b\)` otherwise renders as `(a_b)`, and a rule registered only
   `before='emphasis'` still loses. The old code treated `$$` and `\[` as inline rules too, so a display
   formula can sit in the middle of a paragraph; we keep that. Fallback if precedence still cannot be
   reproduced: extract the math spans in a pre-pass, replace them by opaque placeholders that survive
   escaping, and substitute the rendered math after parsing. The corpus check (task 4.2) decides if it is
   needed. `mathoid.py` takes `escape` from `mistune.util`; note that it always escapes `&` (0.8's
   `smart_amp` did not double-escape an existing entity), which only affects the fallback text.

5. **`<latex>` as a block rule.** In 0.8 the tag was added to the private `_pre_tags` list so that a `<latex>`
   block may contain blank lines. In 3.x a local block rule registered before the HTML-block rule recognises
   `<latex ...>...</latex>` and the renderer sends it to Texoid when the style enables it; otherwise it falls
   back to the normal raw-HTML path of the style (escaped or passed to bleach), as today.

6. **Tables:** the `table` plugin, with the renderer's table hook wrapping the output in
   `<div class="h-scrollable-table">` and `<table class="table">`.

7. **Links:** override the renderer's `link` (also used by autolinks and the `url` plugin) to add
   `rel="nofollow"` when the style asks and the URL has a host outside `NOFOLLOW_EXCLUDED`; same `urlparse`
   logic as today, so `mailto:` and relative links get no `rel`.

8. **Headings:** `min(level + 2, 6)`. The old code emitted `<h7>` and `<h8>` for `#####`/`######`, which are
   not HTML elements. This cap is a small deliberate change (one `min()`), listed in the spec.

9. **`#Title` compatibility in the block parser, not in the text.** A `BlockParser` subclass overrides the
   `atx_heading` entry of `SPECIFICATION` so the space after the hashes is optional
   (`^ {0,3}(?P<atx_1>#{1,6})(?!#+)(?P<atx_2>[ \t]*|[ \t]*[^#\s].*?)$`). Checked on 3.4.0: `#Title` and
   `##Sub` become headings, while fenced code (``` and ~~~), `<style>` and `<pre>` blocks, list items and
   quotes behave correctly because the parser already knows its context; `#include` outside any block is a
   heading, as in 0.8. Rejected: a regex pre-pass over the source, which would also rewrite lines inside raw
   HTML blocks (a staff `<style>` with `#a { color: red }` would break) and needs its own fence scanner. This
   is the only compatibility code.

10. **Post-processing is untouched:** the HTML string still goes to lxml (camo, lazy loading, paragraph
    stripping) and then bleach with the same cleaner cache.

11. **Verification beyond unit tests** (kept outside the repo because the corpus must never be committed): a
    script run by the controller loads the corpus (`~/Documentos/online-judge-corpus/corpus.jsonl`, 182
    documents) and, with a recording stand-in for `MathoidMathParser`, compares the (kind, formula) sequence
    produced by the 0.8 code (from `master`, in a separate environment) and by the new code for every
    document; it also renders every document with every style for errors and time. Its report goes to the
    maintainer; nothing from it is committed.

12. **Tests patch module names; the rewrite keeps them importable from `judge.jinja2.markdown`.** The
    scenarios depend on values fixed at import time (`NOFOLLOW_WHITELIST`, `TEXOID_ENABLED`, `camo_client`) or
    on settings that are off under test (`MATHOID_URL` is `False`; no style sets `nofollow` to `False`). The
    tests therefore use `override_settings(MARKDOWN_STYLES=..., MATHOID_URL=...)` and `mock.patch` on
    `NOFOLLOW_WHITELIST`, `TEXOID_ENABLED`, `TexoidRenderer`, `MathoidMathParser` and `camo_client` in
    `judge.jinja2.markdown`; the rewrite keeps these names there. Existing tests are adapted where mistune 3
    changes the HTML: a line that is only `<img src="...">` is an HTML block without a `<p>` wrapper, so the
    expected strings of `test_post_process` and `test_bleach` change.

13. **Red/green evidence comes from a baseline worktree.** Before the dependency changes, each group's tests are
    run against an unmodified `master` worktree with its own environment (0.8): tests of behavior that is kept
    must pass there (they characterize today's behavior), tests of new guarantees (timing, malformed input,
    `<h6>` cap, scheme allowlist, `#Title` inside HTML blocks) must fail. This avoids a red step that is only
    an import error, since the old module cannot be imported once mistune 3 is installed.

14. **The XSS battery is written by the implementer and extended by a security reviewer.** No list of the
    payloads of the earlier spike survives. The implementer seeds it with the inputs of the commit `373ae519`
    tests and adds several variants for each category named in the spec (at least 40 in total); an independent
    security review may add more. The oracle is independent of the renderer: parse the output with lxml and
    check attributes and URL schemes after normalization (strip whitespace and control characters, decode
    entities, lowercase).

## Risks / Trade-offs

- **Math delimiters behave differently** (precedence against escapes, emphasis, code; the throwaway spike
  stubbed Mathoid, so math was never validated end to end) -> the corpus equality check over 71 documents with
  `~x~`, 3 with `$$`/`\[`, the unit tests of the spec, and the pre-pass fallback of decision 4.
- **Visible changes in staff content**: 24 of 182 documents use raw HTML, 9 use tables, 33 use setext headings
  and 9 use `_x_`; Markdown inside raw HTML is no longer rendered. Accepted by the maintainer; the corpus run
  reports how many documents change so the deploy is not a surprise.
- **A 3.x minor changes an extension API** -> pin `<4`, use documented hooks only, the suite and the corpus run
  are repeatable when `uv lock --upgrade` moves the version.
- **Test timing flakiness**: the budget is 1 s against measured times under 0.05 s, a 20x margin.
- **Stale HTML after deploy**: `{% cache %}` fragments (problems, blog, user "about" 24 h; contests and
  organizations 1 h) keep old HTML until they expire; comments are not fragment-cached. Acceptable; flushing
  the cache is optional and not part of the change.
- **The XSS battery is public**: the payload shapes that worked against 0.8 are already public through the
  tests of commit `373ae519`; the battery adds no new disclosure.

## Migration Plan

1. Merge to `master` after the suite (Python 3.13 and 3.14), flake8, the Scenario-to-test check and the corpus
   report pass.
2. Deploy with the normal `./scripts/update` (backup, image rebuild from the new `uv.lock`, migrate: no
   migrations here, start). No `dmoj-docker` change.
3. Rollback: revert the merge commit, push, run `./scripts/update` again. No data was changed, so nothing
   has to be restored.
