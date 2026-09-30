"""
Lokalny serwer portalu mapowego (1_portal_mapowy_wisl.py).

Działa jak `python -m http.server`, ale:
- dodaje nagłówek Cache-Control: no-cache - przeglądarka przy każdym otwarciu
  pyta serwer, czy plik się zmienił (odpowiedź 304, gdy nie), więc po
  przebudowie portalu nie pokazuje starej wersji z pamięci podręcznej
  (sam http.server wysyła tylko Last-Modified i przeglądarka potrafi długo
  używać starej kopii);
- zawsze serwuje katalog projektu, niezależnie od katalogu uruchomienia
  (logo portalu ma ścieżkę /data/...).

Uruchomienie:  python serwer.py [port]      (domyślnie 8000)
"""
import argparse
import functools
import http.server
from pathlib import Path

KATALOG = Path(__file__).resolve().parent


class BezPamieciPodrecznej(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description='Lokalny serwer portalu WISL')
    parser.add_argument('port', nargs='?', type=int, default=8000)
    port = parser.parse_args().port
    handler = functools.partial(BezPamieciPodrecznej, directory=str(KATALOG))
    with http.server.ThreadingHTTPServer(('', port), handler) as serwer:
        print(f'Portal: http://localhost:{port}/wygerenowane_animacje/aplikacja_mapowa.html')
        serwer.serve_forever()


if __name__ == '__main__':
    main()
