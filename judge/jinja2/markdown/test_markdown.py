import re
import time
from html import unescape
from html.entities import name2codepoint
from unittest import mock

from django.test import SimpleTestCase, override_settings
from lxml import html

from . import fragment_tree_to_str, fragments_to_tree, get_cleaner, markdown

MATHML_N = """\
<math xmlns="http://www.w3.org/1998/Math/MathML">
<semantics>
<mi>N</mi>
<annotation encoding="application/x-tex">N</annotation>
</semantics>
</math>
"""

MATHML_CHUDNOVSKY = r"""
<math xmlns="http://www.w3.org/1998/Math/MathML"
      alttext="{\displaystyle {\frac {1}{\pi }}=12\sum _{k=0}^{\infty }{\frac {(-1)^{k}(6k)!(545140134k+13591409)}{(3k)!(k!)^{3}\left(640320\right)^{3k+3/2}}}}">
  <semantics>
    <mrow class="MJX-TeXAtom-ORD">
      <mstyle displaystyle="true" scriptlevel="0">
        <mrow class="MJX-TeXAtom-ORD">
          <mfrac>
            <mn>1</mn>
            <mi>π<!-- π --></mi>
          </mfrac>
        </mrow>
        <mo>=</mo>
        <mn>12</mn>
        <munderover>
          <mo>∑<!-- ∑ --></mo>
          <mrow class="MJX-TeXAtom-ORD">
            <mi>k</mi>
            <mo>=</mo>
            <mn>0</mn>
          </mrow>
          <mrow class="MJX-TeXAtom-ORD">
            <mi mathvariant="normal">∞<!-- ∞ --></mi>
          </mrow>
        </munderover>
        <mrow class="MJX-TeXAtom-ORD">
          <mfrac>
            <mrow>
              <mo stretchy="false">(</mo>
              <mo>−<!-- − --></mo>
              <mn>1</mn>
              <msup>
                <mo stretchy="false">)</mo>
                <mrow class="MJX-TeXAtom-ORD">
                  <mi>k</mi>
                </mrow>
              </msup>
              <mo stretchy="false">(</mo>
              <mn>6</mn>
              <mi>k</mi>
              <mo stretchy="false">)</mo>
              <mo>!</mo>
              <mo stretchy="false">(</mo>
              <mn>545140134</mn>
              <mi>k</mi>
              <mo>+</mo>
              <mn>13591409</mn>
              <mo stretchy="false">)</mo>
            </mrow>
            <mrow>
              <mo stretchy="false">(</mo>
              <mn>3</mn>
              <mi>k</mi>
              <mo stretchy="false">)</mo>
              <mo>!</mo>
              <mo stretchy="false">(</mo>
              <mi>k</mi>
              <mo>!</mo>
              <msup>
                <mo stretchy="false">)</mo>
                <mrow class="MJX-TeXAtom-ORD">
                  <mn>3</mn>
                </mrow>
              </msup>
              <msup>
                <mrow>
                  <mo>(</mo>
                  <mn>640320</mn>
                  <mo>)</mo>
                </mrow>
                <mrow class="MJX-TeXAtom-ORD">
                  <mn>3</mn>
                  <mi>k</mi>
                  <mo>+</mo>
                  <mn>3</mn>
                  <mrow class="MJX-TeXAtom-ORD">
                    <mo>/</mo>
                  </mrow>
                  <mn>2</mn>
                </mrow>
              </msup>
            </mrow>
          </mfrac>
        </mrow>
      </mstyle>
    </mrow>
    <annotation encoding="application/x-tex">{\displaystyle {\frac {1}{\pi }}=12\sum _{k=0}^{\infty }{\frac {(-1)^{k}(6k)!(545140134k+13591409)}{(3k)!(k!)^{3}\left(640320\right)^{3k+3/2}}}}</annotation>
  </semantics>
</math>
"""  # noqa: E501


class TestMarkdown(SimpleTestCase):
    BLEACHED_STYLE = 'problem'
    UNBLEACHED_STYLE = 'problem-full'

    def test_bleach(self):
        """Scenario: Staff style removes scripts and keeps allowed markup"""
        self.assertHTMLEqual(markdown('<script>void(0)</script>', self.BLEACHED_STYLE),
                             '&lt;script&gt;void(0)&lt;/script&gt;')
        self.assertHTMLEqual(markdown('<img style="display: block; margin: 0 auto">', self.BLEACHED_STYLE),
                             '<img style="display: block; margin: 0 auto;">')
        self.assertHTMLEqual(markdown('<style>a { color: red; }</style>', self.BLEACHED_STYLE),
                             '<style>a { color: red; }</style>')

    def test_bleach_mathml(self):
        """Scenario: Staff style removes scripts and keeps allowed markup"""
        self.assertHTMLEqual(markdown(MATHML_N, self.BLEACHED_STYLE), MATHML_N)
        cleaner = get_cleaner(self.BLEACHED_STYLE, None)
        self.assertHTMLEqual(cleaner.clean(MATHML_CHUDNOVSKY), MATHML_CHUDNOVSKY)

    def test_no_bleach(self):
        """Scenario: Unbleached staff style keeps raw HTML"""
        self.assertHTMLEqual(markdown('<script>void(0)</script>', self.UNBLEACHED_STYLE),
                             '<script>void(0)</script>')

    def test_post_process(self):
        """Scenario: Lazy loading"""
        self.assertHTMLEqual(markdown('<img src="test.png">', self.UNBLEACHED_STYLE, lazy_load=True),
                             '<noscript><img src="test.png"></noscript>'
                             '<img src="/static/blank.gif" data-src="test.png" class="unveil">')


class TestFragmentUtils(SimpleTestCase):
    def test_simple(self):
        tree = fragments_to_tree('<p>a</p><p>b</p>')
        self.assertIsInstance(tree, html.HtmlElement)
        self.assertEqual(len(tree.getchildren()), 2)

        self.assertIsInstance(tree[0], html.HtmlElement)
        self.assertEqual(tree[0].tag, 'p')
        self.assertEqual(tree[0].text, 'a')

        self.assertIsInstance(tree[1], html.HtmlElement)
        self.assertEqual(tree[1].tag, 'p')
        self.assertEqual(tree[1].text, 'b')

        self.assertHTMLEqual(fragment_tree_to_str(tree), '<p>a</p><p>b</p>')

    def test_text_prefix(self):
        tree = fragments_to_tree('z<p>a</p><p>b</p>')
        self.assertIsInstance(tree, html.HtmlElement)
        self.assertEqual(len(tree.getchildren()), 2)
        self.assertEqual(tree.text, 'z')

        self.assertHTMLEqual(fragment_tree_to_str(tree), 'z<p>a</p><p>b</p>')


