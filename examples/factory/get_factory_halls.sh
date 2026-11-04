#!/bin/sh
# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
# The factory's four halls: four scenes of NVIDIA's PhysicalAI-SmartSpaces (CC BY 4.0, MTMC_Tracking_2025), with the
# cameras each hall uses. About 6 GB; files already present are kept.
set -e
cd "$(dirname "$0")/../.."
BASE="https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces/resolve/main/MTMC_Tracking_2025"
ROOT="${ARGUS_DATA:-data}/smartspaces"
get() {  # split, scene, file
  mkdir -p "$ROOT/$2/$(dirname "$3")"
  out="$ROOT/$2/$3"
  [ -s "$out" ] && return 0
  curl -sSfL --retry 3 -o "$out.part" "$BASE/$1/$2/$3" && mv "$out.part" "$out" && echo "$2/$3"
}
for f in calibration.json map.png ground_truth.json; do
  get val Warehouse_015 $f; get val Warehouse_016 $f; get train Warehouse_000 $f; get train Warehouse_010 $f
done
for c in 01 02 03 04 05 06 07 08 09 10 11 12; do get val Warehouse_015 videos/Camera_$c.mp4; done
get val Warehouse_015 videos/Camera.mp4
get val Warehouse_016 videos/Camera.mp4
for c in 01 02 03 04 05 06 07 08 09 10 11; do get val Warehouse_016 videos/Camera_$c.mp4; done
for c in 0000 0004 0008 0012 0016 0020; do get train Warehouse_000 videos/Camera_$c.mp4; done
for c in 0000 0012; do get train Warehouse_010 videos/Camera_$c.mp4; done
