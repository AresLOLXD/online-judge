import logging

import requests
from django.conf import settings
from django.forms import Widget
from django.utils.html import format_html

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
    try:
        return bool(response.json().get('success', False))
    except ValueError:
        log.warning('Turnstile verification response was not valid JSON', exc_info=True)
        return False


class TurnstileWidget(Widget):
    class Media:
        js = ('https://challenges.cloudflare.com/turnstile/v0/api.js',)

    def render(self, name, value, attrs=None, renderer=None):
        return format_html(
            '<div class="cf-turnstile" data-sitekey="{}" data-response-field-name="{}"></div>',
            settings.TURNSTILE_SITE_KEY,
            name,
        )
