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
            timeout=5.0,
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

    @patch('judge.utils.turnstile.requests.post')
    def test_malformed_json_response_fails_closed(self, mock_post):
        mock_post.return_value = Mock(json=Mock(side_effect=ValueError('bad json')))
        self.assertFalse(validate_turnstile('any-token'))
