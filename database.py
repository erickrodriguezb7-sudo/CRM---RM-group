"""Capa de acceso a datos del CRM (SQLite).

Todas las fechas se guardan como texto ISO 'YYYY-MM-DD' para que las
comparaciones y los ordenamientos funcionen directamente en SQL (el último
acceso de cada usuario lleva además la hora: 'YYYY-MM-DD HH:MM').
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta
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

ADMIN = "Administrador"
ROLES = [ADMIN, "Usuario"]
LARGO_MIN_CONTRASENA = 8

# PBKDF2 de la biblioteca estándar: sin dependencias nuevas. Las iteraciones se
# guardan junto a cada hash, así que subirlas más adelante no invalida las
# contraseñas ya guardadas.
ITERACIONES_HASH = 600_000


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

        CREATE TABLE IF NOT EXISTS usuarios (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario         TEXT NOT NULL UNIQUE COLLATE NOCASE,
            nombre          TEXT NOT NULL,
            contrasena_hash TEXT NOT NULL,
            rol             TEXT NOT NULL DEFAULT 'Usuario',
            activo          INTEGER NOT NULL DEFAULT 1,
            fecha_creacion  TEXT NOT NULL,
            ultimo_acceso   TEXT
        );

        -- `datos` guarda en JSON todo lo que lleva la factura (cliente,
        -- personas, líneas...) tal como se emitió, y `pdf` el archivo: aunque
        -- después cambie la ficha del cliente, la factura se descarga igual.
        CREATE TABLE IF NOT EXISTS facturas (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            numero         TEXT NOT NULL UNIQUE,
            anio           INTEGER NOT NULL,
            secuencia      INTEGER NOT NULL,
            cliente_id     INTEGER REFERENCES clientes (id) ON DELETE SET NULL,
            cliente_nombre TEXT NOT NULL,
            fecha_emision  TEXT NOT NULL,
            total          REAL NOT NULL,
            datos          TEXT NOT NULL,
            pdf            BLOB NOT NULL,
            creado_por     TEXT,
            fecha_creacion TEXT NOT NULL,
            UNIQUE (anio, secuencia)
        );

        CREATE INDEX IF NOT EXISTS idx_facturas_cliente
            ON facturas (cliente_id, id DESC);

        -- Ajustes que cambia un administrador (p. ej. el próximo número de
        -- factura fijado a mano).
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );
        """
    )

    # Bases creadas antes de distinguir suplidores de clientes: los registros
    # existentes quedan como "Cliente".
    columnas = {r["name"] for r in conn.execute("PRAGMA table_info(clientes)")}
    if "tipo" not in columnas:
        conn.execute("ALTER TABLE clientes ADD COLUMN tipo TEXT NOT NULL DEFAULT 'Cliente'")
    # La cédula (o RNC) aparece en la factura.
    if "cedula" not in columnas:
        conn.execute("ALTER TABLE clientes ADD COLUMN cedula TEXT")

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
        INSERT INTO clientes (nombre, empresa, telefono, email, ubicacion, cedula,
                              productos_interes, estado, tipo, fecha_creacion)
        VALUES (:nombre, :empresa, :telefono, :email, :ubicacion, :cedula,
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
               email = :email, ubicacion = :ubicacion, cedula = :cedula,
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

    return {
        "total": total,
        "por_estado": por_estado,
        "activos": activos,
    }


# --------------------------------------------------------------------------
# Facturas
# --------------------------------------------------------------------------

PREFIJO_FACTURA = "RMG"

# Facturas hechas fuera del sistema antes de empezar a usarlo: la numeración de
# ese año sigue después de la última. RMG-2026-0001 se hizo y se envió a mano.
ULTIMA_FUERA_DEL_SISTEMA = {2026: 1}


def numero_factura(anio, secuencia):
    """(2026, 2) -> 'RMG-2026-0002'."""
    return f"{PREFIJO_FACTURA}-{anio}-{secuencia:04d}"


def _clave_numeracion(anio):
    return f"proxima_factura_{anio}"


def _secuencia_usada(conn, anio, secuencia):
    return conn.execute(
        "SELECT 1 FROM facturas WHERE anio = ? AND secuencia = ?", (anio, secuencia)
    ).fetchone() is not None


def secuencia_fijada(conn, anio):
    """Próximo número fijado a mano por un administrador, o None."""
    row = conn.execute(
        "SELECT valor FROM configuracion WHERE clave = ?", (_clave_numeracion(anio),)
    ).fetchone()
    return int(row["valor"]) if row else None


def ultima_secuencia(conn, anio):
    """Último número usado en el año, contando los emitidos fuera del sistema."""
    row = conn.execute("SELECT MAX(secuencia) FROM facturas WHERE anio = ?", (anio,)).fetchone()
    return max(row[0] or 0, ULTIMA_FUERA_DEL_SISTEMA.get(anio, 0))


def siguiente_secuencia(conn, anio):
    """El número fijado a mano si hay uno libre; si no, el siguiente al último.
    La numeración vuelve a 0001 cada año."""
    fijada = secuencia_fijada(conn, anio)
    if fijada is not None and not _secuencia_usada(conn, anio, fijada):
        return fijada
    return ultima_secuencia(conn, anio) + 1


def fijar_siguiente_secuencia(conn, anio, secuencia):
    """Fija el número de la próxima factura del año. Devuelve un mensaje de
    error, o None si quedó guardado."""
    if secuencia < 1:
        return "El número debe ser 1 o mayor."
    if _secuencia_usada(conn, anio, secuencia):
        return f"La factura {numero_factura(anio, secuencia)} ya existe."
    conn.execute(
        """
        INSERT INTO configuracion (clave, valor) VALUES (?, ?)
        ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor
        """,
        (_clave_numeracion(anio), str(secuencia)),
    )
    conn.commit()
    return None


def quitar_secuencia_fijada(conn, anio):
    """Vuelve a la numeración automática (el siguiente al último)."""
    conn.execute("DELETE FROM configuracion WHERE clave = ?", (_clave_numeracion(anio),))
    conn.commit()


def siguiente_numero(conn, anio):
    return numero_factura(anio, siguiente_secuencia(conn, anio))


def crear_factura(conn, datos, generar_pdf, usuario=None):
    """Asigna el número siguiente, genera el PDF con él y guarda la factura.

    `datos` es el diccionario de la factura sin número; `generar_pdf` recibe
    ese diccionario ya numerado y devuelve los bytes del PDF. Si dos personas
    generan a la vez y chocan en el número, se reintenta con el siguiente.
    Devuelve el id de la factura.
    """
    anio = date.fromisoformat(datos["fecha_emision"]).year
    for _ in range(5):
        secuencia = siguiente_secuencia(conn, anio)
        numerada = {**datos, "numero": numero_factura(anio, secuencia)}
        pdf = generar_pdf(numerada)
        try:
            cur = conn.execute(
                """
                INSERT INTO facturas (numero, anio, secuencia, cliente_id, cliente_nombre,
                                      fecha_emision, total, datos, pdf, creado_por,
                                      fecha_creacion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    numerada["numero"], anio, secuencia, numerada.get("cliente_id"),
                    numerada["cliente"]["nombre"], numerada["fecha_emision"],
                    numerada["total"], json.dumps(numerada, ensure_ascii=False), pdf,
                    usuario, datetime.now().strftime("%Y-%m-%d %H:%M"),
                ),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            continue
        # El número fijado a mano ya se usó: las siguientes vuelven a ser
        # automáticas.
        if secuencia_fijada(conn, anio) == secuencia:
            conn.execute("DELETE FROM configuracion WHERE clave = ?", (_clave_numeracion(anio),))
        conn.commit()
        return cur.lastrowid
    raise RuntimeError("No se pudo asignar un número de factura. Inténtalo de nuevo.")


def listar_facturas(conn, cliente_id=None):
    """Facturas sin el PDF, de la más reciente a la más antigua."""
    sql = """
        SELECT id, numero, anio, secuencia, cliente_id, cliente_nombre,
               fecha_emision, total, creado_por, fecha_creacion
          FROM facturas
    """
    params = ()
    if cliente_id is not None:
        sql += " WHERE cliente_id = ?"
        params = (cliente_id,)
    sql += " ORDER BY anio DESC, secuencia DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def obtener_factura(conn, factura_id):
    """La factura con su PDF y sus datos ya convertidos a diccionario."""
    row = conn.execute("SELECT * FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if not row:
        return None
    factura = dict(row)
    factura["datos"] = json.loads(factura["datos"])
    return factura


def ultima_factura_cliente(conn, cliente_id):
    """Datos de la factura más reciente del cliente (para prellenar la
    siguiente), o None si nunca se le ha facturado."""
    row = conn.execute(
        "SELECT datos FROM facturas WHERE cliente_id = ? ORDER BY id DESC LIMIT 1",
        (cliente_id,),
    ).fetchone()
    return json.loads(row["datos"]) if row else None


def es_ultima_del_anio(conn, factura_id):
    """Solo la última factura de su año se puede eliminar: así la numeración
    queda seguida y la siguiente reutiliza ese número."""
    row = conn.execute(
        """
        SELECT f.secuencia = (SELECT MAX(secuencia) FROM facturas WHERE anio = f.anio)
          FROM facturas f
         WHERE f.id = ?
        """,
        (factura_id,),
    ).fetchone()
    return bool(row and row[0])


def eliminar_factura(conn, factura_id):
    """Devuelve False (sin borrar nada) si no es la última de su año."""
    if not es_ultima_del_anio(conn, factura_id):
        return False
    conn.execute("DELETE FROM facturas WHERE id = ?", (factura_id,))
    conn.commit()
    return True


def guardar_cedula(conn, cliente_id, cedula):
    conn.execute("UPDATE clientes SET cedula = ? WHERE id = ?", (cedula, cliente_id))
    conn.commit()


# --------------------------------------------------------------------------
# Usuarios y acceso
# --------------------------------------------------------------------------

# Nunca se lee el hash fuera de este módulo.
COLUMNAS_USUARIO = "id, usuario, nombre, rol, activo, fecha_creacion, ultimo_acceso"


def hash_contrasena(contrasena, sal=None, iteraciones=ITERACIONES_HASH):
    """'pbkdf2_sha256$iteraciones$sal$hash' (sal aleatoria si no se da)."""
    sal = sal or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", contrasena.encode(), sal.encode(), iteraciones).hex()
    return f"pbkdf2_sha256${iteraciones}${sal}${h}"


def verificar_contrasena(contrasena, guardado):
    _, iteraciones, sal, _ = guardado.split("$")
    return hmac.compare_digest(hash_contrasena(contrasena, sal, int(iteraciones)), guardado)


def contar_usuarios(conn):
    return conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]


def crear_usuario(conn, usuario, nombre, contrasena, rol):
    """Devuelve el id nuevo, o None si ya existe ese nombre de usuario
    (sin distinguir mayúsculas)."""
    try:
        cur = conn.execute(
            """
            INSERT INTO usuarios (usuario, nombre, contrasena_hash, rol, fecha_creacion)
            VALUES (?, ?, ?, ?, ?)
            """,
            (usuario, nombre, hash_contrasena(contrasena), rol, date.today().isoformat()),
        )
    except sqlite3.IntegrityError:
        return None
    conn.commit()
    return cur.lastrowid


def autenticar(conn, usuario, contrasena):
    """Devuelve el usuario si las credenciales son válidas y la cuenta está
    activa; si no, None. Un acceso correcto queda registrado con fecha y hora."""
    row = conn.execute(
        "SELECT id, contrasena_hash, activo FROM usuarios WHERE usuario = ?", (usuario.strip(),)
    ).fetchone()
    if not row:
        # Mismo tiempo de respuesta que con un usuario real, para no delatar
        # qué nombres existen.
        hash_contrasena(contrasena)
        return None
    if not verificar_contrasena(contrasena, row["contrasena_hash"]) or not row["activo"]:
        return None
    conn.execute(
        "UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M"), row["id"]),
    )
    conn.commit()
    return obtener_usuario(conn, row["id"])


def obtener_usuario(conn, usuario_id):
    row = conn.execute(
        f"SELECT {COLUMNAS_USUARIO} FROM usuarios WHERE id = ?", (usuario_id,)
    ).fetchone()
    return dict(row) if row else None


def listar_usuarios(conn):
    return [
        dict(r)
        for r in conn.execute(
            f"SELECT {COLUMNAS_USUARIO} FROM usuarios ORDER BY nombre COLLATE NOCASE"
        ).fetchall()
    ]


def actualizar_usuario(conn, usuario_id, nombre, rol, activo):
    conn.execute(
        "UPDATE usuarios SET nombre = ?, rol = ?, activo = ? WHERE id = ?",
        (nombre, rol, int(activo), usuario_id),
    )
    conn.commit()


def cambiar_contrasena(conn, usuario_id, contrasena):
    conn.execute(
        "UPDATE usuarios SET contrasena_hash = ? WHERE id = ?",
        (hash_contrasena(contrasena), usuario_id),
    )
    conn.commit()


def eliminar_usuario(conn, usuario_id):
    conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
    conn.commit()
