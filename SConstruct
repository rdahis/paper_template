# SConstruct -- dependency-tracked build, from data to paper, with provenance.
#
# Usage (from the repository root):
#   scons -k                 build every out-of-date data step, table, figure and value
#   scons -k paper           ... and compile products/paper/main.pdf (draft provenance)
#   scons -k paper FINAL=1   ... compile without provenance colours and tags
#   scons status             passages, values and exhibits that need attention
#   scons -n                 dry run: what would rebuild
#   scons --debug=explain -n why each target is out of date
#   scons -k ADOPT=1         record existing data outputs as built, run nothing
#
# A target rebuilds when its script, code/setup.R, or an input it reads changed
# since its last build. Declarations live in code/{data,analysis}/SConscript,
# drafted by code/scons/extract_deps.py and reviewed by hand. Build state lives
# in .sconsign.dblite, per machine (git-ignored).
#
# Provenance. Every script run writes output/provenance/records/<script>.json:
# the commit, the hashes of every input and output, and the values the script
# saved with save_value(). code/provenance/prov.py reads these records to say
# which exhibits, numbers and passages are out of date, and why.

import os
import subprocess
import sys
import tempfile
import time
from fnmatch import fnmatch
from glob import glob

sys.path.insert(0, os.path.join(Dir('#').abspath, 'code', 'provenance'))
import core  # noqa: E402
import text  # noqa: E402

env = Environment(ENV=dict(os.environ))

# Hash a file only when its timestamp changes. Full MD5 on every run would read
# every large input each time; a Dropbox sync that touches the mtime costs one
# re-hash on the other machine and no rebuild if the content is equal.
env.Decider('MD5-timestamp')

# Machine class: declared, never detected. A SConscript may declare server-only
# steps under `if HIGH_MEM:`; elsewhere their cached outputs are read as inputs.
HIGH_MEM = os.environ.get('HIGH_MEM', 'false') == 'true'
env['ENV']['HIGH_MEM'] = 'true' if HIGH_MEM else 'false'

# Python scripts import save_value from here; Stata finds save_value.ado here.
PROV_DIR = os.path.join(Dir('#').abspath, 'code', 'provenance')
env['ENV']['PYTHONPATH'] = os.pathsep.join(filter(None, [PROV_DIR, os.environ.get('PYTHONPATH')]))
env['ENV']['S_ADO'] = f'{PROV_DIR};BASE;SITE;PLUS;PERSONAL;OLDPLACE'
STATA = os.environ.get('STATA', 'stata-mp')
# The interpreter on PATH, not the one bundled with SCons, which lacks your packages.
PYTHON = os.environ.get('PYTHON', 'python3')

LOG_DIR = 'output/logs/scons'

# ADOPT=1 records the data files already on disk as built from the current
# scripts and inputs, without running anything. Only code/data/ is read. Use
# it once on a machine whose data/ predates SCons; adoption trusts the files.
ADOPT = ARGUMENTS.get('ADOPT', '0') == '1'
FINAL = ARGUMENTS.get('FINAL', '0') == '1'

ROOT = Dir('#').abspath


def exists(path):
    """os.path.exists for a repo-relative path, from any SConscript."""
    return os.path.exists(os.path.join(ROOT, path.lstrip('#')))


def _glob(pattern):
    return sorted(os.path.relpath(p, ROOT) for p in glob(os.path.join(ROOT, pattern.lstrip('#'))))


def _repo(node):
    return core.rel(os.path.relpath(node.abspath, ROOT))


RUNNERS = {
    'R': lambda s: ['Rscript', '--vanilla', s],
    'Py': lambda s: [PYTHON, s],
    'Stata': lambda s: [STATA, '-b', 'do', s],
}


def _run(lang):
    def action(target, source, env):
        script, log = str(source[0]), str(target[0])
        record = target[1]
        outs = [_repo(t) for t in target[2:]]
        if ADOPT:
            missing = [o for o in outs if not exists(o) and not o.startswith('output/')]
            if missing:
                sys.stderr.write(f'!!! {script} not adopted; missing: {", ".join(missing)}\n')
                return 1
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, 'w') as fh:
                fh.write(f'Adopted (ADOPT=1): outputs on disk recorded as built; {script} was not run.\n')
            core.write_record(_repo(source[0]), [_repo(s) for s in source], outs, {}, core.now(), 0)
            return 0

        fd, values = tempfile.mkstemp(prefix='prov-', suffix='.jsonl')
        os.close(fd)
        run_env = dict(env['ENV'], PROV_VALUES=values, PROV_SCRIPT=_repo(source[0]))
        started, t0 = core.now(), time.time()
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, 'w') as fh:
            rc = subprocess.call(RUNNERS[lang](script), cwd=ROOT, env=run_env,
                                 stdout=fh, stderr=subprocess.STDOUT)
        if lang == 'Stata':
            # Stata writes <script>.log into the working directory and exits 0
            # even when the do-file fails; the log is the only evidence.
            slog = os.path.join(ROOT, os.path.splitext(os.path.basename(script))[0] + '.log')
            if os.path.exists(slog):
                os.replace(slog, log)
                with open(log, errors='replace') as fh:
                    if any(line.startswith('r(') for line in fh):
                        rc = rc or 1
        if rc != 0:
            os.remove(values)
            with open(log, errors='replace') as fh:
                tail = fh.readlines()[-15:]
            sys.stderr.write(f'!!! {script} failed (exit {rc}); last lines of {log}:\n')
            sys.stderr.write(''.join(tail))
            return rc
        core.write_record(_repo(source[0]), [_repo(s) for s in source], outs,
                          core.read_values(values), started, time.time() - t0)
        os.remove(values)
        return 0
    return action


