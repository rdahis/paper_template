#!/bin/bash
# setup.sh -- prepare a fresh clone. Run once from the repository root.
#
# Expected layout (the paper's shared Dropbox folder):
#   <Paper>/data/raw/            raw inputs, shared by all coauthors
#   <Paper>/data/intermediate/   heavy intermediates built on the server
#   <Paper>/github/<you>/        this repository (one clone per coauthor)
set -u

mkdir -p data/intermediate data/clean output/tables output/figures output/logs tmp

if [ -d ../../data/raw ]; then
  echo "ok: shared data at $(cd ../../data && pwd)"
else
  echo "warning: ../../data/raw not found. Clone this repository into <Paper>/github/<you>/,"
  echo "         next to the shared <Paper>/data/ folder."
fi

for tool in scons Rscript python3 latexmk git; do
  if command -v "$tool" > /dev/null; then echo "ok: $tool"; else echo "missing: $tool"; fi
done
command -v scons > /dev/null || echo "  install SCons with: brew install scons  (or pip install scons)"

# On a machine whose data/ was copied from elsewhere, record it as built
# instead of rebuilding everything:  scons -k ADOPT=1
