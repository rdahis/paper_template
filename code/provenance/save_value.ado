*! save_value -- record a number the paper cites, with its provenance.
*!
*!   save_value beta_main, value(_b[treat]) format(%9.3f)
*!   save_value n_obs, value(e(N)) format(%12.0fc)
*!
*! The paper then writes \val{beta_main}. SCons adds code/provenance to the
*! adopath (S_ADO) and sets PROV_VALUES; each call appends one JSON line there.
*! Run outside SCons, the call only displays what it would save.
*! Keys: letters, digits, _ . : -   value() takes any expression.
*! Untested in CI: there is no Stata licence there.
program define save_value
    version 14
    syntax anything(name=key id="value key"), Value(string) [Format(string) Note(string)]
    if !ustrregexm("`key'", "^[A-Za-z0-9_.:-]+$") {
        display as error "save_value: key `key' may use only letters, digits, _ . : -"
        exit 198
    }
    if "`format'" == "" local format "%12.2fc"
    tempname v
    scalar `v' = `value'
    local text = strtrim(string(`v', "`format'"))
    local raw = strofreal(`v', "%21.15g")
    local path : env PROV_VALUES
    if "`path'" == "" {
        display as text "save_value: `key' = `text' (not recorded: run through scons)"
        exit
    }
    tempname fh
    file open `fh' using "`path'", write append text
    file write `fh' `"{"key": "`key'", "value": `raw', "text": "`text'", "note": "`note'"}"' _n
    file close `fh'
end
