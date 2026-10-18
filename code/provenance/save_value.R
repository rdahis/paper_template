# save_value() -- record a number the paper cites, with its provenance.
#
#   save_value("beta_main", coef(m)["treat"], digits = 3)
#   save_value("n_obs", nobs(m))                         # integers get a big mark: 12,345
#   save_value("share_treated", 100 * mean(d$treat), digits = 1, note = "percent")
#
# The paper then writes \val{beta_main}. When SCons runs the script it sets
# PROV_VALUES, and each call appends one JSON line there; the run record keeps
# the value, the text the paper shows, and the commit and inputs it came from.
# Run outside SCons (interactively), the call only prints what it would save.
#
# Keys: letters, digits, _ . : -  and unique across the project. Sourced by
# code/setup.R; needs no package.

save_value <- function(key, value, digits = NULL, fmt = NULL, big_mark = ",", note = "") {
  if (!grepl("^[A-Za-z0-9_.:-]+$", key)) {
    stop("save_value(): key '", key, "' may use only letters, digits, _ . : -")
  }
  value <- unname(value)
  if (length(value) != 1) stop("save_value(): '", key, "' must be a single value")

  text <- if (!is.null(fmt)) {
    sprintf(fmt, value)
  } else if (is.numeric(value) && !is.null(digits)) {
    formatC(value, format = "f", digits = digits, big.mark = big_mark)
  } else if (is.numeric(value) && isTRUE(all.equal(value, round(value)))) {
    formatC(round(value), format = "d", big.mark = big_mark)
  } else if (is.numeric(value)) {
    formatC(value, format = "f", digits = 2, big.mark = big_mark)
  } else {
    as.character(value)
  }

  json_str <- function(s) {
    s <- gsub("\\\\", "\\\\\\\\", s)
    s <- gsub("\"", "\\\\\"", s)
    paste0("\"", gsub("\n", " ", s), "\"")
  }
  raw <- if (is.numeric(value) && is.finite(value)) format(value, digits = 15) else json_str(as.character(value))
  line <- sprintf("{\"key\": %s, \"value\": %s, \"text\": %s, \"note\": %s}",
                  json_str(key), raw, json_str(text), json_str(note))

  path <- Sys.getenv("PROV_VALUES")
  if (nzchar(path)) {
    cat(line, "\n", file = path, append = TRUE, sep = "")
  } else {
    message("save_value: ", key, " = ", text, " (not recorded: run through scons)")
  }
  invisible(value)
}
