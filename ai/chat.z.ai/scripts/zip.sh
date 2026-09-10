#!/bin/bash
# zip.sh — Pure zip (no Repomix) of files staged in scratch/upload/.
#
# Mirrors LineByLine's blank.sh: the user stages arbitrary files in
# $SCRATCH/upload/ (e.g. bug.zip, deploy.log, screenshots, transcripts),
# runs this script, and gets a timestamped zip path on the clipboard
# for pasting into the chat.z.ai file picker.
#
# Use this when repomix is the wrong tool — e.g. attaching a debug log,
# a transcript, an existing zip, or a screenshot of a UI bug. Repomix is
# for the repo's source; this is for everything else.
#
# Usage:
#   1. Stage files in ~/GitHub/sonar-issue-exporter/scratch/upload/
#   2. Run ./zip.sh
#   3. Paste the clipboard path into the chat file picker
#
# Aborts with an error if scratch/upload/ is empty (nothing to zip).

snippet() {
  if [[ -z "$(ls -A "$upload" 2>/dev/null)" ]]; then
    echo "Nothing to zip: $upload is empty" >&2
    echo "Stage files in $upload/ first." >&2
    exit 1
  fi
}

# shellcheck source=.base.sh
. "$(dirname "$(readlink -f "$0")")/.base.sh"
