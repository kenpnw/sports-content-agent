#!/bin/bash
# Build English thesis docx
set -e

cd "$(dirname "$0")"
HERE="$(pwd)"

OUT_ROOT="/sessions/clever-vigilant-wright/mnt/sports-content-agent"
COMBINED="$HERE/_combined.md"

# Concatenate all chapters in order
cat \
    01_frontmatter.md \
    02_chapter_intro.md \
    03_chapter_related.md \
    04_chapter_design.md \
    05_chapter_impl.md \
    06_chapter_eval.md \
    07_chapter_conclusion.md \
    08_references.md \
    09_acknowledgments.md \
    > "$COMBINED"

echo "[info] combined size: $(wc -l < "$COMBINED") lines, $(wc -c < "$COMBINED") bytes"

# Run pandoc
pandoc "$COMBINED" \
    --from markdown \
    --to docx \
    --output "$OUT_ROOT/Master_Thesis_v1_English.docx" \
    --resource-path="$HERE:../..:../../thesis_figures/out" \
    --toc \
    --toc-depth=2

echo "[done] -> $OUT_ROOT/Master_Thesis_v1_English.docx"
ls -la "$OUT_ROOT/Master_Thesis_v1_English.docx"
