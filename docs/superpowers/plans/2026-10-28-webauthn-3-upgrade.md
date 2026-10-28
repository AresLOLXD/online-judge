# WebAuthn 3.x Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The site's security-key (WebAuthn) registration and login run on `webauthn>=3,<4` with the tests the feature never had, and a real browser with a virtual authenticator can register a key and log in with it.

**Architecture:** First pin today's TOTP, scratch-code and key-deletion behaviour with tests on the old code. Then swap the library and port the whole server side in one task (the old and new APIs cannot coexist), driven by tests that use a software authenticator written in the test module. Then port the browser JavaScript to the standard JSON shapes, and finally prove the whole path in Chromium with a DevTools virtual authenticator, using a throwaway script outside the repository.

**Tech Stack:** Django 5.2, `webauthn` 3.0.1 (`cbor2`, `cryptography` already locked; adds `pyasn1`, `pyasn1-modules`), `uv`, Django test runner on MariaDB, Node 24 with `playwright-core` driving the Chromium cached in `~/.cache/ms-playwright`.

**Spec:** `docs/superpowers/specs/2026-10-28-webauthn-3-upgrade-design.md`

## Global Constraints

- Branch `feat/webauthn-3-upgrade` (the design is already committed on it). Conventional Commits with a body, ending with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push, never open a PR, never deploy. Code, comments and commit messages in English.
- Python 3.13 and 3.14, Django 5.2, `uv` for dependencies. The trial lock with `webauthn>=3,<4` adds only `pyasn1` and `pyasn1-modules` and removes `future`; any other lock change is a defect to report.
- No database migration. `WebAuthnCredential` keeps its fields and meaning: `cred_id` is the credential id in unpadded base64url, `public_key` is the credential public key bytes (COSE) in unpadded base64url, `counter` is the sign count. `judge/utils/two_factor.py` already has `webauthn_encode` / `webauthn_decode` for this.
- The origin check keeps using `'https://' + request.get_host()` (the 3.x verifier compares it for exact equality with `clientDataJSON.origin`); the relying party id keeps coming from `settings.WEBAUTHN_RP_ID`; the `WEBAUTHN_RP_ID` 404 guard in `WebAuthnView` stays.
- Registration stays `attestation='none'` and user verification stays `discouraged` / not required. No passkeys, no discoverable credentials, no new UI, no change to TOTP behaviour.
- The session challenge is single use: removed from the session on every verification attempt (registration POST and two-factor login POST), success or failure.
- Library rule for replays (3.0.1): an assertion is rejected when its sign count is not greater than the stored one and either is non-zero; 0 followed by 0 is accepted.
- The browser code must not depend on `PublicKeyCredential.parseCreationOptionsFromJSON` or `credential.toJSON()`.
- The maintainer has no YubiKey; every check must be possible without one. Nothing is added to `pyproject.toml` for Node or Playwright, and the browser script lives outside the repository.
- **Never touch the repository's `.venv`.** Every `uv sync`, `uv run`, test run uses `UV_PROJECT_ENVIRONMENT` under `$SCRATCH` and `UV_LINK_MODE=copy`. Never create `.venv`, `static/` or `formcheckerprob/` in the repo (delete `formcheckerprob/` if a test run leaves it). Do not edit `dmoj/local_settings.py`. Stage only the files a task names.
- `$SCRATCH` is the session scratchpad directory. uv and npm may use the network only to fetch packages (`uv lock` / `uv sync`, `npm install playwright-core`). Nothing else touches the network or any remote server.
- Tests need MySQL. The controller starts the throwaway MariaDB (datadir `$SCRATCH/mysql/data`, socket `/tmp/oj-mariadb.sock`, `127.0.0.1:3306`, root/root, database `dmoj`) and `$SCRATCH/matrix_settings.py` before dispatch and stops it afterwards; implementers never start, stop or alter database services (Task 4 may create and drop its own database `dmoj_e2e`). Run tests as `PYTHONPATH=$SCRATCH DJANGO_SETTINGS_MODULE=matrix_settings UV_PROJECT_ENVIRONMENT=$SCRATCH/env313 uv run --no-sync python manage.py test judge --noinput` (and `env314` for 3.14). Baseline on this branch: 167 tests OK.
- New tests live in `judge/views/tests/test_two_factor.py` (that directory already holds view tests). Users and profiles come from `judge.models.tests.util` (`create_user`).

## Review Focus

