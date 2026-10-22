# rspiro_bridge.R: called by spirotrace.rspiro (never run by hand).
# Computes GLI predicted, LLN and z-score ranges with the rspiro package for each
# input row, at the corners of the age and height intervals implied by the
# report's rounding, and over the printed value's rounding interval.
#   Usage: Rscript rspiro_bridge.R gli_input.csv gli_output.csv
#   Exit status: 0 ok, 2 rspiro not installed, 3 self-test failed (nothing written).
# Spirometry: GLI-2012 (zscore_GLI, with the ethnic group) and GLI global 2022
# (zscore_GLIgl). Diffusing capacity: GLI 2017 (zscore_GLIdiff; height in metres).

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("usage: Rscript rspiro_bridge.R gli_input.csv gli_output.csv")
if (!requireNamespace("rspiro", quietly = TRUE)) {
  message("R package 'rspiro' is not installed. In R, run: install.packages(\"rspiro\")")
  quit(status = 2)
}
suppressPackageStartupMessages(library(rspiro))

num <- function(x) as.numeric(unlist(x))[1]
# one bad input row (rspiro stops on it) must not lose every other subject's result
safe <- function(expr) tryCatch(expr, error = function(e) NA_real_)

spiro_params <- c("FEV1", "FVC", "FEV1FVC")
diff_params <- c("TLCO", "KCO", "VA")

pred_s <- function(age, ht, sex, eth, p) safe(num(pred_GLI(age, ht, gender = sex, ethnicity = eth, param = p)))
lln_s <- function(age, ht, sex, eth, p) safe(num(LLN_GLI(age, ht, gender = sex, ethnicity = eth, param = p)))
z_s <- function(age, ht, sex, eth, p, y) {
  a <- list(age = age, height = ht, gender = sex, ethnicity = eth)
  a[[p]] <- y
  safe(num(do.call(zscore_GLI, a)))
}
has_gl <- exists("zscore_GLIgl", where = asNamespace("rspiro"), mode = "function")
z_gl <- function(age, ht, sex, p, y) {
  if (!has_gl) return(NA_real_)
  a <- list(age = age, height = ht, gender = sex)
  a[[p]] <- y
  safe(num(do.call(zscore_GLIgl, a)))
}
has_diff <- exists("zscore_GLIdiff", where = asNamespace("rspiro"), mode = "function")
pred_d <- function(age, ht, sex, p, si) {
  if (!has_diff) return(NA_real_)
  safe(num(pred_GLIdiff(age, ht, gender = sex, param = p, SI = si)))
}
lln_d <- function(age, ht, sex, p, si) {
  if (!has_diff) return(NA_real_)
  safe(num(LLN_GLIdiff(age, ht, gender = sex, param = p, SI = si)))
}
z_d <- function(age, ht, sex, p, y, si) {
  if (!has_diff) return(NA_real_)
  a <- list(age = age, height = ht, gender = sex, SI = si)
  a[[p]] <- y
  safe(num(do.call(zscore_GLIdiff, a)))
}

# ---- self-test against the device's example report (GLI 2012, female, Caucasian, 172.5 cm,
# ---- 24.07 years): predicted, LLN, the best value's rounding interval, printed z.
expected <- list(FVC = c(4.36, 3.49, 4.495, 4.505, 0.25), FEV1 = c(3.74, 3.00, 3.845, 3.855, 0.25),
                 FEV1FVC = c(0.863, 0.747, 3.845 / 4.505, 3.855 / 4.495, -0.10))
