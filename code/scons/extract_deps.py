#!/usr/bin/env python3
"""
extract_deps.py — draft an SConscript from the file paths an R script names.

Usage (from the repository root):
    python3 code/scons/extract_deps.py code/analysis [code/data ...] > code/analysis/SConscript

The first directory is the one emitted. Any further directories are context:
their scripts are scanned so that a file both directories could claim goes to
one owner, but no block is written for them.

The output is a DRAFT. Review it by hand before committing: this reads R
source, it does not run it, so it sees only paths it can work out statically.

What it resolves. Every string expression in a script is evaluated where it
can be: literals, variables assigned a string earlier (`out_dir <- "output/x"`),
and file.path(), here::here(), paste0(), paste(sep = ""), sprintf() and c()
built from those. A part it cannot resolve (a loop variable, a function
argument) becomes a wildcard, and the path is expanded by globbing the files a
previous run left on disk. A template that matches nothing is reported as
UNRESOLVED rather than guessed, and one can match stale files from an older run.

Function parameters and loop variables are bound to what the script passes
them: `f <- function(year)` called as f(2022), lapply(years, f) or
lapply(years, function(year) ...), and `for (year in years)`. A function the
script never calls, or a call whose argument cannot be resolved, leaves the
parameter a wildcard as before.

A format string still unfilled after evaluation ("..._%d.tif" on its own, not
inside the sprintf() that fills it) is recorded only when it is passed straight
to a read call or to a function the script defines. Otherwise it is skipped and
noted: the sprintf() that uses it already yields the paths actually read, and
the bare template would claim the whole family (all 38 yearly rasters for a
script that reads one year).

How a resolved path is classified:
  - an argument of a write call -> target (ggsave, saveRDS, fwrite, write_*, ...)
  - output/...                  -> target
  - data/..., ../../...         -> source
  - code/functions/*.R          -> source, and scanned in turn for its own reads
A write call none of whose arguments resolves to a path is reported as
UNRESOLVED: its output has to be declared by hand.
"""

import fnmatch
import glob
import itertools
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

PATH_PREFIXES = ("data/", "output/", "../../", "code/")
HAS_EXT = re.compile(r"\.[A-Za-z0-9]{1,5}(\.gz)?$")
SETUP = "code/setup.R"
EXACT = 10**6  # specificity of a literal path, beats any template
WILD = "\0"    # an unresolved part of a path
MAX_ALTS = 64  # cap on the alternatives one expression may expand to
MAX_LISTED = 8  # more templates than this from one expression collapse to one
PLACEHOLDER = re.compile(r"%[-+ 0#]*[0-9.]*[sdifg]")

WRITE_FUNS = {
    "ggsave", "saveRDS", "write_rds", "write_csv", "write.csv", "write_tsv",
    "write_dta", "fwrite", "writeLines", "sink", "pdf", "png", "cairo_pdf",
    "svg", "jpeg", "save_kable", "st_write", "writeRaster", "save", "etable",
    "save_plot", "write_xlsx", "write.xlsx", "saveWidget", "modelsummary",
}
READ_FUNS = {
    "readRDS", "read_rds", "fread", "read_csv", "read.csv", "read_tsv",
    "read_delim", "read.delim", "read_excel", "read_xlsx", "read_xls",
    "read_dta", "read_parquet", "read_fst", "read_feather", "read_sf",
    "st_read", "rast", "raster", "stack", "brick", "vect", "load",
    "readLines", "open_dataset", "vroom", "read_json", "fromJSON",
}
# Iterators that call their second argument once per element of their first.
MAP_FUNS = {
    "lapply", "sapply", "vapply", "mclapply", "future_lapply", "map", "map_dfr",
    "map_dfc", "map_chr", "map_lgl", "map_int", "map_dbl", "walk",
}
JOIN_FUNS = {"file.path", "here", "path"}           # join with "/"
PASS_FUNS = {"normalizePath", "path.expand", "I"}   # value of the first argument

TOKEN = re.compile(r"""
    (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<id>[A-Za-z._][A-Za-z0-9._]*(?:::[A-Za-z._][A-Za-z0-9._]*)?)
  | (?P<num>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?L?)
  | (?P<assign><<-|<-|->)
  | (?P<op>%[^%\n]*%|==|!=|<=|>=|&&|\|\||[-+*/^$@\[\]&|<>!~:?])
  | (?P<punct>[(),{}=;])
  | (?P<nl>\n)
  | (?P<ws>[ \t\r]+)
  | (?P<other>.)
""", re.VERBOSE)
UNESCAPE = re.compile(r"\\(.)")


