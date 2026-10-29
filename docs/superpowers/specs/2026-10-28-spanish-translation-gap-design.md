# Spanish translation gap design

## Intent and why

The maintainer's site runs with Spanish as the language and users see English in many places, for example the help box at the top of the problem data editing page. The committed catalog `locale/es/LC_MESSAGES/django.po` is 100 % translated (1454 translated, 0 fuzzy, 0 untranslated). The gap is elsewhere, and it has three causes:

1. Strings added to the code (by this fork's recent work and by upstream changes) never reached the catalog, so `gettext` returns the English original. A regeneration with `manage.py makemessages -l es -e py,html,txt` (what the project's own workflow runs) finds 98 of them: 68 empty and 30 marked fuzzy. Django ignores fuzzy entries at runtime, so they also show English, and all of the 22 that were reviewed carry a WRONG guessed translation (for example "Deactivate users" guessed as "activar", "Preview" as "Anterior", `{time}` as "tiempo").
2. Some text is English and not marked for translation at all (hard-coded in templates, JavaScript and Python), so no catalog can fix it.
3. Nothing tells the maintainer when the gap reopens. The fork's `updatemessages.yml` only runs for `DMOJ/online-judge`, so on this fork the catalog is maintained by hand.

The goal is that a Spanish user, and the Spanish-speaking maintainer working in the admin, see Spanish everywhere the application controls the text.

## Goals

- Every string in scope (below) has a normal, non-fuzzy Spanish translation in `locale/es/LC_MESSAGES/django.po`, written from scratch for the 22 fuzzy ones.
- The hard-coded English texts that a user or the maintainer can see (list below) are marked for translation and translated, in the `django` catalog, or in `djangojs.po` for JavaScript.
- A command the maintainer can run before deploying reports how many strings lack a Spanish translation, in about two seconds, without modifying the working tree.
- After the change, regenerating the catalog (the same `makemessages` command) in a scratch copy reports 0 untranslated and 0 fuzzy in both domains, `msgfmt --check --check-format` passes, and the pages named below render their text in Spanish.

## In scope (the translations)

- The 36 strings from this fork's recent work: the problem data page help and warning boxes, the zip / `init.yml` import messages, the custom checker messages, the Turnstile failure message, and "This security key is already registered". Spanish drafts already exist at `$SCRATCH/i18n_work.po` (scratchpad of the session that wrote this design); they are inputs the builder may reuse after checking them, not requirements.
- The other 62 entries (22 fuzzy + 40 empty): the Markdown editor toolbar, tabs and guide (the `martor` app, shown under every comment box, ticket and blog form), the messages "Please click on Preview before posting your comment / creating your ticket" and the source-code confirm dialog of the comment editor, "Search contests..." and "There are no past contests." on the contest list, `{time}` / `on {time}` of the date helper, the staff-only admin texts (muting and deactivating users, "Archive any submission", "Create private problems", "Archive locked submissions:", the performance ceiling labels), and the file-size unit entries.
- The rating level label "Amateur" (`judge/ratings.py`), which is shown on profiles and rankings and is the only untranslated one of its series (the others are Novato, Experto, Maestro...): translate it as "Aficionado". The catalog already has `msgid "Amateur"` with `msgstr "Amateur"` (so it counts as translated and no regeneration flags it), and a second entry would be a duplicate that `msgfmt` rejects. This is the ONE allowed exception to "appended entries only": change that single existing `msgstr` to "Aficionado". No other existing entry is edited. Other entries whose `msgstr` equals the `msgid` (cognates such as Blog, Error, Ping, and the inconsistent "Email" of the registration form) are out of scope: only the entries named in this document are fixed.

## In scope (hard-coded text that must become translatable)

Taken from the recon list `$SCRATCH/i18n_discovery/layer2_hardcoded.tsv`; the builder confirms each row by reading the code before changing it:

- The username form shown after a social login (`judge/social_auth.py`: the `Username` label and two validation messages).
- "Nothing to preview" written in `martor/static/martor/js/martor.js` (JavaScript catalog `djangojs`).
- "No TOTP key generated on server side?" in `judge/views/two_factor.py` (added by this fork).
- The `ValidationError` messages of the contest formats and the contest and profile models (`judge/contest_format/*.py`, `judge/models/contest.py`, `judge/models/profile.py`) that the maintainer sees in the admin.
- Anything else in the recon list that is high confidence AND reachable by a regular user or by the maintainer in the admin, excluding what the non-goals below name.

## Non-goals

