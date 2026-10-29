#!/bin/bash
# Reports interface strings that have no Spanish translation, in a throwaway worktree of REF (default HEAD).
# Usage: ./check_translations.sh [ref]
# Exit status: 0 all translated, 1 something is missing, 2 the check could not run.
set -u

ref=${1:-HEAD}

for tool in git xgettext msgattrib; do
  if ! [ -x "$(command -v "$tool")" ]; then
    echo "Error: $tool is not installed." >&2
    exit 2
  fi
done

cd "$(dirname "$0")" || exit 2
root=$(git rev-parse --show-toplevel) || exit 2
main_checkout=$(git worktree list --porcelain | sed -n '1s/^worktree //p')

if ! git rev-parse --verify --quiet "$ref^{commit}" >/dev/null; then
  echo "Error: '$ref' is not a git ref or commit." >&2
  exit 2
fi

tmp=$(mktemp -d) || exit 2
worktree=$tmp/worktree
# shellcheck disable=SC2329  # invoked through the EXIT trap
cleanup() {
  cd / || true
  git -C "$root" worktree remove --force "$worktree" >/dev/null 2>&1
  git -C "$root" worktree prune
  rm -rf "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

git -C "$root" worktree add --quiet --detach "$worktree" "$ref" || exit 2
if [ -f "$root/dmoj/local_settings.py" ]; then
  cp "$root/dmoj/local_settings.py" "$worktree/dmoj/local_settings.py"
fi

# Use the project's environment without letting uv create a .venv inside the throwaway worktree.
python_cmd=(python)
if [ -x "$(command -v uv)" ]; then
  if [ -z "${UV_PROJECT_ENVIRONMENT:-}" ] && [ -d "$main_checkout/.venv" ]; then
    export UV_PROJECT_ENVIRONMENT=$main_checkout/.venv
  fi
  if [ -n "${UV_PROJECT_ENVIRONMENT:-}" ]; then
    python_cmd=(uv run --no-sync python)
  fi
fi

log=$tmp/makemessages.log
cd "$worktree" || exit 2
for args in "-e py,html,txt" "-d djangojs"; do
  # shellcheck disable=SC2086  # the options are meant to be split
  if ! "${python_cmd[@]}" manage.py makemessages -v 0 -l es $args >>"$log" 2>&1; then
    echo "Error: makemessages $args failed. Last lines of its log:" >&2
    tail -n 20 "$log" >&2
    exit 2
  fi
done

# Prints "<msgid, cut to 100 characters>  (<first source location>)" for each entry of a PO file read from stdin.
list_entries() {
  awk 'BEGIN { RS = ""; FS = "\n" }
    {
      location = ""; id = ""; reading = 0
      for (i = 1; i <= NF; i++) {
        line = $i
        if (line ~ /^#: / && location == "") { split(substr(line, 4), parts, " "); location = parts[1] }
        if (line ~ /^msgid_plural|^msgstr/) reading = 0
        if (line ~ /^msgid /) { reading = 1; line = substr(line, 7) }
        if (reading && line ~ /^"/) id = id substr(line, 2, length(line) - 2)
      }
      if (id == "") next  # the header entry
      if (length(id) > 100) id = substr(id, 1, 97) "..."
      print id "  (" location ")"
    }'
}

status=0
for domain in django djangojs; do
  po=$worktree/locale/es/LC_MESSAGES/$domain.po
  if ! [ -f "$po" ]; then
    echo "Error: makemessages did not produce $domain.po." >&2
    exit 2
  fi
  untranslated=$(msgattrib --untranslated --no-obsolete --no-wrap "$po" | list_entries)
  fuzzy=$(msgattrib --only-fuzzy --no-obsolete --no-wrap "$po" | list_entries)
  untranslated_count=$(printf '%s' "$untranslated" | grep -c '^')
  fuzzy_count=$(printf '%s' "$fuzzy" | grep -c '^')
  echo "$domain: untranslated=$untranslated_count fuzzy=$fuzzy_count"
  if [ "$untranslated_count" -gt 0 ]; then
    status=1
    printf '%s\n' "$untranslated" | sed 's/^/  untranslated: /'
  fi
  if [ "$fuzzy_count" -gt 0 ]; then
    status=1
    printf '%s\n' "$fuzzy" | sed 's/^/  fuzzy: /'
  fi
done

if [ "$status" -eq 0 ]; then
  echo "All strings are translated."
else
  echo
  echo "Translate the new strings in locale/es/LC_MESSAGES/django.po (and djangojs.po)."
  echo "The .mo files are compiled by compilemessages; the deployment's copy_static does it."
fi
exit "$status"
