# CLAUDE.md

Guidance for AI coding agents working in this repository. Personal and machine-specific notes belong in
`CLAUDE.local.md`, not here.

## Commands

- Install: `uv sync` (add `--extra mysql` for the compiled MySQL driver)
- Test: `uv run python manage.py test judge` (needs MySQL or MariaDB; the page tests need
  `uv run python manage.py compilejsi18n` first)
- Lint: `uv run flake8`
- CI (`.github/workflows/build.yml`) runs lint, unit tests and the style build as separate required jobs.
- Code, comments and commit messages are in English; commits follow Conventional Commits.

## OpenSpec and Superpowers

OpenSpec owns the what and the why. Superpowers owns the how. The OpenSpec commands available here are
`/opsx:explore`, `/opsx:propose`, `/opsx:update`, `/opsx:apply`, `/opsx:sync` and `/opsx:archive`. There is
no verify command; verify is defined below as a Superpowers step.

1. **When OpenSpec is needed.** A change that alters visible behavior or a contract (pages, API v2
   responses, contest formats, the judge bridge protocol, data in models and migrations, settings that
   change deployment) starts with `/opsx:propose`, never with code. Small bug fixes, internal refactors
   and changes with no behavior impact do not need OpenSpec and follow the normal Superpowers flow.
2. **Ownership.** OpenSpec owns `proposal.md`, the delta specs, `design.md` and `tasks.md`. Superpowers
   owns the interactive design conversation, the detailed plans, TDD, subagents and code review. For an
   OpenSpec change the outcome of the brainstorming goes into `proposal.md` and `design.md`; do not write a
   separate file under `docs/superpowers/specs/`.
3. **One task list.** `tasks.md` is the only master task list. A plan from `superpowers:writing-plans`
   details one group of those tasks and is saved at `openspec/changes/<change>/plans/<change>-<group>.md`.
   Never keep a parallel list of tasks.
4. **Flow per change.** `/opsx:explore` or `superpowers:brainstorming` -> `/opsx:propose` -> review by the
   maintainer -> `superpowers:writing-plans` per task group -> `superpowers:subagent-driven-development`
   with TDD (it replaces `/opsx:apply` as the executor; the controller ticks the checkbox in `tasks.md`
   after each task passes its review) -> verify -> `/opsx:archive` -> `superpowers:finishing-a-development-branch`.
5. **Scenarios and tests.** Every Scenario (Given/When/Then) of a delta spec has at least one test, and
   `tasks.md` records it under each group as `Covers: <capability> / <requirement> / <scenario>`. A test
   that maps to no Scenario, or a Scenario with no test, is reported in verify.
6. **Verify.** Before archiving: run the full test suite and `uv run flake8` and read the output
   (`superpowers:verification-before-completion`), then list every Scenario with the test that covers it and
   every test added by the change that covers no Scenario. The final whole-branch reviewer reports this list.
7. **Archive.** Do not archive until the tests, flake8 and verify pass. The archive commit goes on the same
   branch as the code, before the branch is merged or opened as a pull request.
8. **Divergence.** If the implementation starts to diverge from the spec, stop, update the delta spec with
   `/opsx:update` (or ask the maintainer) and only then continue.
9. **Commits.** One small commit per step. Never push unless the maintainer asks for it.