def strip_comments(line):
    """Drop an R comment, leaving any '#' inside a string alone."""
    quote = None
    escaped = False
    for i, ch in enumerate(line):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def tokenize(text):
    toks = []
    line = 1
    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        if kind == "nl":
            toks.append(("nl", "\n", line))
            line += 1
        elif kind != "ws":
            val = m.group()
            if kind == "str":
                val = UNESCAPE.sub(r"\1", val[1:-1])
            toks.append((kind, val, line))
    toks.append(("eof", "", line))
    return toks


class Parser:
    """Parse just enough R to evaluate string-valued expressions.

    Nodes: ("str", s) | ("id", name) | ("call", fname, [(argname, node)], line)
    | ("other",). Anything with an operator in it is "other".
    """

    def __init__(self, toks):
        self.t = toks

    def skip_nl(self, i):
        while self.t[i][0] == "nl":
            i += 1
        return i

    def primary(self, i):
        i = self.skip_nl(i)
        kind, val, line = self.t[i]
        if kind == "str":
            return ("str", val), i + 1
        if kind == "num":
            return ("str", val.rstrip("L")), i + 1
        if kind == "id" and self.t[i + 1][1] == "(" and self.t[i + 1][0] == "punct":
            args, j = self.args(i + 2)
            return ("call", val.split("::")[-1], args, line), j
        if kind == "id":
            return ("id", val), i + 1
        if val == "(" and kind == "punct":
            node, j = self.expr(i + 1)
            j = self.skip_nl(j)
            return node, (j + 1 if self.t[j][1] == ")" else j)
        return ("other",), i + 1

    def expr(self, i):
        node, j = self.primary(i)
        if self.t[j][0] in ("op",) or (self.t[j][0] == "punct" and self.t[j][1] == "("):
            return ("other",), self.to_boundary(j)
        return node, j

    def to_boundary(self, i):
        """Advance to the next ',' or ')' or newline at depth 0."""
        depth = 0
        while self.t[i][0] != "eof":
            kind, val, _ = self.t[i]
            if kind in ("punct", "op") and val in ("(", "[", "{"):
                depth += 1
            elif kind in ("punct", "op") and val in (")", "]", "}"):
                if depth == 0:
                    return i
                depth -= 1
            elif depth == 0 and (val == "," or kind == "nl"):
                return i
            i += 1
        return i

    def args(self, i):
        """Parse call arguments starting after '('; return (args, index after ')')."""
        out = []
        while True:
            i = self.skip_nl(i)
            kind, val, _ = self.t[i]
            if kind == "eof":
                return out, i
            if kind == "punct" and val == ")":
                return out, i + 1
            name = None
            if kind == "id" and self.t[i + 1][1] == "=" and self.t[i + 1][0] == "punct":
                name, i = val, i + 2
            node, j = self.expr(i)
            # an argument that spans lines or has trailing operators: skip to its end
            j = self.skip_nl(j)
            if self.t[j][1] not in (",", ")"):
                node = ("other",)
                depth = 0
                while self.t[j][0] != "eof":
                    v = self.t[j][1]
                    if v in ("(", "[", "{"):
                        depth += 1
                    elif v in (")", "]", "}"):
                        if depth == 0:
                            break
                        depth -= 1
                    elif v == "," and depth == 0:
                        break
                    j += 1
            out.append((name, node))
            if self.t[j][1] == ",":
                j += 1
            i = j


def product(parts, sep=""):
    combos = itertools.islice(itertools.product(*parts), MAX_ALTS)
    return sorted({sep.join(c) for c in combos})


_RESOLVED = {}  # (id(env), name) -> values; cleared by scan() for each file


