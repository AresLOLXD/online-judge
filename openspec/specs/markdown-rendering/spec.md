# markdown-rendering Specification

## Purpose
Defines how user-written Markdown is turned into HTML by the `markdown` template filter: the supported syntax
and site extensions, the safety guarantees of each style, and the bounds on malicious or malformed input.

All scenarios are tested in `judge/jinja2/markdown/test_markdown.py` (Django `SimpleTestCase`, no database), in
the class named by each scenario's **Test** line. A test that covers a scenario carries
`Scenario: <scenario name>` in its docstring. "Safe-mode styles" means the styles that escape raw HTML and are
not post-processed by bleach: `default`, `comment`, `self-description`, `organization-about` and `ticket`.
"Staff styles" are the ones configured with bleach, for example `problem`.

## Requirements

### Requirement: Rendering time is bounded
The filter SHALL render any input of up to the comment length limit (8192 characters) in at most 1 second, for
every style, including inputs built to trigger worst-case parsing. Inputs longer than the limit (previews, profile,
organization and ticket texts) are not bounded by this requirement.

#### Scenario: Repeated unterminated autolink openers
- **WHEN** `<http://` repeated up to 8192 characters is rendered with the `comment` style
- **THEN** rendering finishes within 1 second
- **Test**: `TestPathologicalInput`

#### Scenario: Repeated quadratic-prone constructs
- **WHEN** each of `[a](` x2048, `<!--` x2048, `**` x4096, `~~` x4096, `*a ` x2730 and `_a ` x2730 is rendered with the `comment` style
- **THEN** every rendering finishes within 1 second
- **Test**: `TestPathologicalInput`

### Requirement: Malformed or deeply nested input never raises
The filter SHALL return HTML, and SHALL NOT raise, for unterminated, mismatched or deeply nested Markdown and for
control characters.

#### Scenario: Deep nesting and unterminated constructs
- **WHEN** 1000 nested `>` quote markers, 1000 nested list levels, 5000 `[`, an unterminated fenced block, an unclosed HTML tag and a NUL character are each rendered with `comment` and `problem`
- **THEN** each call returns a string without raising and within 1 second
- **Test**: `TestMalformedInput`

### Requirement: Safe-mode styles never produce executable markup
For safe-mode styles the output SHALL contain no element with an event-handler attribute, no `script`, `iframe`
or `object` element, and no link or image URL whose scheme is `javascript:` or `vbscript:`, however the input
spells or encodes it.

#### Scenario: Raw HTML is shown as text
- **WHEN** `<script>alert(1)</script>` and `<img src=x onerror=alert(1)>` are rendered with the `comment` style
- **THEN** the output contains the text escaped (`&lt;script&gt;`) and no `script` or `img` element
- **Test**: `TestSafeModeStyles`

#### Scenario: Dangerous schemes in links, images and autolinks
- **WHEN** `[x](javascript:alert(1))`, the same with mixed case, leading spaces, a tab or newline inside the scheme, a control character before it, `vbscript:`, an entity-encoded scheme, `![x](javascript:alert(1))` and `<javascript:alert(1)>` are rendered with every safe-mode style
- **THEN** no `href` or `src` of the output, after removing whitespace and control characters, decoding entities and lowercasing, starts with `javascript:` or `vbscript:`
- **Test**: `TestSafeModeStyles`

#### Scenario: Quotes cannot break out of a link attribute
- **WHEN** an autolink or link target contains `"`, `'`, `<`, `>` or `&` followed by `onmouseover=` and the output is parsed as HTML
- **THEN** the anchor has only the expected attributes and the URL is a single escaped `href` value
- **Test**: `TestAutolinkInjection`

#### Scenario: Payload battery
- **WHEN** each payload of a fixed battery (at least 40, with several variants of each category: scheme tricks, attribute breaking, raw HTML, entity tricks, nested constructs, math and code delimiters around markup) is rendered with every safe-mode style and parsed
- **THEN** no parsed element carries an `on*` attribute, and no `href` or `src` has a script scheme as defined above
- **Test**: `TestSafeModeStyles`

### Requirement: Staff styles are sanitized by their allowlist
Styles configured with bleach SHALL pass raw HTML through the style's allowlist, which removes disallowed tags
and attributes and keeps allowed tags, CSS properties and MathML.