class TestAutolinkInjection(SimpleTestCase):
    USER_STYLES = ('comment', 'default', 'self-description', 'ticket', 'organization-about')

    def render(self, source, style):
        return html.fragment_fromstring(str(markdown(source, style)), create_parent='div')

    def test_no_event_handler_attributes(self):
        """Scenario: Quotes cannot break out of a link attribute"""
        sources = (
            '<http://x.com/"onmouseover="alert(1)>',
            'http://x.com/"onmouseover="alert(1)',
            '<a"onmouseover="alert(1)@b.c>',
            '<x:"onmouseover="alert(1)>',
            '<ftp://h/"onmouseover="alert(1)>',
            '<mailto:a"onmouseover="alert(1)@b.c>',
        )
        for style in self.USER_STYLES:
            for source in sources:
                with self.subTest(style=style, source=source):
                    tree = self.render(source, style)
                    for element in tree.iter():
                        for name in element.attrib:
                            self.assertFalse(name.lower().startswith('on'), (element.tag, name))

    def test_href_is_the_escaped_url(self):
        """Scenario: Quotes cannot break out of a link attribute"""
        for source in ('<http://x.com/"y>', 'http://x.com/"y'):
            with self.subTest(source=source):
                links = self.render(source, 'comment').findall('.//a')
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0].get('href'), 'http://x.com/%22y')
                self.assertEqual(links[0].text, 'http://x.com/"y')

    def test_single_quote_in_url(self):
        """Scenario: Quotes cannot break out of a link attribute"""
        tree = self.render("<http://x.com/'onmouseover='y>", 'comment')
        for element in tree.iter():
            for name in element.attrib:
                self.assertFalse(name.lower().startswith('on'), (element.tag, name))
        links = tree.findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get('href'), 'http://x.com/%27onmouseover=%27y')
        self.assertEqual(links[0].text, "http://x.com/'onmouseover='y")

    def test_normal_autolinks_unchanged(self):
        links = self.render('<https://example.com/page>', 'comment').findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get('href'), 'https://example.com/page')
        self.assertEqual(links[0].text, 'https://example.com/page')

        links = self.render('<a@b.c>', 'comment').findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get('href'), 'mailto:a@b.c')
        self.assertEqual(links[0].text, 'a@b.c')

        source = 'see https://example.com/x?a=1&b=2 now'
        links = self.render(source, 'comment').findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get('href'), 'https://example.com/x?a=1&b=2')
        raw = str(markdown(source, 'comment'))
        self.assertIn('&amp;b=2', raw)
        self.assertNotIn('&amp;amp;', raw)

    def test_entity_in_scheme_is_not_a_link(self):
        """Not tied to a Scenario: a `&Tab;` entity inside a scheme is no link, the text stays visible."""
        tree = self.render('<java&Tab;script:alert(1)>', 'comment')
        self.assertEqual(tree.findall('.//a'), [])
        self.assertIn('<java\tscript:alert(1)>', tree.text_content())

    def test_dangerous_schemes_are_dropped(self):
        sources = (
            '<javascript:alert(1)>',
            '<JaVaScRiPt:alert(1)>',
            '<vbscript:msgbox(1)>',
            '<java\tscript:alert(1)>',
            '<javascript:alert(1)@b.c>',
            '<&#106;avascript:alert(1)>',
            '<java&Tab;script:alert(1)>',
        )
        for style in self.USER_STYLES:
            for source in sources:
                with self.subTest(style=style, source=source):
                    for link in self.render(source, style).iter('a'):
                        href = re.sub(r'[^a-z0-9/:]+', '', (link.get('href') or '').lower())
                        self.assertFalse(href.startswith(('javascript:', 'vbscript:')), href)

        links = self.render('<javascript:alert(1)>', 'comment').findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].text, 'javascript:alert(1)')

        # An entity-encoded scheme is not a link: it is decoded and shown as escaped text.
        self.assertEqual(self.render('<&#106;avascript:alert(1)>', 'comment').findall('.//a'), [])
        self.assertIn('&lt;javascript:alert(1)&gt;', str(markdown('<&#106;avascript:alert(1)>', 'comment')))


class TestInputEdgeCases(SimpleTestCase):
    def test_empty_input(self):
        self.assertEqual(markdown('', 'comment'), '')

    def test_entities_and_unicode(self):
        result = str(markdown('a &amp; b <3 \U0001F600', 'comment'))
        self.assertIn('a &amp; b', result)
        self.assertIn('&lt;3', result)
        self.assertEqual(result.count('\U0001F600'), 1)
        self.assertNotIn('&amp;amp;', result)

    def test_crlf_line_endings(self):
        result = str(markdown('a\r\n\r\nb', 'comment'))
        self.assertEqual(len(fragments_to_tree(result).findall('p')), 2)
        self.assertNotIn('\r', result)

    def test_long_single_line(self):
        start = time.perf_counter()
        markdown('a' * 8192, 'comment')
        self.assertLess(time.perf_counter() - start, 1.0)


SAFE_STYLES = ('default', 'comment', 'self-description', 'organization-about', 'ticket')


def parse_fragment(raw):
    """Parse as a browser does: libxml2 knows only the HTML 4 entity names, so decode the HTML5-only ones first."""
    def decode(match):
        decoded = unescape(match.group(0))
        # Entities that stand for markup characters (&LT;, &QUOT;...) are text in a browser; leave them to lxml.
        return match.group(0) if match.group(1) in name2codepoint or decoded in '<>&"\'' else decoded

    return html.fragment_fromstring(re.sub(r'&([A-Za-z][A-Za-z0-9]*);', decode, raw), create_parent='div')


def render_tree(source, style, **kwargs):
    return parse_fragment(str(markdown(source, style, **kwargs)))


EXECUTABLE_TAGS = frozenset(
    ('script', 'iframe', 'object', 'form', 'embed', 'base', 'meta', 'link', 'style', 'applet', 'frame'),
)
URL_ATTRIBUTES = frozenset(('href', 'src', 'action', 'formaction', 'xlink:href', 'data', 'poster', 'ping'))


def executable_markup(tree):
    """
    Return what a browser could execute or load in the tree; independent of the renderer, so [] means safe.

    A denylist for the safe-mode styles only (raw HTML is escaped there): staff styles legitimately keep
    `style` elements and the like, so never use this on them.
    """
    found = []
    for element in tree.iter():
        if not isinstance(element.tag, str):  # comments and processing instructions
            continue
        if element.tag.lower() in EXECUTABLE_TAGS:
            found.append(f'<{element.tag}>')
        for name, value in element.attrib.items():
            name = name.lower()
            # The attribute value is decoded once, as a browser does it.
            scheme_text = re.sub(r'[\x00-\x20]', '', value).lower()
            if name.startswith('on'):
                found.append(f'{element.tag} {name}={value!r}')
            elif name in URL_ATTRIBUTES and scheme_text.startswith(('javascript:', 'vbscript:')):
                found.append(f'{element.tag} {name}={value!r}')
    return found


