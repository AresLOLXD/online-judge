import logging
from html import unescape
from urllib.parse import urlparse

import mistune
from bleach.css_sanitizer import CSSSanitizer
from bleach.sanitizer import Cleaner
from django.conf import settings
from lxml import html
from lxml.etree import ParserError, XMLSyntaxError
from markupsafe import Markup
from mistune.plugins.formatting import strikethrough
from mistune.plugins.table import table
from mistune.plugins.url import url
from mistune.util import escape as escape_html, safe_entity

from judge.highlight_code import highlight_code
from judge.jinja2.markdown.lazy_load import lazy_load as lazy_load_processor
from judge.utils.camo import client as camo_client
from judge.utils.mathoid import MathoidMathParser
from judge.utils.texoid import TEXOID_ENABLED, TexoidRenderer
from .bleach_whitelist import all_styles, mathml_attrs, mathml_tags
from .math import latex as latex_plugin, math as math_plugin
from .. import registry

logger = logging.getLogger('judge.html')

NOFOLLOW_WHITELIST = settings.NOFOLLOW_EXCLUDED


class AwesomeRenderer(mistune.HTMLRenderer):
    def __init__(self, escape: bool = True, nofollow: bool = True, math: bool = False,
                 math_engine: str | None = None, texoid: bool = False):
        super().__init__(escape=escape)
        self.nofollow = nofollow
        self.texoid = TexoidRenderer() if texoid else None
        self.mathoid = MathoidMathParser(math_engine or 'svg') if math else None

    def inline_math(self, formula: str) -> str:
        if self.mathoid is None or not formula:
            return r'\(' + safe_entity(formula) + r'\)'
        return self.mathoid.inline_math(formula)

    def display_math(self, formula: str) -> str:
        if self.mathoid is None or not formula:
            return r'\[' + safe_entity(formula) + r'\]'
        return self.mathoid.display_math(formula)

    def latex(self, source: str, inline: bool = False) -> str:
        source = unescape(source)
        result = self.texoid.get_result(source)
        if not result:
            return '<pre>' + escape_html(source) + '</pre>'
        if 'error' in result:
            return '<pre>' + escape_html(result['error']) + '</pre>'
        img = ('<img src="%(svg)s" onerror="this.src=\'%(png)s\';this.onerror=null" '
               'class="tex-full" width="%(width)s" height="%(height)s">') % {
            'svg': result['svg'], 'png': result['png'],
            'width': result['meta']['width'], 'height': result['meta']['height'],
        }
        style = ['max-width: 100%',
                 'height: %s' % result['meta']['height'],
                 'max-height: %s' % result['meta']['height'],
                 'width: %s' % result['meta']['width']]
        tag = 'span' if inline else 'div'
        if not inline:
            style.append('text-align: center')
        return '<%s style="%s">%s</%s>' % (tag, ';'.join(style), img, tag)

    def text(self, text):
        # Decode then re-escape, so that an entity typed by the author is not escaped twice
        # (mistune only does this when escape is off); the result is escaped either way.
        return safe_entity(text)

    def _needs_nofollow(self, href):
        try:
            host = urlparse(href).netloc
        except ValueError:
            return True
        return bool(host) and host not in NOFOLLOW_WHITELIST

    def link(self, text, url, title=None):
        attrs = {'href': self.sanitize_url(url)}
        if title:
            attrs['title'] = title
        if self.nofollow and self._needs_nofollow(attrs['href']):
            attrs['rel'] = 'nofollow'
        return '<a' + self.render_attrs(attrs) + '>' + text + '</a>'

    def heading(self, text, level, **attrs):
        return super().heading(text, min(level + 2, 6), **attrs)

    def block_code(self, code, info=None):
        lang = safe_entity(info.strip()).split(None, 1)[0] if info and info.strip() else None
        if lang:
            return highlight_code(code, lang)
        return super().block_code(code, info)


