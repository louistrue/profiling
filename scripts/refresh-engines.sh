#!/usr/bin/env bash
# Refresh ALL benchmarked engines to their current "production" state:
#   - ifc-lite WASM   -> latest PUBLISHED npm packages
#   - ifc-lite native -> latest `main` (built from a dedicated read-only worktree,
#                        never the live ifc-lite working tree / a feature branch)
#   - web-ifc         -> latest published npm
#
# Rationale: a benchmark must reflect what users actually run. Building native
# against a local feature branch (e.g. an in-flight WIP) produced a 13x-too-slow
# Tekla number (39.6s vs 2.9s) — see results/RESULTS.md "Confounds".
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IFCLITE_REPO="${IFCLITE_REPO:-$HERE/../ifc-lite}"
MAIN_WT="${MAIN_WT:-$HERE/../ifc-lite-main-bench}"

echo "==> 1/4 ifc-lite native: sync main worktree at $MAIN_WT"
git -C "$IFCLITE_REPO" fetch origin main --quiet
if git -C "$IFCLITE_REPO" worktree list | grep -q "$MAIN_WT"; then
  git -C "$MAIN_WT" fetch origin main --quiet
  git -C "$MAIN_WT" checkout --detach origin/main --quiet
else
  git -C "$IFCLITE_REPO" worktree add --detach "$MAIN_WT" origin/main
fi
echo "    main @ $(git -C "$MAIN_WT" rev-parse --short HEAD)"

echo "==> 2/4 ifc-lite native: cargo build --release (against main)"
( cd "$HERE/ifclite-rs" && cargo build --release )

echo "==> 3/4 ifc-lite WASM: pnpm add latest published @ifc-lite/*"
( cd "$HERE" && pnpm add \
    @ifc-lite/geometry@latest @ifc-lite/parser@latest @ifc-lite/wasm@latest \
    @ifc-lite/data@latest @ifc-lite/query@latest )

echo "==> 4/4 web-ifc: npm install web-ifc@latest"
( cd "$HERE/webifc" && npm install web-ifc@latest )

echo "==> done. Engine versions:"
for p in parser geometry wasm data query; do
  printf "    @ifc-lite/%-9s %s\n" "$p" "$(grep -m1 '\"version\"' "$HERE/node_modules/@ifc-lite/$p/package.json" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
done
printf "    web-ifc           %s\n" "$(grep -m1 '\"version\"' "$HERE/webifc/node_modules/web-ifc/package.json" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
echo
echo "Now run: pnpm native && pnpm start && (cd webifc && pnpm start)"
