#!/usr/bin/env bash
# The Edge Function validates with the same question definitions as the browser.
# Run after editing site/assets/questions.js, before deploying the function.
set -euo pipefail
cd "$(dirname "$0")/.."
cp site/assets/questions.js supabase/functions/_shared/questions.js
echo "synced questions.js"
