#!/bin/bash
# Rebuild the document fixtures from their sources. The outputs are checked
# in so every trial starts from the same bytes; run this only to change them.
set -e
cd "$(dirname "$0")"
soffice --headless --convert-to pdf:writer_web_pdf_Export contract.html invoice.html >/dev/null
soffice --headless --infilter="CSV:44,34,76,1" --convert-to xlsx sales.csv >/dev/null
magick -size 520x160 xc:none -stroke '#1a237e' -strokewidth 5 -fill none \
  -draw "path 'M 20,110 C 60,20 90,150 130,70 S 190,30 210,100 C 230,140 260,40 300,80 S 360,120 390,60 C 410,30 440,120 500,90'" \
  signature.png