- Registering a credential id that already exists (the same key twice, or a key another profile registered) must answer 400, not a 500 from the unique constraint (Task 2 test `test_duplicate_credential_id_is_rejected`).
- A malformed `credential` JSON on registration, or a `webauthn_response` that is not valid JSON or not an object, must be a clean 400 / form error and never a 500 (Task 2 tests `test_malformed_credential_is_a_400`, `test_malformed_webauthn_response_is_a_form_error`). Today `json.loads` and `credential['response']` are unguarded.
- A credential id that belongs to another profile must not log the user in (Task 2 `test_other_profiles_credential_is_rejected`).
- A user with both TOTP and WebAuthn enabled must still be able to log in with a TOTP code or a scratch code (Task 1 `test_totp_login_with_webauthn_enabled`, repeated unchanged after Task 2).
- Deleting the last key of a staff member who has no TOTP must keep failing with "Staff may not disable 2FA", and deleting any key must reset `is_webauthn_enabled` when none are left (Task 1 delete tests).

## Preparation (controller only, not a subagent task)

- [ ] Start the MariaDB, confirm `mariadb -uroot -proot -h127.0.0.1 -e "select 1"` works, and confirm `$SCRATCH/matrix_settings.py`, `$SCRATCH/static_root/jsi18n/en/djangojs.js` and `$SCRATCH/env313` exist (rebuild `env313` / `env314` with `uv sync --locked` from this branch if missing).

---

### Task 1: Pin the current 2FA behaviour with tests

**Files:**
- Create: `judge/views/tests/test_two_factor.py`

**Interfaces:**
- Produces for Task 2: the module `judge/views/tests/test_two_factor.py` with a base class `TwoFactorTestCase(TestCase)` whose `setUp` makes a profile with TOTP enabled (`create_user(...)`, `profile.is_totp_enabled = True`, `profile.totp_key = pyotp.random_base32(length=32)`, `profile.generate_scratch_codes()`) and logs the test client in with `client.force_login`. Task 2 adds its classes to the same module and reuses it.

- [ ] **Step 1: Write the tests (they must pass on the unchanged code).** Class `TwoFactorLoginTestCase(TwoFactorTestCase)`, posting to `reverse('login_2fa')`: `test_totp_code_logs_in` (a valid `pyotp.TOTP(key).now()` redirects and sets `session['2fa_passed']`), `test_wrong_totp_code_is_rejected` (form error `Invalid two-factor authentication token or scratch code.`, no `2fa_passed`), `test_scratch_code_works_once` (the code is removed from `profile.scratch_codes`, reusing it fails), `test_empty_submission_is_rejected` (error `Must specify either totp_token or webauthn_response.`), `test_totp_login_with_webauthn_enabled` (profile has `is_webauthn_enabled=True` and no credentials, a valid TOTP code still logs in). Class `WebAuthnDeleteTestCase(TwoFactorTestCase)` with `@override_settings(WEBAUTHN_RP_ID='testserver')` that creates `WebAuthnCredential` rows directly with dummy values: `test_owner_can_delete_a_key`, `test_other_profiles_key_is_a_404`, `test_staff_without_totp_cannot_delete_last_key` (400, body `Staff may not disable 2FA`, using `is_staff=True` and `is_totp_enabled=False`), `test_deleting_last_key_clears_the_flag` (`is_webauthn_enabled` becomes False).

- [ ] **Step 2: Run them on the current code.**
  Run: `... manage.py test judge.views.tests.test_two_factor --noinput` (command prefix from Global Constraints).
  Expected: all pass. Any failure means the test describes behaviour the code does not have: fix the test, not the code.

- [ ] **Step 3: Run `uv run flake8` on the new file and commit** `judge/views/tests/test_two_factor.py` as `test(two-factor): pin the TOTP, scratch-code and key-deletion behaviour`.

---

### Task 2: Port the server side to webauthn 3.x

**Files:**
- Modify: `pyproject.toml` (`"webauthn<1"` -> `"webauthn>=3,<4"`), `uv.lock` (regenerated by `uv lock`, never hand-edited), `judge/utils/two_factor.py`, `judge/models/profile.py`, `judge/views/two_factor.py`, `judge/forms.py`
- Test: `judge/views/tests/test_two_factor.py`

