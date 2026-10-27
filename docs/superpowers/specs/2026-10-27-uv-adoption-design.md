# Adopt uv as the single way to install the site's dependencies

## Problem

Dependencies live only in `requirements.txt` (no `pyproject.toml`, no lock file,
no pinned Python). Three places install them, each in its own way:

- A developer machine: a hand-made virtualenv (the maintainer's `.venv` runs
  Python 3.14).
- CI (`.github/workflows/build.yml`: jobs `lint` and `unit`;
  `compilemessages.yml`, `makemessages.yml`, `updatemessages.yml`): Python 3.11
  and `pip install -r requirements.txt` plus ad-hoc extras (`mysqlclient`,
  `coverage`, `pymysql`, the flake8 plugins). The `unit` job keys its pip cache on
  `hashFiles('requirements.txt')`.
- The production Docker image (a separate repository, `AresLOLXD/dmoj-docker`):
  its `dmoj/base/Dockerfile` is `FROM python:3.11-slim-bookworm`, copies
  `repo/requirements.txt` from this repository (a git submodule of this fork) and
  runs `pip3 install -r`.

Nothing is locked, so what each place resolves differs and drifts over time, and
the Python version differs between the developer machine (3.14) and CI/server
(3.11). The maintainer wants CI and local installs to use the same thing, and the
newest Python the project really supports.

## What was measured (2026-10-27, with uv in throwaway virtualenvs)

`uv pip install -r requirements.txt` plus `pymysql coverage`, then
`manage.py test judge` (163 tests) against MariaDB, with `static/jsi18n` present:

| Python | Install | Tests |
|---|---|---|
| 3.11 | ok | 163 OK |
| 3.12 | ok | 163 OK |
| 3.13 | ok | 163 OK |
| 3.14 | ok only with a uv-managed interpreter (the system 3.14 lacks `Python.h`, so `llist` does not build) | 2 errors (Turnstile tests) |

On 3.14, Django 4.2's test client fails copying the template `Context`
(`'super' object has no attribute 'dicts'`), and the suite takes 41 s instead
of 5 s. Django 4.2 officially supports Python up to 3.12; 3.13 works in
practice. Separately, without `static/jsi18n/en/djangojs.js` three tests error on
every Python version; that file is not built by the CI `unit` job (whether CI
currently fails on them is not known from the repository).

## Goals

- One source of truth for the dependencies: `pyproject.toml` plus a committed
  `uv.lock`, used identically by a developer machine and by every CI job.
- Python pinned to **3.13** (the newest version on which the whole suite passes),
  in `.python-version` and `requires-python`.
- A clean checkout becomes a working environment with one command (`uv sync`).
- `requirements.txt` is deleted (decided by the maintainer).

## Non-goals and anti-goals

- Not updating any dependency version. The current constraints are carried over
  verbatim (`Django>=4.2,<5`, `mistune<2`, `packaging<22`, `importlib-metadata<5`,
  `webauthn<1`, `social-auth-core==4.3.0`, ...). Updating them (Django 5.2 LTS first,
  which is what unlocks Python 3.14) is a separate, pending project.
- Not changing `AresLOLXD/dmoj-docker`. The maintainer updates it later; this
  work ends with a GitHub issue there (below).
- No application code changes, no test changes, no change to how the site is
  deployed.
- Failure to avoid: the Docker image build breaking silently. `dmoj-docker`
  copies `repo/requirements.txt`; after this change a rebuild from a commit of
  this repository that deleted it fails until `dmoj-docker` is updated. That is
  accepted and is stated in the issue and in the final report.

## Design

### Files

