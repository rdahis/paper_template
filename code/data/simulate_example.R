# simulate_example.R -- stand-in for a raw-data step: writes the clean panel the
# toy analysis reads. Replace with clean_<source>.R / assemble_<level>.R scripts
# that read ../../data/raw/ and write one data/clean/<level>.rds per observation
# level. Delete this file once the project has real data.

source("code/setup.R")
set.seed(20261018)

n <- 2000
d <- data.frame(
  unit = seq_len(n),
  treated = rbinom(n, 1, 0.4),
  x = rnorm(n)
)
d$y <- 1 + 0.25 * d$treated + 0.5 * d$x + rnorm(n)

dir.create(here::here("data/clean"), recursive = TRUE, showWarnings = FALSE)
saveRDS(d, here::here("data/clean/unit.rds"))
