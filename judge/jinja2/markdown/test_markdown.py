import re
import time
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
                             '<p><img style="display: block; margin: 0 auto;"></p>')
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
                             '<p><noscript><img src="test.png"></noscript>'
                             '<img src="/static/blank.gif" data-src="test.png" class="unveil"></p>')


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
                self.assertEqual(links[0].get('href'), 'http://x.com/"y')
                self.assertEqual(links[0].get('rel'), 'nofollow')

    def test_single_quote_in_url(self):
        """Scenario: Quotes cannot break out of a link attribute"""
        tree = self.render("<http://x.com/'onmouseover='y>", 'comment')
        for element in tree.iter():
            for name in element.attrib:
                self.assertFalse(name.lower().startswith('on'), (element.tag, name))
        links = tree.findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get('href'), "http://x.com/'onmouseover='y")

    def test_normal_autolinks_unchanged(self):
        links = self.render('<https://example.com/page>', 'comment').findall('.//a')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].get('href'), 'https://example.com/page')
        self.assertEqual(links[0].get('rel'), 'nofollow')
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

        # The ampersand of an entity-encoded scheme must itself be escaped in the href.
        self.assertIn('&amp;#106;', str(markdown('<&#106;avascript:alert(1)>', 'comment')))
        self.assertIn('&amp;Tab;', str(markdown('<java&Tab;script:alert(1)>', 'comment')))


SAFE_STYLES = ('default', 'comment', 'self-description', 'organization-about', 'ticket')


def render_tree(source, style, **kwargs):
    return html.fragment_fromstring(str(markdown(source, style, **kwargs)), create_parent='div')


def executable_markup(tree):
    """Return what a browser could execute in the tree; independent of the renderer, so an empty list means safe."""
    found = []
    for element in tree.iter():
        if not isinstance(element.tag, str):  # comments and processing instructions
            continue
        if element.tag.lower() in ('script', 'iframe', 'object'):
            found.append(f'<{element.tag}>')
        for name, value in element.attrib.items():
            if name.lower().startswith('on'):
                found.append(f'{element.tag} {name}={value!r}')
            # lxml has decoded the entities once, as a browser does; only whitespace and controls are left to drop.
            elif name.lower() in ('href', 'src') and \
                    re.sub(r'[\x00-\x20]', '', value).lower().startswith(('javascript:', 'vbscript:')):
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
)


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
