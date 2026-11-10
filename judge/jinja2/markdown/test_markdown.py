import re
import time
from html import unescape
from html.entities import name2codepoint
from unittest import mock

from django.test import SimpleTestCase
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


def assert_fast(source, style='comment'):
    start = time.perf_counter()
    result = markdown(source, style)
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
