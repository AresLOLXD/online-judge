# Cloudflare Turnstile Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side Cloudflare Turnstile verification to the DMOJ registration form to block automated bot signups, as a form field on `CustomRegistrationForm`, without modifying `RegistrationView` or the existing (optional, unused) reCAPTCHA integration.

**Architecture:** A new isolated module `judge/utils/turnstile.py` provides a `validate_turnstile(token)` helper (HTTP POST to Cloudflare's `siteverify` endpoint via `requests`, fail-closed on network errors) and a `TurnstileWidget` (Django form widget that renders the Cloudflare challenge div and declares its JS via `Media`, so it rides on the `{{ form.media.js }}` the template already renders). `CustomRegistrationForm` in `judge/views/register.py` gets one new conditional field (`turnstile`) plus one `clean_turnstile()` method — gated on `hasattr(settings, 'TURNSTILE_SECRET_KEY')`, mirroring the existing reCAPTCHA guard in the same file. The registration template gets one new `{% if form.turnstile %}` block mirroring the existing `{% if form.captcha %}` block.

**Tech Stack:** Django 4.2 forms, `requests` (already a pinned dependency, already used in `judge/utils/pwned.py`), Django's built-in test client (`django.test.TestCase`) and `unittest.mock.patch`.

## Global Constraints

- Minimal diff against upstream `DMOJ/online-judge` — touch only what this feature needs.
- Do not modify `judge/utils/recaptcha.py`, the existing `captcha` field, or `RegistrationView` (the class-based view itself, as opposed to the form class defined in the same file).
- Do not send `remote_ip`/`remoteip` to Cloudflare's `siteverify` API — it's optional, and omitting it avoids touching `get_form_kwargs`/`RegistrationView`.
- Fail-closed: any network error or timeout calling Cloudflare's API is treated as verification failure (blocks registration).
- No new dependencies — `requests` is already in `requirements.txt`.
- `flake8` (120 col limit, pycharm import order, `flake8-commas`, `flake8-quotes`) must pass with no new warnings.
- `dmoj/local_settings.py` is gitignored and not present in this checkout — settings changes described here are instructions for the user's own deployment, not a file this plan edits directly.

---

## Task 1: `validate_turnstile()` helper with fail-closed network handling

**Files:**
- Create: `judge/utils/turnstile.py`
- Test: `judge/utils/tests/test_turnstile.py`

**Interfaces:**
- Produces: `judge.utils.turnstile.validate_turnstile(token: str) -> bool`
- Produces: `judge.utils.turnstile.TURNSTILE_VERIFY_URL` (str constant, `'https://challenges.cloudflare.com/turnstile/v0/siteverify'`)

- [ ] **Step 1: Write the failing tests**

```python
# judge/utils/tests/test_turnstile.py
from unittest.mock import patch, Mock

from django.test import SimpleTestCase, override_settings
import requests

from judge.utils.turnstile import validate_turnstile


@override_settings(TURNSTILE_SECRET_KEY='test-secret')
class ValidateTurnstileTestCase(SimpleTestCase):
    @patch('judge.utils.turnstile.requests.post')
    def test_success(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {'success': True})
        self.assertTrue(validate_turnstile('good-token'))
        mock_post.assert_called_once_with(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': 'test-secret', 'response': 'good-token'},
            timeout=5,
        )

    @patch('judge.utils.turnstile.requests.post')
    def test_rejected_by_cloudflare(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {'success': False, 'error-codes': ['invalid-input-response']})
        self.assertFalse(validate_turnstile('bad-token'))

    @patch('judge.utils.turnstile.requests.post')
    def test_network_error_fails_closed(self, mock_post):
        mock_post.side_effect = requests.ConnectionError('boom')
        self.assertFalse(validate_turnstile('any-token'))

    @patch('judge.utils.turnstile.requests.post')
    def test_timeout_fails_closed(self, mock_post):
        mock_post.side_effect = requests.Timeout('too slow')
        self.assertFalse(validate_turnstile('any-token'))

    def test_empty_token_rejected_without_http_call(self):
        with patch('judge.utils.turnstile.requests.post') as mock_post:
            self.assertFalse(validate_turnstile(''))
            mock_post.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test judge.utils.tests.test_turnstile -v 2`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'judge.utils.turnstile'`

- [ ] **Step 3: Write the implementation**

```python
# judge/utils/turnstile.py
import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
REQUEST_TIMEOUT = 5.0  # seconds


def validate_turnstile(token):
    """
    Verifies a Cloudflare Turnstile response token server-side.
    Fails closed: any network error, timeout, or falsy Cloudflare
    response is treated as a failed verification.
    """
    if not token:
        return False
    try:
        response = requests.post(
            TURNSTILE_VERIFY_URL,
            data={
                'secret': settings.TURNSTILE_SECRET_KEY,
                'response': token,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        log.warning('Turnstile verification request failed', exc_info=True)
        return False
    return bool(response.json().get('success', False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test judge.utils.tests.test_turnstile -v 2`
Expected: `Ran 5 tests ... OK`

- [ ] **Step 5: Run flake8 on the new files**

Run: `.venv/bin/flake8 judge/utils/turnstile.py judge/utils/tests/test_turnstile.py`
Expected: no output (no violations)

- [ ] **Step 6: Commit**

```bash
git add judge/utils/turnstile.py judge/utils/tests/test_turnstile.py
git commit -m "Add fail-closed Cloudflare Turnstile verification helper"
```

---

## Task 2: `TurnstileWidget` (render + auto-loaded JS via `Media`)

**Files:**
- Modify: `judge/utils/turnstile.py`
- Test: `judge/utils/tests/test_turnstile.py`

**Interfaces:**
- Consumes: nothing from Task 1 beyond the same module.
- Produces: `judge.utils.turnstile.TurnstileWidget` — a `django.forms.Widget` subclass. `TurnstileWidget().render(name, value, attrs=None, renderer=None)` returns an HTML string containing a `<div class="cf-turnstile" data-sitekey="..." data-response-field-name="{name}">`. `TurnstileWidget.Media.js == ('https://challenges.cloudflare.com/turnstile/v0/api.js',)`.

- [ ] **Step 1: Write the failing tests**

Append to `judge/utils/tests/test_turnstile.py`:

```python
from django.forms import Widget

from judge.utils.turnstile import TurnstileWidget


@override_settings(TURNSTILE_SITE_KEY='test-site-key')
class TurnstileWidgetTestCase(SimpleTestCase):
    def test_is_a_widget(self):
        self.assertIsInstance(TurnstileWidget(), Widget)

    def test_render_includes_sitekey_and_field_name(self):
        html = TurnstileWidget().render('turnstile', None)
        self.assertIn('class="cf-turnstile"', html)
        self.assertIn('data-sitekey="test-site-key"', html)
        self.assertIn('data-response-field-name="turnstile"', html)

    def test_media_declares_turnstile_script(self):
        self.assertIn(
            'https://challenges.cloudflare.com/turnstile/v0/api.js',
            list(TurnstileWidget().media._js),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test judge.utils.tests.test_turnstile.TurnstileWidgetTestCase -v 2`
Expected: FAIL / ERROR with `ImportError: cannot import name 'TurnstileWidget'`

- [ ] **Step 3: Add the widget to `judge/utils/turnstile.py`**

Add these imports to the top of the file (alongside the existing ones):

```python
from django.forms import Widget
from django.utils.html import format_html
```

Append to the end of `judge/utils/turnstile.py`:

```python
class TurnstileWidget(Widget):
    class Media:
        js = ('https://challenges.cloudflare.com/turnstile/v0/api.js',)

    def render(self, name, value, attrs=None, renderer=None):
        return format_html(
            '<div class="cf-turnstile" data-sitekey="{}" data-response-field-name="{}"></div>',
            settings.TURNSTILE_SITE_KEY,
            name,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test judge.utils.tests.test_turnstile -v 2`
Expected: `Ran 8 tests ... OK`

- [ ] **Step 5: Run flake8**

Run: `.venv/bin/flake8 judge/utils/turnstile.py judge/utils/tests/test_turnstile.py`
Expected: no output

- [ ] **Step 6: Commit**

```bash
git add judge/utils/turnstile.py judge/utils/tests/test_turnstile.py
git commit -m "Add TurnstileWidget rendering the Cloudflare challenge div"
```

---

## Task 3: Wire the field into `CustomRegistrationForm`

**Files:**
- Modify: `judge/views/register.py`
- Test: `judge/tests.py`

**Interfaces:**
- Consumes: `judge.utils.turnstile.validate_turnstile(token: str) -> bool` and `judge.utils.turnstile.TurnstileWidget` from Tasks 1–2.
- Produces: `CustomRegistrationForm` has a `turnstile` field (present only when `settings.TURNSTILE_SECRET_KEY` is set) and a `clean_turnstile(self)` method. No change to `RegistrationView`.

- [ ] **Step 1: Write the failing test**

`judge/tests.py` currently contains only a placeholder comment. Replace its contents with:

```python
# judge/tests.py
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from judge.models import Language


@override_settings(TURNSTILE_SITE_KEY='test-site-key', TURNSTILE_SECRET_KEY='test-secret')
class RegistrationTurnstileTestCase(TestCase):
    def setUp(self):
        Language.objects.get_or_create(key='PY3', defaults={
            'name': 'Python 3', 'common_name': 'Python', 'ace': 'python', 'pygments': 'python3',
        })

    def _post_data(self, **overrides):
        data = {
            'username': 'newbotuser',
            'email': 'newbotuser@example.com',
            'password1': 'a-very-uncommon-pw-1',
            'password2': 'a-very-uncommon-pw-1',
            'timezone': 'America/Toronto',
            'language': Language.objects.get(key='PY3').pk,
            'organizations': [],
            'turnstile': 'some-token',
        }
        data.update(overrides)
        return data

    @patch('judge.views.register.validate_turnstile', return_value=True)
    def test_registration_succeeds_with_valid_turnstile(self, mock_validate):
        response = self.client.post(reverse('registration_register'), self._post_data())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='newbotuser').exists())
        mock_validate.assert_called_once_with('some-token')

    @patch('judge.views.register.validate_turnstile', return_value=False)
    def test_registration_rejected_with_invalid_turnstile(self, mock_validate):
        response = self.client.post(reverse('registration_register'), self._post_data())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newbotuser').exists())
        self.assertFormError(response.context['form'], 'turnstile', 'Anti-bot verification failed. Please try again.')

    def test_registration_rejected_without_turnstile_field(self):
        data = self._post_data()
        del data['turnstile']
        response = self.client.post(reverse('registration_register'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newbotuser').exists())
        self.assertFormError(response.context['form'], 'turnstile', 'This field is required.')
```

Add the missing `User` import at the top:

```python
from django.contrib.auth.models import User
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python manage.py test judge.tests -v 2`
Expected: FAIL — `ImportError: cannot import name 'validate_turnstile' from 'judge.views.register'` (the view module doesn't reference it yet)

- [ ] **Step 3: Wire the field into `judge/views/register.py`**

Add to the imports at the top of `judge/views/register.py` (alongside the existing `from judge.utils...` imports):

```python
from judge.utils.turnstile import TurnstileWidget, validate_turnstile
```

Add the field and clean method to `CustomRegistrationForm`, directly after the existing `if ReCaptchaField is not None:` block (`judge/views/register.py:36-37`):

```python
    if hasattr(settings, 'TURNSTILE_SECRET_KEY'):
        turnstile = forms.CharField(widget=TurnstileWidget(), required=True, label='')

        def clean_turnstile(self):
            token = self.cleaned_data['turnstile']
            if not validate_turnstile(token):
                raise forms.ValidationError(gettext('Anti-bot verification failed. Please try again.'))
            return token
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test judge.tests -v 2`
Expected: `Ran 3 tests ... OK`

- [ ] **Step 5: Run the full judge test suite to check for regressions**

Run: `.venv/bin/python manage.py test judge -v 2`
Expected: all tests pass (no failures introduced by this change)

- [ ] **Step 6: Run flake8**

Run: `.venv/bin/flake8 judge/views/register.py judge/tests.py`
Expected: no output

- [ ] **Step 7: Commit**

```bash
git add judge/views/register.py judge/tests.py
git commit -m "Require Cloudflare Turnstile verification on registration"
```

---

## Task 4: Render the widget in the registration template

**Files:**
- Modify: `templates/registration/registration_form.html`

**Interfaces:**
- Consumes: `form.turnstile` (Task 3) — a Django bound field that is falsy/absent when `TURNSTILE_SECRET_KEY` isn't configured, and whose `.errors` behaves like any other bound field.
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Add the template block**

In `templates/registration/registration_form.html`, immediately after the existing captcha block:

```html
            {% if form.captcha %}
                <div style="margin-top: 0.5em">{{ form.captcha }}</div>
                {% if form.captcha.errors %}
                    <div class="form-field-error">{{ form.captcha.errors }}</div>
                {% endif %}
            {% endif %}
```

add:

```html
            {% if form.turnstile %}
                <div style="margin-top: 0.5em">{{ form.turnstile }}</div>
                {% if form.turnstile.errors %}
                    <div class="form-field-error">{{ form.turnstile.errors }}</div>
                {% endif %}
            {% endif %}
```

- [ ] **Step 2: Verify the widget's script rides on the existing `form.media.js` call**

`templates/registration/registration_form.html`'s `{% block js_media %}` already contains `{{ form.media.js }}` — no edit needed there. Confirm by inspecting the file:

Run: `grep -n "form.media" templates/registration/registration_form.html`
Expected output includes both `{{ form.media.css }}` (in `block media`) and `{{ form.media.js }}` (in `block js_media`).

- [ ] **Step 3: Manual verification with the dev server**

This step requires `dmoj/local_settings.py` to exist with a working database and, for a real end-to-end check, valid `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY` values (Cloudflare provides test keys that always pass/fail, documented at their Turnstile testing docs, for use without a live site). If `local_settings.py` isn't set up in this environment, skip this step and rely on Task 3's automated tests — note that explicitly when reporting completion.

Run: `.venv/bin/python manage.py runserver`, visit `http://localhost:8000/accounts/register/`, confirm:
- The Turnstile challenge widget renders below the organizations field.
- Submitting without solving it shows "This field is required." under the widget.
- Submitting with a passing test sitekey/secret pair creates the account and redirects to `/accounts/register/complete/`.

- [ ] **Step 4: Commit**

```bash
git add templates/registration/registration_form.html
git commit -m "Render Turnstile challenge widget on the registration form"
```

---

## Task 5: Document local settings for deployment

**Files:**
- None in-repo (`dmoj/local_settings.py` is gitignored and not tracked)

- [ ] **Step 1: Confirm `local_settings.py` is gitignored**

Run: `grep -n "local_settings" .gitignore`
Expected: `dmoj/local_settings.py` is listed (already confirmed present in this repo).

- [ ] **Step 2: Add the two settings to the deployment's `dmoj/local_settings.py`**

This file is not part of the repo, so this step is a deployment action rather than a commit. Add:

```python
TURNSTILE_SITE_KEY = '<real site key from the Cloudflare Turnstile dashboard>'
TURNSTILE_SECRET_KEY = '<real secret key from the Cloudflare Turnstile dashboard>'
```

- [ ] **Step 3: Restart the site process** so the new settings take effect, per the deployment's normal restart procedure (outside the scope of this repo/plan).

---

## Self-Review Notes

- **Spec coverage:** `validate_turnstile` + fail-closed network handling (Task 1), `TurnstileWidget` + auto-loaded `Media.js` (Task 2), form field/`clean_turnstile`/no changes to `RegistrationView` (Task 3), template block (Task 4), settings documentation (Task 5). All spec sections and acceptance criteria are covered by a task.
- **No `remote_ip`:** confirmed `validate_turnstile(token)` takes no IP parameter anywhere in this plan, matching the spec's decision to avoid touching `get_form_kwargs`.
- **Type consistency:** `validate_turnstile(token: str) -> bool` signature is identical across Tasks 1, 3's import, and the `clean_turnstile` call site. `TurnstileWidget` is defined once in Task 2 and only imported (never redefined) in Task 3.
