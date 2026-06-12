#!/usr/bin/env bash
# Generate a clean HA-core-shaped tree from the current HACS state.
#
# Usage: ./scripts/build_core_tree.sh /path/to/core_fork
#
# Run from habitron_repo root. Idempotent: wipes the target's habitron
# subtrees before refilling.
#
# Does NOT touch Core-only files (CODEOWNERS, requirements_all.txt,
# requirements_test_all.txt, .strict-typing). Those are maintained
# directly in the Core fork.
#
# What this script does:
#   1. Copies custom_components/habitron/ -> <core>/homeassistant/components/habitron/
#   2. Copies tests/components/habitron/  -> <core>/tests/components/habitron/
#   3. Rewrites Python imports: custom_components.habitron -> homeassistant.components.habitron
#   4. Strips HACS-only manifest fields (version, homeassistant)
#   5. Ensures "quality_scale": "platinum" is present in the manifest
#   6. Rewrites test-fixture imports from pytest_homeassistant_custom_component
#      to the core test-helper layout (tests.common)

set -euo pipefail

CORE_REPO="${1:?usage: $0 <core-fork-path>}"

if [[ ! -d "$CORE_REPO/homeassistant" ]]; then
    echo "ERROR: $CORE_REPO does not look like a HA core checkout" >&2
    echo "       (no homeassistant/ directory found)" >&2
    exit 1
fi

# Verify we're running from the HACS repo root
if [[ ! -d "custom_components/habitron" ]] || [[ ! -d "tests/components/habitron" ]]; then
    echo "ERROR: must be run from the habitron_repo root" >&2
    echo "       (missing custom_components/habitron/ or tests/components/habitron/)" >&2
    exit 1
fi

SRC_INTEGRATION="custom_components/habitron"
SRC_TESTS="tests/components/habitron"
DST_INTEGRATION="$CORE_REPO/homeassistant/components/habitron"
DST_TESTS="$CORE_REPO/tests/components/habitron"

echo "==> Wiping previous core-tree contents"
rm -rf "$DST_INTEGRATION" "$DST_TESTS"

echo "==> Copying integration source"
cp -r "$SRC_INTEGRATION" "$DST_INTEGRATION"

echo "==> Stripping HACS-only artefacts from core integration tree"
# Files that exist because HACS ships integrations as standalone repos
# (LICENSE, README, .gitattributes) or that belong to the HACS-side
# user-data layout (data/, firmware/, logos/, www/). Core integrations
# are documented at home-assistant.io and never ship runtime assets
# or brand assets in-tree.
rm -rf \
    "$DST_INTEGRATION/.gitattributes" \
    "$DST_INTEGRATION/LICENSE" \
    "$DST_INTEGRATION/README.md" \
    "$DST_INTEGRATION/data" \
    "$DST_INTEGRATION/firmware" \
    "$DST_INTEGRATION/logos" \
    "$DST_INTEGRATION/www"

echo "==> Copying tests"
cp -r "$SRC_TESTS" "$DST_TESTS"

# Drop any leftover __pycache__ that may have been copied along.
find "$DST_INTEGRATION" "$DST_TESTS" -type d -name __pycache__ -exec rm -rf {} +

echo "==> Rewriting integration imports"
# Match both 'from custom_components.habitron...' and
# 'import custom_components.habitron' and 'patch("custom_components.habitron...")'
# patterns by replacing the dotted prefix.
grep -rl 'custom_components\.habitron' "$DST_INTEGRATION" "$DST_TESTS" 2>/dev/null \
    | xargs --no-run-if-empty sed -i 's|custom_components\.habitron|homeassistant.components.habitron|g'

echo "==> Adjusting manifest.json (strip HACS-only fields, set quality_scale)"
python3 - "$DST_INTEGRATION/manifest.json" <<'PYEOF'
import json
import sys

manifest_path = sys.argv[1]
with open(manifest_path) as f:
    manifest = json.load(f)

# HACS-only fields
manifest.pop("version", None)
manifest.pop("homeassistant", None)
manifest.pop("issue_tracker", None)

# Core required
manifest["quality_scale"] = "platinum"

# Documentation URL for Core points at the official integration page,
# not the GitHub source repo.
manifest["documentation"] = "https://www.home-assistant.io/integrations/habitron"

# Preserve a sensible key order: known keys first, rest appended
ordered_keys = [
    "domain",
    "name",
    "codeowners",
    "config_flow",
    "dependencies",
    "documentation",
    "integration_type",
    "iot_class",
    "issue_tracker",
    "quality_scale",
    "requirements",
    "ssdp",
]
ordered = {k: manifest[k] for k in ordered_keys if k in manifest}
for k, v in manifest.items():
    if k not in ordered:
        ordered[k] = v

with open(manifest_path, "w") as f:
    json.dump(ordered, f, indent=2)
    f.write("\n")
PYEOF

echo "==> Rewriting test-fixture imports"
# Map pytest_homeassistant_custom_component.common -> tests.common
# Plain 'from pytest_homeassistant_custom_component import X' is rarer
# but handled too. Anything else from that package needs manual review.
grep -rl 'pytest_homeassistant_custom_component' "$DST_TESTS" 2>/dev/null \
    | xargs --no-run-if-empty sed -i \
        -e 's|pytest_homeassistant_custom_component\.common|tests.common|g' \
        -e 's|from pytest_homeassistant_custom_component |from tests.common |g'

# The import rewrites above change import paths, which breaks isort
# ordering for the core layout. Re-run ruff (with the core repo's own
# config) so the generated tree is lint-clean exactly as core CI expects.
if command -v ruff >/dev/null 2>&1; then
    echo "==> ruff --fix + format on the generated tree (core config)"
    (
        cd "$CORE_REPO"
        ruff check --fix --quiet \
            homeassistant/components/habitron tests/components/habitron || true
        ruff format --quiet \
            homeassistant/components/habitron tests/components/habitron || true
    )
fi

echo
echo "Generated core-tree at:"
echo "  $DST_INTEGRATION"
echo "  $DST_TESTS"
echo
echo "Next steps (run from $CORE_REPO):"
echo "  python -m script.hassfest --integration-path homeassistant/components/habitron"
echo "  python -m pytest tests/components/habitron"
echo "  python -m mypy --strict homeassistant.components.habitron"