def assert_fast(source, style='comment', **kwargs):
    start = time.perf_counter()
    result = markdown(source, style, **kwargs)
    elapsed = time.perf_counter() - start
    if elapsed >= 1.0:
        raise AssertionError(f'{style}: {source[:40]!r} took {elapsed:.2f} s')
    return result


PAYLOADS = (
    # The sources of TestAutolinkInjection.
    '<http://x.com/"onmouseover="alert(1)>',
    'http://x.com/"onmouseover="alert(1)',
    '<a"onmouseover="alert(1)@b.c>',
    '<x:"onmouseover="alert(1)>',
    '<ftp://h/"onmouseover="alert(1)>',
    '<mailto:a"onmouseover="alert(1)@b.c>',
    '<http://x.com/"y>',
    'http://x.com/"y',
    "<http://x.com/'onmouseover='y>",
    '<https://example.com/page>',
    '<a@b.c>',
    'see https://example.com/x?a=1&b=2 now',
    '<javascript:alert(1)>',
    '<JaVaScRiPt:alert(1)>',
    '<vbscript:msgbox(1)>',
    '<java\tscript:alert(1)>',
    '<javascript:alert(1)@b.c>',
    '<&#106;avascript:alert(1)>',
    '<java&Tab;script:alert(1)>',
    # Scheme tricks.
    '[x](javascript:alert(1))',
    '[x](JAVASCRIPT:alert(1))',
    '[x](  javascript:alert(1))',
    '[x](java\tscript:alert(1))',
    '[x](java\nscript:alert(1))',
    '[x](\x01javascript:alert(1))',
    '[x](\x00javascript:alert(1))',
    '[x](&#x6A;avascript:alert(1))',
    '[x](&#0000106avascript:alert(1))',
    '[x](javascript&colon;alert(1))',
    '[x](javascript&#58;alert(1))',
    '[x](jav&#x09;ascript:alert(1))',
    '[x](vbscript:msgbox(1))',
    '[x](livescript:alert(1))',
    '[x](data:text/html,<script>alert(1)</script>)',
    '[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)',
    '[x](%6Aavascript:alert(1))',
    '[x](javascript%3Aalert(1))',
    '[x](\\javascript:alert(1))',
    '![x](javascript:alert(1))',
    '![x](vbscript:msgbox(1))',
    '![x](data:image/svg+xml,<svg onload=alert(1)>)',
    '<JAVASCRIPT:alert(1)>',
    # Attribute breaking in link targets, titles and references.
    '[x](http://a.b/"onmouseover="alert(1))',
    '[x](<http://a.b/"onmouseover="alert(1)>)',
    '[x](http://a.b/ "t\\" onmouseover=\\"alert(1)")',
    '[x](http://a.b "title" onmouseover="alert(1)")',
    "[x](http://a.b 't\" onmouseover=\"alert(1)')",
    "[x](http://a.b/ 'x'onmouseover='alert(1)')",
    '[x](http://a.b/>onmouseover=alert(1))',
    '[x](http://a.b/<img src=x onerror=alert(1)>)',
    '[x][r]\n\n[r]: http://a.b/"onmouseover="alert(1)',
    '[x][r]\n\n[r]: javascript:alert(1)',
    '[x][r]\n\n[r]: http://a.b "t" onmouseover="alert(1)"',
    '![x](http://a.b/i.png"onerror="alert(1))',
    '![x"onerror="alert(1)](http://a.b/i.png)',
    "![x](http://a.b/i.png 't' onerror='alert(1)')",
    # Raw HTML.
    '<script>alert(1)</script>',
    '<ScRiPt>alert(1)</ScRiPt>',
    '<scr<script>ipt>alert(1)</scr</script>ipt>',
    '<img src=x onerror=alert(1)>',
    '<img/src=x/onerror=alert(1)>',
    '<svg onload=alert(1)>',
    '<svg><script>alert(1)</script></svg>',
    '<iframe src="javascript:alert(1)"></iframe>',
    '<object data="javascript:alert(1)"></object>',
    '<form action="javascript:alert(1)"><button>x</button></form>',
    '<a href="javascript:alert(1)">x</a>',
    '<a href=" jav&#x09;ascript:alert(1)">x</a>',
    '<body onload=alert(1)>',
    '<div onmouseover="alert(1)">x</div>',
    '<!-- --><script>alert(1)</script>',
    '<!--><img src=x onerror=alert(1)>-->',
    '<![CDATA[<script>alert(1)</script>]]>',
    '<math><mtext></p><img src=x onerror=alert(1)>',
    '<style>@import "javascript:alert(1)";</style>',
    # Entity tricks.
    '&lt;script&gt;alert(1)&lt;/script&gt;',
    '&#60;script&#62;alert(1)&#60;/script&#62;',
    '&#x3C;img src=x onerror=alert(1)&#x3E;',
    '&amp;lt;script&amp;gt;alert(1)',
    '&lt;img src=x onerror=alert(1)&gt;',
    '&#106;avascript:alert(1)',
    '<a href="&#106;avascript:alert(1)">x</a>',
    # Nested constructs: links in images in quotes in lists, tables, emphasis and headings.
    '> - [![x](javascript:alert(1))](http://a.b/"onmouseover="alert(1))',
    '- > [x](javascript:alert(1))',
    '> > ![x](http://a.b/"onerror="alert(1))',
    '[![x](http://a.b/i.png)](javascript:alert(1))',
    '1. - > <script>alert(1)</script>',
    '| a | b |\n|---|---|\n| [x](javascript:alert(1)) | <img src=x onerror=alert(1)> |',
    '**[x](javascript:alert(1))**',
    '*<img src=x onerror=alert(1)>*',
    '# <img src=x onerror=alert(1)>',
    '[<script>alert(1)</script>](http://a.b)',
    # Math and code delimiters around markup.
    '~<img onerror=x>~',
    '~a" onmouseover="alert(1)~',
    '~~<img src=x onerror=alert(1)>~~',
    '$$<script>$$',
    '$$<script>alert(1)</script>$$',
    '\\(<img src=x onerror=alert(1)>\\)',
    '\\[<script>alert(1)</script>\\]',
    '`<b onclick=x>`',
    '`~<img onerror=x>~`',
    '```\n<script>alert(1)</script>\n```',
    # Review additions: Scheme tricks (links, images, references, autolinks, bare).
    '[x](jAvAsCrIpT:alert(1))',
    '[x](&#x6a;&#x61;&#x76;&#x61;&#x73;&#x63;&#x72;&#x69;&#x70;&#x74;:alert(1))',
    '[x](&#106&#97&#118&#97&#115&#99&#114&#105&#112&#116&#58;alert(1))',
    '[x](java&Tab;script:alert(1))',
    '[x](java&NewLine;script:alert(1))',
    '[x](&Tab;javascript:alert(1))',
    '[x](&#x20;javascript:alert(1))',
    '[x](\x1fjavascript:alert(1))',
    '[x](\x0bjavascript:alert(1))',
    '[x](\x0cjavascript:alert(1))',
    '[x](java\rscript:alert(1))',
    '[x](java\x00script:alert(1))',
    '[x](javascript://%0aalert(1))',
    '[x](javascript://example.com/%0Aalert(1))',
    '[x](JaVa%0aScRiPt:alert(1))',
    '[x](vbscript&colon;msgbox(1))',
    '[x](data:text/html;charset=utf-8,<script>alert(1)</script>)',
    '[x](DATA:text/html,<script>alert(1)</script>)',
    '[x](data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+)',
    '![x](data:text/html,<script>alert(1)</script>)',
    '![x]( \tjavascript:alert(1))',
    '[x](file:///etc/passwd)',
    '[x](steam://run/1)',
    '[x]: javascript:alert(1)\n\n[x]',
    '[x][]\n\n[x]: <javascript:alert(1)>',
    '[X]: JAVASCRIPT:alert(1)\n\n[x]',
    '![x][r]\n\n[r]: javascript:alert(1)',
    '<jAvAsCrIpT:alert(1)>',
    '<javascript&colon;alert(1)>',
    '<java\nscript:alert(1)>',
    '<\x01javascript:alert(1)>',
    '<data:text/html,<script>alert(1)</script>>',
    'javascript:alert(1)',
    'www.example.com/"onmouseover="alert(1)',
    '<"onmouseover="alert(1)"@b.c>',
    '<mailto:a@b.c?subject="onmouseover="alert(1)>',
    # Review additions: Attribute breaking (targets, titles, alt text, references, fence info strings).
    '[x](http://a.b/&quot;onmouseover=&quot;alert(1))',
    '[x](http://a.b/&#34;onmouseover=&#34;alert(1))',
    '[x](http://a.b/?a=1&onmouseover=alert(1))',
    "[x](http://a.b/'onmouseover='alert(1))",
    '[x](http://a.b/`onmouseover=`alert(1))',
    '[x](<http://a.b/ onmouseover=alert(1)>)',
    '[x](http://a.b "&quot; onmouseover=&quot;alert(1)")',
    '[x](http://a.b "&#34; onmouseover=&#34;alert(1)")',
    '![<img src=x onerror=alert(1)>](http://a.b/i.png)',
    '![x&quot; onerror=&quot;alert(1)](http://a.b/i.png)',
    '![x](http://a.b/i.png "t\\" onerror=\\"alert(1)")',
    '![x](<http://a.b/i.png onerror=alert(1)>)',
    '[<img src=x onerror=alert(1)>][r]\n\n[r]: http://a.b',
    '[x"onmouseover="alert(1)][r]\n\n[r]: http://a.b',
    "[r]: http://a.b 'x\" onmouseover=\"alert(1)'\n\n[r]",
    '```"onmouseover="alert(1)\nx\n```',
    '```<img src=x onerror=alert(1)>\nx\n```',
    '```javascript"><script>alert(1)</script>\nx\n```',
    '~~~"onmouseover="alert(1)\nx\n~~~',
    # Review additions: Raw HTML.
    '<img src=x onerror=alert(1)',
    '<a href="javascript:alert(1)"',
    '<svg/onload=alert(1)>',
    '<details open ontoggle=alert(1)>',
    '<input autofocus onfocus=alert(1)>',
    '<video><source onerror=alert(1)></video>',
    '<embed src="javascript:alert(1)">',
    '<base href="javascript:alert(1)//">',
    '<meta http-equiv="refresh" content="0;url=javascript:alert(1)">',
    '<link rel="stylesheet" href="javascript:alert(1)">',
    '<form><button formaction="javascript:alert(1)">x</button></form>',
    '<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>',
    '<svg><animate attributeName="href" values="javascript:alert(1)"/><a><text>x</text></a></svg>',
    '<marquee onstart=alert(1)>x</marquee>',
    '<style>*{background:url(javascript:alert(1))}</style>',
    '<div style="width:expression(alert(1))">x</div>',
    '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
    '<textarea></textarea><img src=x onerror=alert(1)>',
    '<xmp><script>alert(1)</script></xmp>',
    '<!--[if IE]><script>alert(1)</script><![endif]-->',
    '<!-- --!><img src=x onerror=alert(1)>',
    '<?xml ?><script>alert(1)</script>',
    '</p><script>alert(1)</script>',
    '<scr\x00ipt>alert(1)</scr\x00ipt>',
    '<img src=x onerror\x00=alert(1)>',
    '<img\nsrc=x\nonerror=alert(1)>',
    '<div>\n<script>alert(1)</script>\n</div>',
    '<pre>\n<script>alert(1)</script>\n</pre>',
    '<style>\n</style><script>alert(1)</script>',
    '<img src=x onerror=&#97;lert(1)>',
    '<latex><script>alert(1)</script></latex>',
    '<latex inline="x" onerror="alert(1)">x</latex>',
    # Review additions: Entity tricks.
    '&#x3c;script&#x3e;alert(1)&#x3c;/script&#x3e;',
    '&#0000060;script&#0000062;alert(1)',
    '&#60script&#62alert(1)',
    '&#x26;lt;script&#x26;gt;alert(1)',
    '&amp;#60;script&amp;#62;alert(1)',
    '<a href=&quot;javascript:alert(1)&quot;>x</a>',
    '&bogus;<script>alert(1)</script>',
    '&#xD800;<img src=x onerror=alert(1)>',
    '&quot;onmouseover=&quot;alert(1)',
    '[x](&#x6A&#x61vascript:alert(1))',
    '&#106;&#97;vascript&colon;alert(1)',
    # Review additions: Nested constructs.
    '- [x](javascript:alert(1))',
    '1. > ![x](javascript:alert(1))',
    '> [![x"onerror="alert(1)](http://a.b/i.png)](http://a.b/"onmouseover="alert(1))',
    '[[x](javascript:alert(1))](http://a.b)',
    '![![x](javascript:alert(1))](http://a.b/i.png)',
    '[![x](javascript:alert(1))](javascript:alert(1))',
    '~~[x](javascript:alert(1))~~',
    '# [x](javascript:alert(1))',
    '#<img src=x onerror=alert(1)>',
    '##"onmouseover="alert(1)',
    '| [x](javascript:alert(1)) |\n|---|\n| y |',
    '<http://a.b/[x](javascript:alert(1))>',
    '[x](http://a.b/[y](javascript:alert(1)))',
    '> - > - ![x](http://a.b/"onerror="alert(1))',
    '- ```\n  <script>alert(1)</script>\n  ```',
    '    <script>alert(1)</script>',
    '<img src=x onerror=alert(1)>\n===',
    '***<img src=x onerror=alert(1)>***',
    'a  \n<script>alert(1)</script>',
    '\\<script>alert(1)</script>',
    '\\[x](javascript:alert(1))',
    '[x](http://a.b/\\)onmouseover=alert(1))',
    'https://a.b/~~"onmouseover="alert(1)~~',
    'https://a.b/**"onmouseover="alert(1)**',
    # Review additions: Math and code delimiters around markup.
    '~<script>alert(1)</script>~',
    '~a<img src=x onerror=alert(1)>~',
    '$$<img src=x onerror=alert(1)>$$',
    '$$\n<script>alert(1)</script>\n$$',
    '$$a" onmouseover="alert(1)$$',
    '\\(a" onmouseover="alert(1)\\)',
    '\\(<script>alert(1)</script>',
    '~<img src=x onerror=alert(1)>',
    '$$<img src=x onerror=alert(1)>',
    '\\[<img src=x onerror=alert(1)>',
    '~[x](javascript:alert(1))~',
    '$$[x](javascript:alert(1))$$',
    '\\([x](javascript:alert(1))\\)',
    '~a [b~](javascript:alert(1))',
    '[x~](javascript:alert(1))~',
    '`$$<script>$$`',
    '``<img src=x onerror=alert(1)>``',
    '~~~\n<script>alert(1)</script>\n~~~',
    '`<img src=x onerror=alert(1)>',
)


