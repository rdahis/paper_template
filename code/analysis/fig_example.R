# fig_example.R -- outcome against the covariate, by treatment status. No title
# inside the figure: the caption in the paper carries it.

source("code/setup.R")

d <- readRDS(here::here("data/clean/unit.rds"))

dir.create(here::here("output/figures"), recursive = TRUE, showWarnings = FALSE)
pdf(here::here("output/figures/fig_example.pdf"), width = 6, height = 4, family = "serif")
par(mar = c(4, 4, 1, 1))
plot(d$x, d$y, col = ifelse(d$treated == 1, "#1b6ca8", "#bbbbbb"), pch = ifelse(d$treated == 1, 17, 16),
     cex = 0.5, xlab = "Covariate x", ylab = "Outcome y", las = 1)
for (g in 0:1) abline(lm(y ~ x, data = d[d$treated == g, ]), lty = 2 - g, lwd = 2,
                      col = c("#777777", "#1b6ca8")[g + 1])
legend("topleft", c("Control", "Treated"), pch = c(16, 17), lty = c(2, 1),
       col = c("#777777", "#1b6ca8"), bty = "n")
invisible(dev.off())

save_value("share_treated", 100 * mean(d$treated), digits = 1, note = "percent")
