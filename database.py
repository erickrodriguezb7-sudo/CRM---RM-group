"""Capa de acceso a datos del CRM (SQLite).

Todas las fechas se guardan como texto ISO 'YYYY-MM-DD' para que las
comparaciones y los ordenamientos funcionen directamente en SQL.
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "crm.db"

# Fecha de modificación de este archivo al cargarlo; app.py la compara para
# saber si el módulo en memoria quedó viejo tras una actualización del código.
MTIME_CARGA = Path(__file__).stat().st_mtime

ESTADOS = ["Negociación", "Cliente Activo", "Inactivo"]
TIPOS = ["Cliente", "Suplidor"]
TIPOS_CONTACTO = ["Llamada", "Email", "Reunión", "WhatsApp", "Visita"]
RESULTADOS = [
    "Interesado",
    "Pendiente de respuesta",
    "Cotización enviada",
    "Venta cerrada",
    "No interesado",
    "Sin respuesta",
]

DIAS_SIN_CONTACTO = 7

# Días desde el último contacto (o desde el alta, si nunca se contactó) hasta
# el próximo seguimiento, según tipo y estado.
DIAS_SEGUIMIENTO = {
    "Cliente": {"Negociación": 3, "Cliente Activo": 14, "Inactivo": 60},
    "Suplidor": {"Negociación": 7, "Cliente Activo": 30, "Inactivo": 90},
}

# El resultado del último contacto manda sobre la tabla anterior. Los que no
# aparecen aquí ("Venta cerrada") usan los días del tipo y estado.
DIAS_POR_RESULTADO = {
    "Cotización enviada": 2,
    "Interesado": 3,
    "Pendiente de respuesta": 3,
    "Sin respuesta": 3,
    "No interesado": 60,
}


# --------------------------------------------------------------------------
# Conexión e inicialización
# --------------------------------------------------------------------------

def get_conn():
    """Conexión a SQLite. check_same_thread=False porque Streamlit reejecuta
    el script en hilos distintos."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre              TEXT NOT NULL,
            empresa             TEXT,
            telefono            TEXT,
            email               TEXT,
            ubicacion           TEXT,
            giro_negocio        TEXT,
            productos_interes   TEXT,
            estado              TEXT NOT NULL DEFAULT 'Negociación',
            tipo                TEXT NOT NULL DEFAULT 'Cliente',
            fecha_creacion      TEXT NOT NULL,
            proximo_seguimiento TEXT
        );

        CREATE TABLE IF NOT EXISTS contactos (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id    INTEGER NOT NULL,
            fecha         TEXT NOT NULL,
            tipo_contacto TEXT NOT NULL,
            notas         TEXT,
            resultado     TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_contactos_cliente
            ON contactos (cliente_id, fecha DESC);
        """
    )

    # Bases creadas antes de distinguir suplidores de clientes: los registros
    # existentes quedan como "Cliente".
    columnas = {r["name"] for r in conn.execute("PRAGMA table_info(clientes)")}
    if "tipo" not in columnas:
        conn.execute("ALTER TABLE clientes ADD COLUMN tipo TEXT NOT NULL DEFAULT 'Cliente'")

    # El seguimiento ya no se fija a mano: los registros que quedaron sin fecha
    # reciben la calculada.
    for row in conn.execute(
        "SELECT id FROM clientes WHERE proximo_seguimiento IS NULL OR proximo_seguimiento = ''"
    ).fetchall():
        recalcular_seguimiento(conn, row["id"], commit=False)

    conn.commit()


# --------------------------------------------------------------------------
# Clientes
# --------------------------------------------------------------------------

def crear_cliente(conn, datos):
    cur = conn.execute(
        """
        INSERT INTO clientes (nombre, empresa, telefono, email, ubicacion,
                              productos_interes, estado, tipo, fecha_creacion)
        VALUES (:nombre, :empresa, :telefono, :email, :ubicacion,
                :productos_interes, :estado, :tipo, :fecha_creacion)
        """,
        {**datos, "fecha_creacion": date.today().isoformat()},
    )
    recalcular_seguimiento(conn, cur.lastrowid)
    return cur.lastrowid


def actualizar_cliente(conn, cliente_id, datos):
    """Guarda los datos del registro.

    El seguimiento solo se recalcula si cambia el tipo o el estado; corregir un
    teléfono no debe deshacer un seguimiento pospuesto a mano.
    """
    antes = obtener_cliente(conn, cliente_id)
    conn.execute(
        """
        UPDATE clientes
           SET nombre = :nombre, empresa = :empresa, telefono = :telefono,
               email = :email, ubicacion = :ubicacion,
               productos_interes = :productos_interes, estado = :estado,
               tipo = :tipo
         WHERE id = :id
        """,
        {**datos, "id": cliente_id},
    )
    if (antes["tipo"], antes["estado"]) != (datos["tipo"], datos["estado"]):
        recalcular_seguimiento(conn, cliente_id, commit=False)
    conn.commit()


def eliminar_cliente(conn, cliente_id):
    """Elimina el cliente y, en cascada, todo su historial de contactos."""
    conn.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()


def obtener_cliente(conn, cliente_id):
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    return dict(row) if row else None


def listar_clientes(conn, busqueda="", estado="Todos", tipo="Ambos"):
    """Lista suplidores y clientes con su último contacto y total de contactos.

    La búsqueda cubre nombre, empresa, ubicación y productos de interés.
    `tipo` filtra por "Cliente" o "Suplidor"; "Ambos" no filtra.
    """
    sql = """
        SELECT c.*,
               MAX(ct.fecha)                     AS ultimo_contacto,
               COUNT(ct.id)                      AS total_contactos
          FROM clientes c
          LEFT JOIN contactos ct ON ct.cliente_id = c.id
         WHERE 1 = 1
    """
    params = {}

    if busqueda:
        sql += """
             AND (c.nombre LIKE :q OR c.empresa LIKE :q
                  OR c.ubicacion LIKE :q OR c.productos_interes LIKE :q)
        """
        params["q"] = f"%{busqueda}%"

    if estado and estado != "Todos":
        sql += " AND c.estado = :estado"
        params["estado"] = estado

    if tipo and tipo != "Ambos":
        sql += " AND c.tipo = :tipo"
        params["tipo"] = tipo

    sql += " GROUP BY c.id ORDER BY c.nombre COLLATE NOCASE"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def contar_clientes(conn):
    return conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]


# --------------------------------------------------------------------------
# Contactos
# --------------------------------------------------------------------------

def agregar_contacto(conn, cliente_id, fecha, tipo_contacto, notas, resultado):
    """Registra el contacto y devuelve el próximo seguimiento recalculado."""
    conn.execute(
        """
        INSERT INTO contactos (cliente_id, fecha, tipo_contacto, notas, resultado)
        VALUES (?, ?, ?, ?, ?)
        """,
        (cliente_id, fecha.isoformat(), tipo_contacto, notas, resultado),
    )
    return recalcular_seguimiento(conn, cliente_id)


def eliminar_contacto(conn, contacto_id):
    row = conn.execute("SELECT cliente_id FROM contactos WHERE id = ?", (contacto_id,)).fetchone()
    conn.execute("DELETE FROM contactos WHERE id = ?", (contacto_id,))
    if row:
        recalcular_seguimiento(conn, row["cliente_id"], commit=False)
    conn.commit()


def listar_contactos(conn, cliente_id=None):
    sql = """
        SELECT ct.*, c.nombre AS cliente, c.empresa AS empresa
          FROM contactos ct
          JOIN clientes c ON c.id = ct.cliente_id
    """
    params = ()
    if cliente_id is not None:
        sql += " WHERE ct.cliente_id = ?"
        params = (cliente_id,)
    sql += " ORDER BY ct.fecha DESC, ct.id DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def dias_hasta_seguimiento(tipo, estado, ultimo_resultado=None):
    """Días entre el último contacto y el próximo seguimiento."""
    if ultimo_resultado in DIAS_POR_RESULTADO:
        return DIAS_POR_RESULTADO[ultimo_resultado]
    por_estado = DIAS_SEGUIMIENTO.get(tipo, DIAS_SEGUIMIENTO["Cliente"])
    # Estados que ya no existen (el antiguo "Prospecto") cuentan como Negociación.
    return por_estado.get(estado, por_estado["Negociación"])


def recalcular_seguimiento(conn, cliente_id, commit=True):
    """Fija el próximo seguimiento a partir del último contacto (o del alta).

    Devuelve la nueva fecha, o None si el registro no existe.
    """
    cliente = conn.execute(
        "SELECT tipo, estado, fecha_creacion FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()
    if not cliente:
        return None

    ultimo = conn.execute(
        """
        SELECT fecha, resultado FROM contactos
         WHERE cliente_id = ?
         ORDER BY fecha DESC, id DESC
         LIMIT 1
        """,
        (cliente_id,),
    ).fetchone()

    base = date.fromisoformat(ultimo["fecha"] if ultimo else cliente["fecha_creacion"])
    dias = dias_hasta_seguimiento(
        cliente["tipo"], cliente["estado"], ultimo["resultado"] if ultimo else None
    )
    nueva = base + timedelta(days=dias)
    conn.execute(
        "UPDATE clientes SET proximo_seguimiento = ? WHERE id = ?",
        (nueva.isoformat(), cliente_id),
    )
    if commit:
        conn.commit()
    return nueva


def fijar_proximo_seguimiento(conn, cliente_id, fecha):
    conn.execute(
        "UPDATE clientes SET proximo_seguimiento = ? WHERE id = ?",
        (fecha.isoformat() if fecha else None, cliente_id),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Seguimiento y métricas
# --------------------------------------------------------------------------

def seguimientos(conn, dias_proximos=7):
    """Devuelve (vencidos, hoy, proximos) según la fecha de próximo seguimiento."""
    hoy = date.today()
    limite = (hoy + timedelta(days=dias_proximos)).isoformat()

    filas = [
        dict(r)
        for r in conn.execute(
            """
            SELECT c.*, MAX(ct.fecha) AS ultimo_contacto
              FROM clientes c
              LEFT JOIN contactos ct ON ct.cliente_id = c.id
             WHERE c.proximo_seguimiento IS NOT NULL
               AND c.proximo_seguimiento <> ''
               AND c.proximo_seguimiento <= ?
             GROUP BY c.id
             ORDER BY c.proximo_seguimiento
            """,
            (limite,),
        ).fetchall()
    ]

    hoy_iso = hoy.isoformat()
    vencidos = [f for f in filas if f["proximo_seguimiento"] < hoy_iso]
    para_hoy = [f for f in filas if f["proximo_seguimiento"] == hoy_iso]
    proximos = [f for f in filas if f["proximo_seguimiento"] > hoy_iso]
    return vencidos, para_hoy, proximos


def clientes_sin_contactar(conn, dias=DIAS_SIN_CONTACTO):
    """Clientes cuyo último contacto (o alta, si nunca se les contactó)
    tiene `dias` o más de antigüedad."""
    limite = (date.today() - timedelta(days=dias)).isoformat()
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT c.*,
                   MAX(ct.fecha) AS ultimo_contacto,
                   COUNT(ct.id)  AS total_contactos
              FROM clientes c
              LEFT JOIN contactos ct ON ct.cliente_id = c.id
             GROUP BY c.id
            HAVING COALESCE(MAX(ct.fecha), c.fecha_creacion) <= ?
             ORDER BY COALESCE(MAX(ct.fecha), c.fecha_creacion)
            """,
            (limite,),
        ).fetchall()
    ]


def metricas(conn):
    por_estado = {e: 0 for e in ESTADOS}
    for row in conn.execute("SELECT estado, COUNT(*) AS n FROM clientes GROUP BY estado"):
        por_estado[row["estado"]] = row["n"]

    total = sum(por_estado.values())
    activos = por_estado.get("Cliente Activo", 0)

    contactos_mes = conn.execute(
        "SELECT COUNT(*) FROM contactos WHERE fecha >= ?",
        ((date.today() - timedelta(days=30)).isoformat(),),
    ).fetchone()[0]

    return {
        "total": total,
        "por_estado": por_estado,
        "activos": activos,
        "tasa_conversion": (activos / total * 100) if total else 0.0,
        "contactos_mes": contactos_mes,
    }
