import logging

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
from mistune.util import safe_entity

from judge.jinja2.markdown.lazy_load import lazy_load as lazy_load_processor
from judge.utils.camo import client as camo_client
from .bleach_whitelist import all_styles, mathml_attrs, mathml_tags
from .. import registry

logger = logging.getLogger('judge.html')


class AwesomeRenderer(mistune.HTMLRenderer):
    def __init__(self, escape=True):
        super().__init__(escape=escape)

    def text(self, text):
        # Decode then re-escape, so that an entity typed by the author is not escaped twice
        # (mistune only does this when escape is off); the result is escaped either way.
        return safe_entity(text)


def _create_markdown(escape):
    return mistune.Markdown(renderer=AwesomeRenderer(escape=escape), plugins=[strikethrough, table, url])


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
    bleach_params = styles.get('bleach', {})

    post_processors = []
    if styles.get('use_camo', False) and camo_client is not None:
        post_processors.append(camo_client.update_tree)
    if lazy_load:
        post_processors.append(lazy_load_processor)

    result = _create_markdown(escape)(value)

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