- The optional `newsletter` app templates (about 50 strings): the app is not installed on the production site.
- The English example snippets inside the Markdown guide (`guide.html`), which are Markdown samples and not interface text.
- RSS/Atom feed titles (`judge/feed.py`), technical HTTP 400/404 response bodies, API token and middleware messages, and the static `502.html` served by nginx (it cannot use gettext).
- Other languages, the other catalogs, and the upstream Crowdin synchronisation.
- A CI check that fails the build (decided by the maintainer: the check is a command that is run by hand, because every merge from upstream DMOJ brings strings without Spanish and a blocking check would fail each time).
- Tracking `.mo` files in git (they are ignored and compiled by `compilemessages`, which the maintainer's `copy_static` script runs).

## Anti-goals (a failure even if every string is translated)

- Breaking an existing translation, changing any existing `msgid`, or reordering or reflowing the existing catalog: the diff of `django.po` must consist of appended entries only, plus the single `msgstr` line of the existing "Amateur" entry named above, so that merges from upstream stay clean.
- Any `msgstr` that changes or drops a placeholder (`%d`, `%s`, `%(name)s`, `{time}`) or breaks a plural form.
- Leaving any entry fuzzy, or wrong text that merely looks like Spanish.
- Changing the behaviour of the code that gets wrapped for translation: only the wrapping changes (no change of logic, of message identity for the cases that tests assert on, or of the language of data stored in the database such as revision comments).

## Constraints and decisions

- Decided by the maintainer: scope as above (users and staff, without newsletter); the 22 fuzzy guesses are all rewritten from scratch; prevention is a command run by hand, not CI.
- Header of the catalog: `Language: es_ES`, `nplurals=2; plural=(n != 1);`. Register and terminology follow the existing catalog: formal "usted" where addressing the user, *verificador* (checker), *caso de prueba* (test case), *envío* (submission), *rejuzgar* (rejudge), *concurso* (contest), *lote* (batch), *generador* (generator).
- New catalog entries are appended at the end of `django.po` (after the last normal entry, before any obsolete `#~` block) with their `#:` location comments and `#, python-format` flags, taken from a regenerated scratch catalog. Do not run `makemessages` on the repository's own `locale/` (it rewrites every location comment).
- File-size units such as `%s KB` are international: their entries are filled with the same text so that the catalog counts them as translated.
- The literal "Rejudged" that the rejudge help text quotes is a revision comment stored in English in the database: it stays in English inside quotes.
- Code, comments and commit messages in English; Spanish only inside `msgstr` values; Conventional Commits.
- Deployment: the maintainer's server needs `./scripts/copy_static` (which runs `compilemessages`) for the new strings to show.

## What is left to the builder

- Exact Spanish wording within the terminology above, and the choice between `gettext` and `gettext_lazy` for each wrapped Python string (lazy where the text is built at import time, such as form labels and model fields).
- The mechanism for the JavaScript string (the project already ships JavaScript catalogs through `statici18n`).
- The form of the prevention command (a small script next to `make_style.sh`, for example), provided it works on a throwaway copy so it never changes the working tree and prints the counts for both domains plus the list of missing entries.
- Where to fix existing tests, if wrapping a message changes how a test sees it.

## How this will be verified

1. `msgfmt --check --check-format -o /dev/null locale/es/LC_MESSAGES/django.po` and the same for `djangojs.po`; the diff of both catalogs shows appended entries only (plus the one "Amateur" `msgstr` line in `django.po`; a check on `git diff --numstat` or on the removed lines must accept exactly that one removed line and nothing else).
2. The prevention command, run on the final tree, reports 0 untranslated and 0 fuzzy for `django` and `djangojs`.
3. A placeholder comparison script over every new entry and every plural form.
4. Runtime proof with Django: with the compiled catalog and the language set to `es`, the new msgids resolve to Spanish (a throwaway script outside the repository), including the problem data page help text, the editor toolbar labels, the contest list texts and the social-auth username form messages.
5. The existing test suite stays green (209 tests on Django 5.2, Python 3.13 and 3.14 at the time of writing); flake8 clean.
6. A visual check of the pages in Spanish in a real browser, with network blocked and without clicking links (hover and screenshots only), for the problem data page and a comment box. It is a task of the plan (not left to the maintainer) and it is done outside the repository: a throwaway database, a scratch settings module that sets `LANGUAGE_CODE = 'es'` (the project default in `dmoj/settings.py` is `'en'`), a user with edit rights and a problem with test data created by a seed script, the existing local HTTPS harness used for the WebAuthn browser check, and Chromium launched without clicking links of any scheme.

## Where the inputs live

`$SCRATCH` in this document means the scratchpad directory of the session that wrote it: `/tmp/claude-1000/-var-home-areslolxd-Documentos-online-judge/6b1cb67e-65ce-4d10-8f6f-3a9fec626c0d/scratchpad`. It is temporary. The plan must copy the files it needs (`i18n_work.po` drafts, `i18n_discovery/layer1_django.tsv`, `layer2_hardcoded.tsv`, `scan_hardcoded.py`) into the plan's own workspace at the start, and must not assume `$SCRATCH` survives.
