# AGPL Source Link in Footer

## Problem

This repo is licensed under AGPLv3. Section 13 of the AGPL requires that,
when a modified version of the program is run as a network service, users
interacting with it remotely must be offered a way to obtain the
Corresponding Source of the version actually running (i.e. this fork,
including local modifications such as the Turnstile registration changes).

The footer (`templates/base.html`) already credits the upstream project
("proudly powered by DMOJ", linking to `https://dmoj.ca`), but that link
points to the upstream project's site, not to the source of this fork.
There is currently no link to this fork's source code.

## Design

Add a static "source code" link to the footer, next to the existing DMOJ
credit, pointing to `https://github.com/AresLOLXD/online-judge` (this
fork's public repository).

- Location: `templates/base.html`, inside the `#footer-content` span,
  immediately after the existing "proudly powered by DMOJ" link (line 284),
  following the same `|`-separated list pattern used by the other footer
  items.
- Text is wrapped in `_()` for translation, consistent with the rest of the
  footer.
- Styling matches the existing DMOJ link (`color: #808080`).
- The link is hardcoded (not admin-configurable), matching how the DMOJ
  credit link is also hardcoded — it points to a specific repository tied
  to this codebase, not something that varies per deployment.

## Out of scope

- No changes to `misc_config.footer` or any admin-configurable settings.
- No changes to any other page or template.