def evaluate(node, env, depth=0, stack=frozenset(), coarse=False):
    """Return the alternative string values of a node, WILD marking unknowns.

    stack holds the names being resolved, so a name bound to itself (a call
    f(x) where f's parameter is x) resolves to WILD instead of recursing.
    coarse treats every name with more than one value as WILD; see paths_of().
    """
    if depth > 20:
        return [WILD]
    kind = node[0]
    if kind == "str":
        return [node[1]]
    if kind == "id":
        name = node[1]
        if name not in env or name in stack:
            return [WILD]
        key = (id(env), name, coarse)
        if key not in _RESOLVED:
            vals = set()
            for value in env[name]:
                vals.update(evaluate(value, env, depth + 1, stack | {name}, coarse))
            # One untraceable value makes the name a wildcard: listing the known
            # values beside it only splits one template into overlapping ones.
            if WILD in vals or (coarse and len(vals) > 1):
                vals = {WILD}
            _RESOLVED[key] = sorted(vals)[:MAX_ALTS]
        return _RESOLVED[key]
    if kind == "call":
        fname, args = node[1], node[2]
        positional = [a for n, a in args if n is None]
        named = {n: a for n, a in args if n is not None}
        if fname in JOIN_FUNS:
            return product([evaluate(a, env, depth + 1, stack, coarse) for a in positional], "/")
        if fname == "paste0":
            return product([evaluate(a, env, depth + 1, stack, coarse) for a in positional])
        if fname == "paste":
            sep = evaluate(named["sep"], env, depth + 1, stack, coarse) if "sep" in named else [" "]
            if len(sep) != 1 or WILD in sep[0]:
                return [WILD]
            return product([evaluate(a, env, depth + 1, stack, coarse) for a in positional], sep[0])
        if fname == "sprintf" and positional:
            fmts = evaluate(positional[0], env, depth + 1, stack, coarse)
            fills = [evaluate(a, env, depth + 1, stack, coarse) for a in positional[1:]]
            out = set()
            for fmt in fmts:
                pieces = PLACEHOLDER.split(fmt)
                slots = [fills[k] if k < len(fills) else [WILD] for k in range(len(pieces) - 1)]
                for combo in itertools.islice(itertools.product(*slots), MAX_ALTS):
                    out.add("".join(p + v for p, v in zip(pieces, combo)) + pieces[-1])
            return sorted(out)[:MAX_ALTS]
        if fname in ("c", "list"):
            vals = set()
            for _, a in args:
                vals.update(evaluate(a, env, depth + 1, stack, coarse))
            return sorted(vals)[:MAX_ALTS]
        if fname in PASS_FUNS and positional:
            return evaluate(positional[0], env, depth + 1, stack, coarse)
    return [WILD]


def paths_of(node, env):
    """evaluate(), but a long list of templates collapses to one wildcard.

    tab_x_%s_%s%s over 2 levels x 14 outcomes and an unknown suffix is better
    declared as tab_x_*_*.tex than as 28 near-identical templates. A list of
    exact paths (one file per year read) is kept as is.
    """
    values = evaluate(node, env)
    if len(values) > MAX_LISTED and any(WILD in v for v in values):
        values = evaluate(node, env, coarse=True)
    return values


def as_path(value):
    """Return (glob pattern, specificity) for a value that names a file, else None."""
    if value.startswith("./"):
        value = value[2:]
    # A format string held in a variable and filled by sprintf() later.
    value = PLACEHOLDER.sub(WILD, value)
    if not value.startswith(PATH_PREFIXES):
        return None
    base = value.rsplit("/", 1)[-1]
    if WILD not in value:
        return (value, EXACT) if HAS_EXT.search(value) else None
    # A wildcard must leave at least three literal characters in the file name
    # besides its extension, or the pattern would claim every file in a shared
    # directory (paste0("output/figures/maps/", filename)).
    stem = HAS_EXT.sub("", base.replace(WILD, "\x01")).replace("\x01", "")
    if len(stem) < 3:
        return None
    pattern = re.sub(WILD + "+", "*", value)
    return pattern, value.index(WILD)


def walk(node, visit):
    visit(node)
    if node[0] == "call":
        for _, a in node[2]:
            walk(a, visit)


def call_args(toks, i):
    """Token index where each argument of the call opening at toks[i] == '(' starts."""
    starts, depth, j, start = [], 0, i + 1, i + 1
    while toks[j][0] != "eof":
        kind, val, _ = toks[j]
        if kind in ("punct", "op") and val in ("(", "[", "{"):
            depth += 1
        elif kind in ("punct", "op") and val in (")", "]", "}"):
            if depth == 0:
                if j > start:
                    starts.append(start)
                return starts
            depth -= 1
        elif depth == 0 and kind == "punct" and val == ",":
            starts.append(start)
            start = j + 1
        j += 1
    return starts


