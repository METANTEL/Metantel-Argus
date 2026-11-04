#!/bin/sh
# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
# The console's type (optional; without it the page uses the system fonts): Inter 4.1 and JetBrains Mono 2.304, both
# under the SIL Open Font License 1.1, fetched from their projects with their licences and checked against hashes.
set -e
cd "$(dirname "$0")/../.."
D="${ARGUS_DATA:-data}/fonts"
mkdir -p "$D"
curl -sSfL -o "$D/InterVariable.ttf" "https://github.com/rsms/inter/raw/v4.1/docs/font-files/InterVariable.ttf"
curl -sSfL -o "$D/Inter-LICENSE.txt" "https://github.com/rsms/inter/raw/v4.1/LICENSE.txt"
curl -sSfL -o "$D/JetBrainsMono[wght].ttf" "https://github.com/JetBrains/JetBrainsMono/raw/v2.304/fonts/variable/JetBrainsMono%5Bwght%5D.ttf"
curl -sSfL -o "$D/JetBrainsMono-OFL.txt" "https://github.com/JetBrains/JetBrainsMono/raw/v2.304/OFL.txt"
cd "$D"
shasum -a 256 -c <<'EOF'
4989b125924991b90d05b2d16e0e388c48f7d5bb8b30539bbf9c755278d0ccaf  InterVariable.ttf
662a196d58f1183bf2d77428b6d5283fe3f45161ab021bea4036bc98e5cac016  JetBrainsMono[wght].ttf
EOF
