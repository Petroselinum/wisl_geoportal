suppressPackageStartupMessages({
  library(sf)
  library(spatstat)
  library(sparr)
})


args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Brak argumentu z nazwa pliku sufiksu!")

file_suffix <- args[1]

# Wspolna rozdzielczosc siatki z odpowiednikami w Pythonie (kde_gat.py,
# kde_uszkodzenia.py, kde_martwe_drewno.py uzywaja 500x500)
ROZDZIELCZOSC <- 500

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

if (nrow(tlo_df) < 100) {
  cat("Uwaga: tylko", nrow(tlo_df), "traktow tla (prog wiarygodnosci: 100). Wynik moze byc niewiarygodny.\n")
}

# 3. Utworzenie punktów przestrzennych
# ppp(..., window=) po cichu ODRZUCA punkty leżące poza oknem (np. przez
# uproszczenie granicy Polski przy zaokrągleniach współrzędnych) - trzeba
# odfiltrować wagi TYM SAMYM warunkiem, inaczej wektor wag przestaje się
# zgadzać długością z zachowanymi punktami (bivariate.density odmawia
# wtedy pracy: "length of 'weights' must match number of observations").
#
# Marks NIE sa tu wagami dla risk()/bivariate.density() (te maja osobny
# parametr `weights`, patrz niżej) - trzymane tylko informacyjnie, zeby ppp
# bylo czytelne przy ewentualnym debugowaniu w R.
tlo_in <- inside.owin(tlo_df$x, tlo_df$y, poland_owin)
uszk_in <- inside.owin(uszk_df$x, uszk_df$y, poland_owin)
if (any(!tlo_in) || any(!uszk_in)) {
  cat("Uwaga: odrzucono", sum(!tlo_in), "punkt(y) tla i", sum(!uszk_in),
      "punkt(y) uszkodzen spoza granic Polski (KDE_temp/poland_bounds.geojson).\n")
}
tlo_df <- tlo_df[tlo_in, ]
uszk_df <- uszk_df[uszk_in, ]

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

# 4. Dobor pasma - LSCV.risk() jest dedykowany do porownania dwoch wzorcow
# punktowych (case/control), w przeciwienstwie do OS(), ktora patrzy tylko
# na rozrzut tla. Dziala na SUROWYCH lokalizacjach punktow (LSCV.risk nie
# przyjmuje wag), ale wybrane pasmo stosujemy pozniej do wazonych gestosci
# ponizej. Fallback do OS(tlo) gdy CV sie nie powiedzie (np. zbyt malo /
# zbyt regularnie rozlozonych punktow uszkodzen).
h0 <- tryCatch({
  h <- LSCV.risk(f = uszk_ppp, g = tlo_ppp, method = "kelsall-diggle", verbose = FALSE)
  cat("Pasmo (LSCV.risk):", h, "\n")
  h
}, error = function(e) {
  h <- OS(tlo_ppp)
  cat("LSCV.risk nie powiodlo sie (", conditionMessage(e), "), uzywam OS(tlo):", h, "\n")
  h
})

# 5. Estymacja gestosci Z UWZGLEDNIENIEM WAG (WSP_Z dla tla,
# WSP_Z*NASIL_USZK dla uszkodzen).
#
# WAZNA PULAPKA (sprawdzona empirycznie): risk() wywolane bezposrednio na
# obiektach ppp z marks CICHO IGNORUJE te marks jako wagi - marks() jest
# zerowane wewnatrz risk() przed policzeniem gestosci, a bivariate.density()
# (ktore risk() wywoluje wewnetrznie) ma OSOBNY parametr `weights`,
# niepowiazany z marks. Efekt: bez tej poprawki test istotnosci liczyl
# "czy uszkodzone trakty (0/1) skupiaja sie wzgledem tla", a nie "czy
# WSP_Z*NASIL_USZK-wazona ilosc uszkodzen sie skupia" - inna metoda niz
# percentylowa mapa w kde_uszkodzenia.py, mimo ze mialy liczyc to samo.
#
# Rozwiazanie: policzyc wazone gestosci recznie przez bivariate.density()
# (ktore weights obsluguje), a gotowe obiekty klasy `bivden` podac do
# risk() - w tej galezi risk() NIE przelicza juz gestosci samo, tylko
# bierze je 1:1 (sprawdzone w zrodle sparr::risk).
fd <- bivariate.density(
  uszk_ppp, h0 = h0, resolution = ROZDZIELCZOSC, edge = "diggle",
  weights = uszk_df$waga, verbose = FALSE
)
gd <- bivariate.density(
  tlo_ppp, h0 = h0, resolution = ROZDZIELCZOSC, edge = "diggle",
  weights = tlo_df$waga, verbose = FALSE
)

fit_risk <- risk(f = fd, g = gd, tolerate = TRUE, verbose = FALSE)

cat("Zakres rr (log):", range(fit_risk$rr$v, na.rm = TRUE), "\n")
cat("Pasmo f (uszkodzenia):", fit_risk$f$h0, "\n")
cat("Pasmo g (tlo):", fit_risk$g$h0, "\n")

# ZASTRZEZENIE: formula wariancji uzywana wewnatrz sparr do liczenia
# powyzszego p (tol.asy.fix) zaklada rownowagowy proces punktowy
# (standardowa asymptotyka Kelsall-Diggle 1995, oparta o LICZBE punktow,
# nie o efektywna wielkosc proby po uwzglednieniu wag). Powyzsza poprawka
# naprawia GESTOSC/rr (teraz poprawnie wazona), ale p-wartosci przy silnie
# niejednorodnych wagach nalezy traktowac jako przyblizenie, nie scisly
# test - podobnie jak ponizszy brak korekty na wielokrotne testowanie.
cat("n uszkodzen (punkty):", npoints(uszk_ppp), " n tla (punkty):", npoints(tlo_ppp), "\n")

# 6. Ekstrakcja obszarów istotnych (p < 0.05)
# UWAGA: powierzchnia p<=0.05 NIE jest skorygowana o wielokrotne testowanie
# (siatka ROZDZIELCZOSC x ROZDZIELCZOSC pikseli testowana niezaleznie) - to
# akceptowane w literaturze ograniczenie metody tolerance contours
# (Kelsall & Diggle), ale wynik nalezy czytac jako eksploracyjny, nie
# potwierdzajacy w sensie scislej kontroli błędu I rodzaju.
p_im <- fit_risk$P
rr_im <- fit_risk$rr

p_window <- solutionset(p_im <= 0.05 & rr_im > 0)

cat("Pole okna istotnego (m^2, bez korekty na wielokrotne testowanie):", area.owin(p_window), "\n")

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
