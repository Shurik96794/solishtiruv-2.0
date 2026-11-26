"""Server-side permission and revisioned section storage foundation."""
import json
import sqlite3

SECTIONS = tuple(range(18))

def initialize(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS section_access (login TEXT NOT NULL, section INTEGER NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('read','write')), PRIMARY KEY(login,section))")
    conn.execute("CREATE TABLE IF NOT EXISTS section_data (section INTEGER PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)")

def allowed(conn, identity, section, write=False):
    if not identity or section not in SECTIONS:
        return False
    login, role = identity
    if role == 'admin':
        return True
    row = conn.execute("SELECT mode FROM section_access WHERE login=? AND section=?", (login, section)).fetchone()
    return bool(row and (not write or row[0] == 'write'))

def grant(conn, identity, login, section, mode):
    if not identity or identity[1] != 'admin':
        raise PermissionError()
    if section not in SECTIONS or mode not in ('read','write',None):
        raise ValueError()
    if not conn.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
        raise ValueError('Unknown user')
    if mode is None:
        conn.execute("DELETE FROM section_access WHERE login=? AND section=?", (login,section))
    else:
        conn.execute("INSERT OR REPLACE INTO section_access VALUES (?,?,?)", (login,section,mode))

def read(conn, identity, section):
    if not allowed(conn,identity,section):
        raise PermissionError()
    row = conn.execute("SELECT revision,payload FROM section_data WHERE section=?", (section,)).fetchone()
    return {'revision':row[0],'data':json.loads(row[1])} if row else {'revision':0,'data':None}

def write(conn, identity, section, revision, data):
    # Caller must use a fresh connection; serialize permission and revision checks.
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not allowed(conn,identity,section,True):
            raise PermissionError()
        row = conn.execute("SELECT revision FROM section_data WHERE section=?", (section,)).fetchone()
        current = row[0] if row else 0
        if revision != current:
            raise ValueError('Revision conflict')
        conn.execute("INSERT OR REPLACE INTO section_data VALUES (?,?,?)",(section,current+1,json.dumps(data,ensure_ascii=False)))
        conn.commit()
        return current+1
    except Exception:
        conn.rollback()
        raise
