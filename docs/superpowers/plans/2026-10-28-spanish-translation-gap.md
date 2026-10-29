# Spanish Translation Gap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Spanish user and the Spanish-speaking maintainer see Spanish in every interface text this project controls (about 130 strings), and a command tells the maintainer when strings are missing.

**Architecture:** First make the remaining hard-coded English strings translatable (Python wrapping, one JavaScript string). Then append the Spanish entries to the catalogs in two reviewable blocks (user-facing; staff and newly wrapped), never regenerating the repository's own catalog. Then add a command that regenerates the catalog in a throwaway worktree and reports what is missing. Finally prove the result in a real browser in Spanish.

**Tech Stack:** Django `gettext`, gettext tools (`xgettext`, `msgattrib`, `msgfmt`, `msgmerge`), statici18n for the JavaScript catalog, git worktrees, bash.

**Spec:** `docs/superpowers/specs/2026-10-28-spanish-translation-gap-design.md`

## Global Constraints

- Branch `fix/es-translations` (the design is committed on it). Conventional Commits with a body, ending with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push. Code, comments and commit messages in English; Spanish only inside `msgstr` values.
- **Never run `makemessages` on the repository's own `locale/`.** Regenerate only inside a throwaway `git worktree` (or a scratch copy) and copy entries from there. The catalogs are changed only by appending entries.
- `locale/es/LC_MESSAGES/django.po`: header `Language: es_ES`, `Plural-Forms: nplurals=2; plural=(n != 1);`. The diff of `django.po` and `djangojs.po` must be added lines only, plus ONE removed/added `msgstr` line pair: the existing `msgid "Amateur"` (`msgstr "Amateur"` becomes `msgstr "Aficionado"`). New entries go after the last normal entry and before any obsolete `#~` block, carrying their `#:` location lines and `#, python-format` flags from the regenerated worktree catalog. No fuzzy entries, no duplicate `msgid`s, no changed `msgid`s.
- Terminology and register follow the catalog: formal "usted"; *verificador* (checker), *caso de prueba* (test case), *envío* (submission), *rejuzgar* (rejudge), *concurso* (contest), *lote* (batch), *generador* (generator). Placeholders (`%d`, `%s`, `%(name)s`, `{time}`) and HTML markup are kept exactly; plural entries have two forms. File-size units (`%s KB`, `%sM` ...) use `msgstr` identical to the `msgid`. The quoted literal "Rejudged" (a revision comment stored in English) stays in English inside quotes. `on {time}` becomes `el {time}`.
- Wrapping a string for translation must not change the English output or the behaviour. Tests that assert on message text must keep passing unchanged.
- Scope: the entries and files named in the tasks. Not in scope: the `newsletter` templates, Markdown guide examples, RSS/Atom titles, technical HTTP 400/404 bodies, API and middleware messages, `502.html`, other languages, other cognates whose `msgstr` equals the `msgid`, CI enforcement, tracking `.mo` files.
- **Never touch the repository's `.venv`.** Run Django with `export SCRATCH=/tmp/claude-1000/-var-home-areslolxd-Documentos-online-judge/6b1cb67e-65ce-4d10-8f6f-3a9fec626c0d/scratchpad UV_LINK_MODE=copy PYTHONPATH=$SCRATCH DJANGO_SETTINGS_MODULE=matrix_settings UV_PROJECT_ENVIRONMENT=$SCRATCH/env313`, then `uv run --no-sync python manage.py ...`. The MariaDB is started by the controller; implementers never start, stop or alter database services (Task 6 may create and drop its own database). Baseline on this branch: 209 tests OK on Django 5.2. Never create `.venv`, `static/`, `formcheckerprob/` or `.mo` files in the repo (delete them if a command leaves any). Stage only the files a task names.
- Inputs live in the session scratchpad, which is temporary: before dispatching Task 3 the controller copies `$SCRATCH/i18n_work.po` (drafts of the 36 fork entries) and `$SCRATCH/i18n_discovery/` (`layer1_django.tsv`, `layer1_djangojs.tsv`, `layer2_hardcoded.tsv`, `scan_hardcoded.py`) into the SDD workspace folder `.superpowers/sdd/2026-10-28-spanish-translation-gap/inputs/`; tasks read them from there.
- Translation tasks (3 and 4) are done by an implementer WITH a shell (python-pro). Reviews of 3 and 4 must read the Spanish pairs, not only run tools.

## Review Focus

