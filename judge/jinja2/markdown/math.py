def _math_rule(token_type, group):
    def parse(inline, match, state):
        state.append_token({'type': token_type, 'raw': match.group(group)})
        return match.end()

    return parse


def math(md):
    # mistune wraps every pattern in a group named after the rule and joins them into one regex, so the formula
    # group of each rule needs a name of its own. The rules go before `escape`, which would otherwise eat the
    # backslash of `\(` and `\[`.
    # shortcut: a multi-line `$$ ... $$` whose inner line starts with `#` is cut by the relaxed `#Title` heading
    # rule, accepted limit.
    # shortcut: an unterminated `\(`, `\[` or `<latex>` opener is rescanned to the end of the input, so the cost grows
    # quadratically (about 0.15 s at 8192 characters, about 8 s at 64 KB). The `/widgets/preview/*` endpoints and the
    # unbounded profile, organization and ticket text fields accept longer inputs: cap their length (follow-up) or
    # bound the patterns.
    for name, pattern, token_type, start_chars in (
        ('math_dollar', r'\$\$(?P<dollar_formula>[\s\S]+?)\$\$', 'display_math', '$'),
        ('math_bracket', r'\\\[(?P<bracket_formula>[\s\S]+?)\\\]', 'display_math', '\\'),
        ('math_paren', r'\\\((?P<paren_formula>[\s\S]+?)\\\)', 'inline_math', '\\'),
        ('math_tilde', r'(?<!~)~(?!~)(?P<tilde_formula>[^~]+?)~(?!~)', 'inline_math', '~'),
    ):
        group = name.removeprefix('math_') + '_formula'
        md.inline.register(name, pattern, _math_rule(token_type, group), before='escape', start_chars=start_chars)


def _parse_latex(block, match, state):
    source = match.group(0)
    # Same split as mistune 0.8: the opening tag runs to the first `>`, the source ends at the last `<`.
    tag_end = source.index('>')
    state.append_token({
        'type': 'latex',
        'raw': source[tag_end + 1:source.rindex('<')],
        'attrs': {'inline': 'inline' in source[:tag_end]},
    })
    # `$` stops before the newline; step over it so it does not become an empty paragraph.
    return match.end() + 1


def latex(md):
    # Lazy and tied to a closing tag that ends its line, so two blocks stay separate and an unterminated tag does
    # not match. The block may contain blank lines, which the HTML block rules would end on. It goes ahead of
    # `raw_html`, the rule in BlockParser.DEFAULT_RULES that would otherwise take any line starting with a tag.
    # shortcut: an unterminated `<latex>` is rescanned to the end of the input (quadratic, see `math`), cap the input
    # length or bound the pattern when longer texts are accepted.
    md.block.register('latex', r'^ {0,3}<latex(?=[\s>])[^>]*>[\s\S]*?</latex>[ \t]*$', _parse_latex, before='raw_html')