class TestExecutableMarkupOracle(SimpleTestCase):
    """Positive control of executable_markup; it maps to no Scenario by design (it tests the test helper)."""

    def test_bad_fragments_are_flagged(self):
        for fragment in (
            '<script>x</script>',
            '<img onerror=x>',
            '<a href=" JaVa\tscript:x">x</a>',
            '<a href="&#106;avascript:x">x</a>',
            '<a href="javascript&colon;x">x</a>',
            '<img src="vbscript:x">',
            '<form action="javascript:x"></form>',
            '<base href="x">',
        ):
            with self.subTest(fragment=fragment):
                tree = parse_fragment(fragment)
                self.assertNotEqual(executable_markup(tree), [])

    def test_harmless_fragment_is_not_flagged(self):
        for fragment in ('<a href="https://a.b">x</a>', '<a href="javascript&amp;colon;x">x</a>'):
            with self.subTest(fragment=fragment):
                self.assertEqual(executable_markup(parse_fragment(fragment)), [])


class TestPathologicalInput(SimpleTestCase):
    def test_repeated_unterminated_autolink_openers(self):
        """Scenario: Repeated unterminated autolink openers"""
        assert_fast('<http://' * 1024)

    def test_repeated_quadratic_prone_constructs(self):
        """Scenario: Repeated quadratic-prone constructs"""
        for source in ('[a](' * 2048, '<!--' * 2048, '**' * 4096, '~~' * 4096, '*a ' * 2730, '_a ' * 2730):
            with self.subTest(source=source[:12]):
                assert_fast(source)


