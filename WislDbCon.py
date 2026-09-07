from sqlmodel import create_engine
import urllib
 
 
def connection(driver='{ODBC Driver 17 for SQL Server}',
               server='localhost,1433',
               database='WISL_Baza_zbiorcza',
               user='sa',
               password='Fifka125!'):

 
    if any(param in (None, '') for param in [driver, server, database, user, password]):
        raise ValueError("Wszystkie parametry muszą być podane i nie mogą być puste.")
 
    params = urllib.parse.quote_plus(f'''
                                         DRIVER={driver};
                                         SERVER={server};
                                         DATABASE={database};
                                         UID={user};
                                         PWD={password};
                                         TrustServerCertificate=yes;''')
    engine = create_engine("mssql+pyodbc:///?odbc_connect=%s" % params)
    return engine
