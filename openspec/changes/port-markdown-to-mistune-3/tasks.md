# Tasks

All tests go in `judge/jinja2/markdown/test_markdown.py` and carry `Scenario: <scenario name>` in their
docstring. Run them with `uv run python manage.py test judge.jinja2.markdown` (no database needed for this
module; the full suite needs MySQL or MariaDB and `manage.py compilejsi18n`).

## 1. Dependency, safety core and post-processing

- [x] 1.1 Create a baseline worktree of unmodified `master` outside the repository with its own environment (mistune 0.8). Write this group's tests first: `TestSafeModeStyles` (raw HTML as text, dangerous schemes in every safe-mode style, the XSS battery of design decision 14), `TestPathologicalInput`, `TestMalformedInput`, `TestPostProcessing` (image proxy with a patched `camo_client`, paragraph stripping), `TestInlineExtras` (bare URL becomes a link, `~~x~~` becomes `del`). Run them in the baseline worktree and record in the commit message which pass (they characterize kept behavior) and which fail (new guarantees such as the 22 s autolink input); have an independent security review read the battery and add payloads.
- [x] 1.2 In `pyproject.toml` replace `mistune<2` with `mistune>=3.4,<4` and run `uv lock`; verify `uv lock --check` passes, `uv.lock` pins a 3.4 or later version, and only `mistune` (and anything it newly needs or drops) changed.
- [x] 1.3 Rewrite `judge/jinja2/markdown/__init__.py` on mistune 3: renderer subclass with escaping per style, the library's URL policy, the `strikethrough`, `table` and `url` plugins, unchanged filter signature, unchanged lxml post-processing and bleach cleaner cache; remove the 0.8 grammar/lexer classes; keep `NOFOLLOW_WHITELIST`, `TEXOID_ENABLED`, `TexoidRenderer`, `MathoidMathParser` and `camo_client` importable from `judge.jinja2.markdown` (design decision 12); verify the tests of 1.1 pass, and that the existing `TestMarkdown`, `TestFragmentUtils` and `TestAutolinkInjection` pass after adapting only what the output changes intentionally (no `<p>` around a lone `<img>` line, `%22` and `%27` in hrefs), keeping their security assertions; the two `rel="nofollow"` assertions of `TestAutolinkInjection` move to group 2's `TestLinks`, which owns that behavior. `NOFOLLOW_WHITELIST`, `TEXOID_ENABLED` and `TexoidRenderer` are removed while unused (flake8) and re-added by groups 2 and 3, whose tests patch them.
- [ ] 1.4 Measure the per-call cost of building the `Markdown` object (1000 builds); if over 5 ms add a cache keyed by (escape, nofollow, texoid, math, math_engine) and re-run the module tests; record the measured number in the commit message.

Covers: markdown-rendering / Rendering time is bounded / Repeated unterminated autolink openers
Covers: markdown-rendering / Rendering time is bounded / Repeated quadratic-prone constructs
Covers: markdown-rendering / Malformed or deeply nested input never raises / Deep nesting and unterminated constructs
Covers: markdown-rendering / Safe-mode styles never produce executable markup / Raw HTML is shown as text
Covers: markdown-rendering / Safe-mode styles never produce executable markup / Dangerous schemes in links, images and autolinks
Covers: markdown-rendering / Safe-mode styles never produce executable markup / Quotes cannot break out of a link attribute
Covers: markdown-rendering / Safe-mode styles never produce executable markup / Payload battery
Covers: markdown-rendering / Staff styles are sanitized by their allowlist / Staff style removes scripts and keeps allowed markup
Covers: markdown-rendering / Staff styles are sanitized by their allowlist / Unbleached staff style keeps raw HTML
Covers: markdown-rendering / Output post-processing is preserved / Lazy loading
Covers: markdown-rendering / Output post-processing is preserved / Image proxy
Covers: markdown-rendering / Output post-processing is preserved / Paragraph stripping
Covers: markdown-rendering / Bare URLs and strikethrough are supported / Bare URL and strikethrough

## 2. Site presentation: links, headings, tables, code

- [ ] 2.1 Write the tests first: `TestLinks` (nofollow by host with a patched `NOFOLLOW_WHITELIST`, a style without nofollow through `override_settings(MARKDOWN_STYLES=...)`, the scheme allowlist), `TestHeadings`, `TestHeadingWithoutSpace`, `TestTables`, `TestCode`; run them in the baseline worktree of 1.1 and record which pass (kept behavior: nofollow, tables, code, `#Title`) and which fail (new: `<h6>` cap, scheme allowlist, `#Title` untouched inside HTML blocks).
- [ ] 2.2 Implement the `nofollow` logic in the renderer's link hook (host outside `NOFOLLOW_EXCLUDED`, none for relative and `mailto:`), the heading shift `min(level + 2, 6)`, the scrollable table wrapper, and the code block hook (highlight with a language, escaped `<pre><code>` without); verify `TestLinks`, `TestHeadings`, `TestTables` and `TestCode` pass.
- [ ] 2.3 Implement the `#Title` rule as a `BlockParser` subclass that relaxes `atx_heading` (design decision 9) and use it from the filter; verify `TestHeadingWithoutSpace` passes, including `#include <stdio.h>` inside a fence and inside a `<pre>` block, and `#a { color: red }` inside a `<style>` block.

