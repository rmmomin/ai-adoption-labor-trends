#!/usr/bin/env Rscript
# X-13 seasonal adjustment of independently assembled monthly hours.
args <- commandArgs(trailingOnly = TRUE)
out <- normalizePath(args[1])
root <- if (length(args) >= 2) normalizePath(args[2]) else normalizePath(file.path(out, "../.."))
.libPaths(c(file.path(root, ".research-runtime/R-library"), .libPaths()))
library(seasonal)
x <- read.csv(file.path(out, "x13_monthly_inputs.csv"), colClasses = c(naics = "character"))
dir.create(file.path(out, "x13"), showWarnings = FALSE)
results <- list()
checks <- list()
for (id in unique(x$series)) {
  d <- x[x$series == id, ]
  d <- d[order(d$date), ]
  y <- ts(d$value, start = c(as.integer(substr(d$date[1], 1, 4)), as.integer(substr(d$date[1], 6, 7))), frequency = 12)
  stopifnot(all(is.finite(y)), all(y > 0))
  dest <- file.path(out, "x13", id)
  dir.create(dest, showWarnings = FALSE)
  # X-11 retains the irregular component. No quarter is smoothed away or deleted.
  # No trading-day/Easter adjustment: these are reference-week labor observations.
  model_method <- "automatic_arima"
  auto_error <- ""
  fit <- tryCatch(seas(y, transform.function = "log", regression.aictest = NULL,
              automdl = "", outlier = "", x11 = "", seats = NULL, estimate.maxiter = 2000,
              x11.save = c("d10", "d11", "d12", "d13"), dir = dest), error = function(e) e)
  if (inherits(fit, "error")) {
    auto_error <- conditionMessage(fit)
    if (!grepl("converge|convergence", auto_error, ignore.case = TRUE)) stop(fit)
    # Prespecified standard airline model fallback only when automatic estimation fails.
    # This changes the forecast model; X-11 still retains actual irregular movements.
    model_method <- "fixed_airline_after_nonconvergence"
    fit <- seas(y, transform.function = "log", regression.aictest = NULL,
              automdl = NULL, arima.model = "(0 1 1)(0 1 1)", outlier = "", x11 = "", seats = NULL,
              estimate.maxiter = 2000, x11.save = c("d10", "d11", "d12", "d13"), dir = dest)
    writeLines(auto_error, file.path(dest, "automatic_model_error.txt"))
  }
  d$adjusted <- as.numeric(final(fit))
  d$seasonal_factor <- d$value/d$adjusted
  stopifnot(nrow(d) == length(final(fit)), all(is.finite(d$adjusted)), all(d$adjusted > 0))
  results[[id]] <- d
  checks[[id]] <- data.frame(series = id, observations = length(y),
     start = d$date[1], end = tail(d$date, 1),
     model_method = model_method, mean_seasonal_factor = mean(d$seasonal_factor),
     min_seasonal_factor = min(d$seasonal_factor), max_seasonal_factor = max(d$seasonal_factor))
  capture.output(summary(fit), file = file.path(dest, "model_summary.txt"))
  capture.output(print(fit$call), file = file.path(dest, "original_call.txt"))
  cat("Adjusted", id, "\n")
}
write.csv(do.call(rbind, results), file.path(out, "x13_monthly_adjusted.csv"), row.names = FALSE)
write.csv(do.call(rbind, checks), file.path(out, "x13_diagnostics.csv"), row.names = FALSE)
capture.output(sessionInfo(), file = file.path(out, "seasonal_runtime.txt"))
