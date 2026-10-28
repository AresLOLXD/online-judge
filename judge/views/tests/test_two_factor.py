import json

import pyotp
from django.test import TestCase, override_settings
from django.urls import reverse

from judge.models import WebAuthnCredential
from judge.models.tests.util import create_user
from judge.views.tests.test_problem_data_view import renders_pages


class TwoFactorTestCase(TestCase):
    def setUp(self):
        self.profile = create_user(username='tfa_user').profile
        self.profile.is_totp_enabled = True
        self.profile.totp_key = pyotp.random_base32(length=32)
        self.profile.save(update_fields=['is_totp_enabled', 'totp_key'])
        self.profile.generate_scratch_codes()
        self.client.force_login(self.profile.user)

    def pass_2fa(self):
        session = self.client.session
        session['2fa_passed'] = True
        session.save()


@renders_pages
class TwoFactorLoginTestCase(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('login_2fa')

    def test_totp_code_logs_in(self):
        response = self.client.post(self.url, {'totp_or_scratch_code': pyotp.TOTP(self.profile.totp_key).now()})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session['2fa_passed'])

    def test_wrong_totp_code_is_rejected(self):
        response = self.client.post(self.url, {'totp_or_scratch_code': '000000'})
        self.assertContains(response, 'Invalid two-factor authentication token or scratch code.')
        self.assertNotIn('2fa_passed', self.client.session)

    def test_scratch_code_works_once(self):
        code = json.loads(self.profile.scratch_codes)[0]
        response = self.client.post(self.url, {'totp_or_scratch_code': code})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session['2fa_passed'])
        self.profile.refresh_from_db()
        self.assertNotIn(code, json.loads(self.profile.scratch_codes))

        session = self.client.session
        del session['2fa_passed']
        session.save()
        response = self.client.post(self.url, {'totp_or_scratch_code': code})
        self.assertContains(response, 'Invalid two-factor authentication token or scratch code.')
        self.assertNotIn('2fa_passed', self.client.session)

    def test_empty_submission_is_rejected(self):
        response = self.client.post(self.url, {})
        self.assertContains(response, 'Must specify either totp_token or webauthn_response.')
        self.assertNotIn('2fa_passed', self.client.session)

    def test_totp_login_with_webauthn_enabled(self):
        self.profile.is_webauthn_enabled = True
        self.profile.save(update_fields=['is_webauthn_enabled'])
        response = self.client.post(self.url, {'totp_or_scratch_code': pyotp.TOTP(self.profile.totp_key).now()})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session['2fa_passed'])


@override_settings(WEBAUTHN_RP_ID='testserver')
class WebAuthnDeleteTestCase(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.pass_2fa()
        self.profile.is_webauthn_enabled = True
        self.profile.save(update_fields=['is_webauthn_enabled'])

    def create_credential(self, profile, cred_id):
        return WebAuthnCredential.objects.create(user=profile, name=cred_id, cred_id=cred_id,
                                                 public_key='dummy', counter=0)

    def test_owner_can_delete_a_key(self):
        keep = self.create_credential(self.profile, 'keep')
        gone = self.create_credential(self.profile, 'gone')
        response = self.client.post(reverse('webauthn_delete', args=[gone.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.profile.webauthn_credentials.all()), [keep])

    def test_other_profiles_key_is_a_404(self):
        other = self.create_credential(create_user(username='other').profile, 'other')
        response = self.client.post(reverse('webauthn_delete', args=[other.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(WebAuthnCredential.objects.filter(pk=other.pk).exists())

    def test_staff_without_totp_cannot_delete_last_key(self):
        self.profile.user.is_staff = True
        self.profile.user.save(update_fields=['is_staff'])
        self.profile.is_totp_enabled = False
        self.profile.save(update_fields=['is_totp_enabled'])
        last = self.create_credential(self.profile, 'last')
        response = self.client.post(reverse('webauthn_delete', args=[last.pk]))
        self.assertContains(response, 'Staff may not disable 2FA', status_code=400)
        self.assertTrue(WebAuthnCredential.objects.filter(pk=last.pk).exists())

    def test_deleting_last_key_clears_the_flag(self):
        last = self.create_credential(self.profile, 'last')
        self.client.post(reverse('webauthn_delete', args=[last.pk]))
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_webauthn_enabled)
