# judge/tests.py
from unittest.mock import patch

from django.contrib.auth.models import User
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
