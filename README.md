# Paper Template

A working structure for empirical papers with several coauthors. It has three parts:
1. A shared Dropbox folder for data, with one git clone per coauthor.
2. An SCons build that reruns only what changed, from raw data to compiled paper.
3. A provenance layer that records where each number, table and figure came from, and flags any passage written against results that have since changed.

Start a new paper with the `/new-paper` Claude Code skill, or by hand as described in **Setup** below.

## Layout

```
<Paper>/                              Dropbox: ~/Dropbox/Academic/Papers/<Paper>/
├── data/
│   ├── raw/                          raw inputs, never modified, shared
│   └── intermediate/                 heavy intermediates built on the server, shared
└── github/
    ├── ricardo/                      one clone of this repository per coauthor
    └── coauthor/
        ├── SConstruct                the build
        ├── setup.sh                  run once per clone
        ├── code/
        │   ├── setup.R               sourced by every R script
        │   ├── data/                 clean_*, assemble_* -> data/intermediate, data/clean
        │   ├── analysis/             tab_*, fig_* -> output/tables, output/figures
        │   ├── functions/            shared helpers
        │   ├── scons/extract_deps.py drafts SConscript blocks from R source
        │   └── provenance/           run records, save_value(), prov.py
        ├── data/{intermediate,clean}/  built locally            (not in git)
        ├── output/{tables,figures,logs,provenance}/  built      (not in git)
        ├── tmp/                                                 (not in git)
        └── products/
            ├── paper/                main.tex, sections/, references.bib, provenance.lock
            ├── talk/
            └── sub/                  shared styles, provenance.sty
```

Each coauthor's clone reads shared data at `../../data/raw/`. Built files stay inside the clone and out of git, so two coauthors never overwrite each other's builds. Dropbox syncs the clones, which lets you open a coauthor's branch without checking it out yourself. Git remains the record of what changed.

## Setup

1. Create `<Paper>/data/raw/` and `<Paper>/github/` in the shared Dropbox folder.
2. Clone the repository into `<Paper>/github/<you>/`.
3. Run `bash setup.sh`. It creates the local folders and checks for `scons`, `Rscript`, `latexmk` and `git`.
4. Run `scons -k`, then `scons -k paper`.