class TestMalformedInput(SimpleTestCase):
    def test_deep_nesting_and_unterminated_constructs(self):
        """Scenario: Deep nesting and unterminated constructs"""
        sources = (
            '>' * 1000,
            '\n'.join(' ' * (2 * i) + '- x' for i in range(1000)),
            '[' * 5000,
            '```python\nx',
            '<div',
            'a\x00b',
            '> ' * 1000,
            '- ' * 1000,
            '*' * 5000 + 'a',
            '![' * 2500,
        )
        for style in ('comment', 'problem'):
            for source in sources:
                with self.subTest(style=style, source=source[:12]):
                    self.assertIsInstance(assert_fast(source, style), str)


class TestSafeModeStyles(SimpleTestCase):
    def test_raw_html_is_shown_as_text(self):
        """Scenario: Raw HTML is shown as text"""
        for style in SAFE_STYLES:
            with self.subTest(style=style):
                self.assertIn('&lt;script&gt;', str(markdown('<script>alert(1)</script>', style)))
                self.assertEqual(render_tree('<script>alert(1)</script>', style).findall('.//script'), [])
                self.assertEqual(render_tree('<img src=x onerror=alert(1)>', style).findall('.//img'), [])

    def test_dangerous_schemes_in_links_images_and_autolinks(self):
        """Scenario: Dangerous schemes in links, images and autolinks"""
        sources = (
            '[x](javascript:alert(1))',
            '[x](JaVaScRiPt:alert(1))',
            '[x]( javascript:alert(1))',
            '[x](   javascript:alert(1))',
            '[x](java\tscript:alert(1))',
            '[x](java\nscript:alert(1))',
            '[x](\x01javascript:alert(1))',
            '[x](vbscript:msgbox(1))',
            '[x](&#106;avascript:alert(1))',
            '![x](javascript:alert(1))',
            '<javascript:alert(1)>',
        )
        for style in SAFE_STYLES:
            for source in sources:
                with self.subTest(style=style, source=source):
                    self.assertEqual(executable_markup(render_tree(source, style)), [])

    def test_payload_battery(self):
        """Scenario: Payload battery"""
        self.assertGreaterEqual(len(PAYLOADS), 40)
        for style in SAFE_STYLES:
            for payload in PAYLOADS:
                with self.subTest(style=style, payload=payload):
                    self.assertEqual(executable_markup(render_tree(payload, style)), [])


class TestPostProcessing(SimpleTestCase):
    class PrefixingProxy:
        @staticmethod
        def update_tree(tree):
            for image in tree.iter('img'):
                image.set('src', 'https://camo.invalid/' + image.get('src'))

    def test_image_proxy(self):
        """Scenario: Image proxy"""
        source = '![x](https://a.invalid/i.png)'
        with mock.patch('judge.jinja2.markdown.camo_client', self.PrefixingProxy):
            self.assertEqual(render_tree(source, 'comment').find('.//img').get('src'),
                             'https://camo.invalid/https://a.invalid/i.png')
        with mock.patch('judge.jinja2.markdown.camo_client', None):
            self.assertEqual(render_tree(source, 'comment').find('.//img').get('src'), 'https://a.invalid/i.png')

    def test_paragraph_stripping(self):
        """Scenario: Paragraph stripping"""
        result = str(markdown('proudly powered by **DMOJ**', 'default', strip_paragraphs=True))
        self.assertIn('<strong>DMOJ</strong>', result)
        self.assertNotIn('<p>', result)


