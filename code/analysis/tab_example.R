# tab_example.R -- the main regression: a bare booktabs tabular for the paper
# to wrap, and the numbers the text cites, saved with save_value().

source("code/setup.R")

d <- readRDS(here::here("data/clean/unit.rds"))
m1 <- lm(y ~ treated, data = d)
m2 <- lm(y ~ treated + x, data = d)

coef_se <- function(m, v) {
  s <- summary(m)$coefficients
  c(sprintf("%.3f", s[v, 1]), sprintf("(%.3f)", s[v, 2]))
}
row <- function(label, cells) paste(label, paste(cells, collapse = " & "), sep = " & ")

t1 <- coef_se(m1, "treated")
t2 <- coef_se(m2, "treated")
lines <- c(
  "\\begin{tabular}{lcc}",
  "\\toprule",
  " & (1) & (2) \\\\",
  "\\midrule",
  paste0(row("Treated", c(t1[1], t2[1])), " \\\\"),
  paste0(row("", c(t1[2], t2[2])), " \\\\"),
  "\\midrule",
  paste0(row("Control for $x$", c("No", "Yes")), " \\\\"),
  paste0(row("Observations", formatC(c(nobs(m1), nobs(m2)), big.mark = ",", format = "d")), " \\\\"),
  paste0(row("$R^2$", sprintf("%.3f", c(summary(m1)$r.squared, summary(m2)$r.squared))), " \\\\"),
  "\\bottomrule",
  "\\end{tabular}"
)
dir.create(here::here("output/tables"), recursive = TRUE, showWarnings = FALSE)
writeLines(lines, here::here("output/tables/tab_example.tex"))

b <- coef(m2)[["treated"]]
se <- summary(m2)$coefficients["treated", 2]
save_value("beta_treated", b, digits = 3)
save_value("se_treated", se, digits = 3)
save_value("beta_treated_pct_mean", 100 * b / mean(d$y[d$treated == 0]), digits = 1,
           note = "percent of the control mean")
save_value("n_units", nobs(m2))
