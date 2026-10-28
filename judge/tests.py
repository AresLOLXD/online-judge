# judge/tests.py
import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django import forms
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from social_core.exceptions import AuthInputError

from judge.models import Language
from judge.social_auth import SocialAuthExceptionMiddleware, verify_email
from judge.timezone import TimezoneMiddleware


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


class RegistrationTurnstileDisabledTestCase(TestCase):
    # No @override_settings here: TURNSTILE_SECRET_KEY has no default in dmoj/settings.py,
    # so this exercises the opt-out state where the turnstile field must not exist.
    def setUp(self):
        Language.objects.get_or_create(key='PY3', defaults={
            'name': 'Python 3', 'common_name': 'Python', 'ace': 'python', 'pygments': 'python3',
        })

    def test_turnstile_field_absent_and_registration_succeeds_without_it(self):
        response = self.client.post(reverse('registration_register'), {
            'username': 'newplainuser',
            'email': 'newplainuser@example.com',
            'password1': 'a-very-uncommon-pw-2',
            'password2': 'a-very-uncommon-pw-2',
            'timezone': 'America/Toronto',
            'language': Language.objects.get(key='PY3').pk,
            'organizations': [],
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='newplainuser').exists())


class FooterSourceLinkTestCase(TestCase):
    def test_homepage_footer_contains_source_link(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'https://github.com/AresLOLXD/online-judge')


class VerifyEmailTestCase(SimpleTestCase):
    def test_missing_email_raises_auth_input_error(self):
        for email in (None, ''):
            with self.subTest(email=email):
                with self.assertRaises(AuthInputError):
                    verify_email(None, {'email': email})

    def test_present_email_passes(self):
        self.assertIsNone(verify_email(None, {'email': 'user@example.com'}))

    def test_middleware_redirects_with_library_message(self):
        response = SocialAuthExceptionMiddleware(lambda request: None).process_exception(
            RequestFactory().get('/'), AuthInputError(None, code='profile_email_missing'),
        )
        self.assertEqual(
            response.url,
            reverse('social_auth_error') + '?message=The%20provider%20did%20not%20supply%20an%20email%20address.',
        )


class TimezoneMiddlewareTestCase(SimpleTestCase):
    def test_form_datetime_uses_current_offset(self):
        # Under Django 5 a pytz zone makes make_aware use the historical local-mean-time offset.
        middleware = TimezoneMiddleware(lambda request: forms.DateTimeField().clean('2026-11-15 18:00:00'))
        cases = (
            (None, datetime.datetime(2026, 11, 15, 23, 0, tzinfo=datetime.timezone.utc)),
            ('America/Mexico_City', datetime.datetime(2026, 11, 16, 0, 0, tzinfo=datetime.timezone.utc)),
        )
        for tzname, expected in cases:
            with self.subTest(timezone=tzname):
                request = RequestFactory().get('/')
                request.profile = SimpleNamespace(timezone=tzname) if tzname else None
                self.assertEqual(middleware(request).astimezone(datetime.timezone.utc), expected)