Requirements: [SCons](https://scons.org) (`brew install scons`), Python 3, R, and a TeX distribution with `latexmk`, XeLaTeX and biber. Stata is supported but optional.

## Building

```bash
scons -k                  # every out-of-date data step, table, figure and value
scons -k paper            # ... and products/paper/main.pdf
scons -k paper FINAL=1    # the PDF without provenance colours and tags
scons status              # what needs re-reading or rebuilding, and why
scons -n                  # dry run
scons --debug=explain -n  # why each target would rebuild
```

A target rebuilds when its script, `code/setup.R`, or a declared input changed. Each script is declared once in `code/data/SConscript` or `code/analysis/SConscript`, with its outputs as targets and the files it reads as sources:

```python
R(['#output/tables/tab_main.tex'],
  ['#code/analysis/tab_main.R', '#data/clean/unit-year.rds'])
```

`Py()` and `Stata()` declare Python and Stata scripts the same way. Draft the blocks for a whole folder with `python3 code/scons/extract_deps.py code/analysis code/data`, then review them. A script whose paths are built at run time needs its block written by hand. **An input that is not declared is not tracked.**

Two options from Structural Transformation and Politics carry over:
- **Server-only steps:** a SConscript declares them under `if HIGH_MEM:`. On a laptop their cached outputs in `../../data/intermediate/` are read as inputs.
- **Copied data:** on a machine whose `data/` was copied from elsewhere, `scons -k ADOPT=1` records the files on disk as built, without running anything.

## Provenance

Fast development leaves the draft out of sync with the code. A number gets typed from an old log. A paragraph describes a sample restriction that has since moved. A table is regenerated, but the sentence interpreting it is not. The provenance layer records what every number, exhibit and passage was built from, and reports which ones are out of date.

### Numbers: `save_value()` and `\val{}`

Scripts save the numbers the text cites, and the paper refers to them by key:

```r
save_value("beta_main", coef(m)[["treated"]], digits = 3)   # R
save_value("n_units", nobs(m))                               # 2,000
```
```python
from save_value import save_value                            # Python
save_value("beta_main", fit.params["treated"], digits=3)
```
```stata
save_value beta_main, value(_b[treated]) format(%9.3f)       // Stata
```
```latex
Treatment raises the outcome by \val{beta_main} units.
```

The paper never contains a hand-typed result. In the draft PDF, generated numbers are blue and show their script, commit and build time on hover. **A black number is one somebody typed.** A number shows in orange when it was built from uncommitted code, and an undefined key shows as a red `??key??`.

### Exhibits: `\exhibit{}` and `\exhibitgraphic{}`

```latex
\exhibit{tables/tab_main.tex}                         % \input from output/
\exhibitgraphic[width=.8\textwidth]{figures/fig_main.pdf}
```

Every generated `.tex` table starts with a comment naming its script, commit and build time. In the draft PDF, each exhibit carries the same tag underneath. If the code or data behind an exhibit changed after it was built, the tag reads `STALE`.

### Run records

Every script SCons runs writes `output/provenance/records/<script>.json`. The record holds:
- the commit, and any code inputs that differed from it;
- who built it, on which machine, and when;
- the content hash of every input and output;
- the values the script saved.

Linked through their inputs and outputs, the records form a tree from each exhibit back to raw data. `prov.py` compares the hashes in that tree with the files on disk now.

### Passages and sign-off

Every `\section` and `\subsection` is a passage, identified by its `\label`. A finer unit can be wrapped in a `passage` environment:

```latex
\begin{passage}{results-magnitude}[code/analysis/tab_main.R]
...
\end{passage}
```

A passage depends on three kinds of thing:
1. every `\val` in it;
2. every exhibit in it, plus any exhibit it `\cref`s;
3. every file named in `\dependson{...}`, or in the passage's optional argument (globs allowed).

Use `\dependson` for prose that describes code rather than citing outputs. The empirical-strategy section is the typical case: `\dependson{code/functions/designs.R}`.

Signing off records what a passage depended on when someone last checked it:

```bash
python3 code/provenance/prov.py signoff sec:results     # one passage (globs allowed: 'sec:*')
python3 code/provenance/prov.py signoff --clean         # every unsigned passage without issues
```

The sign-offs live in `products/paper/provenance.lock`. Commit the lock together with the text it vouches for. From then on, each passage is in one of five states:

| State | Meaning | Margin of the draft PDF |
|---|---|---|
| ok | nothing it depends on changed since sign-off | — |
| pending | its inputs are unchanged, but an upstream script or data file changed, so the next build will change something it cites | orange |
| changed | a value, exhibit or declared file differs from sign-off; the report lists old → new | red |
| broken | it cites a value or exhibit that does not exist | red |
| unsigned | nobody has signed it off | grey, with the `unsigned` package option |

### Commands

```bash
python3 code/provenance/prov.py status              # what needs attention (scons status)
python3 code/provenance/prov.py status --strict     # exit 1 if anything is stale: run before circulating
python3 code/provenance/prov.py tree sec:results    # dependency tree of a passage, down to raw data
python3 code/provenance/prov.py impact code/data/clean_x.R   # everything downstream of a change
python3 code/provenance/prov.py values              # every value, its script and commit
python3 code/provenance/prov.py lint                # checks that need no build (run in CI)
```

Example, after changing the data step but before rebuilding:

```
PENDING  sec:results-main  "Main estimates"  products/paper/sections/results.tex:3
           upstream: input data/clean/unit.rds is stale (rebuild code/data/simulate_example.R)
```

After `scons -k`:

```
CHANGED  sec:results-main  "Main estimates"  products/paper/sections/results.tex:3
           out:tables/tab_example.tex: df5b1698 -> 6610158e (code/analysis/tab_example.R @ a19226d)
           val:beta_treated: 0.296 -> 0.196 (code/analysis/tab_example.R @ a19226d)
```

### What it cannot do

Provenance cannot tell that a passage is wrong. It can only tell that something the passage depends on changed since a person last checked it. A dependency that is neither cited (`\val`, `\exhibit`) nor declared (`\dependson`) is invisible to it. Coverage is therefore only as good as the declarations, and it improves the more the text cites through `\val` and `\exhibit`.

## Continuous integration

`.github/workflows/checks.yml` runs on every pull request. Its checks need no data:

| Check | What it catches |
|---|---|
| R scripts parse | syntax errors, before a long build reaches them |
| Python compiles, SConstruct loads, provenance lint | malformed SConscripts, two scripts with the same name, duplicate passage ids, `\dependson` paths that do not exist, sign-offs for deleted passages |
| Repository checks | tracked data files or files over 5 MB; scripts not declared in a SConscript; added lines that call `setwd()`, `rm(list = ls())` or `install.packages()`, or hardcode an absolute path |
| Secret scan | credentials committed by mistake (gitleaks) |

`template-selftest.yml` runs the toy pipeline end to end, but only in `rdahis/paper_template`. Delete it in a new paper.

## Starting from the toy example

The template ships a toy pipeline to show every piece working:
- `simulate_example.R` writes simulated data;
- `tab_example.R` and `fig_example.R` build a table and a figure and save values;
- the paper sections cite them.

To make it your paper, delete the toy scripts and their blocks in the SConscripts, then replace the section text. Keep the `\label`s on sections and subsections: they are the passage ids.

## Working conventions

- **Issues are tasks.** One person is responsible for each, and each carries a label (`build`, `analysis`, `writing`, `review`).
- **Branches and pull requests.** All changes go through pull requests, with [conventional commit](https://www.conventionalcommits.org) messages.
- **Revisions.** For an R&R, give each referee comment its own issue and record the issue number next to the comment. Once all of them are closed, the response letter follows from the pull requests.
- **Data documentation.** One `data/clean/<level>.rds` per observation level (`unit-year.rds`), and every cleaning step named for its source (`clean_<source>.R`).

## Further reading

- [Gentzkow & Shapiro (2014), Code and Data for the Social Sciences](https://web.stanford.edu/~gentzkow/research/CodeAndData.pdf)
- [Gentzkow & Shapiro Lab's template](https://github.com/gslab-econ/template)
- [Julian Reif's Stata coding guide](https://reifjulian.github.io/guide)
