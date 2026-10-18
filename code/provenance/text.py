"""Prose provenance: passages, their dependencies, sign-off, and staleness.

A passage is a unit of text someone vouches for. There are two kinds:

  - every \\section and \\subsection, from its heading to the next one. Its id is
    its \\label (unlabelled ones get an unstable "auto:" id and a lint warning);
  - an explicit  \\begin{passage}{id}[deps] ... \\end{passage},  for a finer unit.
    Its text is carved out of the subsection around it.

A passage depends on
  - val:KEY          every \\val{KEY} in it
  - out:PATH         every \\exhibit{PATH} / \\exhibitgraphic{PATH} in it, every
                     \\input or \\includegraphics of a file under output/, and the
                     exhibit inside any float it \\cref's or \\ref's
  - file:PATH        every path in \\dependson{...} or in the passage's [deps];
                     globs allowed. val:KEY and output/... are accepted there too.

Signing off (prov.py signoff ID) records the current fingerprint of each
dependency in provenance.lock, next to the document. From then on the passage is

  ok         nothing it depends on changed
  changed    a value, exhibit or file differs from what it was at sign-off
  pending    nothing changed yet, but an upstream script or input did, so a
             rebuild will change something it depends on
  broken     a dependency cannot be resolved (undefined value, missing exhibit)
  unsigned   never signed off

The lock is versioned with the paper, so sign-offs travel between coauthors.
"""

import bisect
import fnmatch
import glob
import hashlib
import json
import os
import re

from core import Graph, ROOT, absolute, file_hash, git, now, rel, who

DEFAULT_DOC = 'products/paper/main.tex'
STATES = ('broken', 'changed', 'pending', 'unsigned', 'ok')

COMMENT = re.compile(r'(?<!\\)%.*$')
INCLUDE = re.compile(r'\\(?:input|include)\s*\{([^}]*)\}')
SECTION = re.compile(r'\\(section|subsection)(\*?)\s*(?:\[[^\]]*\])?\s*\{')
LABEL_AFTER = re.compile(r'\s*\\label\s*\{([^}]*)\}')
PASSAGE_BEGIN = re.compile(r'\\begin\{passage\}\s*\{([^}]*)\}(?:\s*\[([^\]]*)\])?')
PASSAGE_END = re.compile(r'\\end\{passage\}')
FLOAT = re.compile(r'\\begin\{(table|figure)(\*?)\}(.*?)\\end\{\1\2\}', re.S)
LABEL = re.compile(r'\\label\s*\{([^}]*)\}')
VAL = re.compile(r'\\val\s*\{([^}]*)\}')
EXHIBIT = re.compile(r'\\exhibit(?:graphic)?\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}')
RAW_OUT = re.compile(r'\\(?:input|includegraphics)\s*(?:\[[^\]]*\])?\s*\{[^}]*?output/([^}]*)\}')
DEPENDSON = re.compile(r'\\dependson\s*\{([^}]*)\}')
REF = re.compile(r'\\(?:[cC]ref|ref|autoref|vref|[cC]pageref|labelcref)\*?\s*\{([^}]*)\}')
KEY_OK = re.compile(r'^[A-Za-z0-9_.:-]+$')
GRAPHIC_EXT = ('', '.pdf', '.png', '.jpg', '.jpeg', '.eps')


def _group(text, i):
    """Content of the brace group opening at text[i], and the index after it."""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == '\\':
            j += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    return text[i + 1:], len(text)


def _split(arg):
    return [a.strip() for a in arg.split(',') if a.strip()]


