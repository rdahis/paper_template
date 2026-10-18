#!/usr/bin/env python3
"""prov.py -- what the paper says, what it was built from, and what is out of date.

Usage (from the repository root):

  python3 code/provenance/prov.py status            passages and exhibits that need attention
  python3 code/provenance/prov.py status --all      ... and every passage that is ok
  python3 code/provenance/prov.py signoff sec:data  vouch for a passage as it reads now
  python3 code/provenance/prov.py signoff --clean   sign every unsigned passage whose deps resolve
  python3 code/provenance/prov.py tree sec:results  dependency tree of a passage, down to raw data
  python3 code/provenance/prov.py tree output/tables/tab_main.tex
  python3 code/provenance/prov.py impact code/data/clean_x.R
                                                    everything downstream of a file
  python3 code/provenance/prov.py values            every saved value, its script and commit
  python3 code/provenance/prov.py lint              checks that need no build (CI)
  python3 code/provenance/prov.py prune             drop sign-offs of passages that no longer exist

--doc products/talk/main.tex points any command at another document (default:
the paper). scons status runs `status`; scons paper writes the --tex file the
draft PDF reads.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import Graph, rel  # noqa: E402
import text  # noqa: E402

COLOR = sys.stdout.isatty() and os.environ.get('NO_COLOR') is None
PAINT = {'broken': '31;1', 'changed': '31', 'pending': '33', 'unsigned': '90', 'ok': '32', 'stale': '33'}


def paint(s, state):
    return f'\033[{PAINT[state]}m{s}\033[0m' if COLOR else s


# --- status ------------------------------------------------------------------

def cmd_status(args):
    graph = Graph()
    doc = text.Document(args.doc)
    rows = text.status(doc, text.Resolver(graph))
    stale = {out: graph.why_stale(s) for out, s in graph.producer.items()
             if out.startswith('output/') and graph.why_stale(s)}

    if args.tex:
        text.write_status_tex(args.tex, rows, graph)
    if args.json:
        json.dump({'passages': rows, 'stale_outputs': stale}, sys.stdout, indent=1)
        print()
        return 0

    counts = {s: sum(r['state'] == s for r in rows) for s in text.STATES}
    summary = ', '.join(f'{n} {s}' for s, n in counts.items() if n)
    lines = [f'{doc.main}: {len(rows)} passages ({summary or "none"})', '']
    for state in text.STATES:
        for r in rows:
            if r['state'] != state or (state == 'ok' and not args.all):
                continue
            if state == 'unsigned' and not (args.all or r['reasons']):
                continue
            lines.append(f"{paint(state.upper().ljust(8), state)} {r['id']}  \"{r['title']}\"  "
                         f"{r['file']}:{r['line']}")
            for why in r['reasons']:
                lines.append(f'           {why}')
            if args.verbose:
                for i in r['info']:
                    lines.append(f'           ({i})')
    unsigned = [r['id'] for r in rows if r['state'] == 'unsigned' and not r['reasons']]
    if unsigned and not args.all:
        lines.append(paint(f"UNSIGNED {len(unsigned)}: {', '.join(unsigned)}", 'unsigned'))
    if stale:
        lines += ['', 'Outputs out of date with their code or inputs (run scons):']
        for out, why in sorted(stale.items()):
            lines.append(f'  {paint(out, "stale")}')
            lines += [f'      {w}' for w in why]
    if graph.duplicates:
        lines += ['', 'Value keys saved by more than one script (the paper shows the last one read):']
        lines += [f'  {k}: {", ".join(sorted(s))}' for k, s in sorted(graph.duplicates.items())]
    if not graph.records:
        lines += ['', 'No run records yet: build with scons first.']
    print('\n'.join(lines))

    if args.md:
        with open(args.md, 'w') as fh:
            fh.write('# Provenance status\n\n```\n' + '\n'.join(lines) + '\n```\n')
    bad = counts['broken'] + counts['changed'] + counts['pending'] + bool(stale)
    return 1 if args.strict and bad else 0


# --- signoff -----------------------------------------------------------------

def cmd_signoff(args):
    doc = text.Document(args.doc)
    resolver = text.Resolver()
    ids = [u['id'] for u in doc.units if text.matches(u['id'], args.ids)]
    if args.clean:
        rows = text.status(doc, resolver)
        ids += [r['id'] for r in rows if r['state'] == 'unsigned' and not r['reasons']]
    if not ids:
        if args.clean and not args.ids:
            print('Nothing to sign: no unsigned passage without issues.')
            return 0
        print('No passage matches. Ids are \\label names (prov.py status --all lists them).')
        return 1
    signed, refused = text.signoff(doc, list(dict.fromkeys(ids)), force=args.force, resolver=resolver)
    for s in signed:
        print(f'{paint("signed", "ok")}   {s}')
    for s, why in refused:
        print(f'{paint("refused", "changed")}  {s}: {why}')
    if signed:
        print(f'\nUpdated {rel(doc.lock_path)}: commit it with the text it vouches for.')
    return 1 if refused else 0


# --- tree / impact -----------------------------------------------------------

def _node_for_path(graph, path, prefix, last, seen, out):
    branch = '`-- ' if last else '|-- '
    script = graph.producer.get(path)
    if script is None:
        out.append(f'{prefix}{branch}{path}')
        return
    why = graph.why_stale(script)
    r = graph.records[script]
    mark = paint(' STALE', 'stale') if why else ''
    out.append(f'{prefix}{branch}{path}  <- {script} @ {graph.tag(script)}, '
               f"{r['built_at'][:16].replace('T', ' ')} by {r['built_by']}{mark}")
    if script in seen:
        out.append(f'{prefix}{"    " if last else "|   "}`-- (see above)')
        return
    _script_children(graph, script, prefix + ('    ' if last else '|   '), seen | {script}, out)


def _script_children(graph, script, prefix, seen, out):
    r = graph.records[script]
    kids = [p for p in sorted(r['inputs']) if p != script]
    for i, p in enumerate(kids):
        _node_for_path(graph, p, prefix, i == len(kids) - 1, seen, out)


def cmd_tree(args):
    graph = Graph()
    resolver = text.Resolver(graph)
    target = args.target
    out = []
    doc = text.Document(args.doc)
    unit = next((u for u in doc.units if u['id'] == target), None)
    if unit:
        row = next(r for r in text.status(doc, resolver) if r['id'] == target)
        out.append(f"{target}  \"{unit['title']}\"  [{paint(row['state'], row['state'])}]")
        deps = doc.deps(unit)
        for i, d in enumerate(deps):
            last = i == len(deps) - 1
            fp, shown = resolver.fingerprint(d)
            kind, _, name = d.partition(':')
            if kind == 'val':
                script = resolver.producer(d)
                line = f"{'`-- ' if last else '|-- '}\\val{{{name}}} = {shown}"
                if script:
                    r = graph.records[script]
                    mark = paint(' STALE', 'stale') if graph.why_stale(script) else ''
                    line += (f"  <- {script} @ {graph.tag(script)}, "
                             f"{r['built_at'][:16].replace('T', ' ')} by {r['built_by']}{mark}")
                out.append(line)
            else:
                path = 'output/' + name if kind == 'out' else name
                _node_for_path(graph, path, '', last, set(), out)
    elif target in graph.values:
        v = graph.values[target]
        out.append(f"\\val{{{target}}} = {v['text']}  <- {v['script']} @ {graph.tag(v['script'])}")
        _script_children(graph, v['script'], '', {v['script']}, out)
    else:
        path = rel(target)
        if path in graph.records:
            out.append(f'{path} @ {graph.tag(path)}')
            _script_children(graph, path, '', {path}, out)
        elif path in graph.producer:
            _node_for_path(graph, path, '', True, set(), out)
        else:
            print(f'{target}: not a passage id, value key, script or built output.')
            return 1
    print('\n'.join(out))
    return 0


def cmd_impact(args):
    """Everything downstream of a file: outputs, values, passages."""
    graph = Graph()
    start = rel(args.path)
    hit_paths, frontier, scripts = {start}, [start], set()
    while frontier:
        p = frontier.pop()
        for script, r in graph.records.items():
            if script not in scripts and (p in r['inputs'] or p == script):
                scripts.add(script)
                for o in r['outputs']:
                    if o not in hit_paths:
                        hit_paths.add(o)
                        frontier.append(o)
    keys = sorted(k for k, v in graph.values.items() if v['script'] in scripts)
    outs = sorted(p for p in hit_paths if p != start and p.startswith('output/'))
    deps = {f'val:{k}' for k in keys} | {f"out:{p[len('output/'):]}" for p in outs} | {f'file:{start}'}
    doc = text.Document(args.doc)
    passages = [u for u in doc.units if deps & set(doc.deps(u))]
    print(f'Downstream of {start}:')
    print(f'  scripts ({len(scripts)}): ' + (', '.join(sorted(scripts)) or '-'))
    print(f'  outputs ({len(outs)}):')
    for o in outs:
        print(f'    {o}')
    print(f'  values ({len(keys)}): ' + (', '.join(keys) or '-'))
    print(f'  passages in {doc.main} ({len(passages)}):')
    for u in passages:
        print(f"    {u['id']}  \"{u['title']}\"  {u['file']}:{u['line']}")
    return 0


# --- values / lint / prune / registry ----------------------------------------

def cmd_values(args):
    graph = Graph()
    if not graph.values:
        print('No values saved yet.')
    width = max((len(k) for k in graph.values), default=0)
    for key, v in sorted(graph.values.items()):
        r = graph.records[v['script']]
        stale = paint(' STALE', 'stale') if graph.why_stale(v['script']) else ''
        print(f"{key.ljust(width)}  {v['text']:>12}  {v['script']} @ {graph.tag(v['script'])}  "
              f"{r['built_at'][:16].replace('T', ' ')}{stale}")
    return 0


def cmd_lint(args):
    status = 0
    for d in args.docs or [args.doc]:
        if not os.path.exists(d):
            continue
        doc = text.Document(d)
        errors, warnings = text.lint(doc)
        print(f'{doc.main}: {len(doc.units)} passages, {len(errors)} errors, {len(warnings)} warnings')
        for e in errors:
            print(f'  error: {e}')
            print(f'::error::{e}')
        for w in warnings:
            print(f'  warning: {w}')
            print(f'::warning::{w}')
        status |= bool(errors)
    return status


def cmd_prune(args):
    gone = text.prune(text.Document(args.doc))
    print('Dropped: ' + (', '.join(gone) if gone else 'nothing'))
    return 0


def cmd_registry(args):
    text.write_registry(args.path)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--doc', default=text.DEFAULT_DOC, help='LaTeX document (default %(default)s)')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('status')
    s.add_argument('--all', action='store_true', help='list ok and unsigned passages too')
    s.add_argument('-v', '--verbose', action='store_true', help='show edits and added/removed deps')
    s.add_argument('--strict', action='store_true', help='exit 1 if anything is changed, pending or broken')
    s.add_argument('--tex', help='also write the status file the draft PDF reads')
    s.add_argument('--md', help='also write the report as markdown')
    s.add_argument('--json', action='store_true')
    s.set_defaults(func=cmd_status)

    s = sub.add_parser('signoff')
    s.add_argument('ids', nargs='*', help='passage ids; shell-style globs allowed (sec:*)')
    s.add_argument('--clean', action='store_true', help='also sign every unsigned passage with no issues')
    s.add_argument('--force', action='store_true', help='sign even if deps are unresolved or pending')
    s.set_defaults(func=cmd_signoff)

    s = sub.add_parser('tree')
    s.add_argument('target', help='passage id, value key, script, or output path')
    s.set_defaults(func=cmd_tree)

    s = sub.add_parser('impact')
    s.add_argument('path', help='a script, data file or output')
    s.set_defaults(func=cmd_impact)

    sub.add_parser('values').set_defaults(func=cmd_values)

    s = sub.add_parser('lint')
    s.add_argument('docs', nargs='*', help='documents to lint (default --doc)')
    s.set_defaults(func=cmd_lint)

    sub.add_parser('prune').set_defaults(func=cmd_prune)

    s = sub.add_parser('registry')
    s.add_argument('path')
    s.set_defaults(func=cmd_registry)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
