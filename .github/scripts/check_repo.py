"""Repository checks that need no data: run by .github/workflows/checks.yml.

Three checks, each printed as its own section:

1. Data files: no data file (.rds, .csv, .parquet, ...) and nothing over
   MAX_MB is tracked. Data lives in data/ and ../../data/, never in git.
2. Orphan scripts: every script in code/data/ and code/analysis/ is named in
   its SConscript (a comment counts, so a script run by hand is fine once it
   is documented there). Every helper in code/functions/ is sourced by at
   least one live script.
3. Banned patterns: lines *added* relative to --base must not call setwd(),
   rm(list = ls()), install.packages() or hardcode an absolute path. Only the
   diff is checked, so existing lines do not fail the build.

Usage: python .github/scripts/check_repo.py [--base <git ref>]
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys

MAX_MB = 5
DATA_EXT = {'.rds', '.rda', '.rdata', '.dta', '.parquet', '.feather', '.fst',
            '.csv', '.tsv', '.xls', '.xlsx', '.shp', '.dbf', '.gpkg', '.tif',
            '.tiff', '.zip', '.gz', '.7z', '.sav'}
SCRIPT_DIRS = ['code/data', 'code/analysis']
SKIP_DIRS = ('code/old/', 'code/explorations/')

BANNED = [
    (re.compile(r'\bsetwd\s*\(|\bos\.chdir\s*\('), 'changes the working directory (INV-19)'),
    (re.compile(r'\brm\s*\(\s*list\s*=\s*ls\s*\('), 'rm(list = ls()) (INV-19)'),
    (re.compile(r'\binstall\.packages\s*\('), 'install.packages() outside code/setup.R (INV-19)'),
    (re.compile(r'''["'](/Users/|/home/|~/|[A-Za-z]:[\\/])'''), 'absolute path (INV-16)'),
]
# setup.R is the one place allowed to install packages.
BANNED_EXEMPT = {'code/setup.R': {'install.packages() outside code/setup.R (INV-19)'}}


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True,
                          text=True).stdout


def tracked():
    return [f for f in git('ls-files', '-z').split('\0') if f]


def check_data_files(files):
    bad = []
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        size = os.path.getsize(f) / 1e6 if os.path.exists(f) else 0
        if ext in DATA_EXT:
            bad.append(f'{f}: data file ({ext}) is tracked')
        elif size > MAX_MB:
            bad.append(f'{f}: {size:.1f} MB exceeds {MAX_MB} MB')
    return bad


def check_orphans(files):
    def read(path):
        return open(path, encoding='utf-8').read() if os.path.exists(path) else ''

    bad = []
    for d in SCRIPT_DIRS:
        text = read(f'{d}/SConscript')
        # Glob tokens in comments, e.g. "build_olb_*.R", also account for scripts.
        globs = set(re.findall(r'[\w*]+\*[\w*]*\.(?:R|py|do)', text))
        for f in files:
            if os.path.dirname(f) != d or not f.endswith(('.R', '.py', '.do')):
                continue
            name = os.path.basename(f)
            if name not in text and not any(fnmatch.fnmatch(name, g) for g in globs):
                bad.append(f'{f}: not named in {d}/SConscript')

    live = [f for f in files if f.startswith('code/') and f.endswith('.R')
            and not f.startswith(SKIP_DIRS)]
    sources = ''.join(read(f) for f in live if not f.startswith('code/functions/'))
    for f in files:
        if f.startswith('code/functions/') and f.endswith('.R'):
            if os.path.basename(f) not in sources:
                bad.append(f'{f}: not sourced by any live script')
    return bad


def check_banned(base):
    diff = git('diff', '--unified=0', '--no-color', f'{base}...HEAD', '--',
               '*.R', '*.py', '*.do', ':!code/old/*', ':!code/explorations/*', ':!.github/*')
    bad, path, line_no = [], None, 0
    for line in diff.splitlines():
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else None
        elif line.startswith('@@'):
            line_no = int(re.search(r'\+(\d+)', line).group(1))
        elif line.startswith('+') and path:
            code = line[1:]
            if not code.lstrip().startswith('#'):
                for pattern, label in BANNED:
                    if label in BANNED_EXEMPT.get(path, set()):
                        continue
                    if pattern.search(code):
                        bad.append(f'{path}:{line_no}: {label}\n    {code.strip()}')
            line_no += 1
    return bad


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', help='git ref to diff against for banned patterns')
    args = parser.parse_args()

    files = tracked()
    sections = [('Data files', check_data_files(files)),
                ('Orphan scripts', check_orphans(files))]
    if args.base:
        sections.append(('Banned patterns in added lines', check_banned(args.base)))
    else:
        print('Banned patterns: skipped (no --base)\n')

    failed = False
    for title, problems in sections:
        print(f'{title}: {"FAIL" if problems else "ok"}')
        for p in problems:
            print(f'  {p}')
            # GitHub annotation: shows on the PR's Files tab.
            loc = p.split(':')[0]
            print(f'::error file={loc}::{title}: {p.splitlines()[0]}')
        failed |= bool(problems)
        print()
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
