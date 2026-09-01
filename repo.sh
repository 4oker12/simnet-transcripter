#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
runtime_pattern='(^|/)(models|results|logs|test_audio|tmp|cache|__pycache__|\.venv[^/]*|venv[^/]*|env[^/]*)/|(^|/)\.env($|\.)|\.(mp3|wav|m4a|ogg|webm|flac|tar|tgz|zip)$|\.tar\.gz$'
secret_pattern='PRIVATE'' KEY|BEGIN'' OPENSSH|API_''KEY|TOKEN''=|PASSWORD''=|SECRET''=|Authorization'':|Bearer'' '
status_command() {
    echo "Branch: $(git branch --show-current)"
    echo "Remote: $(git remote get-url origin 2>/dev/null || echo missing)"
    echo "Last commit: $(git log -1 --oneline 2>/dev/null || echo 'no commits yet')"
    git status --short --branch
    upstream="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)"
    if [[ -n "$upstream" ]]; then
        counts="$(git rev-list --left-right --count "$upstream"...HEAD)"
        echo "Upstream $upstream: behind $(awk '{print $1}' <<<"$counts"), ahead $(awk '{print $2}' <<<"$counts")"
    else echo "Upstream: not configured"; fi
}
case "${1:-}" in
    status) status_command ;;
    pull)
        [[ -z "$(git status --porcelain)" ]] || { echo "Working tree is not clean; commit or stash changes before pull" >&2; exit 1; }
        git fetch origin
        git pull --rebase origin main ;;
    save)
        message="${2:-}"
        [[ -n "$message" ]] || { echo "Usage: $0 save \"commit message\"" >&2; exit 2; }
        [[ "$(git branch --show-current)" == "main" ]] || { echo "repo.sh save only pushes main" >&2; exit 1; }
        tracked_unsafe="$(git ls-files | grep -E "$runtime_pattern" || true)"
        [[ -z "$tracked_unsafe" ]] || { echo "Unsafe tracked files found:" >&2; echo "$tracked_unsafe" >&2; exit 1; }
        git add -A -- . ':!models' ':!results' ':!logs' ':!test_audio' ':!tmp'
        staged="$(git diff --cached --name-only --diff-filter=ACMR)"
        [[ -n "$staged" ]] || { echo "Nothing safe to commit"; exit 0; }
        unsafe="$(grep -E "$runtime_pattern" <<<"$staged" || true)"
        [[ -z "$unsafe" ]] || { echo "Unsafe staged files found:" >&2; echo "$unsafe" >&2; exit 1; }
        while IFS= read -r path; do
            size="$(git cat-file -s ":$path")"
            (( size <= 10485760 )) || { echo "Staged file exceeds 10 MiB: $path" >&2; exit 1; }
        done <<<"$staged"
        if git grep --cached -n -I -E "$secret_pattern" -- $staged; then echo "Potential secret found; aborting" >&2; exit 1; fi
        git diff --cached --stat
        git diff --cached --check
        git commit -m "$message"
        git push -u origin main ;;
    *) echo "Usage: $0 {status|pull|save \"commit message\"}" >&2; exit 2 ;;
esac