def bind_parameters(toks, parser, env, calls):
    """Give function parameters and for-loop variables the values passed to them.

    Adds to env, so a name keeps every value it can take: a top-level
    assignment, each call site's argument, and a wildcard ("other") wherever a
    value cannot be traced. Over-binding widens a path to more alternatives; it
    never narrows one, so a dependency is not lost.
    """
    def params(i):
        """[(name, default node or None)] of the `function(` at toks[i]."""
        args, _ = parser.args(i + 2)
        out = []
        for name, node in args:
            if name is None and node[0] == "id":
                out.append((node[1], None))
            elif name is not None:
                out.append((name, node))
        return out

    def is_function(i):
        return (toks[i][0] == "id" and toks[i][1] == "function"
                and toks[i + 1][0] == "punct" and toks[i + 1][1] == "(")

    def bind(name, node):
        env.setdefault(name, []).append(node)

    # Named functions: `f <- function(...)`.
    defs = {}
    for i, (kind, val, _) in enumerate(toks):
        if (kind == "id" and toks[i + 1][0] == "assign" and toks[i + 1][1] in ("<-", "<<-")
                and is_function(parser.skip_nl(i + 2))):
            defs[val] = params(parser.skip_nl(i + 2))

    bound = {name: False for name in defs}
    for i, (kind, val, _) in enumerate(toks):
        if kind != "id" or toks[i + 1][1] != "(" or toks[i + 1][0] != "punct":
            continue
        fname = val.split("::")[-1]
        if fname in defs:
            args, _ = parser.args(i + 2)
            plist = defs[fname]
            named = {n: a for n, a in args if n is not None}
            positional = [a for n, a in args if n is None]
            free = [p for p in plist if p[0] not in named]
            for name, node in named.items():
                if any(p[0] == name for p in plist):
                    bind(name, node)
            for k, (pname, default) in enumerate(free):
                if k < len(positional):
                    bind(pname, positional[k])
                elif default is not None:
                    bind(pname, default)
            bound[fname] = True
        elif fname in MAP_FUNS:
            starts = call_args(toks, i + 1)
            if len(starts) < 2:
                continue
            x_node, _ = parser.expr(starts[0])
            f_at = parser.skip_nl(starts[1])
            if is_function(f_at):
                plist = params(f_at)
            elif toks[f_at][0] == "id" and toks[f_at][1] in defs:
                plist = defs[toks[f_at][1]]
                bound[toks[f_at][1]] = True
            else:
                continue
            if plist:
                bind(plist[0][0], x_node)
        elif fname == "for":
            # for (v in X)
            j = parser.skip_nl(i + 2)
            if toks[j][0] == "id" and toks[j + 1][0] == "id" and toks[j + 1][1] == "in":
                node, _ = parser.expr(j + 2)
                bind(toks[j][1], node)
    # A function never called, or called only in ways not traced, takes anything.
    for fname, was_bound in bound.items():
        if not was_bound:
            for pname, default in defs[fname]:
                bind(pname, ("other",))