Covers: markdown-rendering / External links are not followed by search engines / Nofollow by host
Covers: markdown-rendering / External links are not followed by search engines / Style without nofollow
Covers: markdown-rendering / Link and image URLs use a safe-scheme allowlist / Allowed and replaced schemes
Covers: markdown-rendering / Headings are shifted two levels / Heading levels
Covers: markdown-rendering / Headings without a space after the hashes still work / Heading without a space
Covers: markdown-rendering / Headings without a space after the hashes still work / Fenced code is untouched
Covers: markdown-rendering / Headings without a space after the hashes still work / Raw HTML blocks are untouched
Covers: markdown-rendering / Fenced code is highlighted when a language is given / Code blocks
Covers: markdown-rendering / Tables are scrollable / Table wrapper

## 3. Math and LaTeX blocks

- [ ] 3.1 Write the tests first: `TestMath` (four delimiters with a patched `MathoidMathParser` and `override_settings(MATHOID_URL=...)`, formulas with `_`, `*` and `\\`, tilde math next to `~~x~~`, delimiters inside code, no math engine fallback) and `TestLatexBlocks` (success and error with a patched `TexoidRenderer` and `TEXOID_ENABLED`, including blank lines inside the block); run them in the baseline worktree of 1.1 and record which pass and which fail.
- [ ] 3.2 Implement the math inline rules (`~x~` guarded against `~~`, `\(x\)`, `$$x$$`, `\[x\]`) registered before the escape rule, and the renderer output (math service or the escaped `\(..\)` / `\[..\]` fallback); if the inline API still cannot reproduce the delimiter precedence, use the placeholder pre-pass of design decision 4 instead; update the `escape` import in `judge/utils/mathoid.py`; verify `TestMath` passes.
- [ ] 3.3 Implement the `<latex>` block rule and its Texoid rendering (and the raw-HTML fallback when the style does not enable Texoid); verify `TestLatexBlocks` passes.

Covers: markdown-rendering / Math delimiters are recognised / All four delimiters
Covers: markdown-rendering / Math delimiters are recognised / Math keeps its own characters
Covers: markdown-rendering / Math delimiters are recognised / Tilde math next to strikethrough
Covers: markdown-rendering / Math delimiters are recognised / Math delimiters inside code
Covers: markdown-rendering / Math delimiters are recognised / Math without a math engine
Covers: markdown-rendering / LaTeX blocks are rendered through the LaTeX service / Successful LaTeX block
Covers: markdown-rendering / LaTeX blocks are rendered through the LaTeX service / LaTeX service error

## 4. Integration checks

- [ ] 4.1 Run the full suite (`uv run python manage.py test judge`) on Python 3.13 and 3.14, `uv run flake8`, `uv run python manage.py makemigrations --check --dry-run` (only the known pending `judge` 0154 may appear) and `uv audit --frozen`; verify all pass and `mistune` no longer appears in the audit.
- [ ] 4.2 With a throwaway script outside the repo, compare the (kind, formula) sequence sent to a recording stand-in for the math service by the 0.8 code (built from `master` in a separate environment) and by the new code for every document of `~/Documentos/online-judge-corpus/corpus.jsonl`; verify the sequences are identical for all documents, or that each difference is explained and accepted by the maintainer.
- [ ] 4.3 With the same corpus, render every document with every style and verify: no exception, each render under 1 s, no executable markup in safe-mode output; produce a per-category report of how many documents change visibly (raw HTML blocks, `_x_`, lists and quotes, setext headings, tables, links or images turned into `#harmful-link` by the scheme allowlist) for the maintainer. Nothing from the corpus is committed.
- [ ] 4.4 Render a page that uses the filter through its consumers (`judge.jinja2.test_reference`, the feed and the OpenGraph helper) and verify their tests pass with the new HTML; list every Scenario with the test that covers it and every test added by this change that covers no Scenario (grep `Scenario:` in `test_markdown.py`), as the repository's verify step requires.

## Workflow follow-up

- Archive the change (`/opsx:archive`) after the tests, flake8 and the Scenario-to-test check pass, on the same branch as the code.
- Deploy with the normal `./scripts/update`; the maintainer runs it. HTML in fragment caches is replaced as it expires.
