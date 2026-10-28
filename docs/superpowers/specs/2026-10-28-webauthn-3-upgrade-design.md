# WebAuthn 3.x upgrade design

## Intent and why

Staff want to log in with YubiKeys (WebAuthn security keys). The site's WebAuthn code is built on the
`webauthn<1` package (0.4.7, abandoned) and has never had a single test. Today the feature is also switched
off in production: `WEBAUTHN_RP_ID` defaults to `None` in `dmoj/settings.py` and every WebAuthn view returns
404 when it is unset, and the production `local_settings.py` does not set it. Measured on production
(2026-10-28): 0 rows in `judge_webauthncredential`, 0 profiles with WebAuthn, 1 profile with TOTP. So there
are no stored credentials to keep compatible, and the TOTP login, which the only 2FA user depends on, shares
its form and views with WebAuthn.

This project moves the code to `webauthn>=3,<4` (3.0.1 at the time of writing) and adds the missing tests, so
that the maintainer can later turn WebAuthn on and enrol YubiKeys on a maintained library.

## Goals

- The user-visible flows stay as they are: a user registers a key from the profile edit page, lists and
  deletes keys there, and logs in with a key as an alternative to a TOTP or scratch code. The staff rules
  stay as they are (`DMOJ_REQUIRE_STAFF_2FA`, "Staff may not disable 2FA").
- The server side uses the 3.x functions `generate_registration_options`, `verify_registration_response`,
  `generate_authentication_options` and `verify_authentication_response`.
- New tests cover, before any library change: the TOTP login path, the scratch-code path and the
  "Must specify either totp_token or webauthn_response" path of `TwoFactorLoginForm`. After the change they
  also cover a full WebAuthn registration and login round trip made with a software authenticator written in
  the test code, plus the failure cases below.
- `uv.lock` is regenerated and the suite passes on Python 3.13 and 3.14.

## Non-goals and anti-goals

Non-goals:
- Passkeys, discoverable credentials, or logging in without a username.
- Attestation verification: registration stays `attestation='none'`.
- Requiring user verification: it stays `discouraged`/not required, as today.
- Any new UI, or changes to TOTP behaviour.
- Turning WebAuthn on in production: setting `WEBAUTHN_RP_ID` is a change in the `dmoj-docker` repository.
- Removing the `WEBAUTHN_RP_ID` 404 guard, Django 6, and the `mistune` upgrade (a separate project).

Anti-goals (a failure even if the new tests pass):
- Any change that stops a TOTP or scratch-code login from working.
- A WebAuthn login that succeeds with a wrong challenge, a wrong origin, another user's credential, a
  challenge that was already used, or a replayed assertion. For replays the library's rule applies: an
  assertion is rejected when its sign count is not greater than the stored one and either of them is
  non-zero (checked in the 3.0.1 source). A count of 0 followed by 0 is accepted, as authenticators that do
  not count (many platform authenticators) require; YubiKeys do increment.

## Constraints

- The maintainer has no YubiKey; every check must be possible without one.
- Python 3.13 and 3.14, Django 5.2, `uv` for dependencies. The trial lock with `webauthn>=3,<4` adds only
  `pyasn1` and `pyasn1-modules` and removes `future`; `cryptography`, `cbor2` and `pyOpenSSL` are already
  locked and satisfy the new requirements.
- No database migration. `WebAuthnCredential` keeps its fields and meaning: `cred_id` is the credential id
  in unpadded base64url, `public_key` is the credential public key bytes (COSE) in unpadded base64url, and
  `counter` is the sign count. These helpers already exist in `judge/utils/two_factor.py`.
