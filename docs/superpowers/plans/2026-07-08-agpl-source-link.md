# AGPL Source Link in Footer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a footer link to this fork's public source repository so the site satisfies AGPLv3 Section 13 (network users must be able to obtain the Corresponding Source of the running version).

**Architecture:** One-line addition to the shared Jinja2 base template's footer, next to the existing "proudly powered by DMOJ" credit, using the same translatable-text/styling pattern. A Django test case exercises a page render and asserts the link is present in the response.

**Tech Stack:** Django, Jinja2 (`django_jinja`), Django `TestCase`/`Client`.

## Global Constraints

- Source link target: `https://github.com/AresLOLXD/online-judge` (exact, verbatim — this fork's repo).
- Link must be hardcoded in the template, not admin-configurable (per user decision — matches how the existing DMOJ credit link is hardcoded).
- Link text must be wrapped in `_()` for translation, consistent with the rest of the footer.
- Link styling must match the existing DMOJ credit link: `style="color: #808080"`.
- Placement: inside `#footer-content` in `templates/base.html`, immediately after the existing "proudly powered by DMOJ" link (currently line 284), before the `{% if misc_config.footer %}` block, followed by the same ` | ` separator pattern used by neighboring footer items.
- No changes to `misc_config.footer`, any admin/settings model, or any other template.

---

### Task 1: Add source link to footer and verify via test

**Files:**
- Modify: `templates/base.html:281-300` (footer block)
- Test: `judge/tests.py`

**Interfaces:**
- Consumes: nothing new — reuses the existing `#footer-content` Jinja2 block structure and the `markdown` filter already used by the DMOJ credit link (see current `templates/base.html:284`).
- Produces: nothing consumed by later tasks — this is the only task in the plan.

Current footer block (`templates/base.html:281-300`) for reference:

```html
    <footer>
        <span id="footer-content">
            <br>
            <a style="color: #808080" href="https://dmoj.ca">{{ _('proudly powered by **DMOJ**')|markdown('default', strip_paragraphs=True) }}</a> |
            {% if misc_config.footer %}
                {{ misc_config.footer|safe }} |
            {% endif %}
            <form action="{{ url('set_language') }}" method="post" style="display: inline">
                {% csrf_token %}
            <input name="next" type="hidden" value="{{ request.get_full_path() }}">
            <select name="language" onchange="form.submit()" style="height: 1.5em">
                {% for language in language_info_list(LANGUAGES) %}
                    <option value="{{ language.code }}" {% if language.code == LANGUAGE_CODE %}selected{% endif %}>
                        {{ language.name_local }} ({{ language.code }})
                    </option>
                {% endfor %}
            </select>
          </form>
        </span>
    </footer>
```

- [ ] **Step 1: Write the failing test**

Append to `judge/tests.py`:

```python
class FooterSourceLinkTestCase(TestCase):
    def test_homepage_footer_contains_source_link(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'https://github.com/AresLOLXD/online-judge')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test judge.tests.FooterSourceLinkTestCase -v 2`
Expected: FAIL — response does not contain `https://github.com/AresLOLXD/online-judge`.

(If the test errors instead of failing because `reverse('home')` doesn't resolve, check `judge/urls.py` for the actual name of the homepage URL pattern and adjust the `reverse()` call accordingly — the assertion logic itself does not change.)

- [ ] **Step 3: Add the source link to the footer**

In `templates/base.html`, replace:

```html
            <a style="color: #808080" href="https://dmoj.ca">{{ _('proudly powered by **DMOJ**')|markdown('default', strip_paragraphs=True) }}</a> |
            {% if misc_config.footer %}
```

with:

```html
            <a style="color: #808080" href="https://dmoj.ca">{{ _('proudly powered by **DMOJ**')|markdown('default', strip_paragraphs=True) }}</a> |
            <a style="color: #808080" href="https://github.com/AresLOLXD/online-judge">{{ _('source code') }}</a> |
            {% if misc_config.footer %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test judge.tests.FooterSourceLinkTestCase -v 2`
Expected: PASS

- [ ] **Step 5: Run the full test file to check for regressions**

Run: `python manage.py test judge.tests -v 2`
Expected: All tests PASS (including the pre-existing `RegistrationTurnstileTestCase` and `RegistrationTurnstileDisabledTestCase` tests).

- [ ] **Step 6: Lint**

Run: `flake8 templates/base.html judge/tests.py`

Note: `flake8` targets Python files per `.flake8` config in this repo — it will not lint the `.html` template. Run it anyway to confirm `judge/tests.py` has no violations; visually re-check the template edit against the `.flake8` 120-column limit (the new line is well under it).
Expected: No output (no violations).

- [ ] **Step 7: Commit**

```bash
git add templates/base.html judge/tests.py
git commit -m "$(cat <<'EOF'
Add source code link to footer for AGPL compliance

EOF
)"
```