class AwesomeBlockParser(mistune.BlockParser):
    SPECIFICATION = {
        **mistune.BlockParser.SPECIFICATION,
        # mistune 3 requires whitespace after the hashes; mistune 0.8 did not, and existing content relies on it.
        'atx_heading': r'^ {0,3}(?P<atx_1>#{1,6})(?!#+)(?P<atx_2>[ \t]*|[ \t]*[^#\s].*?)$',
    }


def render_table(renderer, text):
    return '<div class="h-scrollable-table">\n<table class="table">\n' + text + '</table>\n</div>\n'


def _create_markdown(escape: bool, nofollow: bool = True, math: bool = False,
                     math_engine: str | None = None, texoid: bool = False) -> mistune.Markdown:
    renderer = AwesomeRenderer(escape=escape, nofollow=nofollow, math=math, math_engine=math_engine, texoid=texoid)
    plugins = [strikethrough, table, url, math_plugin]
    if texoid:
        plugins.append(latex_plugin)
    markdown = mistune.Markdown(renderer=renderer, block=AwesomeBlockParser(), plugins=plugins)
    # The table plugin registers its own hook when applied, so ours goes after it.
    markdown.renderer.register('table', render_table)
    return markdown


cleaner_cache = {}


def get_cleaner(name, params):
    if name in cleaner_cache:
        return cleaner_cache[name]

    styles = params.pop('styles', None)
    if styles:
        params['css_sanitizer'] = CSSSanitizer(allowed_css_properties=all_styles if styles is True else styles)

    if params.pop('mathml', False):
        params['tags'] = params.get('tags', []) + mathml_tags
        params['attributes'] = params.get('attributes', {}).copy()
        params['attributes'].update(mathml_attrs)

    cleaner = cleaner_cache[name] = Cleaner(**params)
    return cleaner


def fragments_to_tree(fragment):
    tree = html.Element('div')
    try:
        parsed = html.fragments_fromstring(fragment, parser=html.HTMLParser(recover=True))
    except (XMLSyntaxError, ParserError) as e:
        if fragment and (not isinstance(e, ParserError) or e.args[0] != 'Document is empty'):
            logger.exception('Failed to parse HTML string')
        return tree

    if parsed and isinstance(parsed[0], str):
        tree.text = parsed[0]
        parsed = parsed[1:]
    tree.extend(parsed)
    return tree


def strip_paragraphs_tags(tree):
    for p in tree.xpath('.//p'):
        for child in p.iterchildren(reversed=True):
            p.addnext(child)
        parent = p.getparent()
        prev = p.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or '') + (p.text or '')
        else:
            parent.text = (parent.text or '') + (p.text or '')
        parent.remove(p)


def fragment_tree_to_str(tree):
    return html.tostring(tree, encoding='unicode')[len('<div>'):-len('</div>')]


@registry.filter
def markdown(value, style, math_engine=None, lazy_load=False, strip_paragraphs=False):
    styles = settings.MARKDOWN_STYLES.get(style, settings.MARKDOWN_DEFAULT_STYLE)
    escape = styles.get('safe_mode', True)
    nofollow = styles.get('nofollow', True)
    texoid = TEXOID_ENABLED and styles.get('texoid', False)
    math = bool(settings.MATHOID_URL) and styles.get('math', False)
    bleach_params = styles.get('bleach', {})

    post_processors = []
    if styles.get('use_camo', False) and camo_client is not None:
        post_processors.append(camo_client.update_tree)
    if lazy_load:
        post_processors.append(lazy_load_processor)

    result = _create_markdown(escape, nofollow, math and math_engine is not None, math_engine, texoid)(value)

    if post_processors or strip_paragraphs:
        tree = fragments_to_tree(result)
        for processor in post_processors:
            processor(tree)
        if strip_paragraphs:
            strip_paragraphs_tags(tree)
        result = fragment_tree_to_str(tree)
    if bleach_params:
        result = get_cleaner(style, bleach_params).clean(result)
    return Markup(result)