class TestInlineExtras(SimpleTestCase):
    def test_bare_url_and_strikethrough(self):
        """Scenario: Bare URL and strikethrough"""
        tree = render_tree('see https://example.com/a and ~~gone~~', 'comment')
        links = tree.findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get('href'), 'https://example.com/a')
        self.assertEqual(links[0].text, 'https://example.com/a')
        self.assertEqual([deleted.text for deleted in tree.findall('.//del')], ['gone'])


class TestLinks(SimpleTestCase):
    def test_nofollow_by_host(self):
        """Scenario: Nofollow by host"""
        sources = (
            '[a](https://example.com/)',
            '[b](https://excluded.example/)',
            '[c](/problem/a)',
            'https://example.org/x',
            '<a@b.c>',
            '<https://example.net/auto>',
        )
        with mock.patch('judge.jinja2.markdown.NOFOLLOW_WHITELIST', {'excluded.example'}):
            links = render_tree('\n\n'.join(sources), 'comment').findall('.//a')
        self.assertEqual([link.get('rel') for link in links], ['nofollow', None, None, 'nofollow', None, 'nofollow'])

    @override_settings(MARKDOWN_STYLES={
        'plain': {'safe_mode': True, 'nofollow': False},
        'on': {'safe_mode': True, 'nofollow': True},
    })
    def test_style_without_nofollow(self):
        """Scenario: Style without nofollow"""
        # The style with nofollow on is the positive control: the anchor of 'plain' is bare only because of its flag.
        for style, rel in (('on', 'nofollow'), ('plain', None)):
            with self.subTest(style=style):
                links = render_tree('[a](https://example.com/)', style).findall('.//a')
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0].get('href'), 'https://example.com/')
                self.assertEqual(links[0].get('rel'), rel)

    def test_allowed_and_replaced_schemes(self):
        """Scenario: Allowed and replaced schemes"""
        kept = render_tree(
            '[a](https://example.com/)\n\n[b](mailto:a@b.c)\n\n[c](tel:+123)\n\n[d](ftp://example.com/)\n\n'
            '[e](/relative)\n\n![i](data:image/png;base64,AA)',
            'comment',
        )
        self.assertEqual([link.get('href') for link in kept.iter('a')],
                         ['https://example.com/', 'mailto:a@b.c', 'tel:+123', 'ftp://example.com/', '/relative'])
        self.assertEqual([image.get('src') for image in kept.iter('img')], ['data:image/png;base64,AA'])

        replaced = render_tree(
            '[a](steam://run/1)\n\n[b](sms:+1)\n\n[c](file:///etc/passwd)\n\n![i](data:image/svg+xml,AA)',
            'comment',
        )
        self.assertEqual([link.get('href') for link in replaced.iter('a')], ['#harmful-link'] * 3)
        self.assertEqual([image.get('src') for image in replaced.iter('img')], ['#harmful-link'])

    def test_unparsable_host_does_not_raise(self):
        """Not tied to a Scenario: a URL whose host cannot be parsed is rendered without raising."""
        # The link target is percent-encoded to http://%5B::1, which still has a host, so the link is nofollow.
        tree = render_tree('[x](http://[::1)', 'comment')
        self.assertEqual([link.get('rel') for link in tree.findall('.//a')], ['nofollow'])
        self.assertEqual(executable_markup(tree), [])

    def test_protocol_relative_link_is_nofollow(self):
        """Not tied to a Scenario: a protocol-relative link has a host, so it is nofollow."""
        links = render_tree('[x](//example.com/p)', 'comment').findall('.//a')
        self.assertEqual([link.get('rel') for link in links], ['nofollow'])

    def test_link_text_keeps_markup(self):
        """Not tied to a Scenario: markup inside the link text is rendered."""
        self.assertIsNotNone(render_tree('[**b**](https://example.com/)', 'comment').find('.//a/strong'))


HEADING_TAGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')


class TestHeadings(SimpleTestCase):
    def test_heading_levels(self):
        """Scenario: Heading levels"""
        tree = render_tree('# a\n\n### b\n\n###### c', 'comment')
        self.assertEqual([(heading.tag, heading.text) for heading in tree.iter(*HEADING_TAGS)],
                         [('h3', 'a'), ('h5', 'b'), ('h6', 'c')])

    def test_trailing_hashes_are_not_text(self):
        """Not tied to a Scenario: the closing hashes of a heading are not part of its text."""
        headings = list(render_tree('## Sub ##', 'comment').iter(*HEADING_TAGS))
        self.assertEqual([(heading.tag, heading.text) for heading in headings], [('h4', 'Sub')])


class TestHeadingWithoutSpace(SimpleTestCase):
    def test_heading_without_a_space(self):
        """Scenario: Heading without a space"""
        tree = render_tree('#Title\n\n##Sub', 'comment')
        self.assertEqual([(heading.tag, heading.text) for heading in tree.iter(*HEADING_TAGS)],
                         [('h3', 'Title'), ('h4', 'Sub')])
        self.assertNotIn('#', tree.text_content())

    def test_fenced_code_is_untouched(self):
        """Scenario: Fenced code is untouched"""
        tree = render_tree('```\n#include <stdio.h>\n```', 'comment')
        self.assertIn('#include <stdio.h>', tree.find('.//pre').text_content())
        self.assertEqual(list(tree.iter(*HEADING_TAGS)), [])

    def test_raw_html_blocks_are_untouched(self):
        """Scenario: Raw HTML blocks are untouched"""
        source = '<style>\n#a { color: red }\n</style>\n\n<pre>\n#include <x>\n\n#b\n</pre>'
        raw = str(markdown(source, 'problem-full'))
        self.assertIn('<style>\n#a { color: red }\n</style>', raw)
        self.assertIn('<pre>\n#include <x>\n\n#b\n</pre>', raw)
        self.assertEqual(list(parse_fragment(raw).iter(*HEADING_TAGS)), [])

    def test_seven_hashes_is_a_paragraph(self):
        """Not tied to a Scenario: seven hashes are too many for a heading."""
        tree = render_tree('#######x', 'comment')
        self.assertEqual(list(tree.iter(*HEADING_TAGS)), [])
        self.assertEqual([paragraph.text for paragraph in tree.findall('p')], ['#######x'])

    def test_lone_hash_does_not_raise(self):
        """Not tied to a Scenario: a lone hash is rendered without raising."""
        self.assertIsInstance(markdown('#', 'comment'), str)