def scan(script, seen=None):
    """Return (sources, targets, notes) for one R file, following source() calls.

    targets maps path -> specificity: the length of the literal before the first
    wildcard, or EXACT for a plain literal.
    """
    seen = seen if seen is not None else set()
    _RESOLVED.clear()
    sources, targets, notes = set(), {}, []
    if script in seen:
        return sources, targets, notes
    seen.add(script)

    with open(os.path.join(REPO, script), encoding="utf-8", errors="replace") as fh:
        text = "".join(strip_comments(l.rstrip("\n")) + "\n" for l in fh)
    toks = tokenize(text)
    parser = Parser(toks)

    # Pass 1: every assignment `name <- expr` / `name = expr` at statement level,
    # and every call, anywhere.
    env, calls, literals = {}, [], []
    for i, (kind, val, line) in enumerate(toks):
        if kind == "str":
            literals.append((val, line))
        if kind == "id" and toks[i + 1][0] == "assign" and toks[i + 1][1] in ("<-", "<<-"):
            node, _ = parser.expr(i + 2)
            env.setdefault(val, []).append(node)
        elif kind == "id" and toks[i + 1][1] == "(" and toks[i + 1][0] == "punct":
            node, _ = parser.primary(i)
            calls.append(node)

    bind_parameters(toks, parser, env, calls)

    def add_target(path, spec):
        targets[path] = max(targets.get(path, -1), spec)

    def resolve(pattern, spec, line, is_target):
        """Record a path. A template is kept as a pattern, globbed by SCons at
        parse time, so files a script has not yet written on this machine are
        picked up after its first run."""
        if spec != EXACT:
            n = len(glob.glob(os.path.join(REPO, pattern)))
            notes.append(f"TEMPLATE {script}:{line}: {pattern} ({n} file(s) on disk now)")
        if pattern == SETUP:
            return  # added once per script by the caller
        if spec == EXACT and pattern.startswith("code/functions/") and pattern.endswith(".R"):
            sources.add(pattern)
            s2, t2, n2 = scan(pattern, seen)
            sources.update(s2)
            for t, k in t2.items():
                add_target(t, k)
            notes.extend(n2)
        elif is_target or pattern.startswith("output/"):
            add_target(pattern, spec)
        else:
            sources.add(pattern)

    handled = set()
    # Pass 2: write calls. Each argument that resolves to a path is a target.
    for call in calls:
        if call[0] != "call" or call[1] not in WRITE_FUNS:
            continue
        found = False
        for _, arg in call[2]:
            for value in paths_of(arg, env):
                hit = as_path(value)
                if hit:
                    found = True
                    handled.add(hit[0])
                    resolve(hit[0], hit[1], call[3], True)
        if not found and call[1] not in ("etable", "modelsummary", "save", "sink", "writeLines"):
            notes.append(f"UNRESOLVED {script}:{call[3]}: {call[1]}() writes a path that cannot be worked out statically")

    # Pass 3: every other resolvable string expression — reads, and outputs
    # written through a helper the scanner does not know.
    # A value still holding a placeholder is an unfilled format string. It counts
    # only when handed to a reader (or a function of the script) as is; the
    # sprintf() that fills it elsewhere already yields the paths read.
    defined = {name for name, nodes in env.items()
               if any(n[0] == "call" and n[1] == "function" for n in nodes)}
    fed_to_reader = set()
    for call in calls:
        if call[0] == "call" and (call[1] in READ_FUNS or call[1] in defined):
            for _, arg in call[2]:
                for value in evaluate(arg, env):
                    if PLACEHOLDER.search(value):
                        fed_to_reader.add(as_path(value))

    lines_of, filled, unfilled = {}, set(), {}

    def note_value(value, line):
        hit = as_path(value)
        if not hit:
            return
        lines_of.setdefault(hit, line)
        if PLACEHOLDER.search(value):
            unfilled.setdefault(hit, value)
        else:
            filled.add(hit)

    for call in calls:
        def visit(n, line=call[3]):
            if n[0] == "call":
                for value in paths_of(n, env):
                    note_value(value, line)
        walk(call, visit)
    for name, nodes in env.items():
        for node in nodes:
            for value in paths_of(node, env):
                note_value(value, 0)
    for val, line in literals:
        note_value(val, line)
    for (pattern, spec), line in sorted(lines_of.items(), key=lambda kv: kv[0]):
        hit = (pattern, spec)
        if hit in unfilled and hit not in filled and hit not in fed_to_reader:
            notes.append(f"SKIPPED format string {script}:{line}: {unfilled[hit]} "
                         "(never passed to a read call as is)")
            continue
        if pattern not in handled:
            resolve(pattern, spec, line, False)

    sources = {p for p in sources
               if p not in targets and not any(fnmatch.fnmatch(p, t) for t in targets if "*" in t)}
    return sources, targets, notes


def overlaps(a, b):
    """True if pattern (or path) a can name a file pattern b matches."""
    return fnmatch.fnmatch(a.replace("*", "x"), b)


def drop_covered(paths):
    """Drop each pattern that another pattern in the list already matches.

    A parameter bound at several call sites yields one template per value plus a
    wildcard one (tab_x_ols_*.tex and tab_x_*.tex); the widest suffices.
    """
    pats = sorted(p for p in paths if "*" in p)
    keep = set(paths)
    for a in pats:
        for b in pats:
            if a != b and b in keep and overlaps(a, b) and (not overlaps(b, a) or b < a):
                keep.discard(a)
                break
    return keep


