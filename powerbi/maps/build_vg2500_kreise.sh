#!/usr/bin/env bash
# Regenerates vg2500_kreise.topojson, the Power BI Shape Map of German districts (Kreise),
# from BKG's VG2500 open data. The download stays outside the repo; pass its folder.
#
#   curl -LO https://daten.gdz.bkg.bund.de/produkte/vg/vg2500/aktuell/vg2500_12-31.utm32s.shape.zip
#   unzip vg2500_12-31.utm32s.shape.zip -d /some/tmp/vg2500
#   powerbi/maps/build_vg2500_kreise.sh /some/tmp/vg2500
#
# Edition used: Stand 31.12.2025 (dokumentation/aktualitaet.txt), md5 aafe38ae8415878b13e87e0fb0bed7be.
# Not the 01.01.2026 edition: Hanau (06415) left Main-Kinzig-Kreis that day, so its districts no longer
# match the 2025 Regionalstatistik data.
set -euo pipefail

SRC="${1:?usage: build_vg2500_kreise.sh <unzipped VG2500 folder>}"
OUT="$(cd "$(dirname "$0")" && pwd)/vg2500_kreise.topojson"

# GF = 9: land areas with structure (one record per district, so AGS stays unique).
# ags is the 5-digit AGS as a string; it is both the feature id and a property, since it is
# unclear which of the two Shape Map matches on. name is kept for checking.
# Simplification: a 200 m tolerance, not a vertex percentage. Every percentage tried (15-30%)
# dropped islands (the East Frisian Islands, Neuwerk, parts of Rügen) and an enclave hole;
# at 200 m all 465 rings of the source survive, and loss starts only at 400 m. Shared borders
# are single arcs in TopoJSON, so an enclave and the hole around it move together.
npx --yes mapshaper@0.8.8 \
  -i "$SRC/vg2500/VG2500_KRS.shp" encoding=utf8 \
  -filter 'GF == 9' \
  -proj wgs84 \
  -each 'ags = String(AGS), name = GEN' \
  -filter-fields ags,name \
  -simplify interval=200 keep-shapes \
  -o "$OUT" format=topojson id-field=ags quantization=100000 force

echo "wrote $OUT ($(wc -c < "$OUT") bytes)"