**Interfaces:**
- Consumes (Task 1): `TwoFactorTestCase` and the existing test classes, which must keep passing unchanged.
- Produces for Tasks 3 and 4:
  - `GET reverse('webauthn_attest')` answers `application/json` with the library's creation options in WebAuthn JSON form (`challenge`, `user.id`, `excludeCredentials[].id` are base64url strings) and stores `session['webauthn_attest'] = webauthn_encode(challenge)`.
  - `POST reverse('webauthn_attest')` takes `name` and `credential` (a JSON string holding a standard `RegistrationCredential`: `id`, `rawId`, `type`, `response.clientDataJSON`, `response.attestationObject`, optional `response.transports`, `clientExtensionResults`, all binary values base64url) and answers `OK` or a 400.
  - `GET reverse('webauthn_assert')` answers the library's request options (`challenge`, `allowCredentials[].id` base64url) and stores `session['webauthn_assert']`.
  - The `webauthn_response` field of the `login_2fa` form carries a standard `AuthenticationCredential` JSON (`id`, `rawId`, `type`, `response.clientDataJSON`, `response.authenticatorData`, `response.signature`, `response.userHandle`, all base64url).
  - `judge/utils/two_factor.py` keeps only `webauthn_encode` and `webauthn_decode`.
- Test helper produced inside the test module: `class SoftwareAuthenticator` with `credential_id: bytes`, `sign_count: int`, `create(options: dict, origin: str) -> dict` returning a `RegistrationCredential` dict, and `get(options: dict, origin: str, *, count: bool = True) -> dict` returning an `AuthenticationCredential` dict whose sign count is incremented each call (`count=False` keeps it at 0). It uses an EC P-256 key (alg -7), `none` attestation, and builds `clientDataJSON` from the `challenge` in the options it is handed and the `origin` it is given.

- [ ] **Step 1: Write the failing tests** in the same module, with `@override_settings(WEBAUTHN_RP_ID='testserver')` and origin `'https://testserver'`. Registration (`WebAuthnRegistrationTestCase`): `test_options_shape` (`rp.id == 'testserver'`, `attestation == 'none'`, `authenticatorSelection.userVerification == 'discouraged'`, `excludeCredentials` lists the user's stored ids, session holds the challenge), `test_round_trip` (create + POST -> 200 `OK`, one `WebAuthnCredential` with `cred_id == webauthn_encode(credential_id)` and `counter == 0`, `is_webauthn_enabled` True, challenge gone from the session), and one test per failure, each expecting status 400 and no new row: `test_wrong_origin`, `test_wrong_challenge` (request the options twice and answer the first, whose challenge is no longer the session's), `test_challenge_is_single_use` (second POST of the same credential), `test_no_session_challenge`, `test_malformed_credential_is_a_400` (invalid JSON and a JSON object without `response`), `test_oversized_credential`, `test_name_too_long`, `test_duplicate_credential_id_is_rejected`. Login (`WebAuthnLoginTestCase`): `test_options_only_list_own_credentials`, `test_round_trip` (POST `login_2fa` -> redirect, `session['2fa_passed']`, stored `counter == authenticator.sign_count`, challenge gone), `test_response_is_single_use` (the same response posted twice: second is a form error), and form errors for `test_wrong_origin`, `test_wrong_challenge` (same two-requests trick), `test_other_profiles_credential_is_rejected`, `test_unknown_credential_id`, `test_no_session_challenge` (`No WebAuthn challenge issued.`), `test_oversized_response`, `test_malformed_webauthn_response_is_a_form_error` (invalid JSON, and valid JSON that is not an object), `test_non_increasing_sign_count_is_rejected` (stored counter 5, authenticator at 3), plus `test_zero_counter_is_accepted` (`get(..., count=False)` against stored 0). Every failure test asserts the user is not marked `2fa_passed`.

- [ ] **Step 2: Run them to confirm they fail** on the current code and old library.
  Run: `... manage.py test judge.views.tests.test_two_factor --noinput`
  Expected: the new classes FAIL or ERROR (old response shapes); Task 1's classes still pass.

- [ ] **Step 3: Switch the dependency.** Edit `pyproject.toml`, run `uv lock`, check the lock diff against Global Constraints (only `webauthn` updated, `pyasn1` and `pyasn1-modules` added, `future` removed), then `uv sync --locked --python 3.13` into `$SCRATCH/env313`.