def main(directories):
    emit_dir = directories[0]
    scripts = {}
    for d in directories:
        for p in sorted(glob.glob(os.path.join(REPO, d, "*.R"))):
            scripts[os.path.relpath(p, REPO)] = d == emit_dir
    scanned = {script: scan(script) for script in scripts}

    # Ownership. Two scripts naming the same exact file is a genuine duplicate,
    # which SCons refuses, so it is reported. A pattern never claims a file
    # another script names exactly, nor one a more specific pattern of another
    # script covers (tab_muni_bustos_%s_%s vs tab_muni_bustos_upper_%s): those
    # become the pattern's exclusions, applied when SCons globs it.
    all_targets = [(t, k, s) for s, (_, ts, _) in scanned.items() for t, k in ts.items()]

    blocks = []
    for script, emitted in scripts.items():
        if not emitted:
            continue
        sources, targets, notes = scanned[script]
        kept = drop_covered(set(targets)) | drop_covered(set(sources))
        targets = {t: k for t, k in targets.items() if t in kept}
        sources = {p for p in sources if p in kept}
        notes = [n for n in notes if not n.startswith("TEMPLATE")
                 or n.split(": ", 1)[1].rsplit(" (", 1)[0] in kept]
        exact, patterns = [], []
        for t, spec in sorted(targets.items()):
            if spec == EXACT:
                rivals = sorted({s for u, k, s in all_targets if u == t and s != script})
                if rivals:
                    notes.append(f"DUPLICATE target {t} also written by {', '.join(rivals)}")
                exact.append(t)
            else:
                excl = sorted({u for u, k, s in all_targets if s != script and overlaps(u, t)
                               and (k == EXACT or k > spec)})
                ties = sorted({s for u, k, s in all_targets if s != script and k == spec
                               and overlaps(u, t) and overlaps(t, u)})
                if ties:
                    notes.append(f"DUPLICATE pattern {t} also claimed by {', '.join(ties)}")
                patterns.append((t, excl))
        missing = [s for s in sorted(sources) if "*" not in s
                   and not os.path.exists(os.path.join(REPO, s))]
        missing += [s for s in sorted(sources) if "*" in s
                    and not glob.glob(os.path.join(REPO, s))]
        for s in missing:
            notes.append(f"MISSING source {s} (not on disk here)")
        blocks.append((script, sorted(sources), exact, patterns, notes))

    out = sys.stdout
    out.write(f"# {emit_dir}/SConscript — drafted by code/scons/extract_deps.py, then reviewed.\n")
    out.write("# Every path is repo-relative ('#' prefix). The first source is the script.\n")
    out.write("# R() adds output/logs/scons/<script>.log as a target itself. outputs() and\n")
    out.write("# inputs() glob a pattern each time SCons reads this file.\n\n")
    out.write("Import('R', 'outputs', 'inputs')\n\n")
    for script, sources, exact, patterns, notes in blocks:
        name = os.path.basename(script)
        out.write(f"# --- {name}\n")
        for note in dict.fromkeys(notes):
            out.write(f"# {note}\n")
        if not exact and not patterns:
            out.write(f"# NO TARGETS FOUND for {name}: only its log is tracked. Declare outputs by hand.\n")
        out.write("R(\n    [\n")
        for t in exact:
            out.write(f"        '#{t}',\n")
        out.write("    ]")
        for t, excl in patterns:
            if excl:
                ex = "".join(f"\n        '{e}'," for e in excl)
                out.write(f"\n    + outputs('{t}', exclude=[{ex}\n    ])")
            else:
                out.write(f"\n    + outputs('{t}')")
        out.write(",\n    [\n")
        out.write(f"        '#{script}',\n        '#{SETUP}',\n")
        for s in sources:
            if "*" not in s:
                out.write(f"        '#{s}',\n")
        out.write("    ]")
        for s in sources:
            if "*" in s:
                out.write(f"\n    + inputs('{s}')")
        out.write(",\n)\n\n")


if __name__ == "__main__":
    main(sys.argv[1:] or ["code/analysis"])
