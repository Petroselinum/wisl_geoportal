from sqlmodel import create_engine
import os
import urllib.parse

# Parametry połączenia pochodzą ze zmiennych środowiskowych. Hasło NIE ma
# domyślnej wartości - bez WISL_DB_PASSWORD połączenie się nie nawiąże. Reszta
# parametrów to jawna konfiguracja lokalnego serwera, więc ma sensowne domyślne
# wartości, które można nadpisać zmiennymi albo argumentami connection().
ZMIENNE = {
    'driver': ('WISL_DB_DRIVER', '{ODBC Driver 17 for SQL Server}'),
    'server': ('WISL_DB_SERVER', 'localhost,1433'),
    'database': ('WISL_DB_NAME', 'WISL_Baza_zbiorcza'),
    'user': ('WISL_DB_USER', 'sa'),
    'password': ('WISL_DB_PASSWORD', None),
}


def connection(driver=None, server=None, database=None, user=None, password=None):
    podane = {'driver': driver, 'server': server, 'database': database,
              'user': user, 'password': password}

    # Argument jawny ma pierwszeństwo przed zmienną środowiskową, a ta przed
    # wartością domyślną.
    wartosci = {
        nazwa: podane[nazwa] or os.environ.get(zmienna) or domyslna
        for nazwa, (zmienna, domyslna) in ZMIENNE.items()
    }

    brakujace = [ZMIENNE[nazwa][0] for nazwa, wartosc in wartosci.items() if wartosc in (None, '')]
    if brakujace:
        raise ValueError(
            "Brak danych połączenia z bazą WISL: " + ", ".join(brakujace) + ".\n"
            "Ustaw je jako zmienne środowiskowe, np.:\n"
            "    export WISL_DB_PASSWORD='...'\n"
            "albo przekaż je bezpośrednio do connection()."
        )

    params = urllib.parse.quote_plus(f'''
                                         DRIVER={wartosci['driver']};
                                         SERVER={wartosci['server']};
                                         DATABASE={wartosci['database']};
                                         UID={wartosci['user']};
                                         PWD={wartosci['password']};
                                         TrustServerCertificate=yes;''')
    engine = create_engine("mssql+pyodbc:///?odbc_connect=%s" % params)
    return engine