- [ ] **Step 4: Port the code.** Behaviours to implement, in the files named above:
  - `judge/views/two_factor.py` `WebAuthnAttestationView.get`: `generate_registration_options(rp_id=settings.WEBAUTHN_RP_ID, rp_name=settings.SITE_NAME, user_id=request.profile.webauthn_id, user_name=request.user.username, user_display_name=request.user.username, attestation=none, authenticator_selection=AuthenticatorSelectionCriteria(user_verification=DISCOURAGED), exclude_credentials=<descriptors of the profile's stored ids>)`, answer `HttpResponse(options_to_json(options), content_type='application/json')`.
  - `WebAuthnAttestationView.post`: pop `webauthn_attest` from the session first; keep the existing 400s for missing challenge, `credential` over 65536 characters, and `name` over 100; parse the JSON defensively (invalid JSON or a non-object is a 400); verify with `verify_registration_response(credential=<parsed dict>, expected_challenge=webauthn_decode(stored), expected_rp_id=settings.WEBAUTHN_RP_ID, expected_origin='https://' + request.get_host())`; any verifier exception is a 400 with its message; store the row with `cred_id=webauthn_encode(verified.credential_id)`, `public_key=webauthn_encode(verified.credential_public_key)`, `counter=verified.sign_count`; an `IntegrityError` on the unique `cred_id` is a 400 (do not leave the transaction broken).
  - `WebAuthnAttestView.get`: `generate_authentication_options(rp_id=..., allow_credentials=<descriptors of the profile's stored ids>, user_verification=DISCOURAGED)`, same response style, session key `webauthn_assert`.
  - `TwoFactorLoginView.get_form_kwargs`: on POST take the challenge with `session.pop('webauthn_assert', None)`, otherwise `session.get`.
  - `TwoFactorLoginForm.clean` WebAuthn branch: keep the length check, the missing-challenge error and the lookup by `cred_id` scoped to `self.profile`; parse `webauthn_response` defensively (not valid JSON or not an object -> `ValidationError`); call `verify_authentication_response(credential=<dict>, expected_challenge=webauthn_decode(self.webauthn_challenge), expected_rp_id=settings.WEBAUTHN_RP_ID, expected_origin=self.webauthn_origin, credential_public_key=webauthn_decode(credential.public_key), credential_current_sign_count=credential.counter, require_user_verification=False)`; verifier exceptions become `ValidationError(str(e))`; save `verified.new_sign_count`. The TOTP / scratch-code branches stay untouched.
  - Remove `WebAuthnCredential.webauthn_user` and the imports it alone used in `judge/models/profile.py` (`import webauthn`, `webauthn_decode`); remove `WebAuthnJSONEncoder` and its now-unused import in `judge/utils/two_factor.py`; drop the `gravatar` import in `judge/views/two_factor.py` if nothing else uses it.

- [ ] **Step 5: Run the module, then the whole suite.**
  Run: `... manage.py test judge.views.tests.test_two_factor --noinput` -> all pass; then the full command from Global Constraints on `env313` and on `env314` (rebuild it from the new lock) -> `OK` on both, with the 167 baseline tests plus the new ones.

- [ ] **Step 6: Check and commit.** `$SCRATCH/env313/bin/flake8` clean; `manage.py check` clean; `uv lock --check` passes; `makemigrations --check --dry-run` shows only the known pending `judge/migrations/0154_alter_contest_private_contestants_and_more.py`. Commit `pyproject.toml uv.lock judge/utils/two_factor.py judge/models/profile.py judge/views/two_factor.py judge/forms.py judge/views/tests/test_two_factor.py` as `feat(two-factor): upgrade WebAuthn to webauthn 3.x with single-use challenges`, body explaining the abandoned 0.4.7, the removed `webauthn_user` and Gravatar icon, and the single-use challenge.

---

### Task 3: Port the browser JavaScript

**Files:**
- Modify: `templates/user/webauthn-helpers.js`, `templates/user/edit-profile.html` (the `#new-webauthn` handler), `templates/registration/two_factor_auth.html` (the `#use-webauthn` handler)
- Test: `judge/views/tests/test_two_factor.py`

**Interfaces:**
- Consumes (Task 2): the JSON shapes in its Interfaces block.
- Produces for Task 4: in `webauthn-helpers.js`, `decodePublicKeyOptions(publicKey)` (mutates in place: `challenge`, `user.id` and every `id` in `excludeCredentials` / `allowCredentials` become `Uint8Array`s via the existing `urlSafeBase64Decode`), `registrationCredentialToJSON(credential)` and `authenticationCredentialToJSON(credential)` returning the standard shapes from Task 2 with every binary value through `urlSafeBase64Encode` (the signature is base64url now, not hex). `decodeJSONBytes` and the `buf2hex` function in `two_factor_auth.html` are removed.

