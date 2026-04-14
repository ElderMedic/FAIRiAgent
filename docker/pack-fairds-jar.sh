#!/usr/bin/env bash
# Copy the newest fairds*.jar from ~/Downloads into docker/fairds/fairds.jar for Dockerfile.from-local builds.
# JARs are gitignored (large). Default Compose builds FAIR-DS from the public download URL instead.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DEST="${ROOT}/fairds/fairds.jar"
DL="${HOME}/Downloads"

NEWEST=""
if [[ -d "$DL" ]]; then
  NEWEST="$(ls -t "${DL}"/fairds*.jar 2>/dev/null | head -1 || true)"
fi

if [[ -z "${NEWEST}" ]]; then
  echo "No fairds*.jar found in ${DL}"
  exit 1
fi

mkdir -p "${ROOT}/fairds"
cp "${NEWEST}" "${DEST}"
echo "Copied: ${NEWEST} -> ${DEST}"
echo "To build FAIR-DS from this file, set in docker/.env:"
echo "  FAIRDS_DOCKERFILE=Dockerfile.from-local"
