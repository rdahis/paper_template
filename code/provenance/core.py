"""Provenance core: content hashes, git metadata, run records, the staleness graph.

Every script SCons runs leaves one run record, output/provenance/records/<stem>.json:

    script        repo-relative path of the script
    script_hash   content hash of the script when it ran
    git           commit, branch, and the code inputs that differed from it
    built_at/by   ISO timestamp, git user.name, machine
    inputs        {path: hash} for every declared source, script included
    outputs       {path: hash} for every declared target that exists
    values        {key: {value, text, note}} saved by save_value() during the run

The records are the provenance tree. An output's record names the inputs it was
built from; an input that is itself an output has its own record; and so on down
to raw data. Comparing recorded hashes with the files on disk now says which
outputs are stale, and why, without asking SCons.

Hashes. Text outputs (.tex, .txt, .csv, .md) are hashed without their %-comment
lines, so the provenance stamp written into a table never changes its hash. PDFs
are hashed without CreationDate/ModDate/ID, which R and matplotlib write fresh on
every run. Everything else is hashed byte for byte. Hashes are cached by (size,
mtime) in output/provenance/hashcache.json, so a 14GB input is read once, not on
every query.
"""

import datetime
import getpass
import hashlib
import json
import os
import re
import socket
import subprocess
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = os.path.join(ROOT, 'output')
PROV = os.path.join(OUT, 'provenance')
RECORDS = os.path.join(PROV, 'records')
CACHE_PATH = os.path.join(PROV, 'hashcache.json')

TEXT_EXT = {'.tex', '.txt', '.csv', '.md'}
PDF_VOLATILE = re.compile(rb'/(?:CreationDate|ModDate)\s*\(D:[^)]*\)|/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]')
COMMENT_LINE = re.compile(r'^\s*%.*$', re.M)
STAMP_PREFIX = '% provenance:'

_lock = threading.Lock()
_cache = None


def rel(path):
    """Repo-relative path with forward slashes ('../../data/raw/x' stays as is)."""
    return os.path.relpath(os.path.abspath(os.path.join(ROOT, path)), ROOT).replace(os.sep, '/')


def absolute(path):
    return os.path.abspath(os.path.join(ROOT, path))


# --- hashing -----------------------------------------------------------------

def _load_cache():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_PATH) as fh:
                _cache = json.load(fh)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache():
    os.makedirs(PROV, exist_ok=True)
    tmp = f'{CACHE_PATH}.{os.getpid()}.{threading.get_ident()}'
    with open(tmp, 'w') as fh:
        json.dump(_cache, fh, sort_keys=True)
    os.replace(tmp, CACHE_PATH)


def _hash_file(path):
    ext = os.path.splitext(path)[1].lower()
    h = hashlib.md5()
    if ext in TEXT_EXT:
        with open(path, encoding='utf-8', errors='replace') as fh:
            h.update(COMMENT_LINE.sub('', fh.read()).encode())
    elif ext == '.pdf':
        with open(path, 'rb') as fh:
            h.update(PDF_VOLATILE.sub(b'', fh.read()))
    else:
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                h.update(chunk)
    return h.hexdigest()


def file_hash(path, save=True):
    """Normalised content hash of a repo-relative path; None if it does not exist."""
    p = absolute(path)
    if os.path.isdir(p):
        # A directory input stands for its files: hash the sorted (name, hash) list.
        h = hashlib.md5()
        for dirpath, _, names in sorted(os.walk(p)):
            for n in sorted(names):
                f = os.path.join(dirpath, n)
                h.update(f'{os.path.relpath(f, p)}:{file_hash(rel(f), save=False)}\n'.encode())
        if save:
            with _lock:
                _save_cache()
        return h.hexdigest()
    try:
        st = os.stat(p)
    except OSError:
        return None
    key = rel(path)
    with _lock:
        cache = _load_cache()
        hit = cache.get(key)
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
            return hit[2]
    digest = _hash_file(p)
    with _lock:
        cache = _load_cache()
        cache[key] = [st.st_size, st.st_mtime_ns, digest]
        if save:
            _save_cache()
    return digest


# --- git ---------------------------------------------------------------------

def git(*args):
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def git_info(code_paths=()):
    """HEAD, branch, and which of code_paths differ from HEAD (edited or untracked)."""
    commit = git('rev-parse', 'HEAD')
    dirty = []
    if code_paths:
        tracked = [p for p in code_paths if not p.startswith('../')]
        status = git('status', '--porcelain', '--', *tracked) if tracked else ''
        dirty = sorted({line[3:].strip() for line in status.splitlines() if line.strip()})
    return {
        'commit': commit[:7],
        'commit_full': commit,
        'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
        'dirty': dirty,
    }