- [ ] **Step 1: Write the failing render tests** in `test_two_factor.py` (class `WebAuthnPagesTestCase`, with `@override_settings(WEBAUTHN_RP_ID='testserver')`): `test_edit_profile_page_uses_the_new_helpers` (GET `reverse('user_edit_profile')` is 200 and its body contains `registrationCredentialToJSON` and not `decodeJSONBytes`) and `test_two_factor_page_uses_the_new_helpers` (profile with `is_webauthn_enabled=True` and `2fa_passed` unset; GET `reverse('login_2fa')` is 200, contains `authenticationCredentialToJSON`, `use-webauthn`, and not `buf2hex`). Run them: expected FAIL.

- [ ] **Step 2: Implement the helper functions and rewire the two handlers** to call `decodePublicKeyOptions(publicKey)` before `navigator.credentials.create` / `.get`, to send `JSON.stringify(registrationCredentialToJSON(credential))` as `credential` (with `name` as today) and `JSON.stringify(authenticationCredentialToJSON(credential))` into `#id_webauthn_response`. Keep the rest of both handlers (feature check, `$.getJSON`, error alerts) as they are.

- [ ] **Step 3: Verify.**
  Run: `node --check templates/user/webauthn-helpers.js` (exit 0), the two render tests (PASS), then the full suite on `env313` (`OK`) and `flake8`.

- [ ] **Step 4: Commit** the three templates and the test file as `refactor(two-factor): send standard WebAuthn JSON from the browser`.

---

### Task 4: End-to-end check in Chromium with a virtual authenticator (no repository changes)

**Files:** none in the repository. Everything lives under `$SCRATCH/e2e/` (script, settings module, certificate, notes).

**Interfaces:**
- Consumes (Tasks 2 and 3): the committed branch. Produces: a written report only.

- [ ] **Step 1: Build the harness under `$SCRATCH/e2e/`.** A settings module importing `matrix_settings` with `WEBAUTHN_RP_ID = 'localhost'`, `ALLOWED_HOSTS` and CSRF trusted origins for `https://localhost:<port>`; a database `dmoj_e2e` created and migrated with `env313` (then dropped at the end); a local HTTPS server for the Django WSGI app with a self-signed certificate (how it is started is the builder's choice); `npm install playwright-core` in that directory; a Node script launching the cached Chromium (`~/.cache/ms-playwright/chromium-1248/...`, find the executable) with `--ignore-certificate-errors`, opening a CDP session and calling `WebAuthn.enable` and `WebAuthn.addVirtualAuthenticator` with `protocol: 'ctap2'`, `transport: 'usb'`, `hasResidentKey: false`, `hasUserVerification: false`, `automaticPresenceSimulation: true`.

- [ ] **Step 2: Run the scenario** with two users created through `manage.py shell` (one ordinary, one `is_staff` without TOTP) and report, per line, PASS or FAIL with the evidence: (1) the ordinary user logs in with the password, opens the profile edit page, adds a key named `test key`, the page reloads and lists it; (2) the user logs out, logs in again, is sent to `/2fa/`, clicks "Use security key" and lands on the user page; (3) posting the same `webauthn_response` a second time (page-side `fetch`) is refused; (4) the ordinary user deletes the key and `is_webauthn_enabled` is cleared; (5) the staff user registers a key and then cannot delete it (the alert text is `Staff may not disable 2FA`); (6) the browser console shows no JavaScript errors during steps 1-5.

- [ ] **Step 3: Clean up and report.** Drop `dmoj_e2e`, stop the HTTPS server, and delete `formcheckerprob/` if present. Write the report with the table above, the exact Chromium path and `playwright-core` version, and anything that could not be shown. Do not commit anything.

---

## Final verification (controller)

On `feat/webauthn-3-upgrade`: full suite on `env313` and `env314`, `flake8`, `manage.py check`, `uv lock --check`, `makemigrations --check --dry-run` (only the known `0154`), and `git status` clean apart from the untracked files that were there before. Then the whole-branch review and `superpowers:finishing-a-development-branch`.

## Follow-ups (controller, outside the branch)

- File an issue in `AresLOLXD/dmoj-docker` (authorized by the maintainer for needed dmoj-docker changes) asking to set `WEBAUTHN_RP_ID = '<site domain>'` in `local_settings.py`, noting that WebAuthn answers 404 until then and that the site must be served over HTTPS.
- Update the memory note `pending-update-dependencies` when the branch is merged.
