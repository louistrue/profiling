#!/usr/bin/env bash
# correctness/run.sh — drive the full apples-to-apples geometry comparison
#                      between ifc-lite (native) and IfcOpenShell (pip 0.8.2)
#                      on one IFC model.
#
# Usage:
#   correctness/run.sh <model-or-path> [out-dir]
#
# Examples:
#   correctness/run.sh duplex.ifc                     # uses models/duplex.ifc
#   correctness/run.sh advanced_model.ifc /tmp/qa
#   correctness/run.sh /abs/path/to/foo.ifc
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <model.ifc | path> [out-dir]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INPUT="$1"
OUT_DIR="${2:-$ROOT/correctness/results}"

# Resolve model: absolute path > $ROOT/models/<name> > error
if [[ -f "$INPUT" ]]; then
  MODEL="$INPUT"
elif [[ -f "$ROOT/models/$INPUT" ]]; then
  MODEL="$ROOT/models/$INPUT"
else
  echo "model not found: $INPUT" >&2
  exit 1
fi
NAME="$(basename "$MODEL" .ifc)"
mkdir -p "$OUT_DIR"

# Build native dumper once if needed.
DUMP_BIN="$ROOT/correctness/dump_ifclite_native/target/release/ifclite-dump"
if [[ ! -x "$DUMP_BIN" ]]; then
  echo ">> building native dumper" >&2
  (cd "$ROOT/correctness/dump_ifclite_native" && cargo build --release >&2)
fi

LITE_NDJSON="$OUT_DIR/$NAME.ifclite.ndjson"
IOS_NDJSON="$OUT_DIR/$NAME.ios.ndjson"
SUMMARY="$OUT_DIR/$NAME.summary.json"
PER_ELEM="$OUT_DIR/$NAME.per-element.ndjson"
HTML="$OUT_DIR/$NAME.report.html"
SEMANTIC="$OUT_DIR/$NAME.semantic.json"
SEMANTIC_NDJSON="$OUT_DIR/$NAME.semantic.ndjson"

echo ">> ifc-lite native dump"
"$DUMP_BIN" "$MODEL" "$LITE_NDJSON"

echo ">> IfcOpenShell dump"
# Pass the local-frame anchor the native dumper wrote (georeferenced models)
# so both engines are compared near the origin (f32-safe). Harmless when absent.
python3 "$ROOT/correctness/dump_ifcopenshell.py" "$MODEL" "$IOS_NDJSON" "$LITE_NDJSON.origin"

echo ">> diff (T1-T5)"
python3 "$ROOT/correctness/diff.py" "$LITE_NDJSON" "$IOS_NDJSON" \
  --out "$SUMMARY" --per-element "$PER_ELEM" --html "$HTML"

echo ">> semantic (T6 opening-cut and filler-alignment)"
python3 "$ROOT/correctness/semantic.py" "$MODEL" "$LITE_NDJSON" \
  --anchor "$LITE_NDJSON.origin" \
  --out "$SEMANTIC" --per-pair "$SEMANTIC_NDJSON"

echo ""
echo "Outputs in $OUT_DIR:"
echo "  $LITE_NDJSON"
echo "  $IOS_NDJSON"
echo "  $SUMMARY"
echo "  $PER_ELEM"
echo "  $HTML"
echo "  $SEMANTIC"
echo "  $SEMANTIC_NDJSON"