class TestTables(SimpleTestCase):
    def test_table_wrapper(self):
        """Scenario: Table wrapper"""
        tree = render_tree('| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |', 'comment')
        wrappers = tree.findall('.//div[@class="h-scrollable-table"]')
        self.assertEqual(len(wrappers), 1)
        tables = wrappers[0].findall('table[@class="table"]')
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(tree.findall('.//table')), 1)
        self.assertEqual(len(tables[0].findall('thead/tr')), 1)
        self.assertEqual(len(tables[0].findall('tbody/tr')), 2)

    def test_table_cells_keep_markup_and_escaped_pipe(self):
        """Not tied to a Scenario: cells render inline markup and honour an escaped pipe."""
        cells = render_tree('| x | y |\n|---|---|\n| **b** | a \\| b |', 'comment').findall('.//tbody/tr/td')
        self.assertEqual(len(cells), 2)
        self.assertIsNotNone(cells[0].find('strong'))
        self.assertEqual(cells[1].text, 'a | b')


class TestCode(SimpleTestCase):
    def test_code_blocks(self):
        """Scenario: Code blocks"""
        tree = render_tree('```python\nprint(1)\n```', 'comment')
        highlighted = tree.findall('.//*[@class="codehilite"]')
        self.assertEqual(len(highlighted), 1)
        self.assertIn('print', highlighted[0].text_content())
        self.assertNotEqual(highlighted[0].findall('.//span'), [])

        source = '```\n<b>&</b>\n```'
        code = render_tree(source, 'comment').find('.//pre/code')
        self.assertEqual(code.text.strip(), '<b>&</b>')
        self.assertIn('<pre><code>&lt;b&gt;&amp;&lt;/b&gt;', str(markdown(source, 'comment')))

    def test_unknown_language_falls_back(self):
        """Not tied to a Scenario: an unknown or hostile language gives plain escaped preformatted text."""
        for language in ('notalang', '<script>alert(1)</script>', 'a"onmouseover="alert(1)'):
            with self.subTest(language=language):
                tree = render_tree(f'```{language}\nx < y\n```', 'comment')
                self.assertIn('x < y', tree.find('.//pre/code').text)
                self.assertEqual(tree.findall('.//script'), [])
                self.assertEqual(executable_markup(tree), [])

    def test_info_string_uses_the_first_word(self):
        """Not tied to a Scenario: only the first word of the info string names the language."""
        tree = render_tree('```python title="x"\nx = 1\n```', 'comment')
        self.assertEqual(len(tree.findall('.//*[@class="codehilite"]')), 1)

    def test_code_span_keeps_a_literal_entity(self):
        """Not tied to a Scenario: an entity inside a code span is shown literally, not decoded."""
        self.assertIn('<code>a &amp;amp; b</code>', str(markdown('`a &amp; b`', 'comment')))


class RecordingMath:
    """Stands in for MathoidMathParser: records every formula it is asked to render."""

    calls = []

    def __init__(self, type):
        self.type = type

    def inline_math(self, formula):
        self.calls.append(('inline', formula))
        return f'<span class="m-inline">{formula}</span>'

    def display_math(self, formula):
        self.calls.append(('display', formula))
        return f'<span class="m-display">{formula}</span>'


def math_stubs():
    RecordingMath.calls.clear()
    return (
        override_settings(MATHOID_URL='http://mathoid.invalid'),
        mock.patch('judge.jinja2.markdown.MathoidMathParser', RecordingMath),
    )


def render_math_raw(source, style='comment', **kwargs):
    settings_override, parser_patch = math_stubs()
    with settings_override, parser_patch:
        return str(markdown(source, style, math_engine='svg', **kwargs))


def render_math(source, style='comment', **kwargs):
    return fragments_to_tree(render_math_raw(source, style, **kwargs))


class TestMath(SimpleTestCase):
    def test_all_four_delimiters(self):
        """Scenario: All four delimiters"""
        tree = render_math(r'~a+b~ \(a+b\) $$a+b$$ \[a+b\]')
        self.assertEqual(RecordingMath.calls,
                         [('inline', 'a+b'), ('inline', 'a+b'), ('display', 'a+b'), ('display', 'a+b')])
        self.assertEqual(len(tree.findall('.//span[@class="m-inline"]')), 2)
        self.assertEqual(len(tree.findall('.//span[@class="m-display"]')), 2)

    def test_math_keeps_its_own_characters(self):
        """Scenario: Math keeps its own characters"""
        for source, formula in (
            (r'\(a_b\)', 'a_b'),
            ('$$x_1*y_2$$', 'x_1*y_2'),
            ('~a_b~', 'a_b'),
            (r'\[a\\b\]', r'a\\b'),
        ):
            with self.subTest(source=source):
                tree = render_math(source)
                self.assertEqual([call[1] for call in RecordingMath.calls], [formula])
                self.assertEqual(tree.findall('.//em') + tree.findall('.//strong'), [])
                self.assertEqual(tree.text_content().strip(), formula)

    def test_math_is_protected_from_emphasis(self):
        """Not tied to a Scenario: a formula with a real emphasis pair inside reaches the service unchanged."""
        for source, formula in (('$$a*b*c$$', 'a*b*c'), ('~a_b_c~', 'a_b_c')):
            with self.subTest(source=source):
                tree = render_math(source)
                self.assertEqual([call[1] for call in RecordingMath.calls], [formula])
                self.assertEqual(tree.findall('.//em') + tree.findall('.//strong'), [])
                self.assertEqual(tree.text_content().strip(), formula)

    def test_tilde_math_next_to_strikethrough(self):
        """Scenario: Tilde math next to strikethrough"""
        tree = render_math('~a~ and ~~b~~')
        self.assertEqual(RecordingMath.calls, [('inline', 'a')])
        self.assertEqual([deleted.text for deleted in tree.findall('.//del')], ['b'])

    def test_math_delimiters_inside_code(self):
        """Scenario: Math delimiters inside code"""
        raw = render_math_raw('`~a<b~`\n\n```\n$$a&b$$\n```')
        self.assertEqual(RecordingMath.calls, [])
        self.assertIn('~a&lt;b~', raw)
        self.assertIn('$$a&amp;b$$', raw)
        tree = fragments_to_tree(raw)
        self.assertEqual([code.text.strip() for code in tree.findall('.//code')], ['~a<b~', '$$a&b$$'])

    def test_math_without_a_math_engine(self):
        """Scenario: Math without a math engine"""
        raw = str(markdown('~a<b~ $$a<b$$', 'comment'))
        self.assertIn(r'\(a&lt;b\)', raw)
        self.assertIn(r'\[a&lt;b\]', raw)

        # An engine name without a math service (MATHOID_URL false) gives the same fallback text.
        settings_override, parser_patch = math_stubs()
        with parser_patch, override_settings(MATHOID_URL=False):
            raw = str(markdown('~a<b~ $$a<b$$', 'comment', math_engine='svg'))
        self.assertEqual(RecordingMath.calls, [])
        self.assertIn(r'\(a&lt;b\)', raw)
        self.assertIn(r'\[a&lt;b\]', raw)

    def test_entity_in_a_fallback_formula(self):
        """Not tied to a Scenario: an entity typed in a formula is not escaped twice by the fallback text."""
        raw = str(markdown('~a &lt; b~', 'comment'))
        self.assertIn(r'\(a &lt; b\)', raw)
        self.assertNotIn('&amp;lt;', raw)
        render_math('~a &lt; b~')
        self.assertEqual(RecordingMath.calls, [('inline', 'a &lt; b')])

    def test_math_in_link_heading_and_table(self):
        """Not tied to a Scenario: math reaches the math service once inside a link, a heading and a table cell."""
        for source, path in (
            ('[~a~](http://x.y)', './/a/span[@class="m-inline"]'),
            ('## ~a~', './/h4/span[@class="m-inline"]'),
            ('| x |\n|---|\n| \\(c\\) |', './/td/span[@class="m-inline"]'),
        ):
            with self.subTest(source=source):
                tree = render_math(source)
                self.assertEqual(len(RecordingMath.calls), 1)
                self.assertEqual(len(tree.findall(path)), 1)

    def test_unpaired_delimiters_stay_literal(self):
        """Not tied to a Scenario: single or unpaired delimiters are plain text."""
        for source, text in (('a ~ b', 'a ~ b'), ('$$a$', '$$a$'), (r'\~a\~', '~a~')):
            with self.subTest(source=source):
                tree = render_math(source)
                self.assertEqual(RecordingMath.calls, [])
                self.assertEqual(tree.text_content().strip(), text)
        # `~a~~b~` is not specified: it only has to render and keep both letters visible.
        raw = render_math_raw('~a~~b~')
        text = fragments_to_tree(raw).text_content()
        self.assertTrue('a' in text and 'b' in text, raw)

    def test_unterminated_math_openers_are_fast(self):
        """Not tied to a Scenario: repeated unterminated math openers render within the time budget."""
        settings_override, parser_patch = math_stubs()
        with settings_override, parser_patch:
            for source in (
                '\\(' * 4096, '\\[' * 4096, '$$a ' * 2048, '~a ' * 2730, '$' * 8192, '~ ' * 4096,
                '\\[a ' * 2048, '\\(a ' * 2730,
            ):
                with self.subTest(source=source[:8]):
                    assert_fast(source, math_engine='svg')
                    assert_fast(source)