- The origin check keeps using `'https://' + request.get_host()` (the 3.x verifier compares it for exact
  equality with the browser's `clientDataJSON.origin`), and the relying party id keeps coming from
  `settings.WEBAUTHN_RP_ID`. Consequence: a plain `http://localhost:8000` development server cannot complete
  a WebAuthn login or registration; a real-key run needs HTTPS (production, or an HTTPS reverse proxy in
  front of a dev server).
- The browser code must keep working in every browser that supports WebAuthn, so it must not depend on
  `PublicKeyCredential.parseCreationOptionsFromJSON` or `credential.toJSON()` being present.
- Code, comments and commit messages in English; `uv run flake8` clean; tests run with
  `uv run python manage.py test judge`.

## Decisions

Decided by the maintainer:
- Keep WebAuthn and upgrade it to the current major version, because staff want to use YubiKeys.

My calls (the maintainer can reverse them):
- The server sends the options as the JSON produced by the library (`options_to_json`) and the JavaScript
  turns the base64url fields into `ArrayBuffer`s itself; the client posts the standard `RegistrationCredential`
  / `AuthenticationCredential` JSON shape that the 3.x verifiers accept.
- The Gravatar `icon` of the user in the registration options is dropped, because the 3.x API has no such
  field and browsers and authenticators do not show it.
- `WebAuthnCredential.webauthn_user` (an old-library object) is removed; the verifiers take the stored
  public key and sign count directly.
- The session challenge is single use: it is removed from the session on every verification attempt, in the
  registration POST and in the two-factor login POST, whether the attempt succeeds or fails. A failed attempt
  therefore needs a new challenge, which the pages already request on every click of "Add" and "Use security
  key". Tests cover "a second post with the same challenge fails" and "no challenge in the session fails".
- The unit tests build a minimal software authenticator (EC P-256 key, `none` attestation, `cbor2`,
  `cryptography`) instead of using a browser, so the suite stays fast and needs no hardware.
- The browser-level check is a throwaway script, not a committed test, so that the project gets no Node or
  Playwright dependency. Its result is reported in the task that runs it.

## What is left to the builder

- The exact shape of the JSON helpers in the templates, the names of the new test classes, and whether the
  software authenticator lives in a test helper module or inside `judge/tests.py`.
- Failure cases to cover at least: wrong challenge, wrong origin, unknown credential id, a credential that
  belongs to another profile, a sign count that does not increase, an oversized response, and a missing
  session challenge.
- The maintainer has no physical YubiKey, so nothing in this project depends on one (see "How this will be
  verified"). The details of the throwaway browser script (file layout, how the local HTTPS server is
  started, how the cached Chromium is launched) are left to the builder.

## Deployment prerequisites (outside this repository)

- `WEBAUTHN_RP_ID = '<site domain>'` in the `dmoj-docker` `local_settings.py` (tracked in an issue there).
  WebAuthn also needs the site to be served over HTTPS, which production already does.
- Not part of the acceptance of this project: the first real YubiKey enrolment on the production site, which
  whoever on the staff owns a key does later. The protocol-level behaviour is already covered by the virtual
  authenticator run; TOTP keeps working whatever happens with a key.

## How this will be verified

1. Characterization tests for the TOTP and scratch-code paths pass on the old code and again after the swap.
2. The round-trip and failure-case tests pass on the new code.
3. Suite and flake8 on Python 3.13 and 3.14; `manage.py check`; `makemigrations --check` reports only the
   known pending `0154` drift and nothing new.
4. An end-to-end run in a real browser with a **virtual authenticator** instead of a physical key: Chromium's
   DevTools `WebAuthn` domain emulates a CTAP2 security key over USB (with a sign counter that increments, no
   resident keys, no user verification), so the run registers a key from the profile edit page and then logs
   in with it, through the project's real templates and JavaScript. It is a throwaway script kept **outside
   the repository** (Node with `playwright-core` driving the Chromium that is already cached in
   `~/.cache/ms-playwright`; nothing is added to `pyproject.toml` or the repo) against the Django pages served
   over HTTPS locally with a self-signed certificate, `WEBAUTHN_RP_ID = 'localhost'` and the origin
   `https://localhost:<port>`. It must show: registration succeeds and the key is listed; login with the key
   succeeds; a second login that reuses the same challenge fails; deleting the key follows the staff rules.
   What it cannot show is behaviour specific to Yubico hardware; that is the deferred real enrolment above.