- `pyproject.toml` (new). A uv "virtual" project, not a package:
  `[project] name = "online-judge"`, `version = "0.0.0"`,
  `requires-python = ">=3.13,<3.14"` **[builder-visible call]**: the upper bound
  reflects the measurement above and is widened when Django is updated;
  `[tool.uv] package = false`.
  - `dependencies`: exactly the packages now in `requirements.txt`, constraints
    unchanged, including `qrcode[pil]`, `pillow>=13.0.0`, `bleach[css]`, and the
    explanatory comment about `importlib-metadata<5`. The four GitHub
    dependencies (`dmoj-wpadmin`, `django-fernet-fields`, `jsonfield`, `ansi2html`)
    stay as git URLs, declared in `[tool.uv.sources]` or as PEP 508 direct references
    (builder's choice), and are locked to an exact commit by `uv.lock`.
  - `[project.optional-dependencies] mysql = ["mysqlclient"]`. **[my call]** CI's
    `unit` job needs the compiled driver, developers use the pure-Python
    `pymysql` shim that `manage.py` already falls back to.
  - `[dependency-groups] dev = [...]`: the flake8 stack CI installs today
    (`flake8`, `flake8-import-order`, `flake8-future-import`, `flake8-commas`,
    `flake8-logging-format`, `flake8-quotes`), `coverage`, and `pymysql`
    **[my call]** (so a plain `uv sync` gives a working dev environment and the
    three message workflows, which today install `pymysql`, need nothing extra).
    It also holds `setuptools<81`, because `flake8-logging-format` imports
    `pkg_resources` without declaring `setuptools`, and newer setuptools no longer
    ships it.
- `.flake8`: `exclude` gains `./.venv`, because the list replaces flake8's built-in
  defaults and `uv sync` creates the environment inside the checkout.
- `.python-version` (new): `3.13`.
- `uv.lock` (new, committed): produced by `uv lock`. It resolves the newest
  versions the constraints allow at lock time (which is also what an unpinned
  `pip install` does today).
- `requirements.txt`: deleted.
- `.gitignore`: add `.venv/` if it is not already covered.
- `README.md`: a short "Installing" section: install uv, `uv sync`,
  `uv run python manage.py test judge`, a note that uv silently replaces an
  existing `.venv` built on another Python (measured), and that `compilemessages`
  needs `--ignore=.venv` because the environment lives in the checkout. Do not
  duplicate the docs.dmoj.ca install guide.

### CI (`.github/workflows/`)

All four workflows that run Python replace `actions/setup-python@v5` 3.11 plus
`pip` with `astral-sh/setup-uv` (cache enabled, keyed by `uv.lock`) and the
Python from `.python-version`:

- `build.yml`, job `lint`: `uv sync --locked --only-group dev` (`--locked`, not
  `--frozen`, so the job fails when `pyproject.toml` and `uv.lock` disagree), then
  flake8 via `uv run`.
- `build.yml`, job `unit`: `uv sync --locked --extra mysql`, copy
  `.ci.settings.py`, start MySQL, `uv run --no-sync coverage run --source=. manage.py test judge`
  and the coverage report. The manual pip cache step goes away.
- `compilemessages.yml`, `makemessages.yml`, `updatemessages.yml`:
  `uv sync --locked` replaces `pip install -r requirements.txt` and
  `pip install pymysql`; their later steps run through `uv run` where they call
  `manage.py`. `compilemessages` passes `--ignore=.venv`, because Django walks the
  whole tree and would otherwise collect the `.po` files of the installed packages.
- The `styles` job (Node only) is untouched.
- Pin each action to a major version tag like the existing workflows do.

### The follow-up issue (not part of the code change)

After this design is approved, open **one GitHub issue in
`AresLOLXD/dmoj-docker`** (the maintainer's fork, never the upstream
`Ninjaclasher/dmoj-docker`). It states what that repository must change once this
one lands: base image `python:3.13-slim-bookworm`; install uv (for example
`COPY --from=ghcr.io/astral-sh/uv`); replace `COPY repo/requirements.txt` +
`pip3 install -r` with copying `repo/pyproject.toml`, `repo/uv.lock` and
`repo/.python-version` and installing from the lock (for example
`uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt`
followed by the existing `pip3 install -r requirements.txt`, the smallest change to
the Dockerfile; `--no-hashes` is required because pip's hash-checking mode rejects
the four VCS dependencies; or `uv sync --locked --no-dev --inexact` with
`UV_PROJECT_ENVIRONMENT=/usr/local`, since the images start `uwsgi`, `celery` and
`python3` from the system PATH, which a plain `uv sync` into `./.venv` is not on, and
an exact sync of the system environment would uninstall the separately pip-installed
`uwsgi`, `django-redis`, `redis` and `websocket-client`); keep those deployment-only
packages that the Dockerfile already installs separately (`pymysql`, `mysqlclient`,
`uwsgi`, `django-redis`, `redis`, `websocket-client`), and review that its own pins
`pymysql==1.2.0` and `mysqlclient==2.2.8` differ from the lock (pymysql 1.2.3,
mysqlclient 2.3.0); the lock's `mysql` extra and `dev` group are not installed in
the image unless asked for; the warning that a rebuild
from a commit without `requirements.txt` fails until this is done; and the note that
the default `python:3.11` image must change at the same time because the lock
requires 3.13. Creating the issue is a write to GitHub on the maintainer's
explicit instruction; the text is shown to the maintainer in the final report.

## Verification (what "done" means)

1. On a clean clone, `uv sync` creates an environment on Python 3.13 with no
   errors (the `llist` C extension builds).
2. `uv lock --check` passes; `uv sync --locked` and `uv sync --locked --extra mysql`
   work.
3. `uv run python manage.py test judge` passes 163 tests with `static/jsi18n`
   present (with it absent only the three pre-existing environment errors remain,
   exactly as on master).
4. `uv run flake8` is clean on the same files as before.
5. `requirements.txt` does not exist, and no file in the repository still refers
   to it (`git grep requirements.txt` finds nothing outside this design and plan).
6. The four workflow files are valid YAML and use uv; their first real run happens
   on GitHub after a push, which the maintainer decides. Until then the CI
   change is verified only by reading it and by running the same commands locally.

## Left to the builder

- `[tool.uv.sources]` versus PEP 508 for the git dependencies.
- Exact wording of the README section and exact action versions.
- Whether to also add `default-groups`; the default (`dev`) is expected.
