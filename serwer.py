"""
Lokalny serwer portalu mapowego (1_portal_mapowy_wisl.py).

Działa jak `python -m http.server`, ale:
- dodaje nagłówek Cache-Control: no-cache - przeglądarka przy każdym otwarciu
  pyta serwer, czy plik się zmienił (odpowiedź 304, gdy nie), więc po
  przebudowie portalu nie pokazuje starej wersji z pamięci podręcznej
  (sam http.server wysyła tylko Last-Modified i przeglądarka potrafi długo
  używać starej kopii);
- zawsze serwuje katalog projektu, niezależnie od katalogu uruchomienia
  (logo portalu ma ścieżkę /data/...);
- domyślnie nasłuchuje TYLKO na 127.0.0.1 (ten komputer) - wcześniej na
  wszystkich interfejsach, więc każdy w sieci lokalnej widział cały katalog
  projektu (.git, KDE_temp ze współrzędnymi traktów, raporty, kod);
- udostępnia WYŁĄCZNIE pliki potrzebne portalowi (DOZWOLONE) - reszta
  katalogu odpowiada 404, także przy --siec;
- po starcie otwiera portal w domyślnej przeglądarce systemu (moduł
  webbrowser), a nie w podglądzie VS Code, do którego trafiał adres
  kliknięty w terminalu edytora. Adres ma dopisek ?v=<czas przebudowy
  portalu>: przeglądarka nie użyje starej kopii z pamięci podręcznej
  (2026-10-09 Firefox pokazywał wersję sprzed usunięcia ortofotomapy Esri,
  zapisaną bez Cache-Control, i nie pytał serwera o nowszą);
- gdy port zajmuje poprzedni serwer.py (np. zostawiony w innym terminalu),
  zatrzymuje go i startuje od nowa; innego programu na porcie nie zamyka -
  podaje jego nazwę i wolny port.

Uruchomienie:  python serwer.py [port] [--siec] [--bez-przegladarki]   (domyślnie 8000)
    --siec              nasłuch na wszystkich interfejsach (dostęp z innych
                        komputerów w sieci lokalnej - nadal tylko pliki portalu)
    --bez-przegladarki  nie otwiera przeglądarki (sam serwer)
"""
import argparse
import errno
import functools
import http.server
import os
import posixpath
import re
import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlsplit

KATALOG = Path(__file__).resolve().parent
PORTAL = '/wygerenowane_animacje/aplikacja_mapowa.html'

# Pliki potrzebne portalowi: sam portal z danymi KDE, logo i mapy PNG
# skryptów kde_* (przycisk "Pobierz mapę PNG").
DOZWOLONE = [
    re.compile(r'/wygerenowane_animacje/[^/]+'),
    re.compile(r'/data/WISL_logo_opis\.png'),
    re.compile(r'/KDE_[A-Za-z_]+/[^/]+\.png'),
]


