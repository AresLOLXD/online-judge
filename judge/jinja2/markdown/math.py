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
    for name, pattern, token_type, start_chars in (
        ('math_dollar', r'\$\$(?P<dollar_formula>[\s\S]+?)\$\$', 'display_math', '$'),
        ('math_bracket', r'\\\[(?P<bracket_formula>[\s\S]+?)\\\]', 'display_math', '\\'),
        ('math_paren', r'\\\((?P<paren_formula>[\s\S]+?)\\\)', 'inline_math', '\\'),
        ('math_tilde', r'(?<!~)~(?!~)(?P<tilde_formula>[^~]+?)~(?!~)', 'inline_math', '~'),
    ):
        group = name.removeprefix('math_') + '_formula'
        md.inline.register(name, pattern, _math_rule(token_type, group), before='escape', start_chars=start_chars)
