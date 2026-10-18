# Parse every live R script without running it: catches syntax errors before a
# long build reaches them. Run by .github/workflows/checks.yml.
#
# Usage: Rscript --vanilla .github/scripts/parse_r.R

files <- system2("git", c("ls-files", "*.R"), stdout = TRUE)
files <- files[!grepl("^code/(old|explorations)/", files)]

failed <- character(0)
for (f in files) {
  msg <- tryCatch({ parse(f); NULL }, error = function(e) conditionMessage(e))
  if (!is.null(msg)) {
    failed <- c(failed, f)
    cat(sprintf("::error file=%s::R parse error: %s\n", f, gsub("\n", " ", msg)))
    cat(sprintf("FAIL %s\n%s\n\n", f, msg))
  }
}

cat(sprintf("Parsed %d R scripts; %d failed.\n", length(files), length(failed)))
quit(status = as.integer(length(failed) > 0))
