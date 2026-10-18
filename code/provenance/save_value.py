"""save_value() -- record a number the paper cites, with its provenance.

    from save_value import save_value
    save_value("beta_main", model.params["treat"], digits=3)
    save_value("n_obs", int(model.nobs))          # integers get a big mark: 12,345

The paper then writes \\val{beta_main}. SCons puts code/provenance on PYTHONPATH
and sets PROV_VALUES; each call appends one JSON line there. Run outside SCons,
the call only prints what it would save. Keys: letters, digits, _ . : -
"""

import json
import os
import re
import sys


def save_value(key, value, digits=None, fmt=None, big_mark=',', note=''):
    if not re.match(r'^[A-Za-z0-9_.:-]+$', key):
        raise ValueError(f"save_value(): key '{key}' may use only letters, digits, _ . : -")
    if hasattr(value, 'item'):
        value = value.item()  # numpy / pandas scalar
    if fmt is not None:
        text = fmt % value if '%' in fmt else fmt.format(value)
    elif isinstance(value, (int, float)) and digits is not None:
        text = f'{value:,.{digits}f}'
    elif isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        text = f'{int(value):,}'
    elif isinstance(value, float):
        text = f'{value:,.2f}'
    else:
        text = str(value)
    if big_mark != ',':
        text = text.replace(',', big_mark)
    path = os.environ.get('PROV_VALUES')
    line = json.dumps({'key': key, 'value': value, 'text': text, 'note': note})
    if path:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(line + '\n')
    else:
        print(f'save_value: {key} = {text} (not recorded: run through scons)', file=sys.stderr)
    return value
