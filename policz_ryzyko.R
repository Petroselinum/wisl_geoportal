suppressPackageStartupMessages({
  library(sf)
  library(spatstat)
  library(sparr)
})


args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Brak argumentu z nazwa pliku sufiksu!")

file_suffix <- args[1]

# 1. Wczytanie okna analizy z wyciszeniem ostrzeżeń GDAL
poland_sf <- suppressWarnings(st_read("KDE_temp/poland_bounds.geojson", quiet = TRUE))
st_crs(poland_sf) <- NA 
poland_owin <- as.owin(poland_sf)

# 2. Wczytanie punktów
tlo_df  <- read.csv("KDE_temp/tlo_points.csv")
uszk_df <- read.csv("KDE_temp/uszk_points.csv")

if (nrow(uszk_df) < 3) {
  cat("Za mało punktów uszkodzeń do przeprowadzenia testu sparr.\n")
  quit(status = 0)
}

# 3. Utworzenie punktów przestrzennych
tlo_ppp <- suppressWarnings(ppp(
  x = tlo_df$x, y = tlo_df$y,
  window = poland_owin,
  marks = tlo_df$waga
))

uszk_ppp <- suppressWarnings(ppp(
  x = uszk_df$x, y = uszk_df$y,
  window = poland_owin,
  marks = uszk_df$waga
))

# 4. Obliczenie ryzyka i p-value (powierzchnia tolerancji)
fit_risk <- risk(
  f = uszk_ppp,
  g = tlo_ppp,
  tolerate = TRUE,
  edge = "diggle",
  h0 = OS(tlo_ppp),
  adapt = FALSE,
  resolution = 400
)

cat("Zakres rr:", range(fit_risk$rr$v, na.rm = TRUE), "\n")
cat("Pasmo f (uszkodzenia):", attr(fit_risk$f, "sigma"), "\n")
cat("Pasmo g (tlo):", attr(fit_risk$g, "sigma"), "\n")

# 5. Ekstrakcja obszarów istotnych (p < 0.05)
p_im <- fit_risk$P
rr_im <- fit_risk$rr

p_window <- solutionset(p_im <= 0.05 & rr_im > 0)

cat("Pole okna istotnego (m^2):", area.owin(p_window), "\n")

if (!is.empty(p_window)) {
  sig_polys_owin <- as.polygonal(p_window)
  sig_sf <- st_as_sf(sig_polys_owin)
  sig_sf <- sig_sf[!st_is_empty(sig_sf), ]
} else {
  sig_sf <- st_sf(geometry = st_sfc(st_polygon()), crs = NA)[0, ]
}

# Zapis do GeoJSON
output_path <- paste0("KDE_uszkodzenia_ryzyko/istotne_", file_suffix, ".geojson")
if (nrow(sig_sf) > 0) {
  suppressWarnings(st_write(sig_sf, output_path, delete_dsn = TRUE, quiet = TRUE))
} else {
  empty_poly <- st_sf(geometry = st_sfc(st_polygon()), crs = NA)[0, ]
  suppressWarnings(st_write(empty_poly, output_path, delete_dsn = TRUE, quiet = TRUE))
}