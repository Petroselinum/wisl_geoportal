from sqlmodel import create_engine
import urllib

def connection(driver='{ODBC Driver 17 for SQL Server}', 
               server='BudniakP', 
               database='WISL_baza_zbiorcza_IV_cykl_MJ20250226', 
               trusted_connection='yes'):
    
    '''Funkcja zwraca obiekt silnika SQLAlchemy do połączenia z lokalną bazą danych WISL'''

    if any (param == '' for param in [driver, server, database, trusted_connection]):
        raise ValueError("Wszystkie parametry muszą być podane i nie mogą być puste.")

    params = urllib.parse.quote_plus(f'''
                                     DRIVER={driver};
                                     SERVER={server};
                                     DATABASE={database};
                                     Trusted_Connection={trusted_connection};
                                     TrustServerCertificate=yes;''')
    
    engine = create_engine("mssql+pyodbc:///?odbc_connect=%s" % params)
    return engine

