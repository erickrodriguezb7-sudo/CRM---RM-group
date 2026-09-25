"""Copia los datos de un crm.db (SQLite) a la base de Supabase.

Uso (una sola vez, con la base de Supabase vacía):

    python migrar_sqlite.py ruta/a/crm.db "postgresql://..."

Conserva los ids, así que los contactos siguen apuntando a su cliente.
"""

import sqlite3
import sys

import database as db

TABLAS = ["clientes", "contactos", "usuarios"]


def main(ruta_sqlite, url):
    origen = sqlite3.connect(ruta_sqlite)
    origen.row_factory = sqlite3.Row
    destino = db.get_conn(url)
    db.init_db(destino)

    with destino.transaction():
        for tabla in TABLAS:
            filas = [dict(r) for r in origen.execute(f"SELECT * FROM {tabla}")]
            if not filas:
                print(f"{tabla}: 0 filas")
                continue
            columnas = list(filas[0])
            sql = (
                f"INSERT INTO {tabla} ({', '.join(columnas)}) "
                f"VALUES ({', '.join(f'%({c})s' for c in columnas)})"
            )
            with destino.cursor() as cur:
                cur.executemany(sql, filas)
            # Que los ids nuevos sigan después del mayor copiado.
            destino.execute(
                f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
                f"(SELECT MAX(id) FROM {tabla}))"
            )
            print(f"{tabla}: {len(filas)} filas")

    print("Listo.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