def _show(target, source, env):
    return f'>>> {os.path.basename(str(source[0]))}'


# Files every script of a language depends on: editing one rebuilds them all.
SETUP = {
    'R': ['#code/setup.R', '#code/provenance/save_value.R'],
    'Py': ['#code/provenance/save_value.py'],
    'Stata': ['#code/provenance/save_value.ado'],
}
records = []


def _declare(lang, targets, sources):
    """One script. sources[0] is the script; its log and run record are targets."""
    script = str(sources[0]).lstrip('#')
    stem = os.path.splitext(os.path.basename(script))[0]
    log = f'#{LOG_DIR}/{stem}.log'
    record = '#' + os.path.relpath(core.record_path(script), ROOT)
    if any(str(r) == record.lstrip('#') for r in records):
        raise SystemExit(f'Two scripts share the stem "{stem}": rename one ({script}).')
    targets = list(dict.fromkeys([log, record] + list(targets)))
    sources = list(dict.fromkeys(list(sources) + [s for s in SETUP[lang] if exists(s)]))
    # A script that reads back a cache it writes would otherwise depend on itself.
    sources = [s for s in sources if s not in targets]
    node = env.Command(targets, sources, Action(_run(lang), _show))
    records.append(node[1])
    # SCons deletes a target before rebuilding it. Outside output/ a target is a
    # cache that can take hours to rebuild, so it is never deleted; the script
    # overwrites it, or reuses it, itself.
    env.Precious(targets if ADOPT else [t for t in targets if not str(t).lstrip('#').startswith('output/')])
    return node


def R(targets, sources):
    return _declare('R', targets, sources)


def Py(targets, sources):
    return _declare('Py', targets, sources)


def Stata(targets, sources):
    return _declare('Stata', targets, sources)


def outputs(pattern, exclude=()):
    """Expand a family of outputs (one PDF per spec) from files on disk.

    The first build on a fresh machine tracks only the log; later builds see
    the files. exclude lists paths or patterns another script owns.
    """
    return ['#' + p for p in _glob(pattern) if not any(fnmatch(p, e) for e in exclude)]


def inputs(pattern):
    """Expand a family of inputs (one raster per year) from files on disk."""
    return ['#' + p for p in _glob(pattern)]


def env_flag(name, default='false'):
    return os.environ.get(name, default).lower() in ('1', 'true', 'yes')


Export('env', 'R', 'Py', 'Stata', 'outputs', 'inputs', 'env_flag', 'exists', 'HIGH_MEM')

SConscript('code/data/SConscript')
if not ADOPT:
    SConscript('code/analysis/SConscript')

# --- provenance registry: every value and exhibit, for the paper ------------
registry = env.Command(
    '#output/provenance/registry.tex', records,
    Action(lambda target, source, env: text.write_registry(str(target[0])), '>>> registry.tex'))
pipeline = records + registry
Default(pipeline)


# --- documents ---------------------------------------------------------------
def document(name, main):
    """A LaTeX document: its sources, the exhibits it reads, the registry, and
    the passage status file the draft reads. latexmk handles the passes."""
    if not exists(main):
        return None
    doc = text.Document(main)
    status_tex = f'#output/provenance/status-{name}.tex'
    status = env.Command(
        status_tex, [registry] + ['#' + f for f in doc.files] + ([f'#{os.path.relpath(doc.lock_path, ROOT)}']
                                                                  if os.path.exists(doc.lock_path) else []),
        Action(f'"{sys.executable}" code/provenance/prov.py --doc {main} status --tex {status_tex[1:]} > /dev/null',
               f'>>> status-{name}.tex'))
    env.AlwaysBuild(status)  # it reads hashes of files SCons does not track
    folder = os.path.dirname(main)
    pretex = r" -usepretex='\def\provfinal{}'" if FINAL else ''
    pdf = env.Command(
        '#' + main.replace('.tex', '.pdf'),
        ['#' + f for f in doc.files] + ['#output/' + e[4:] for e in doc.exhibits()]
        + [registry, status, env.Value(FINAL)] + inputs(f'{folder}/*.bib') + inputs('products/*.bib')
        + inputs('products/sub/*.sty'),
        Action(f'cd "{folder}" && latexmk -silent -interaction=nonstopmode{pretex} {os.path.basename(main)}',
               f'>>> {main}'))
    env.Precious(pdf)
    env.Alias(name, pdf)
    return pdf


paper = document('paper', 'products/paper/main.tex')
talk = document('talk', 'products/talk/main.tex')
env.Alias('docs', [d for d in (paper, talk) if d])

status = env.Command('status-report', records,
                     f'"{sys.executable}" code/provenance/prov.py status')
env.AlwaysBuild(status)
env.Alias('status', status)

Help("""
scons -k                 build everything out of date (data, tables, figures, values)
scons -k paper           ... and compile the paper (talk, docs for the talk / both)
scons -k paper FINAL=1   compile without provenance colours and tags
scons status             what needs re-reading or rebuilding, and why
scons -n                 dry run
scons -k ADOPT=1         record existing data outputs as up to date without running anything
python3 code/provenance/prov.py --help    sign-off, dependency trees, impact of a change
""")
