import hashlib
import json
import os
import struct

import cbor2
import pyotp
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.test import TestCase, override_settings
from django.urls import reverse

from judge.models import WebAuthnCredential
from judge.models.tests.util import create_user
from judge.utils.two_factor import webauthn_decode, webauthn_encode
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


ORIGIN = 'https://testserver'


class SoftwareAuthenticator:
    """A minimal EC P-256 authenticator with `none` attestation, so tests can answer real WebAuthn ceremonies."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.sign_count = 0
        numbers = self.key.public_key().public_numbers()
        self.public_key = cbor2.dumps({
            1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big'),
        })

    def client_data(self, ceremony, options, origin):
        return json.dumps({
            'type': f'webauthn.{ceremony}', 'challenge': options['challenge'], 'origin': origin, 'crossOrigin': False,
        }).encode()

    def authenticator_data(self, rp_id, flags, attested=b''):
        return hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack('>I', self.sign_count) + attested

    def create(self, options, origin):
        attested = (bytes(16) + struct.pack('>H', len(self.credential_id)) + self.credential_id + self.public_key)
        attestation_object = cbor2.dumps({
            'fmt': 'none', 'attStmt': {}, 'authData': self.authenticator_data(options['rp']['id'], 0x41, attested),
        })
        return {
            'id': webauthn_encode(self.credential_id),
            'rawId': webauthn_encode(self.credential_id),
            'type': 'public-key',
            'response': {
                'clientDataJSON': webauthn_encode(self.client_data('create', options, origin)),
                'attestationObject': webauthn_encode(attestation_object),
            },
            'clientExtensionResults': {},
        }

    def get(self, options, origin, *, count=True):
        if count:
            self.sign_count += 1
        client_data = self.client_data('get', options, origin)
        authenticator_data = self.authenticator_data(options['rpId'], 0x01)
        signature = self.key.sign(authenticator_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            'id': webauthn_encode(self.credential_id),
            'rawId': webauthn_encode(self.credential_id),
            'type': 'public-key',
            'response': {
                'clientDataJSON': webauthn_encode(client_data),
                'authenticatorData': webauthn_encode(authenticator_data),
                'signature': webauthn_encode(signature),
                'userHandle': None,
            },
            'clientExtensionResults': {},
        }


@override_settings(WEBAUTHN_RP_ID='testserver')
class WebAuthnRegistrationTestCase(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.pass_2fa()
        self.url = reverse('webauthn_attest')
        self.authenticator = SoftwareAuthenticator()

    def get_options(self):
        response = self.client.get(self.url)
        self.assertEqual(response['Content-Type'], 'application/json')
        return json.loads(response.content)

    def register(self, credential, name='key'):
        return self.client.post(self.url, {'name': name, 'credential': json.dumps(credential)})

    def assert_rejected(self, response, message=None):
        self.assertEqual(response.status_code, 400)
        if message:
            self.assertContains(response, message, status_code=400)
        self.assertFalse(WebAuthnCredential.objects.exists())
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_webauthn_enabled)

    def test_options_shape(self):
        stored = WebAuthnCredential.objects.create(user=self.profile, name='old', cred_id=webauthn_encode(b'old-id'),
                                                   public_key='dummy', counter=0)
        options = self.get_options()
        self.assertEqual(options['rp']['id'], 'testserver')
        self.assertEqual(options['attestation'], 'none')
        self.assertEqual(options['authenticatorSelection']['userVerification'], 'discouraged')
        self.assertEqual(options['user']['id'], webauthn_encode(self.profile.webauthn_id))
        self.assertEqual([item['id'] for item in options['excludeCredentials']], [stored.cred_id])
        self.assertEqual(self.client.session['webauthn_attest'], options['challenge'])

    def test_round_trip(self):
        response = self.register(self.authenticator.create(self.get_options(), ORIGIN))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'OK')
        credential = WebAuthnCredential.objects.get()
        self.assertEqual(credential.cred_id, webauthn_encode(self.authenticator.credential_id))
        self.assertEqual(webauthn_decode(credential.public_key), self.authenticator.public_key)
        self.assertEqual(credential.counter, 0)
        self.assertEqual(credential.user, self.profile)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_webauthn_enabled)
        self.assertNotIn('webauthn_attest', self.client.session)

    def test_wrong_origin(self):
        response = self.register(self.authenticator.create(self.get_options(), 'https://evil.example'))
        self.assert_rejected(response, 'Unexpected client data origin')

    def test_wrong_challenge(self):
        stale = self.get_options()
        self.get_options()
        self.assert_rejected(self.register(self.authenticator.create(stale, ORIGIN)),
                             'Client data challenge was not expected challenge')

    def test_challenge_is_single_use(self):
        credential = self.authenticator.create(self.get_options(), ORIGIN)
        self.assertEqual(self.register(credential).status_code, 200)
        WebAuthnCredential.objects.all().delete()
        self.assert_rejected(self.register(credential))

    def test_no_session_challenge(self):
        options = self.get_options()
        session = self.client.session
        del session['webauthn_attest']
        session.save()
        self.assert_rejected(self.register(self.authenticator.create(options, ORIGIN)))

    def test_malformed_credential_is_a_400(self):
        for body in ('{not json', '[]', '"text"', '{"id": "x"}'):
            with self.subTest(body=body):
                self.get_options()
                response = self.client.post(self.url, {'name': 'key', 'credential': body})
                self.assert_rejected(response)

    def test_oversized_credential(self):
        self.get_options()
        self.assert_rejected(self.client.post(self.url, {'name': 'key', 'credential': 'a' * 65537}))

    def test_name_too_long(self):
        credential = self.authenticator.create(self.get_options(), ORIGIN)
        self.assert_rejected(self.register(credential, name='n' * 101))

    def test_duplicate_credential_id_is_rejected(self):
        self.assertEqual(self.register(self.authenticator.create(self.get_options(), ORIGIN)).status_code, 200)
        response = self.register(self.authenticator.create(self.get_options(), ORIGIN), name='again')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WebAuthnCredential.objects.count(), 1)
        # The failed insert must not leave the request's transaction unusable.
        self.assertEqual(self.get_options()['rp']['id'], 'testserver')


@override_settings(WEBAUTHN_RP_ID='testserver')
class WebAuthnLoginTestCase(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.profile.is_webauthn_enabled = True
        self.profile.save(update_fields=['is_webauthn_enabled'])
        self.url = reverse('login_2fa')
        self.authenticator = SoftwareAuthenticator()
        self.credential = self.store(self.profile, self.authenticator)

    def store(self, profile, authenticator, counter=0):
        return WebAuthnCredential.objects.create(
            user=profile, name='key', cred_id=webauthn_encode(authenticator.credential_id),
            public_key=webauthn_encode(authenticator.public_key), counter=counter,
        )

    def get_options(self):
        response = self.client.get(reverse('webauthn_assert'))
        self.assertEqual(response['Content-Type'], 'application/json')
        return json.loads(response.content)

    def login(self, response_text):
        return self.client.post(self.url, {'webauthn_response': response_text})

    def assert_rejected(self, response, message):
        self.assertContains(response, message)
        self.assertNotIn('2fa_passed', self.client.session)

    def test_options_only_list_own_credentials(self):
        self.store(create_user(username='other').profile, SoftwareAuthenticator())
        options = self.get_options()
        self.assertEqual(options['rpId'], 'testserver')
        self.assertEqual(options['userVerification'], 'discouraged')
        self.assertEqual([item['id'] for item in options['allowCredentials']], [self.credential.cred_id])
        self.assertEqual(self.client.session['webauthn_assert'], options['challenge'])

    def test_round_trip(self):
        response = self.login(json.dumps(self.authenticator.get(self.get_options(), ORIGIN)))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session['2fa_passed'])
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.counter, self.authenticator.sign_count)
        self.assertNotIn('webauthn_assert', self.client.session)

    def test_response_is_single_use(self):
        answer = json.dumps(self.authenticator.get(self.get_options(), ORIGIN))
        self.assertEqual(self.login(answer).status_code, 302)
        session = self.client.session
        del session['2fa_passed']
        session.save()
        self.assert_rejected(self.login(answer), 'No WebAuthn challenge issued.')

    def test_wrong_origin(self):
        answer = self.authenticator.get(self.get_options(), 'https://evil.example')
        self.assert_rejected(self.login(json.dumps(answer)), 'Unexpected client data origin')

    def test_wrong_challenge(self):
        stale = self.get_options()
        self.get_options()
        answer = self.authenticator.get(stale, ORIGIN)
        self.assert_rejected(self.login(json.dumps(answer)), 'Client data challenge was not expected challenge')

    def test_other_profiles_credential_is_rejected(self):
        intruder = SoftwareAuthenticator()
        self.store(create_user(username='other').profile, intruder)
        answer = intruder.get(self.get_options(), ORIGIN)
        self.assert_rejected(self.login(json.dumps(answer)), 'Invalid WebAuthn credential ID.')

    def test_unknown_credential_id(self):
        answer = SoftwareAuthenticator().get(self.get_options(), ORIGIN)
        self.assert_rejected(self.login(json.dumps(answer)), 'Invalid WebAuthn credential ID.')

    def test_no_session_challenge(self):
        answer = self.authenticator.get({'challenge': webauthn_encode(os.urandom(32)), 'rpId': 'testserver'}, ORIGIN)
        self.assert_rejected(self.login(json.dumps(answer)), 'No WebAuthn challenge issued.')

    def test_oversized_response(self):
        self.get_options()
        self.assert_rejected(self.login('a' * 65537), 'Invalid WebAuthn response.')

    def test_malformed_webauthn_response_is_a_form_error(self):
        for body in ('{not json', '[]', '"text"'):
            with self.subTest(body=body):
                self.get_options()
                self.assert_rejected(self.login(body), 'Invalid WebAuthn response.')

    def test_non_increasing_sign_count_is_rejected(self):
        self.credential.counter = 5
        self.credential.save(update_fields=['counter'])
        self.authenticator.sign_count = 2
        answer = self.authenticator.get(self.get_options(), ORIGIN)
        self.assert_rejected(self.login(json.dumps(answer)), 'was not greater than current count')
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.counter, 5)

    def test_zero_counter_is_accepted(self):
        answer = self.authenticator.get(self.get_options(), ORIGIN, count=False)
        self.assertEqual(self.login(json.dumps(answer)).status_code, 302)
        self.assertTrue(self.client.session['2fa_passed'])
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.counter, 0)


@override_settings(WEBAUTHN_RP_ID='testserver')
class WebAuthnPagesTestCase(TwoFactorTestCase):
    def test_edit_profile_page_uses_the_new_helpers(self):
        self.pass_2fa()
        response = self.client.get(reverse('user_edit_profile'))
        self.assertContains(response, 'registrationCredentialToJSON')
        self.assertNotContains(response, 'decodeJSONBytes')

    def test_two_factor_page_uses_the_new_helpers(self):
        self.profile.is_webauthn_enabled = True
        self.profile.save(update_fields=['is_webauthn_enabled'])
        response = self.client.get(reverse('login_2fa'))
        self.assertContains(response, 'authenticationCredentialToJSON')
        self.assertContains(response, 'use-webauthn')
        self.assertNotContains(response, 'buf2hex')