def who():
    return git('config', 'user.name') or getpass.getuser()


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


# --- run records -------------------------------------------------------------

def record_path(script):
    return os.path.join(RECORDS, os.path.splitext(os.path.basename(script))[0] + '.json')


def read_values(path):
    """Values a run saved: one JSON object per line; a later line wins per key."""
    values = {}
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                if line.strip():
                    v = json.loads(line)
                    values[v.pop('key')] = v
    return values


def stamp_text_outputs(outputs, info):
    """Write a provenance comment as the first line of each generated .tex file."""
    tag = info['git']['commit'] + ('+dirty' if info['git']['dirty'] else '')
    line = (f"{STAMP_PREFIX} {info['script']} @ {tag}, built {info['built_at']} "
            f"by {info['built_by']} -- do not edit, rebuild with scons\n")
    for out in outputs:
        p = absolute(out)
        if not out.endswith('.tex') or not os.path.exists(p):
            continue
        with open(p, encoding='utf-8', errors='replace') as fh:
            body = [ln for ln in fh.readlines() if not ln.startswith(STAMP_PREFIX)]
        with open(p, 'w', encoding='utf-8') as fh:
            fh.writelines([line] + body)


def write_record(script, inputs, outputs, values, started, duration):
    """Hash inputs and outputs, stamp .tex outputs, and write the run record."""
    code = [p for p in inputs if p.startswith('code/')]
    info = {
        'script': script,
        'script_hash': file_hash(script, save=False),
        'git': git_info(code),
        'built_at': started,
        'built_by': who(),
        'machine': socket.gethostname().split('.')[0],
        'duration_s': round(duration, 1),
        'values': values,
    }
    stamp_text_outputs(outputs, info)
    info['inputs'] = {p: file_hash(p, save=False) for p in inputs}
    info['outputs'] = {p: file_hash(p, save=False) for p in outputs if os.path.exists(absolute(p))}
    with _lock:
        _save_cache()
    os.makedirs(RECORDS, exist_ok=True)
    path = record_path(script)
    with open(path, 'w') as fh:
        json.dump(info, fh, indent=1, sort_keys=True)
        fh.write('\n')
    return path


def load_records():
    records = {}
    if os.path.isdir(RECORDS):
        for name in sorted(os.listdir(RECORDS)):
            if name.endswith('.json'):
                with open(os.path.join(RECORDS, name)) as fh:
                    r = json.load(fh)
                records[r['script']] = r
    return records


# --- the graph ---------------------------------------------------------------

class Graph:
    """Run records joined into a DAG, with staleness computed against disk now.

    A record is stale when its script, or any input, differs from the hash it
    recorded, or when an input is the output of a record that is itself stale.
    The second rule is what carries a change in a cleaning script down to every
    table built from its output before anything has been rebuilt.
    """

    def __init__(self, records=None):
        self.records = load_records() if records is None else records
        self.producer = {}
        for script, r in self.records.items():
            for out in r['outputs']:
                self.producer[out] = script
        self.values = {}
        self.duplicates = {}
        for script, r in self.records.items():
            for key, v in r.get('values', {}).items():
                if key in self.values and self.values[key]['script'] != script:
                    self.duplicates.setdefault(key, {self.values[key]['script']}).add(script)
                self.values[key] = dict(v, script=script)
        self._why = {}

    def why_stale(self, script, _seen=None):
        """Reasons the record for `script` is stale ([] if current)."""
        if script in self._why:
            return self._why[script]
        seen = (_seen or set()) | {script}
        r = self.records[script]
        why = []
        if file_hash(script) != r['script_hash']:
            why.append(f'script {script} changed')
        for path, recorded in r['inputs'].items():
            if path == script:
                continue
            current = file_hash(path)
            if current is None:
                why.append(f'input {path} is missing')
            elif current != recorded:
                why.append(f'input {path} changed')
            up = self.producer.get(path)
            if up and up not in seen and self.why_stale(up, seen):
                why.append(f'input {path} is stale (rebuild {up})')
        for path, recorded in r['outputs'].items():
            current = file_hash(path)
            if current is None:
                why.append(f'output {path} is missing')
            elif current != recorded:
                why.append(f'output {path} was modified after the build')
        self._why[script] = why
        return why

    def tag(self, script):
        """'abc1234' or 'abc1234+dirty' for the commit a record was built from."""
        g = self.records[script]['git']
        return g['commit'] + ('+dirty' if g['dirty'] else '')
