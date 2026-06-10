#!/usr/bin/env bash
# Switch between Habitron testing modes for the core12 dev environment.
#
# The dev container holds two parallel git repos:
#   /workspaces/core12              ← HA Core fork (branches: rc, habitron-integration)
#   /workspaces/core12/habitron_repo ← HACS integration source (branch: dev)
#
# Depending on which side we want to debug we need a different combination
# of (a) the checked-out core12 branch and (b) the presence of a HACS
# symlink under config/custom_components/habitron:
#
#   hacs   → core12 on rc                 + symlink present
#            HA dev loads habitron as a custom_component from habitron_repo.
#   core   → core12 on habitron-integration + symlink absent
#            HA dev loads habitron as a built-in integration from
#            homeassistant/components/habitron/.
#
# Usage: habitron-mode.sh {hacs|core|status}

set -euo pipefail

CORE_DIR="/workspaces/core12"
HACS_SRC="$CORE_DIR/habitron_repo/custom_components/habitron"
SYMLINK="$CORE_DIR/config/custom_components/habitron"
HACS_BRANCH="${HABITRON_HACS_BRANCH:-rc}"  # override with env var if desired
CORE_BRANCH="${HABITRON_CORE_BRANCH:-habitron-integration}"

color_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
color_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
color_err()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }

check_clean_tree() {
    cd "$CORE_DIR"
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        color_err "ABORT: uncommitted changes in core12. Commit or stash first:"
        echo
        git status --short
        exit 1
    fi
}

print_status() {
    cd "$CORE_DIR"
    local branch
    branch=$(git branch --show-current)
    echo "core12 branch: $branch"
    if [ -L "$SYMLINK" ]; then
        echo "HACS symlink:  present  →  $(readlink "$SYMLINK")"
    elif [ -e "$SYMLINK" ]; then
        color_warn "HACS symlink:  WARNING — exists but is not a symlink: $SYMLINK"
    else
        echo "HACS symlink:  absent"
    fi
    if [ -d "$CORE_DIR/homeassistant/components/habitron" ]; then
        echo "Core in-tree:  present (homeassistant/components/habitron/)"
    else
        echo "Core in-tree:  absent on this branch"
    fi
}

cmd_hacs() {
    check_clean_tree
    if [ ! -d "$HACS_SRC" ]; then
        color_err "ABORT: HACS source not found at $HACS_SRC"
        exit 1
    fi
    git -C "$CORE_DIR" checkout "$HACS_BRANCH"
    mkdir -p "$(dirname "$SYMLINK")"
    ln -sfn "$HACS_SRC" "$SYMLINK"
    echo
    color_ok "=== Habitron now in HACS mode ==="
    print_status
    echo
    color_warn "Reminder: restart the HA dev server to pick up the change."
}

cmd_core() {
    check_clean_tree
    rm -f "$SYMLINK"
    git -C "$CORE_DIR" checkout "$CORE_BRANCH"
    echo
    color_ok "=== Habitron now in Core (built-in) mode ==="
    print_status
    echo
    color_warn "Reminder: restart the HA dev server to pick up the change."
}

case "${1:-}" in
    hacs)   cmd_hacs ;;
    core)   cmd_core ;;
    status) print_status ;;
    *)
        echo "Usage: $0 {hacs|core|status}" >&2
        echo "  hacs    → core12 on '$HACS_BRANCH', HACS symlink present" >&2
        echo "  core    → core12 on '$CORE_BRANCH', HACS symlink absent" >&2
        echo "  status  → print current state (no changes)" >&2
        exit 2
        ;;
esac
