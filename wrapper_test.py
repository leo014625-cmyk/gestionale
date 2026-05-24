import sqlite3
import re

class RealDictCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        # Sostituisci %s con ? ma solo quelli che non sono %%
        query = re.sub(r'(?<!%)%s', '?', query)
        # Sostituisci make_date(anno, mese, 1) con printf
        query = query.replace("make_date(anno, mese, 1)", "printf('%04d-%02d-01', anno, mese)")
        query = query.replace("make_date(f.anno, f.mese, 1)", "printf('%04d-%02d-01', f.anno, f.mese)")
        query = query.replace("ILIKE", "LIKE")
        
        try:
            if params:
                self._cursor.execute(query, params)
            else:
                self._cursor.execute(query)
        except Exception as e:
            print("FAILED QUERY:", query)
            print("PARAMS:", params)
            raise e

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self._cursor.fetchall()]

    def __getattr__(self, name):
        return getattr(self._cursor, name)

class SQLiteWrapper:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def cursor(self, cursor_factory=None):
        return RealDictCursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

wrapper = SQLiteWrapper('./__project_root/gestionale.db')
with wrapper as db:
    cur = db.cursor()
    cur.execute("SELECT * FROM clienti WHERE id = %s", (1,))
    print(cur.fetchone())
    
    cur.execute("SELECT * FROM clienti WHERE nome ILIKE %s", ('%MioNome%',))
    print(cur.fetchall())
