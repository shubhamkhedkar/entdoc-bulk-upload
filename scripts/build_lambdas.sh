#!/usr/bin/env bash
# Builds the Lambda deployment directories that Terraform zips (archive_file).
# Local only - no AWS calls. Needs Python 3.9+ and pip; wheels are fetched for the
# Lambda target platform (python3.12 / linux arm64), so it works from macOS/Windows/Linux.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
rm -rf build && mkdir -p build/api build/processor

cp lambdas/api/*.py build/api/
cp lambdas/processor/*.py build/processor/

"$PY" -m pip install \
  --quiet --upgrade \
  --platform manylinux2014_aarch64 --platform manylinux_2_28_aarch64 \
  --implementation cp --python-version 3.12 --abi cp312 \
  --only-binary=:all: \
  --target build/processor \
  -r lambdas/processor/requirements.txt

find build -name "__pycache__" -type d -prune -exec rm -rf {} +
find build -name "*.dist-info" -type d -prune -exec rm -rf {} +
echo "processor package: $(du -sh build/processor | cut -f1) unzipped (Lambda limit 250 MB)"
(cd build/processor && "$PY" -c "import shutil;shutil.make_archive('/tmp/_size_check','zip','.')")
echo "processor package: $(du -sh /tmp/_size_check.zip | cut -f1) zipped (direct-upload limit 50 MB)"
rm -f /tmp/_size_check.zip