- A message built as `_('... %s') % value` must keep producing the identical English text and must not move the `%` operator inside the `gettext` call (Task 1: the existing tests plus the regenerated catalog showing the msgid with its `%s`).
- `{time}` and `on {time}` keep the `{time}` placeholder (Tasks 3: placeholder comparison script; an entry that loses `{time}` breaks the page that renders it).
- The JavaScript string must reach the page: `makemessages -d djangojs` must extract it and the compiled JavaScript catalog must contain it (Task 2).
- No duplicate `msgid` and `msgfmt --check --check-format` clean on both catalogs after each block (Tasks 3, 4).
- HTML inside msgids (the editor guide text with a link and `%(doc_url)s`) keeps its markup and placeholder identical (Task 3: placeholder and tag comparison).
- The prevention command leaves the working tree untouched even when it fails or is interrupted (Task 5: `git status --porcelain` before and after, and the worktree list is empty afterwards).

---

### Task 1: Make the hard-coded Python strings translatable

**Files:**
- Modify: `judge/social_auth.py` (the `UsernameForm` label, its `error_messages['invalid']`, `clean_username`'s "Sorry, the username is taken."), `judge/views/two_factor.py` (the `'No TOTP key generated on server side?'` response in `TOTPEnableView.post`), `judge/contest_format/atcoder.py`, `default.py`, `ecoo.py`, `icpc.py`, `legacy_ioi.py` (the `ValidationError` messages: "... expects no config or dict as config", `unknown config key "%s"`, `invalid type for config key "%s"`, `invalid value "%s" for config key "%s"`), `judge/models/contest.py` (the three `ValidationError`s around "What is this? A contest that ended before it starts?" and "Contest problem label script: ..."), `judge/models/profile.py` (the two `ValidationError`s "Organization requires a class to be specified" and "Class must be part of the organization"), `judge/models/interface.py` ("Invalid regex: %s").
- Test: existing tests only (no new test class: this task changes no logic).

**Interfaces:**
- Produces for Tasks 4 and 5: the new msgids exactly as the English text appears today, so that a regenerated catalog contains them; the `%s` formatting stays outside the `gettext` call.

- [ ] **Step 1: Read each location and confirm it is user-visible** (a regular user or the maintainer in the admin); skip any string that turns out to be developer-only and say so in the report. Use the call each file already imports (`gettext as _`, or `gettext_lazy` for class-level attributes such as form labels and field definitions evaluated at import time; use the non-lazy form inside methods).
- [ ] **Step 2: Wrap them** (`_('text')`, with `% value` applied to the result). Do not rewrite or reword messages, do not change any other line, do not add imports that the file does not need.
- [ ] **Step 3: Verify.** `uv run --no-sync python manage.py test judge --noinput` stays at 209 tests OK; `$SCRATCH/env313/bin/flake8 --extend-exclude .claude,graphify-out` clean; and a regenerated catalog in a THROWAWAY worktree (`git worktree add --detach $SCRATCH/i18n_t1 HEAD` after committing, copy `dmoj/local_settings.py` into it, `makemessages -l es -e py,html,txt` there, then remove the worktree) contains every wrapped msgid with its `%s` or `%(...)s` intact. Paste the list of msgids found.
- [ ] **Step 4: Commit** the touched files as `fix(i18n): mark hard-coded user-facing messages for translation`.

---

### Task 2: Make the editor's "Nothing to preview" translatable

**Files:**
- Modify: `martor/static/martor/js/martor.js` (the `currentTab.html('<p>Nothing to preview</p>')` at about line 195), `locale/es/LC_MESSAGES/djangojs.po`

**Interfaces:**
- Consumes: the global `gettext()` that `templates/base.html` makes available through `inlinei18n(LANGUAGE_CODE)`.
- Produces: the msgid `Nothing to preview` in the `djangojs` domain with msgstr `Nada que previsualizar`.

- [ ] **Step 1: Change the JavaScript** to build the paragraph from `gettext('Nothing to preview')` with the text inserted safely (text node or escaped), keeping the same markup `<p>…</p>`. Keep working if `gettext` is undefined (fall back to the English text).
- [ ] **Step 2: Regenerate the JS catalog in a throwaway worktree** (`makemessages -l es -d djangojs`) and confirm the msgid is extracted from `martor.js`; if it is not, find out why (the extractor's ignore patterns) and report before changing anything else. Append the entry (with its `#:` line) to `locale/es/LC_MESSAGES/djangojs.po`.
- [ ] **Step 3: Prove it reaches the page.** Compile the catalog into a scratch directory, build the JavaScript catalog the way the project does (`statici18n` / `compilejsi18n` into a scratch static root) and show that the generated `jsi18n/es/djangojs.js` contains `Nothing to preview` with the Spanish text. `node --check martor/static/martor/js/martor.js` exits 0. `msgfmt --check --check-format -o /dev/null locale/es/LC_MESSAGES/djangojs.po` is clean.
- [ ] **Step 4: Commit** the two files as `fix(i18n): translate the editor's empty preview message`.

---

### Task 3: Catalog part A, user-facing entries

**Files:**
- Modify: `locale/es/LC_MESSAGES/django.po`

**Interfaces:**
- Consumes: Tasks 1 and 2 committed; the drafts in `.superpowers/sdd/2026-10-28-spanish-translation-gap/inputs/i18n_work.po`.
- Produces for Task 4: the catalog with part A appended; Task 4 regenerates from the then-current HEAD and handles whatever is still missing.

- [ ] **Step 1: Regenerate in a throwaway worktree of the current HEAD** (never in the repo), list the entries still untranslated or fuzzy, and select part A: the 36 fork entries (drafts exist: read them critically and fix anything wrong; the three doubts are the quoted "archive" option (use "Archivar envíos bloqueados"), "mapping" as "mapeo", and `(*reference)` kept as a literal example); the editor entries from `martor/templates/martor/toolbar.html`, `guide.html`, `editor.html`, `martor/views.py` (Bold, Italic, Horizontal Line, Pre or Code, Math, Inline Math, LaTeX, Quote, Unordered List, Ordered List, Insert Image Link, Upload an Image, Direct Mention a User, Full Screen, Markdown Guide (Help), Uploading..., Markdown Guide, "Or", "... to Get", the guide paragraph with its link, Preview, Editor, Heading, Code, Pre, Display Math, URL/Link, Nothing to preview of the template, and the two messages of `martor/views.py`); `judge/comments.py` and `judge/views/ticket.py` ("Please click on "Preview" before ..."); `templates/comments/media-js.html` (the source-code confirm dialog, keep `\n` line breaks); the contest list texts ("Search contests...", "There are no past contests."); `{time}` and `on {time}`; the file-size unit entries (`msgstr` identical to `msgid`); "Archive locked submissions:". All their fuzzy guesses are discarded and rewritten.
- [ ] **Step 2: Translate and append** them as one block to `locale/es/LC_MESSAGES/django.po` (no `makemessages`/`msgcat`/`msgmerge` on the repo catalog; copy blocks with their `#:` and `#, python-format` lines from the worktree catalog and remove any `#, fuzzy` and `#|` lines). Then the single allowed edit: the existing `msgid "Amateur"` gets `msgstr "Aficionado"`.
- [ ] **Step 3: Validate.** `msgfmt --check --check-format -o /dev/null locale/es/LC_MESSAGES/django.po` exits 0; a script compares the placeholder multiset (`%d`, `%s`, `%(x)s`, `{time}`), HTML tags and plural form count for every new entry; `git diff --numstat` shows additions plus exactly one removed line (the old `Amateur` msgstr) and `git diff` confirms it; no duplicate `msgid` (`msgfmt` would fail). Runtime proof: compile into a scratch directory, load it with `django.utils.translation` set to `es` (throwaway script under `$SCRATCH`, `LOCALE_PATHS` pointing at the scratch directory plus the repo's) and print `gettext` for every new msgid; none may equal its English `msgid` except the unit entries; for plural entries check `ngettext` with 1 and 2.
- [ ] **Step 4: Write the pairs** (`msgid -> msgstr`, one per line) to the report so the reviewer can read them.
- [ ] **Step 5: Commit** `locale/es/LC_MESSAGES/django.po` as `fix(i18n): add the missing Spanish translations for the user-facing interface`.

---

### Task 4: Catalog part B, staff and newly wrapped entries

**Files:**
- Modify: `locale/es/LC_MESSAGES/django.po`

**Interfaces:**
- Consumes: Tasks 1 to 3 committed.
- Produces: a catalog for which a regeneration of the final HEAD in a throwaway worktree reports 0 untranslated and 0 fuzzy in the `django` domain.

- [ ] **Step 1: Regenerate in a throwaway worktree of the current HEAD** and list what is still untranslated or fuzzy; it must be: the staff/admin entries ("%d user was muted.", "Mute users", "Deactivate users", "You do not have permission to deactivate users.", "%d user was banned.", "Archive any submission", "Create private problems", "is archived", "performance ceiling override", "Override performance ceiling of contest", "Rate users even if they make no submissions.", the help text "Overrides the performance_ceiling ...", "custom checker file" if still open) and the new msgids created by Task 1 (the username form, the TOTP message, the contest format messages, the contest, profile and interface validation messages). Anything else still listed (or any non-obsolete entry that is fuzzy) is a surprise: report it and handle it as the design says, or flag it for the controller.
- [ ] **Step 2: Translate and append** as one block, same rules as Task 3 Step 2.
- [ ] **Step 3: Validate** as Task 3 Step 3, and in addition regenerate once more in a throwaway worktree of the new HEAD (commit first) and show `msgattrib --untranslated --no-obsolete` and `msgattrib --only-fuzzy --no-obsolete` counts are 0 for `django`, and 0 for `djangojs`.
- [ ] **Step 4: Write the pairs** to the report.
- [ ] **Step 5: Commit** as `fix(i18n): add the missing Spanish translations for staff and validation messages`.

---

### Task 5: The prevention command

**Files:**
- Create: `check_translations.sh` (repository root, executable, next to `make_style.sh`; follow its style)
- Modify: `README.md` (two lines under the translations or development section, next to the existing `compilemessages` note)

**Interfaces:**
- Produces: `./check_translations.sh [ref]`: for the given git ref (default `HEAD`) it creates a temporary detached `git worktree`, copies `dmoj/local_settings.py` into it when it exists, runs `makemessages -l es -e py,html,txt` and `makemessages -l es -d djangojs` there with the project environment (`uv run --no-sync` if `uv` is available, else `python manage.py`), prints per domain the counts of untranslated and fuzzy entries and the list of the missing msgids with their file locations, removes the worktree on exit (`trap`, also on error or interrupt), and exits 1 when anything is missing and 0 otherwise. It never writes into the working tree.

- [ ] **Step 1: Write the script and a test run plan** (no new Python test: the task is a shell tool). `bash -n check_translations.sh` and `shellcheck` (if installed) are clean.
- [ ] **Step 2: Demonstrate it** on `master` (before this branch: it must report the 98 entries and exit 1), then on the final `HEAD` of the branch (0 untranslated, 0 fuzzy in both domains, exit 0). Record `git status --porcelain` and `git worktree list` before and after each run and show they are identical (no leftover worktree, no modified file), including after interrupting a run (send it SIGINT mid-way).
- [ ] **Step 3: README** two lines: what the command does and when to run it (before deploying, after merging upstream).
- [ ] **Step 4: Commit** the two files as `feat(i18n): add a command that reports missing Spanish translations`.

---

### Task 6: Visual verification in Spanish (no repository changes)

**Files:** none in the repository. Everything under `$SCRATCH/i18n_visual/`.

**Interfaces:**
- Consumes: the final HEAD of the branch and the compiled catalog.

- [ ] **Step 1: Build the harness**: a throwaway database (create, migrate with `env313`, drop at the end), a scratch settings module with `LANGUAGE_CODE = 'es'` that imports `matrix_settings`, a seed script that creates a staff user with edit rights, a public problem with an uploaded test-case zip so that the data page shows its states, a contest and a comment; compile the catalogs into the repository's ignored `.mo` location OR point `LOCALE_PATHS` at a scratch directory (prefer the scratch directory; leave no `.mo` in the repository). Serve it locally over HTTPS reusing the approach of `$SCRATCH/e2e/` (`proxy.js`, `e2e_settings.py`, `seed.py` are examples).
- [ ] **Step 2: Screenshots with Chromium** (the cached `chromium-1248`, `playwright-core` from `$SCRATCH/e2e/node_modules`): all network blocked except the local server, NO clicks on links of any scheme (hover and screenshots only), pages: the problem data page (`/problem/<code>/data`), a page with a comment box and the editor toolbar (hover over a toolbar button to read its tooltip), the contest list, a user page (rating level) and one admin changelist. For each page extract the visible text and list the sentences that are still English (a simple heuristic is fine, report its limits).
- [ ] **Step 3: Report** the screenshots' paths and the still-English list with, for each item, whether it is in scope of the design (a bug) or a known non-goal. Clean up: stop servers, drop the database, close browsers.

---

## Final verification (controller)

On the final HEAD of `fix/es-translations`: the full suite on Python 3.13 and 3.14 (209 tests OK), flake8, `msgfmt --check` on both catalogs, `./check_translations.sh` shows 0/0, the diff of `django.po` contains additions only plus the one `Amateur` pair, and the whole-branch review (most capable model, with the Spanish pairs reviewed in tasks 3 and 4). Then `superpowers:finishing-a-development-branch`.

## Follow-ups (not tasks)

- The maintainer's server needs `./scripts/copy_static` (it runs `compilemessages`) for the new strings to show.
- Deferred, by design: RSS/Atom titles, technical response bodies, the `newsletter` app, the 502 page, other cognates whose `msgstr` equals the `msgid`.