#### Scenario: Staff style removes scripts and keeps allowed markup
- **WHEN** `<script>void(0)</script>`, `<img style="display: block; margin: 0 auto">`, `<style>a { color: red; }</style>` and a MathML fragment are rendered with the `problem` style
- **THEN** the script is escaped as text, the allowed image style and the style element are kept, and the MathML is kept unchanged
- **Test**: `TestMarkdown`

#### Scenario: Unbleached staff style keeps raw HTML
- **WHEN** `<script>void(0)</script>` is rendered with the `problem-full` style
- **THEN** the script element is kept
- **Test**: `TestMarkdown`

### Requirement: Math delimiters are recognised
With a math engine, `~x~` and `\(x\)` SHALL be rendered as inline math and `$$x$$` and `\[x\]` as display math,
using the math service. `~~x~~` is strikethrough, not math, and math delimiters are ignored inside code.

#### Scenario: All four delimiters
- **WHEN** `~a+b~`, `\(a+b\)`, `$$a+b$$` and `\[a+b\]` are rendered with a math engine and a stubbed math service
- **THEN** the stub receives `a+b` four times, twice as inline math and twice as display math, and the output contains its results
- **Test**: `TestMath`

#### Scenario: Math keeps its own characters
- **WHEN** `\(a_b\)`, `$$x_1*y_2$$`, `~a_b~` and `\[a\\b\]` are rendered with a math engine and a stubbed math service
- **THEN** the stub receives `a_b`, `x_1*y_2`, `a_b` and `a\\b` unchanged, with no emphasis or escape processing applied to them
- **Test**: `TestMath`

#### Scenario: Tilde math next to strikethrough
- **WHEN** `~a~ and ~~b~~` is rendered with a math engine
- **THEN** `a` is sent to the math service as inline math and `b` is rendered as struck-through text
- **Test**: `TestMath`

#### Scenario: Math delimiters inside code
- **WHEN** `` `~a~` `` and a fenced block containing `$$a$$` are rendered with a math engine
- **THEN** the math service is not called and the text appears escaped inside code
- **Test**: `TestMath`

#### Scenario: Math without a math engine
- **WHEN** `~a<b~` and `$$a<b$$` are rendered with no math engine
- **THEN** the output contains the escaped text `\(a&lt;b\)` and `\[a&lt;b\]`
- **Test**: `TestMath`

### Requirement: LaTeX blocks are rendered through the LaTeX service
In styles that enable it, a `<latex>` block SHALL be rendered as an image from the LaTeX service, and as a
preformatted error message when the service reports an error or returns nothing.

#### Scenario: Successful LaTeX block
- **WHEN** a `<latex>x^2</latex>` block is rendered with a style that enables LaTeX and a stub returning an image
- **THEN** the output contains one `img` with the stub's sizes, in a `div` (or a `span` for the `inline` attribute)
- **Test**: `TestLatexBlocks`

#### Scenario: LaTeX service error
- **WHEN** the stub reports an error or no result
- **THEN** the output is a `pre` element with the escaped error message or source
- **Test**: `TestLatexBlocks`

### Requirement: Tables are scrollable
Every Markdown table SHALL be rendered inside a `div` of class `h-scrollable-table`, as a `table` of class `table`
with `thead` and `tbody`.

#### Scenario: Table wrapper
- **WHEN** a pipe table with a header row and two body rows is rendered with the `comment` style
- **THEN** the output is one `div.h-scrollable-table` containing `table.table` with one `thead` row and two `tbody` rows
- **Test**: `TestTables`

### Requirement: External links are not followed by search engines
Links and autolinks whose host is not in the excluded-hosts setting SHALL carry `rel="nofollow"` when the style
enables it; links without a host and links to excluded hosts SHALL NOT.

#### Scenario: Nofollow by host
- **WHEN** a link to `https://example.com/`, a link to an excluded host, a relative link `/problem/a`, a bare URL and an email autolink are rendered with `comment`
- **THEN** the first link and the bare URL have `rel="nofollow"`, and the excluded-host link, the relative link and the email anchor (no host) do not
- **Test**: `TestLinks`

