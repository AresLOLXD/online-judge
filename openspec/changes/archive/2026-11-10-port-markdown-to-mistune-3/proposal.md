# Proposal

## Why

Every piece of user-written text on the site (comments, problem statements, blog posts, profile and
organization descriptions, tickets) is rendered by `mistune` 0.8.4, which is pinned as `mistune<2` and
unmaintained. Two concrete problems follow from it:

- The renderer has a measured catastrophic-backtracking ReDoS: a 8192-character comment (the form limit)
  made of repeated `<http://` takes about 22 s to render, growing cubically, and any logged-in user can post
  it. Other shapes (`[a](` x4000, `<!--` x4000) are quadratic. The autolink hole fixed by commit
  `373ae519` came from the same code.
- `uv audit` lists 16 OSV advisories against 0.8.4, all fixed in `mistune` 3.2.1 or 3.3.0 (the ones that
  concern 3.x-only features do not apply here, but the quadratic-parsing and URL-protocol ones do). The
  maintainer also wants the dependency kept up to date.

`mistune` 3.4.0 is linear on the same inputs (at most 0.12 s at 4000 repetitions). Maintainer decision
(2026-11-04): visible rendering differences are acceptable; the site must keep working and the dependency
must move to the maintained major version.

## What Changes

- Replace `mistune<2` with `mistune>=3.4,<4` in `pyproject.toml` and regenerate `uv.lock`. The floor is 3.4
  because the code is written and measured against 3.4.0 (the advisories are fixed from 3.3.0).
- Rewrite the rendering code on the mistune 3 plugin API: `judge/jinja2/markdown/__init__.py`
  (renderer, inline rules, options) and `judge/jinja2/markdown/math.py` (math), and adapt the one
  `mistune` import in `judge/utils/mathoid.py` (`escape` becomes `safe_entity`). The public entry point, the Jinja filter
  `markdown(value, style, math_engine, lazy_load, strip_paragraphs)`, and the style settings
  (`MARKDOWN_STYLES`) keep their signature and meaning.
- Keep these site features: math (`~x~` and `\(x\)` inline, `$$x$$` and `\[x\]` display, rendered through
  Mathoid, falling back to the escaped `\(..\)` / `\[..\]` text; `\(x\)` and `\[x\]` are newly working, not kept: 0.8's
  escape rule ate the backslash), `<latex>` blocks through Texoid, tables
  wrapped in `div.h-scrollable-table`, `rel="nofollow"` except for `NOFOLLOW_EXCLUDED` hosts, heading level
  +2, syntax highlighting of fenced code with a language, safe-mode escaping per style, bleach per style,
  camo, lazy loading of images, `strip_paragraphs`, bare-URL autolinks and `~~strikethrough~~`.
- Add ONE compatibility patch: ATX headings written without a space (`#Title`) are still headings (the
  heading rule of the block parser is relaxed, so fenced code and raw HTML blocks are untouched). 32 of the
  182 real documents in the maintainer's corpus use this form; under CommonMark they would otherwise show a
  literal `#`.
- Link and image URLs are filtered by an allowlist in every style: relative URLs and `http`, `https`,
  `mailto`, `tel`, `ftp(s)` and `irc(s)` are kept, `data:` images of type gif/png/jpeg/webp are kept, and
  anything else (for example `javascript:`, `steam://`, `sms:`, `file:`) becomes the inert `#harmful-link`.
  Today only `javascript:` and `vbscript:` are blocked. Staff styles already restrict protocols to `http`,
  `https` and `mailto` through bleach's defaults, so the change is noticed in the user styles (comments,
  descriptions, tickets) and in the unbleached admin-edited styles.
- Accept CommonMark behaviour everywhere else, including: `_x_` is rendered as emphasis, Markdown inside
  HTML blocks is no longer parsed, list/blockquote edge cases follow CommonMark.
- Add tests: pathological-input timing, an XSS payload battery, and one test group per kept feature.
  **BREAKING (visible, accepted):** the HTML of some existing user content changes slightly after deploy.

## Capabilities

### New Capabilities
- `markdown-rendering`: how user-written Markdown is turned into HTML: which syntax is supported, the site
  extensions (math, `<latex>`, tables, links, headings, code), the per-style safety modes, and the
  guarantees on malicious and pathological input.

### Modified Capabilities

(none: there are no specs under `openspec/specs/` yet)

## Impact

- Code: `judge/jinja2/markdown/__init__.py`, `judge/jinja2/markdown/math.py`,
  `judge/jinja2/markdown/test_markdown.py` (tests), `judge/utils/mathoid.py` (one import). The Jinja filter
  `markdown` is used by about 25 templates plus `judge/feed.py` and `judge/utils/opengraph.py`; their call
  signatures do not change. The `reference` filter and `judge/utils/camo.py` consume the rendered HTML and
  are checked, not changed.
- Dependencies: `mistune` 0.8.4 -> 3.x; `uv.lock` regenerated (the Docker image builds from it).
- Deploy impact: no database migration, no settings change, no static assets. A normal
  `./scripts/update` rebuilds the image with the new lock; no change in `dmoj-docker` is expected. HTML kept
  in `{% cache %}` fragments (problems, blog posts and user "about" 24 h, contests and organizations 1 h)
  is replaced as the entries expire. Rollback is reverting the commit and redeploying; no data is changed.
- Out of scope: an input length cap for the preview endpoints and the unbounded `about` and ticket fields (the 1 s
  bound is for 8192 characters; follow-up), footnotes (no use found), a compatibility layer for other 0.8 quirks, a URL-scheme
  allowlist of our own (the protocol blocking built into mistune 3 is used and checked), new Markdown
  plugins nobody asked for, per-document approval of rendering differences, the bleach allowlists, the
  Mathoid/Texoid/camo services themselves, the `reference` filter, the editor (`martor`) and the other
  dependency work (Python default, git-sourced forks).
