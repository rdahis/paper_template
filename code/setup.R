# setup.R -- sourced first by every R script (SCons adds it as a dependency of
# each one, so editing it rebuilds everything).
#
# Paths. Scripts run from the repository root. Repo-local build artifacts live
# in data/intermediate/ and data/clean/; raw data and server-built heavy files
# live in the paper's shared Dropbox folder, two levels up:
#   <Paper>/data/raw/            raw inputs, never modified
#   <Paper>/data/intermediate/   heavy intermediates built on the server
#   <Paper>/github/<you>/        this repository
# Write those paths as literals, here::here("../../data/raw/<source>/<file>"),
# so code/scons/extract_deps.py can read them.
#
# Packages. Pin versions with groundhog when the project starts:
#   library(groundhog); groundhog.library(c("data.table", "fixest"), "2026-10-01")

suppressPackageStartupMessages({
  library(here)
})

source(here::here("code/provenance/save_value.R"))