class RecordingTexoid:
    """Stands in for TexoidRenderer: returns the configured result and records the LaTeX it was given."""

    result = None
    calls = []

    def get_result(self, latex):
        self.calls.append(latex)
        return self.result


LATEX_IMAGE = {'svg': '/s.svg', 'png': '/s.png', 'meta': {'width': '10px', 'height': '5px'}}


def render_latex(source, result, style='latex'):
    RecordingTexoid.calls.clear()
    RecordingTexoid.result = result
    with (
        mock.patch('judge.jinja2.markdown.TEXOID_ENABLED', True),
        mock.patch('judge.jinja2.markdown.TexoidRenderer', RecordingTexoid),
    ):
        return markdown(source, style)


@override_settings(MARKDOWN_STYLES={'latex': {'safe_mode': False, 'texoid': True}})
class TestLatexBlocks(SimpleTestCase):
    def test_successful_latex_block(self):
        """Scenario: Successful LaTeX block"""
        for source, wrapper in (('<latex>x^2</latex>', 'div'), ('<latex inline>x^2</latex>', 'span')):
            with self.subTest(source=source):
                tree = fragments_to_tree(render_latex(source, LATEX_IMAGE))
                images = tree.findall(f'.//{wrapper}/img')
                self.assertEqual(len(tree.findall('.//img')), 1)
                self.assertEqual(len(images), 1)
                self.assertEqual((images[0].get('width'), images[0].get('height')), ('10px', '5px'))
                self.assertEqual(images[0].get('src'), '/s.svg')
                self.assertEqual(RecordingTexoid.calls, ['x^2'])

    def test_latex_service_error(self):
        """Scenario: LaTeX service error"""
        raw = str(render_latex('<latex>x^2</latex>', {'error': 'bad <tex> &'}))
        self.assertIn('<pre>bad &lt;tex&gt; &amp;</pre>', raw)
        self.assertEqual([pre.text for pre in fragments_to_tree(raw).findall('.//pre')], ['bad <tex> &'])

        # No result: the service receives the source with its entities decoded and the pre shows it escaped.
        raw = str(render_latex('<latex>a &lt; b &amp; c</latex>', None))
        self.assertEqual(RecordingTexoid.calls, ['a < b & c'])
        self.assertIn('<pre>a &lt; b &amp; c</pre>', raw)
        self.assertEqual([pre.text for pre in fragments_to_tree(raw).findall('.//pre')], ['a < b & c'])

    def test_latex_block_with_blank_lines(self):
        """Not tied to a Scenario: a block with blank lines inside is one block."""
        render_latex('<latex>\na\n\nb\n</latex>', LATEX_IMAGE)
        self.assertEqual([call.strip() for call in RecordingTexoid.calls], ['a\n\nb'])

    def test_two_latex_blocks_stay_separate(self):
        """Not tied to a Scenario: two blocks in one document are two images."""
        tree = fragments_to_tree(render_latex('<latex>a</latex>\n\n<latex>b</latex>', LATEX_IMAGE))
        self.assertEqual(len(tree.findall('.//img')), 2)
        self.assertEqual(RecordingTexoid.calls, ['a', 'b'])

    def test_unterminated_latex_does_not_swallow_the_rest(self):
        """Not tied to a Scenario: an unterminated block neither raises nor hides the text after it."""
        self.assertIn('<em>me</em>', render_latex('<latex>x\n\nafter *me*', LATEX_IMAGE))
        self.assertEqual(RecordingTexoid.calls, [])

    def test_latex_is_plain_text_in_a_style_without_texoid(self):
        """Not tied to a Scenario: a style that does not enable LaTeX shows the tag as text."""
        with override_settings(MARKDOWN_STYLES={'comment': {'safe_mode': True}}):
            raw = str(render_latex('<latex>x^2</latex>', LATEX_IMAGE, style='comment'))
        self.assertIn('&lt;latex&gt;', raw)
        self.assertEqual(RecordingTexoid.calls, [])
