# CLAUDE.md — {{PAPER_TITLE}}

Context for Claude Code sessions in this repository.

## Project

{{ONE_PARAGRAPH: question, unit of analysis, design.}}

**Authors:** {{AUTHORS}}

## Layout

This repository is one coauthor's clone, living at `<Paper>/github/<author>/` inside the shared Dropbox folder.
- **Shared data** lives two levels up: `../../data/raw/` holds raw inputs and is read only; `../../data/intermediate/` holds heavy server-built files.
- **Local builds** go to `data/{intermediate,clean}/`, `output/` and `tmp/`. All three are git-ignored, and each coauthor builds their own.
- **Source:** code is in `code/`; LaTeX is in `products/`.

See README.md for the full tree.

## Build

- `scons -k` rebuilds every out-of-date data step, table, figure and value. `scons -k paper` also compiles the paper. Never run scripts outside SCons to produce outputs the paper uses, because they would get no run record.
- Every script is declared in `code/data/SConscript` or `code/analysis/SConscript`, using `R()`, `Py()` or `Stata()`.
  - **When you add or change a script**, update its block so that every file it reads is a source and every file it writes is a target. An undeclared input is not tracked.
  - Draft blocks with `python3 code/scons/extract_deps.py <dir> <other dirs>`, then review the draft.
- **Naming:** `code/data/clean_<source>.R` turns one raw source into an intermediate; `assemble_<level>.R` writes `data/clean/<level>.rds`, one file per observation level; `code/analysis/tab_*` and `fig_*` write `output/tables/` and `output/figures/`.
- **Tables** are bare `tabular` with booktabs rules. Their caption, label and notes live in the paper.
- **Figures** carry no title; the caption carries it.
- **R conventions:** paths via `here::here()`; shared data as literal `here::here("../../data/raw/...")`; packages loaded only in `code/setup.R`; `set.seed()` once, at the top of a stochastic script. No `setwd()`, `rm(list = ls())` or `install.packages()` in scripts (CI blocks these).

## Provenance rules

1. **Never type a result into the paper.** A script saves the number with `save_value("key", x, digits = 3)` (R), `save_value(...)` (Python) or `save_value key, value(...)` (Stata), and the paper writes `\val{key}`.
2. **Generated exhibits** go in with `\exhibit{tables/x.tex}` and `\exhibitgraphic[...]{figures/x.pdf}`, never a raw `\input` or `\includegraphics` of `output/`.
3. **Keep a `\label` on every `\section` and `\subsection`.** Labels are passage ids, and renaming one orphans its sign-off; after a deliberate rename, run `prov.py prune`.
4. **Prose that describes code** (data construction, empirical strategy, sample restrictions) declares that code with `\dependson{code/...}`.
5. **Before editing a passage, read its status:** `python3 code/provenance/prov.py status`, and `tree <id>` for detail. A `changed` passage lists old → new values; rewrite the text to match the new values, not just the numbers.
6. **Sign-off is a human act.** Run `prov.py signoff` only when the user asks. It records that a person checked the text against its current dependencies.
7. **Before circulating a draft**, run `prov.py status --strict`. It exits 1 if anything is stale.

## Workflow

- Issues are tasks, and all changes go through pull requests with conventional commit messages.
- CI (`.github/workflows/checks.yml`) runs four checks that need no data: R parse, provenance lint, repository checks and a secret scan.