class SerwerPortalu(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def send_head(self):
        sciezka = posixpath.normpath(unquote(urlsplit(self.path).path))
        if sciezka in ('/', '.'):
            self.send_response(302)
            self.send_header('Location', PORTAL)
            self.end_headers()
            return None
        if not any(w.fullmatch(sciezka) for w in DOZWOLONE):
            self.send_error(404)
            return None
        return super().send_head()


def wolny_port(adres, od, ile=50):
    """Pierwszy wolny port od `od` (do podpowiedzi przy zajętym porcie) albo None."""
    for port in range(od, od + ile):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((adres, port))
                return port
            except OSError:
                continue
    return None


def procesy_na_porcie(port):
    """PID-y procesów nasłuchujących na porcie TCP (Linux: /proc/net/tcp[6]
    i deskryptory w /proc/<pid>/fd - widoczne są procesy tego samego
    użytkownika). Poza Linuksem pusty zbiór."""
    inody = set()
    for plik in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(plik) as f:
                next(f)
                for linia in f:
                    pola = linia.split()
                    # pola[1] = adres:port szesnastkowo, pola[3] = stan (0A = LISTEN)
                    if pola[3] == '0A' and int(pola[1].rsplit(':', 1)[1], 16) == port:
                        inody.add(pola[9])
        except OSError:
            continue
    pidy = set()
    if not inody:
        return pidy
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            for fd in os.listdir(f'/proc/{pid}/fd'):
                cel = os.readlink(f'/proc/{pid}/fd/{fd}')
                if cel.startswith('socket:[') and cel[8:-1] in inody:
                    pidy.add(int(pid))
                    break
        except OSError:
            continue
    return pidy


def polecenie(pid):
    """Argumenty uruchomienia procesu (/proc/<pid>/cmdline) albo []."""
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            return [a.decode(errors='replace') for a in f.read().split(b'\0') if a]
    except OSError:
        return []


def zwolnij_port(port, adres):
    """Zatrzymuje poprzedni serwer.py nasłuchujący na porcie. Zwraca True,
    gdy port jest już wolny; False, gdy port zajmuje inny program albo nie
    da się ustalić jaki (wtedy nic nie jest zamykane)."""
    pidy = procesy_na_porcie(port)
    if not pidy:
        return False
    obce = [p for p in pidy if not any(Path(a).name == 'serwer.py' for a in polecenie(p))]
    if obce:
        for p in obce:
            print(f'Port {port} zajmuje inny program (PID {p}: {" ".join(polecenie(p))[:100]}) '
                  f'- nie zamykam go.', file=sys.stderr)
        return False
    for p in pidy:
        print(f'Port {port} zajmuje poprzedni serwer portalu (PID {p}) - zatrzymuję go.', flush=True)
        os.kill(p, signal.SIGTERM)
    # czekamy, aż port się zwolni; po 5 s - SIGKILL
    for proba in range(100):
        if wolny_port(adres, port, ile=1) == port:
            return True
        if proba == 50:
            for p in pidy:
                try:
                    os.kill(p, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        time.sleep(0.1)
    return False


def main():
    parser = argparse.ArgumentParser(description='Lokalny serwer portalu WISL')
    parser.add_argument('port', nargs='?', type=int, default=8000)
    parser.add_argument('--siec', action='store_true',
                        help='nasłuch na wszystkich interfejsach (sieć lokalna)')
    parser.add_argument('--bez-przegladarki', action='store_true',
                        help='nie otwieraj portalu w przeglądarce')
    argumenty = parser.parse_args()
    adres = '' if argumenty.siec else '127.0.0.1'
    handler = functools.partial(SerwerPortalu, directory=str(KATALOG))
    url = f'http://localhost:{argumenty.port}{PORTAL}'
    plik_portalu = KATALOG / PORTAL.lstrip('/')
    try:
        serwer = http.server.ThreadingHTTPServer((adres, argumenty.port), handler)
    except OSError as blad:
        if blad.errno != errno.EADDRINUSE:
            raise
        # najczęściej poprzedni serwer.py działa jeszcze w innym terminalu -
        # zatrzymujemy go i startujemy od nowa
        if not zwolnij_port(argumenty.port, adres):
            print(f'Port {argumenty.port} jest zajęty.', file=sys.stderr)
            wolny = wolny_port(adres, argumenty.port + 1)
            if wolny:
                print(f'Wolny port: python serwer.py {wolny}', file=sys.stderr)
            sys.exit(1)
        serwer = http.server.ThreadingHTTPServer((adres, argumenty.port), handler)
    with serwer:
        print(f'Portal: {url}' + ('  (dostępny w sieci lokalnej)' if argumenty.siec else ''), flush=True)
        if not plik_portalu.exists():
            print('Brak zbudowanego portalu - uruchom najpierw 1_portal_mapowy_wisl.py', flush=True)
        elif not argumenty.bez_przegladarki:
            # gniazdo już nasłuchuje (konstruktor serwera), więc przeglądarka
            # może pytać od razu; osobny wątek - otwieranie nie blokuje serwera
            wersja = int(plik_portalu.stat().st_mtime)
            threading.Thread(target=webbrowser.open, args=(f'{url}?v={wersja}',),
                             kwargs={'new': 1}, daemon=True).start()
        print('Zatrzymanie: Ctrl+C', flush=True)
        try:
            serwer.serve_forever()
        except KeyboardInterrupt:
            print('\nSerwer zatrzymany.')


if __name__ == '__main__':
    main()