class Document:
    """A LaTeX document with its \\input files expanded and comments stripped."""

    def __init__(self, main=DEFAULT_DOC):
        self.main = rel(main)
        self.dir = os.path.dirname(absolute(self.main))
        self.lock_path = os.path.join(self.dir, 'provenance.lock')
        self.files = []
        self._starts, self._locs, parts = [], [], []
        pos = 0
        for path, lineno, line in self._expand(absolute(self.main), set()):
            self._starts.append(pos)
            self._locs.append((path, lineno))
            parts.append(line)
            pos += len(line) + 1
        self.text = '\n'.join(parts)
        b = self.text.find('\\begin{document}')
        e = self.text.find('\\end{document}')
        self.body = (b + len('\\begin{document}') if b >= 0 else 0, e if e >= 0 else len(self.text))
        self.errors, self.warnings = [], []
        self.units = self._units()
        self.float_exhibits = self._floats()

    def _expand(self, path, seen):
        if path in seen or not os.path.exists(path):
            return
        seen = seen | {path}
        self.files.append(rel(os.path.relpath(path, ROOT)))
        with open(path, encoding='utf-8', errors='replace') as fh:
            for n, raw in enumerate(fh, 1):
                line = COMMENT.sub('', raw.rstrip('\n'))
                last = 0
                for m in INCLUDE.finditer(line):
                    target = m.group(1).strip()
                    resolved = os.path.normpath(os.path.join(self.dir, target))
                    if not resolved.endswith('.tex'):
                        resolved += '.tex'
                    # Only the document's own sources are expanded; an \input of a
                    # generated file under output/ is an exhibit, not more prose.
                    if '/output/' in resolved.replace(os.sep, '/') or not os.path.exists(resolved):
                        continue
                    yield rel(os.path.relpath(path, ROOT)), n, line[last:m.start()]
                    yield from self._expand(resolved, seen)
                    last = m.end()
                yield rel(os.path.relpath(path, ROOT)), n, line[last:]

    def where(self, offset):
        i = max(bisect.bisect_right(self._starts, offset) - 1, 0)
        return self._locs[i] if self._locs else (self.main, 0)

    def _units(self):
        lo, hi = self.body
        heads = []
        for m in SECTION.finditer(self.text, lo, hi):
            title, end = _group(self.text, m.end() - 1)
            lab = LABEL_AFTER.match(self.text, end)
            heads.append((m.start(), m.group(1), ' '.join(title.split()), lab.group(1) if lab else None))

        passages, open_ = [], None
        events = sorted([(m.start(), 'b', m) for m in PASSAGE_BEGIN.finditer(self.text, lo, hi)]
                        + [(m.start(), 'e', m) for m in PASSAGE_END.finditer(self.text, lo, hi)],
                        key=lambda x: x[0])
        for pos, kind, m in events:
            if kind == 'b':
                if open_:
                    f, n = self.where(pos)
                    self.errors.append(f'{f}:{n}: passage "{m.group(1)}" opens inside passage "{open_[1].group(1)}"')
                    continue
                open_ = (pos, m)
            elif open_:
                passages.append((open_[0], m.end(), open_[1]))
                open_ = None
        if open_:
            f, n = self.where(open_[0])
            self.errors.append(f'{f}:{n}: passage "{open_[1].group(1)}" is never closed')

        units = []
        bounds = [h[0] for h in heads] + [hi]
        first = heads[0][0] if heads else hi
        if self.text[lo:first].strip():
            units.append(dict(id='front', kind='front', title='Front matter', start=lo, end=first, deps=[]))
        for (start, level, title, label), end in zip(heads, bounds[1:]):
            if label:
                uid = label
            else:
                uid = 'auto:' + re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
                f, n = self.where(start)
                self.warnings.append(f'{f}:{n}: \\{level}{{{title}}} has no \\label; its sign-off '
                                     f'is keyed on the title ({uid}) and is lost if the title changes')
            units.append(dict(id=uid, kind=level, title=title, start=start, end=end, deps=[]))
        for start, end, m in passages:
            deps = _split(m.group(2) or '')
            units.append(dict(id=m.group(1).strip(), kind='passage', title=m.group(1).strip(),
                              start=start, end=end, deps=deps))

        # Carve each passage out of the section unit that contains it.
        for u in units:
            spans = [(s, e) for s, e, _ in passages if u['kind'] != 'passage' and u['start'] <= s < u['end']]
            text, cur = [], u['start']
            for s, e in spans:
                text.append(self.text[cur:s])
                cur = e
            text.append(self.text[cur:u['end']])
            u['text'] = ''.join(text)
            u['file'], u['line'] = self.where(u['start'])

        seen = {}
        for u in units:
            if u['id'] in seen:
                self.errors.append(f"{u['file']}:{u['line']}: duplicate passage id \"{u['id']}\" "
                                   f"(also {seen[u['id']]})")
            seen[u['id']] = f"{u['file']}:{u['line']}"
        return units

    def _floats(self):
        """{float label: [out:path, ...]} for every table/figure holding an exhibit."""
        found = {}
        for m in FLOAT.finditer(self.text):
            body = m.group(3)
            exhibits = [_out(p) for p in EXHIBIT.findall(body)] + [_out(p) for p in RAW_OUT.findall(body)]
            for label in LABEL.findall(body):
                if exhibits:
                    found[label.strip()] = exhibits
        return found

    def deps(self, unit):
        """Sorted dependency keys of one unit."""
        t = unit['text']
        out = set()
        out |= {'val:' + k.strip() for k in VAL.findall(t)}
        out |= {_out(p) for p in EXHIBIT.findall(t)}
        out |= {_out(p) for p in RAW_OUT.findall(t)}
        for arg in REF.findall(t):
            for label in _split(arg):
                out |= set(self.float_exhibits.get(label, []))
        declared = list(unit['deps'])
        for arg in DEPENDSON.findall(t):
            declared += _split(arg)
        for d in declared:
            out |= set(_declared(d))
        return sorted(out)

    def exhibits(self):
        """Every out: path the document reads, for SCons to declare as a source."""
        t = self.text[self.body[0]:self.body[1]]
        return sorted({_out(p) for p in EXHIBIT.findall(t)} | {_out(p) for p in RAW_OUT.findall(t)})


