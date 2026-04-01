from sqlmodel import SQLModel
from sqlalchemy import Table, MetaData
from WislDbCon import connection

engine = connection()

metadata = MetaData()

class ADRES_POW(SQLModel, table=True):
    __tablename__ = 'ADRES_POW'
    __table__ = Table('ADRES_POW', metadata, autoload_with=engine)

class DRZEWA_OD_7(SQLModel, table=True):
    __tablename__ = 'DRZEWA_OD_7'
    __table__ = Table('DRZEWA_OD_7', metadata, autoload_with=engine)

class OBL_DRZEWA_OD_7(SQLModel, table=True):
    __tablename__ = 'OBL_DRZEWA_OD_7'
    __table__ = Table('OBL_DRZEWA_OD_7', metadata, autoload_with=engine)

class OBL_ADRES_POW(SQLModel, table=True):
    __tablename__ = 'OBL_ADRES_POW'
    __table__ = Table('OBL_ADRES_POW', metadata, autoload_with=engine)

class DRZEWA_MARTWE(SQLModel, table=True):
    __tablename__ = 'DRZEWA_MARTWE'
    __table__ = Table('DRZEWA_MARTWE', metadata, autoload_with=engine)

class OBL_DRZEWA_MARTWE(SQLModel, table=True):
    __tablename__ = 'OBL_DRZEWA_MARTWE'
    __table__ = Table('OBL_DRZEWA_MARTWE', metadata, autoload_with=engine)