#### Scenario: Style without nofollow
- **WHEN** a link to `https://example.com/` is rendered with a style that sets nofollow to false
- **THEN** the anchor has no `rel` attribute
- **Test**: `TestLinks`

### Requirement: Link and image URLs use a safe-scheme allowlist
In every style, a link or image URL SHALL be kept only if it is relative or uses `http`, `https`, `mailto`, `tel`,
`ftp`, `ftps`, `irc` or `ircs`, or is a `data:` URL of image type gif, png, jpeg or webp; any other URL SHALL be
replaced by the inert target `#harmful-link`.

#### Scenario: Allowed and replaced schemes
- **WHEN** links to `https://example.com/`, `mailto:a@b.c`, `tel:+123`, `ftp://example.com/` and `/relative`, an image with a `data:image/png;base64,AA` source, and links to `steam://run/1`, `sms:+1`, `file:///etc/passwd` and an image with a `data:image/svg+xml,...` source are rendered with the `comment` style
- **THEN** the first group keeps its URLs and the second group has `#harmful-link` as its target
- **Test**: `TestLinks`

### Requirement: Headings are shifted two levels
A heading of level N in the source SHALL be rendered as the heading of level N+2, with levels above 6 rendered as
level 6.

#### Scenario: Heading levels
- **WHEN** `# a`, `### b` and `###### c` are rendered
- **THEN** the output contains `h3` for a, `h5` for b and `h6` for c
- **Test**: `TestHeadings`

### Requirement: Headings without a space after the hashes still work
A line that starts with 1 to 6 `#` characters immediately followed by non-space text SHALL be treated as a heading,
except inside fenced code and raw HTML blocks.

#### Scenario: Heading without a space
- **WHEN** `#Title` and `##Sub` are rendered
- **THEN** the output contains `h3` with `Title` and `h4` with `Sub`, with no literal `#`
- **Test**: `TestHeadingWithoutSpace`

#### Scenario: Fenced code is untouched
- **WHEN** a fenced block containing `#include <stdio.h>` is rendered
- **THEN** the code appears unchanged inside `pre` and no heading is produced
- **Test**: `TestHeadingWithoutSpace`

#### Scenario: Raw HTML blocks are untouched
- **WHEN** `<style>` and `<pre>` blocks whose lines start with `#a { color: red }` and `#include <x>` are rendered with the `problem-full` style
- **THEN** those lines appear unchanged inside their blocks and no heading is produced
- **Test**: `TestHeadingWithoutSpace`

### Requirement: Fenced code is highlighted when a language is given
A fenced block with a language SHALL be highlighted for that language; a block without one SHALL be shown as
escaped preformatted text.

#### Scenario: Code blocks
- **WHEN** a fenced block tagged `python` and an untagged fenced block containing `<b>&</b>` are rendered
- **THEN** the first is highlighted markup and the second is `<pre><code>` with the content escaped
- **Test**: `TestCode`

### Requirement: Output post-processing is preserved
When requested, images SHALL be lazy-loaded, image URLs SHALL be proxied by the image proxy (for styles that enable
it, when configured), and paragraph tags SHALL be removed.

#### Scenario: Lazy loading
- **WHEN** `<img src="test.png">` is rendered with an unbleached style and lazy loading on
- **THEN** the output has the noscript image and the lazy image with `data-src="test.png"` and class `unveil`
- **Test**: `TestMarkdown`

#### Scenario: Image proxy
- **WHEN** an image is rendered with a style that enables the image proxy and a stubbed proxy client is configured
- **THEN** the image URL in the output is the one the proxy produces, and with no proxy client configured it is unchanged
- **Test**: `TestPostProcessing`

#### Scenario: Paragraph stripping
- **WHEN** `proudly powered by **DMOJ**` is rendered with `strip_paragraphs` on
- **THEN** the output contains the emphasized text and no `p` element
- **Test**: `TestPostProcessing`

### Requirement: Bare URLs and strikethrough are supported
A bare `http://` or `https://` URL in text SHALL become a link, and text between double tildes SHALL be rendered
as struck-through text.

#### Scenario: Bare URL and strikethrough
- **WHEN** `see https://example.com/a and ~~gone~~` is rendered with `comment`
- **THEN** the URL is one anchor with the URL as href and text, and `gone` is inside a `del` element
- **Test**: `TestInlineExtras`