def _out(path):
    """'tables/x.tex' or '../../output/tables/x.tex' -> 'out:tables/x.tex'."""
    p = path.strip().replace('\\', '/')
    if 'output/' in p:
        p = p.split('output/', 1)[1]
    if not os.path.splitext(p)[1]:
        for ext in GRAPHIC_EXT:
            if os.path.exists(absolute('output/' + p + ext)):
                p += ext
                break
    return 'out:' + p


def _declared(d):
    if d.startswith('val:'):
        return [d]
    if d.startswith('output/'):
        return [_out(d)]
    if any(c in d for c in '*?['):
        matches = sorted(rel(os.path.relpath(p, ROOT)) for p in glob.glob(absolute(d)))
        return ['file:' + m for m in matches] or ['file:' + d]
    return ['file:' + rel(d)]


# --- fingerprints and status -------------------------------------------------

def text_hash(text):
    return hashlib.md5(' '.join(text.split()).encode()).hexdigest()


class Resolver:
    """Current fingerprint, display string and upstream staleness of a dep key."""

    def __init__(self, graph=None):
        self.graph = graph or Graph()

    def fingerprint(self, dep):
        kind, _, name = dep.partition(':')
        if kind == 'val':
            v = self.graph.values.get(name)
            return (v['text'], v['text']) if v else (None, None)
        path = 'output/' + name if kind == 'out' else name
        h = file_hash(path)
        return h, (h[:8] if h else None)

    def producer(self, dep):
        kind, _, name = dep.partition(':')
        if kind == 'val':
            v = self.graph.values.get(name)
            return v['script'] if v else None
        if kind == 'out':
            return self.graph.producer.get('output/' + name)
        return None

    def upstream(self, dep):
        p = self.producer(dep)
        return self.graph.why_stale(p) if p else []