fails <- character(0)
for (p in names(expected)) {
  e <- expected[[p]]
  tol <- if (p == "FEV1FVC") 0.0006 else 0.006
  got <- c(pred_s(24.07, 1.725, 2, 1, p), lln_s(24.07, 1.725, 2, 1, p))
  zr <- sort(c(z_s(24.07, 1.725, 2, 1, p, e[3]), z_s(24.07, 1.725, 2, 1, p, e[4])))
  if (is.na(got[1]) || abs(got[1] - e[1]) > tol) fails <- c(fails, sprintf("%s pred %.3f (expected %.3f)", p, got[1], e[1]))
  if (is.na(got[2]) || abs(got[2] - e[2]) > tol) fails <- c(fails, sprintf("%s LLN %.3f (expected %.3f)", p, got[2], e[2]))
  if (length(zr) < 2 || e[5] < zr[1] - 0.01 || e[5] > zr[2] + 0.01)
    fails <- c(fails, sprintf("%s z %.3f to %.3f (expected %.2f)", p, zr[1], zr[2], e[5]))
}
if (length(fails)) {
  message("GLI self-test failed:\n  ", paste(fails, collapse = "\n  "))
  quit(status = 3)
}

# ---- rows
inp <- read.csv(args[1], stringsAsFactors = FALSE, fileEncoding = "UTF-8", colClasses = c(id = "character"))
mn <- function(x) if (length(x) && all(!is.na(x))) min(x) else NA_real_
mx <- function(x) if (length(x) && all(!is.na(x))) max(x) else NA_real_
out <- list()
for (i in seq_len(nrow(inp))) {
  r <- inp[i, ]
  alt <- !is.na(suppressWarnings(as.numeric(r$alt))) && as.numeric(r$alt) == 1
  si <- !is.na(suppressWarnings(as.numeric(r$si))) && as.numeric(r$si) == 1
  ages <- seq(r$age_lo, r$age_hi, length.out = 4)
  hts <- c(r$ht_lo, r$ht_hi) / 100
  for (p in c(spiro_params, diff_params)) {
    y <- suppressWarnings(as.numeric(r[[p]]))
    if (is.na(y) && p %in% diff_params) next
    hy <- suppressWarnings(as.numeric(r[[paste0(p, "_h")]]))
    if (length(hy) == 0 || is.na(hy)) hy <- 0
    pr <- l <- z <- zg <- c()
    ze <- lapply(1:5, function(e) c())
    for (age in ages) for (h in hts) {
      if (p %in% spiro_params) {
        pr <- c(pr, pred_s(age, h, r$sex, r$eth, p))
        l <- c(l, lln_s(age, h, r$sex, r$eth, p))
        if (!is.na(y)) {
          z <- c(z, z_s(age, h, r$sex, r$eth, p, y - hy), z_s(age, h, r$sex, r$eth, p, y + hy))
          zg <- c(zg, z_gl(age, h, r$sex, p, y - hy), z_gl(age, h, r$sex, p, y + hy))
          if (alt) for (e in 1:5)
            ze[[e]] <- c(ze[[e]], z_s(age, h, r$sex, e, p, y - hy), z_s(age, h, r$sex, e, p, y + hy))
        }
      } else {
        pr <- c(pr, pred_d(age, h, r$sex, p, si))
        l <- c(l, lln_d(age, h, r$sex, p, si))
        z <- c(z, z_d(age, h, r$sex, p, y - hy, si), z_d(age, h, r$sex, p, y + hy, si))
      }
    }
    row <- data.frame(id = r$id, param = p, pred_min = mn(pr), pred_max = mx(pr),
                      lln_min = mn(l), lln_max = mx(l), z_min = mn(z), z_max = mx(z),
                      zgl_min = mn(zg), zgl_max = mx(zg), stringsAsFactors = FALSE)
    for (e in 1:5) {
      row[[paste0("zeth", e, "_min")]] <- mn(ze[[e]])
      row[[paste0("zeth", e, "_max")]] <- mx(ze[[e]])
    }
    out[[length(out) + 1]] <- row
  }
}
cols <- c("id", "param", "pred_min", "pred_max", "lln_min", "lln_max", "z_min", "z_max",
          "zgl_min", "zgl_max", paste0("zeth", rep(1:5, each = 2), c("_min", "_max")))
res <- if (length(out)) do.call(rbind, out) else
  as.data.frame(setNames(replicate(length(cols), character(0), simplify = FALSE), cols))
write.csv(res, args[2], row.names = FALSE, fileEncoding = "UTF-8")
