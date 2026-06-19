#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/docker/fairds"
TARGET="${TARGET_DIR}/fairds.jar"
URL="${FAIRDS_JAR_URL:-https://download.systemsbiology.nl/download/unlock/fairds-latest.jar}"

mkdir -p "${TARGET_DIR}"

tmp="$(mktemp "${TARGET_DIR}/fairds.jar.XXXXXX")"
trap 'rm -f "${tmp}"' EXIT

echo "Downloading FAIR Data Station JAR from ${URL}"
curl -fL --retry 3 --connect-timeout 20 --output "${tmp}" "${URL}"
mv "${tmp}" "${TARGET}"
trap - EXIT

echo "Updated ${TARGET}"