def load_lock(doc):
    try:
        with open(doc.lock_path) as fh:
            return json.load(fh)
    except OSError:
        return {'version': 1, 'passages': {}}


def save_lock(doc, lock):
    with open(doc.lock_path, 'w') as fh:
        json.dump(lock, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write('\n')


def status(doc, resolver=None):
    """One dict per unit: id, state, reasons (why it is not ok), info (FYI)."""
    resolver = resolver or Resolver()
    signed = load_lock(doc).get('passages', {})
    rows = []
    for u in doc.units:
        deps = doc.deps(u)
        lock = signed.get(u['id'])
        reasons, info, state = [], [], 'ok'
        broken = [d for d in deps if resolver.fingerprint(d)[0] is None]
        for d in broken:
            reasons.append(f'{d} cannot be resolved (not built yet, or misspelt)')
        if broken:
            state = 'broken'
        if lock is None:
            state = state if broken else 'unsigned'
        else:
            changed = []
            for d in deps:
                old = lock['deps'].get(d)
                fp, shown = resolver.fingerprint(d)
                if old is None:
                    info.append(f'{d} added since sign-off')
                elif fp is not None and fp != old['fp']:
                    where = resolver.producer(d)
                    src = f" ({where} @ {resolver.graph.tag(where)})" if where else ''
                    changed.append(f"{d}: {old.get('shown')} -> {shown}{src}")
            for d in sorted(set(lock['deps']) - set(deps)):
                info.append(f'{d} removed since sign-off')
            if text_hash(u['text']) != lock.get('text'):
                info.append(f"text edited since sign-off ({lock.get('signed_by')}, {lock.get('signed_at', '')[:10]})")
            if changed and not broken:
                state = 'changed'
            reasons += changed
        pending = sorted({w for d in deps for w in resolver.upstream(d)})
        if pending:
            if state in ('ok', 'unsigned'):
                state = 'pending' if state == 'ok' else state
            reasons += [f'upstream: {w}' for w in pending]
        rows.append(dict(id=u['id'], title=u['title'], kind=u['kind'], file=u['file'], line=u['line'],
                         state=state, reasons=reasons, info=info, deps=deps,
                         signed=lock and {k: lock[k] for k in ('signed_by', 'signed_at', 'commit')}))
    return rows


def signoff(doc, ids, force=False, resolver=None):
    """Record the current fingerprints of each unit's deps. Returns (signed, refused)."""
    resolver = resolver or Resolver()
    lock = load_lock(doc)
    lock.setdefault('passages', {})
    by_id = {u['id']: u for u in doc.units}
    signed, refused = [], []
    for uid in ids:
        u = by_id.get(uid)
        if u is None:
            refused.append((uid, 'no such passage'))
            continue
        deps = doc.deps(u)
        fps = {d: resolver.fingerprint(d) for d in deps}
        missing = [d for d, (fp, _) in fps.items() if fp is None]
        pending = sorted({w for d in deps for w in resolver.upstream(d)})
        if missing and not force:
            refused.append((uid, 'unresolved: ' + ', '.join(missing)))
            continue
        if pending and not force:
            refused.append((uid, 'upstream not rebuilt (run scons first, or --force): ' + '; '.join(pending)))
            continue
        lock['passages'][uid] = {
            'signed_by': who(),
            'signed_at': now(),
            'commit': git('rev-parse', '--short', 'HEAD'),
            'text': text_hash(u['text']),
            'deps': {d: {'fp': fp, 'shown': shown} for d, (fp, shown) in fps.items() if fp is not None},
        }
        signed.append(uid)
    save_lock(doc, lock)
    return signed, refused


def lint(doc):
    """Checks that need no build: ids, nesting, lock orphans, declared files exist."""
    errors, warnings = list(doc.errors), list(doc.warnings)
    lock = load_lock(doc)
    ids = {u['id'] for u in doc.units}
    for orphan in sorted(set(lock.get('passages', {})) - ids):
        warnings.append(f'{os.path.relpath(doc.lock_path, ROOT)}: sign-off for "{orphan}", '
                        'which is no longer a passage (renamed label? run prov.py prune)')
    for u in doc.units:
        for d in doc.deps(u):
            kind, _, name = d.partition(':')
            if kind == 'val' and not KEY_OK.match(name):
                errors.append(f"{u['file']}:{u['line']}: value key \"{name}\" in {u['id']}: "
                              'use letters, digits, _ . : - only')
            if kind == 'file' and not name.startswith(('../', 'data/', 'output/')) \
                    and not glob.glob(absolute(name)):
                errors.append(f"{u['file']}:{u['line']}: {u['id']} depends on {name}, which does not exist")
    return errors, warnings


def prune(doc):
    lock = load_lock(doc)
    ids = {u['id'] for u in doc.units}
    gone = sorted(set(lock.get('passages', {})) - ids)
    for g in gone:
        del lock['passages'][g]
    save_lock(doc, lock)
    return gone


# --- LaTeX side --------------------------------------------------------------

def tex_escape(s):
    return (str(s).replace('\\', '/').replace('{', '(').replace('}', ')')
            .replace('%', '\\%').replace('&', '\\&').replace('#', '\\#')
            .replace('_', '\\_').replace('$', '\\$').replace('^', '\\^{}').replace('~', '-'))


def value_tex(text):
    """A value's text for typesetting: escape specials, a true minus sign."""
    t = tex_escape(text)
    return re.sub(r'(^|(?<=\s))-(?=\d|\.)', r'\\ensuremath{-}', t)


def write_registry(path, graph=None):
    """output/provenance/registry.tex: every value and exhibit, with provenance."""
    graph = graph or Graph()
    lines = ['% Generated by code/provenance from output/provenance/records/. Do not edit.']
    for key, v in sorted(graph.values.items()):
        r = graph.records[v['script']]
        lines.append(f"\\provvalue{{{key}}}{{{value_tex(v['text'])}}}"
                     f"{{{tex_escape(os.path.basename(v['script']))}}}{{{graph.tag(v['script'])}}}"
                     f"{{{r['built_at'][:16].replace('T', ' ')}}}")
    for out, script in sorted(graph.producer.items()):
        if not out.startswith('output/') or out.startswith('output/provenance/'):
            continue
        r = graph.records[script]
        lines.append(f"\\provexhibit{{{out[len('output/'):]}}}"
                     f"{{{tex_escape(os.path.basename(script))}}}{{{graph.tag(script)}}}"
                     f"{{{r['built_at'][:16].replace('T', ' ')}}}")
    os.makedirs(os.path.dirname(absolute(path)), exist_ok=True)
    with open(absolute(path), 'w') as fh:
        fh.write('\n'.join(lines) + '\n')


def write_status_tex(path, rows, graph):
    """output/provenance/status-<doc>.tex: passage states and stale exhibits."""
    lines = ['% Generated by code/provenance/prov.py status --tex. Do not edit.']
    for r in rows:
        if r['state'] != 'ok':
            detail = '; '.join(r['reasons'] + r['info'])[:900] or r['state']
            lines.append(f"\\provpassagestatus{{{r['id']}}}{{{r['state']}}}{{{tex_escape(detail)}}}")
    for out, script in sorted(graph.producer.items()):
        why = graph.why_stale(script)
        if out.startswith('output/') and why:
            lines.append(f"\\provexhibitstatus{{{out[len('output/'):]}}}{{stale}}{{{tex_escape('; '.join(why))}}}")
    os.makedirs(os.path.dirname(absolute(path)), exist_ok=True)
    with open(absolute(path), 'w') as fh:
        fh.write('\n'.join(lines) + '\n')


def matches(uid, patterns):
    return any(fnmatch.fnmatch(uid, p) for p in patterns)
