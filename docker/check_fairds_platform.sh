#!/usr/bin/env bash
# Report whether this machine can pull the official FAIR-DS image.
# The image manifest is linux/amd64 only. Exit 0 after printing the matching start command.
set -euo pipefail

arch="$(uname -m)"
image="docker-registry.wur.nl/m-unlock/docker/fairds:latest"

echo "Host architecture: ${arch}"
echo "Official image: ${image}"

case "${arch}" in
  x86_64 | amd64)
    echo "Supported. The official image matches this machine."
    echo "Start with:"
    echo "  docker compose up -d --build"
    ;;
  aarch64 | arm64)
    echo "The official image has no linux/arm64 manifest."
    echo "A plain 'docker pull' on this host fails with: no matching manifest for linux/arm64."
    echo "Default Compose pins platform: linux/amd64, so Docker Desktop can emulate it:"
    echo "  docker compose up -d --build"
    echo "To run FAIR-DS natively instead of emulating amd64, build the public JAR:"
    echo "  FAIRDS_PLATFORM=linux/arm64 docker compose -f compose.yaml -f compose.fairds-jar.yaml up -d --build fairds"
    echo "Or skip the FAIR-DS container and use Java 21 or the conda/mamba install in the repository README."
    ;;
  *)
    echo "The official image is published for linux/amd64 only."
    echo "Build the public JAR for this machine, or install FAIRiAgent with conda/mamba and run the JAR:"
    echo "  FAIRDS_PLATFORM=linux/${arch} docker compose -f compose.yaml -f compose.fairds-jar.yaml up -d --build fairds"
    echo "  ../scripts/update_fairds_jar.sh && java -Dserver.port=8083 -jar fairds/fairds.jar"
    ;;
esac
