"""CRM para intermediario de suplidores de productos agrícolas.

Ejecutar con:  streamlit run app.py
"""

import importlib
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import database as db

# Si faltan las librerías del PDF (no se corrió `pip install -r
# requirements.txt`), solo la sección de facturas deja de funcionar, no el CRM.
try:
    import factura
except ImportError as e:
    factura = None
    FALTA_LIBRERIA = (e.name or "reportlab").split(".")[0]

# Al actualizar el código, Streamlit vuelve a ejecutar app.py pero a veces sigue
# usando el database.py viejo que ya tenía en memoria (así falló el despliegue
# del seguimiento automático: "database has no attribute DIAS_SEGUIMIENTO").
# Si el archivo cambió desde que se cargó, se vuelve a cargar.
if getattr(db, "MTIME_CARGA", None) != Path(db.__file__).stat().st_mtime:
    db = importlib.reload(db)
if factura and getattr(factura, "MTIME_CARGA", None) != Path(factura.__file__).stat().st_mtime:
    factura = importlib.reload(factura)

# --------------------------------------------------------------------------
# Configuración general
# --------------------------------------------------------------------------

ASSETS = Path(__file__).parent / "assets"
LOGO = ASSETS / "logo.png"      # logo completo (RM Group) para la barra lateral
ICONO = ASSETS / "icono.png"    # monograma "RM" para la pestaña del navegador

st.set_page_config(
    page_title="CRM RM Group",
    page_icon=str(ICONO),
    layout="wide",
)

VERDE = "#2E7D32"   # hue única para los gráficos de cartera

# Sin colores fijos de texto ni de fondo: Streamlit sigue el modo claro/oscuro
# del navegador, y un color fijo (p. ej. títulos verde oscuro) desaparece en
# modo oscuro. Los fondos semitransparentes funcionan sobre ambos temas.
st.markdown(
    """
    <style>
      .stButton > button {
          width: 100%;
          padding: 0.6rem 1rem;
          font-size: 1rem;
          font-weight: 600;
          border-radius: 8px;
      }
      .stDownloadButton > button,
      .stFormSubmitButton > button {
          width: 100%;
          padding: 0.6rem 1rem;
          font-size: 1rem;
          font-weight: 600;
          border-radius: 8px;
      }
      div[data-testid="stMetric"] {
          background: rgba(46, 125, 50, 0.08);
          border: 1px solid rgba(128, 128, 128, 0.3);
          border-radius: 10px;
          padding: 14px 16px;
      }
      /* El logo lleva su fondo beige: bordes redondeados para que se vea
         como una tarjeta sobre la barra lateral clara u oscura. */
      section[data-testid="stSidebar"] [data-testid="stImage"] img {
          border-radius: 10px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def conexion():
    if "DATABASE_URL" not in st.secrets:
        st.error(
            "Falta `DATABASE_URL` en los Secrets de Streamlit "
            "(o en `.streamlit/secrets.toml` si la corres en tu computadora)."
        )
        st.stop()
    return db.get_conn(st.secrets["DATABASE_URL"])


@st.cache_resource
def preparar_esquema(_conn, version):
    """Crea o actualiza las tablas una vez por versión del esquema. La
    conexión cacheada sobrevive a las actualizaciones del código, así que
    atarlo a ella dejaría sin crear las tablas y columnas nuevas."""
    db.init_db(_conn)


conn = conexion()
# La conexión cacheada queda abierta entre visitas y Supabase corta las que
# pasan mucho tiempo inactivas: si ya no responde, se abre otra.
if not db.conexion_viva(conn):
    conexion.clear()
    conn = conexion()
preparar_esquema(conn, db.VERSION_ESQUEMA)

DASHBOARD = "📊 Dashboard"
FORMULARIO = "➕ Agregar / Editar Suplidor o Cliente"
LISTA_SUPLIDORES = "🏭 Lista de Suplidores"
LISTA_CLIENTES = "📋 Lista de Clientes"
CONTACTOS = "🗒️ Historial de Contactos"
SEGUIMIENTO = "🔔 Seguimiento"
FACTURAS = "🧾 Facturas"
USUARIOS = "👥 Usuarios"   # solo para administradores
ACTIVIDAD = "📜 Actividad"  # solo para administradores

PAGINAS = [DASHBOARD, FORMULARIO, LISTA_SUPLIDORES, LISTA_CLIENTES, CONTACTOS, SEGUIMIENTO, FACTURAS]


def ir_a(pagina, cliente_id=None):
    """Pide un cambio de sección (y opcionalmente fija el cliente en foco).

    No se puede escribir en st.session_state['nav'] aquí porque el radio del
    menú ya fue creado en esta pasada; se deja el destino apuntado y se aplica
    al principio de la siguiente.
    """
    st.session_state["_destino"] = pagina
    if cliente_id is not None:
        st.session_state["cliente_foco"] = cliente_id
    st.rerun()


def avisar(mensaje, tipo="success"):
    """Guarda un mensaje para mostrarlo después del st.rerun().

    Escribirlo directamente antes de recargar no sirve: la recarga descarta
    todo lo pintado en esta pasada.
    """
    st.session_state["_aviso"] = (tipo, mensaje)


def mostrar_aviso():
    if "_aviso" in st.session_state:
        tipo, mensaje = st.session_state.pop("_aviso")
        getattr(st, tipo)(mensaje)


def anotar(accion, detalle="", usuario=None):
    """Deja constancia en 📜 Actividad de lo que hizo el usuario con sesión."""
    db.registrar_actividad(conn, usuario or sesion, accion, detalle)


def es_admin():
    return sesion["rol"] == db.ADMIN


# --------------------------------------------------------------------------
# Utilidades de presentación
# --------------------------------------------------------------------------

COLUMNAS_TABLA = {
    "nombre": "Nombre",
    "tipo": "Tipo",
    "empresa": "Empresa",
    "cedula": "Cédula / RNC",
    "telefono": "Teléfono",
    "email": "Email",
    "ubicacion": "Ubicación",
    "productos_interes": "Productos de interés",
    "estado": "Estado",
    "suplidor_nombre": "Suplidor",
    "total_clientes": "Clientes",
    "asignado_nombre": "Asignado a",
    "ultimo_contacto": "Último contacto",
    "total_contactos": "Contactos",
    "proximo_seguimiento": "Próximo seguimiento",
    "fecha_creacion": "Alta",
}


def tabla_clientes(filas, columnas=None):
    """DataFrame con encabezados en español, listo para mostrar o exportar."""
    cols = columnas or COLUMNAS_TABLA
    if not filas:
        return pd.DataFrame(columns=list(cols.values()))
    df = pd.DataFrame(filas)
    df = df[[c for c in cols if c in df.columns]]
    return df.rename(columns=cols)


def a_csv(df):
    """utf-8-sig para que Excel en Windows muestre bien los acentos."""
    return df.to_csv(index=False).encode("utf-8-sig")


def etiqueta_cliente(c):
    """'Nombre — Empresa', con ⭐ si está asignado al usuario con sesión."""
    empresa = f" — {c['empresa']}" if c.get("empresa") else ""
    mio = "⭐ " if es_mio(c) else ""
    return f"{mio}{c['nombre']}{empresa}"


def es_mio(c):
    return sesion["id"] in (c.get("asignados") or [])


def nombre_asignado(c):
    """'⭐ Tú, Ana, Pedro', o 'Sin asignar'."""
    nombres = [
        "⭐ Tú" if uid == sesion["id"] else nombre
        for uid, nombre in zip(c.get("asignados") or [], c.get("asignados_nombres") or [])
    ]
    nombres.sort(key=lambda n: n != "⭐ Tú")
    return ", ".join(nombres) or "Sin asignar"


def usuarios_asignables(incluir_ids=()):
    """Usuarios activos (más `incluir_ids` aunque estén desactivados, para que
    el formulario muestre bien una asignación existente)."""
    return [u for u in db.listar_usuarios(conn) if u["activo"] or u["id"] in incluir_ids]


def selector_asignados(label, usuarios, actuales=(), key=None):
    """Multiselect de usuarios; devuelve la lista de ids (vacía = sin asignar)."""
    por_id = {u["id"]: u for u in usuarios}
    return st.multiselect(
        label,
        list(por_id),
        default=[i for i in actuales if i in por_id],
        format_func=lambda i: por_id[i]["nombre"],
        placeholder="Sin asignar",
        key=key,
    )


def selector_suplidor(label, suplidores, actual=None, key=None):
    """Selectbox 'Sin suplidor' + suplidores; devuelve el id o None."""
    por_id = {s["id"]: s for s in suplidores}
    opciones = [None] + list(por_id)
    return st.selectbox(
        label,
        opciones,
        index=opciones.index(actual) if actual in opciones else 0,
        format_func=lambda i: "Sin suplidor" if i is None else etiqueta_registro(por_id[i]),
        key=key,
    )


def etiqueta_registro(c):
    """'Nombre (Empresa)' para el registro de actividad, sin la ⭐."""
    return f"{c['nombre']} ({c['empresa']})" if c.get("empresa") else c["nombre"]


def recortar(texto, largo=40):
    texto = texto or "—"
    return texto if len(texto) <= largo else texto[: largo - 1] + "…"


def nombres_usuarios(ids, usuarios):
    """'Ana, Pedro' a partir de los ids, o 'Sin asignar'."""
    nombres = {u["id"]: u["nombre"] for u in usuarios}
    return ", ".join(sorted(nombres.get(i, "?") for i in ids)) or "Sin asignar"


def describir_cambios(antes, despues, usuarios, suplidores=()):
    """'Estado: Negociación → Cliente Activo; Teléfono: — → 809…', o '' si
    no cambió nada."""
    nombres_sup = {s["id"]: s["nombre"] for s in suplidores}
    cambios = []
    for campo, valor in despues.items():
        previo = antes.get(campo)
        if campo == "asignados":
            if sorted(previo or []) == sorted(valor):
                continue
            etiqueta = "Asignado a"
            previo, valor = nombres_usuarios(previo or [], usuarios), nombres_usuarios(valor, usuarios)
        elif (previo or None) == (valor or None):
            continue
        else:
            etiqueta = COLUMNAS_TABLA.get(campo, campo)
        if campo == "suplidor_id":
            etiqueta = "Suplidor"
            previo, valor = nombres_sup.get(previo, "Sin suplidor"), nombres_sup.get(valor, "Sin suplidor")
        cambios.append(f"{etiqueta}: {recortar(previo)} → {recortar(valor)}")
    return "; ".join(cambios)


def dias_desde(fecha_iso):
    """Días transcurridos desde la fecha (negativo si aún no llega)."""
    if not fecha_iso:
        return None
    return (date.today() - datetime.strptime(fecha_iso, "%Y-%m-%d").date()).days


def a_fecha(fecha_iso):
    return datetime.strptime(fecha_iso, "%Y-%m-%d").date() if fecha_iso else None


def fecha_dmy(fecha_iso):
    """'2026-09-30' -> '30/09/2026' (vacío si no hay fecha)."""
    return a_fecha(fecha_iso).strftime("%d/%m/%Y") if fecha_iso else ""


def selector_cliente(label, clientes):
    """Selectbox de clientes que devuelve el id.

    Sin `key`: así el índice calculado desde `cliente_foco` manda, y la
    navegación desde otra sección abre el cliente correcto.
    """
    ids = [c["id"] for c in clientes]
    por_id = {c["id"]: c for c in clientes}
    foco = st.session_state.get("cliente_foco")
    indice = ids.index(foco) if foco in ids else 0

    cid = st.selectbox(label, ids, index=indice, format_func=lambda i: etiqueta_cliente(por_id[i]))
    st.session_state["cliente_foco"] = cid
    return cid


# --------------------------------------------------------------------------
# Acceso con usuario y contraseña
# --------------------------------------------------------------------------

def usuario_actual():
    """Usuario con sesión iniciada, o None.

    Se vuelve a leer de la base en cada pasada: si un administrador desactiva o
    elimina la cuenta, la sesión abierta se cierra en el siguiente clic.
    """
    uid = st.session_state.get("usuario_id")
    if uid is None:
        return None
    usuario = db.obtener_usuario(conn, uid)
    if not usuario or not usuario["activo"]:
        st.session_state.clear()
        return None
    return usuario


def validar_usuario(usuario, nombre):
    """Mensaje de error, o None si los datos sirven."""
    if not nombre.strip():
        return "El nombre es obligatorio."
    if not usuario.strip():
        return "El usuario es obligatorio."
    if " " in usuario.strip():
        return "El usuario no puede llevar espacios."
    return None


def validar_contrasena(contrasena, confirmacion):
    """Mensaje de error, o None si la contraseña sirve."""
    if len(contrasena) < db.LARGO_MIN_CONTRASENA:
        return f"La contraseña debe tener al menos {db.LARGO_MIN_CONTRASENA} caracteres."
    if contrasena != confirmacion:
        return "Las contraseñas no coinciden."
    return None


def formulario_login():
    st.subheader("Iniciar sesión")
    with st.form("form_login"):
        usuario = st.text_input("Usuario")
        contrasena = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar", type="primary")

    if entrar:
        encontrado = db.autenticar(conn, usuario, contrasena)
        if encontrado:
            anotar("Inicio de sesión", usuario=encontrado)
            st.session_state["usuario_id"] = encontrado["id"]
            st.rerun()
        st.error("Usuario o contraseña incorrectos, o la cuenta está desactivada.")


def formulario_primer_admin():
    """Solo aparece mientras no exista ningún usuario."""
    st.subheader("Crear la cuenta de administrador")
    st.caption(
        "Todavía no hay usuarios. Esta primera cuenta será de administrador y "
        f"podrá dar acceso a los demás desde **{USUARIOS}**."
    )
    with st.form("form_primer_admin"):
        nombre = st.text_input("Nombre completo")
        usuario = st.text_input("Usuario", help="Con este nombre se inicia sesión. Sin espacios.")
        contrasena = st.text_input("Contraseña", type="password")
        confirmacion = st.text_input("Confirmar contraseña", type="password")
        crear = st.form_submit_button("Crear cuenta y entrar", type="primary")

    if crear:
        error = validar_usuario(usuario, nombre) or validar_contrasena(contrasena, confirmacion)
        if error:
            st.error(error)
            return
        uid = db.crear_usuario(conn, usuario.strip(), nombre.strip(), contrasena, db.ADMIN)
        anotar("Usuario creado", "Primera cuenta de administrador", usuario=db.obtener_usuario(conn, uid))
        st.session_state["usuario_id"] = uid
        st.rerun()


def pantalla_acceso():
    _, centro, _ = st.columns([1, 1.4, 1])
    with centro:
        st.image(str(LOGO), width="stretch")
        if db.contar_usuarios(conn) == 0:
            formulario_primer_admin()
        else:
            formulario_login()


def formulario_mi_contrasena(usuario):
    with st.form("form_mi_contrasena", clear_on_submit=True):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Nueva contraseña", type="password")
        confirmacion = st.text_input("Confirmar nueva", type="password")
        cambiar = st.form_submit_button("Cambiar")

    if cambiar:
        if not db.autenticar(conn, usuario["usuario"], actual):
            st.error("La contraseña actual no es correcta.")
        elif error := validar_contrasena(nueva, confirmacion):
            st.error(error)
        else:
            db.cambiar_contrasena(conn, usuario["id"], nueva)
            anotar("Contraseña cambiada", "Cambió su propia contraseña")
            st.success("Contraseña cambiada.")


# --------------------------------------------------------------------------
# 1. Dashboard
# --------------------------------------------------------------------------

def pagina_dashboard():
    st.title(DASHBOARD)
    st.caption("Resumen de la cartera de suplidores y clientes y de la actividad comercial.")

    m = db.metricas(conn)
    if m["total"] == 0:
        st.info(f"Todavía no hay suplidores ni clientes registrados. Empieza en **{FORMULARIO}**.")
        return

    sin_contactar = db.clientes_sin_contactar(conn)
    vencidos, para_hoy, _ = db.seguimientos(conn)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes activos", m["activos"])
    c2.metric(f"Sin contactar hace {db.DIAS_SIN_CONTACTO}+ días", len(sin_contactar))
    c3.metric("Seguimientos vencidos", len(vencidos))
    c4.metric("Seguimientos para hoy", len(para_hoy))

    st.divider()
    st.subheader("Registros por estado")
    df_estado = pd.DataFrame(
        {"Estado": list(m["por_estado"]), "Registros": list(m["por_estado"].values())}
    ).set_index("Estado")
    st.bar_chart(df_estado, color=VERDE, horizontal=True, height=260)
    with st.expander("Ver como tabla"):
        st.dataframe(df_estado, width="stretch")

    st.divider()
    st.subheader(f"⏰ Clientes sin contactar hace {db.DIAS_SIN_CONTACTO} días o más")

    if not sin_contactar:
        st.success("Toda la cartera ha sido contactada recientemente.")
        return

    filas = [
        {
            "Nombre": c["nombre"],
            "Tipo": c["tipo"],
            "Empresa": c["empresa"],
            "Teléfono": c["telefono"],
            "Estado": c["estado"],
            "Último contacto": c["ultimo_contacto"] or "Nunca contactado",
            "Días sin contacto": dias_desde(c["ultimo_contacto"] or c["fecha_creacion"]),
        }
        for c in sin_contactar
    ]
    st.dataframe(
        pd.DataFrame(filas).sort_values("Días sin contacto", ascending=False),
        width="stretch",
        hide_index=True,
    )


# --------------------------------------------------------------------------
# 2. Agregar / Editar suplidor o cliente
# --------------------------------------------------------------------------

def pagina_formulario():
    st.title(FORMULARIO)
    mostrar_aviso()

    clientes = db.listar_clientes(conn)
    opciones = [0] + [c["id"] for c in clientes]
    por_id = {c["id"]: c for c in clientes}

    foco = st.session_state.get("cliente_foco") or 0
    indice = opciones.index(foco) if foco in opciones else 0

    cid = st.selectbox(
        "¿Qué quieres hacer?",
        opciones,
        index=indice,
        format_func=lambda i: (
            "🆕 Registrar un suplidor o cliente nuevo"
            if i == 0
            else f"✏️ Editar: {etiqueta_cliente(por_id[i])}"
        ),
    )
    st.session_state["cliente_foco"] = cid or None

    editando = cid != 0
    actual = por_id.get(cid, {})
    usuarios = usuarios_asignables(actual.get("asignados") or [])
    suplidores = [c for c in clientes if c["tipo"] == "Suplidor" and c["id"] != cid]

    st.divider()

    # Las claves llevan el id del cliente para que el formulario se reinicie
    # al cambiar de cliente en vez de arrastrar los valores del anterior. El
    # formulario de alta lleva además un contador, que se incrementa tras cada
    # registro para devolverlo en blanco.
    k = f"_{cid}" if editando else f"_nuevo_{st.session_state.get('alta_gen', 0)}"

    with st.form("form_cliente"):
        col1, col2 = st.columns(2)
        with col1:
            nombre = st.text_input("Nombre de contacto *", value=actual.get("nombre", ""), key="nombre" + k)
            telefono = st.text_input("Teléfono", value=actual.get("telefono") or "", key="tel" + k)
            ubicacion = st.text_input(
                "Ubicación",
                value=actual.get("ubicacion") or "",
                placeholder="Provincia / municipio",
                key="ubi" + k,
            )
        with col2:
            empresa = st.text_input("Empresa", value=actual.get("empresa") or "", key="emp" + k)
            cedula = st.text_input(
                "Cédula / RNC",
                value=actual.get("cedula") or "",
                help="Aparece en las facturas.",
                key="ced" + k,
            )
            email = st.text_input("Email", value=actual.get("email") or "", key="mail" + k)
            tipo = st.selectbox(
                "Tipo *",
                db.TIPOS,
                index=db.TIPOS.index(actual.get("tipo") or "Cliente"),
                key="tipo" + k,
            )

        productos = st.text_area(
            "Productos de interés",
            value=actual.get("productos_interes") or "",
            placeholder="Ej.: sacos de arroz de 100 lb, maíz amarillo, abono 15-15-15…",
            key="prod" + k,
        )

        # Dentro del formulario el campo no puede aparecer y desaparecer según
        # el tipo elegido; si el registro es un suplidor, se ignora al guardar.
        suplidor_id = selector_suplidor(
            "Suplidor (opcional, solo para clientes)",
            suplidores,
            actual.get("suplidor_id"),
            key="sup" + k,
        )

        col3, col4 = st.columns(2)
        # Registros con un estado que ya no existe (p. ej. el antiguo
        # "Prospecto") abren con el primero de la lista.
        estado_actual = actual.get("estado")
        estado = col3.selectbox(
            "Estado",
            db.ESTADOS,
            index=db.ESTADOS.index(estado_actual) if estado_actual in db.ESTADOS else 0,
            key="estado" + k,
        )
        # Solo el administrador asigna (uno o varios usuarios). Lo que registra
        # un usuario queda a su nombre; al editar, la asignación no cambia.
        if es_admin():
            with col3:
                asignados = selector_asignados(
                    "Asignado a", usuarios, actual.get("asignados") or [], key="asig" + k
                )
        else:
            asignados = list(actual.get("asignados") or []) if editando else [sesion["id"]]
            col3.markdown(
                f"**Asignado a:** {nombre_asignado(actual) if editando else '⭐ Tú'}"
            )
        with col4:
            st.markdown("**Próximo seguimiento**")
            if editando and actual.get("proximo_seguimiento"):
                st.markdown(f"🗓️ {fecha_dmy(actual['proximo_seguimiento'])}")
            st.caption(
                "Se calcula solo según el tipo, el estado y el último contacto. "
                "Para moverlo a mano, usa *Posponer* en 🔔 Seguimiento."
            )

        guardar = st.form_submit_button(
            "💾 Guardar cambios" if editando else "💾 Guardar", type="primary"
        )

    if guardar:
        if not nombre.strip():
            st.error("El nombre de contacto es obligatorio.")
        else:
            datos = {
                "nombre": nombre.strip(),
                "empresa": empresa.strip(),
                "cedula": cedula.strip(),
                "telefono": telefono.strip(),
                "email": email.strip(),
                "ubicacion": ubicacion.strip(),
                "productos_interes": productos.strip(),
                "estado": estado,
                "tipo": tipo,
                "suplidor_id": suplidor_id if tipo == "Cliente" else None,
                "asignados": asignados,
            }

            if editando:
                db.actualizar_cliente(conn, cid, datos)
                cambios = describir_cambios(actual, datos, usuarios, suplidores)
                if cambios:
                    anotar("Edición", f"{tipo} {etiqueta_registro(datos)}: {cambios}")
                avisar(f"{tipo} **{datos['nombre']}** actualizado.")
            else:
                nuevo_id = db.crear_cliente(conn, datos)
                detalle = f"{tipo} {etiqueta_registro(datos)} · asignado a {nombres_usuarios(asignados, usuarios)}"
                if datos["suplidor_id"]:
                    suplidor = next(s for s in suplidores if s["id"] == datos["suplidor_id"])
                    detalle += f" · suplidor {etiqueta_registro(suplidor)}"
                anotar("Registro", detalle)
                # Vaciar el formulario de alta para que no reaparezca relleno.
                st.session_state["alta_gen"] = st.session_state.get("alta_gen", 0) + 1
                st.session_state["cliente_foco"] = nuevo_id
                avisar(f"{tipo} **{datos['nombre']}** registrado.")
            st.rerun()

    if not editando:
        return

    st.divider()
    st.subheader(f"Eliminar {actual['tipo'].lower()}")
    st.caption(
        "Eliminar un registro borra también todo su historial de contactos."
        + (" Sus clientes quedan sin suplidor." if actual["tipo"] == "Suplidor" else "")
    )
    col5, col6 = st.columns([1, 2])
    confirmar = col6.checkbox("Confirmo que quiero eliminar este registro", key="conf_del" + k)
    if col5.button("🗑️ Eliminar", disabled=not confirmar):
        db.eliminar_cliente(conn, cid)
        anotar("Eliminación", f"{actual['tipo']} {etiqueta_registro(actual)}")
        st.session_state["cliente_foco"] = None
        avisar(f"{actual['tipo']} **{actual['nombre']}** eliminado.", "warning")
        st.rerun()


# --------------------------------------------------------------------------
# 3. Listas de suplidores y de clientes
# --------------------------------------------------------------------------

# El tipo ya lo dice la sección; cada lista lleva solo su columna de relación.
COLUMNAS_CLIENTES = {c: t for c, t in COLUMNAS_TABLA.items() if c not in ("tipo", "total_clientes")}
COLUMNAS_SUPLIDORES = {c: t for c, t in COLUMNAS_TABLA.items() if c not in ("tipo", "suplidor_nombre")}


def pagina_lista(titulo, tipo, columnas, archivo, extra=None):
    """Lista de clientes o de suplidores (según `tipo`) con filtros,
    exportación y acciones rápidas. `extra(id, registro)` agrega acciones
    propias de la sección sobre el registro elegido."""
    st.title(titulo)
    mostrar_aviso()
    plural = "clientes" if tipo == "Cliente" else "suplidores"

    col1, col3, col8 = st.columns([3, 2, 2])
    busqueda = col1.text_input("🔍 Buscar", placeholder="Nombre, empresa, ubicación o productos…")
    estado = col3.selectbox("Filtrar por estado", ["Todos"] + db.ESTADOS)
    usuarios = usuarios_asignables()
    nombres = {u["id"]: u["nombre"] for u in usuarios}
    asignado = col8.selectbox(
        "Asignado a",
        [None, sesion["id"], db.SIN_ASIGNAR] + [i for i in nombres if i != sesion["id"]],
        format_func=lambda i: {None: "Todos", sesion["id"]: "⭐ Mis asignados",
                               db.SIN_ASIGNAR: "Sin asignar"}.get(i) or nombres[i],
    )

    total = db.contar_clientes(conn, tipo)
    if total == 0:
        st.info(f"Todavía no hay {plural} registrados. Empieza en **{FORMULARIO}**.")
        return

    registros = db.listar_clientes(conn, busqueda, estado, tipo, asignado)
    for c in registros:
        c["asignado_nombre"] = nombre_asignado(c)
    st.caption(f"Mostrando **{len(registros)}** de **{total}** {plural}. ⭐ = asignado a ti.")

    df = tabla_clientes(registros, columnas)
    if df.empty:
        st.warning("Ningún registro coincide con la búsqueda.")
    else:
        st.dataframe(df, width="stretch", hide_index=True)

    # En el archivo completo van los nombres tal cual, sin la ⭐ de quien exporta.
    todos = db.listar_clientes(conn, tipo=tipo)
    for c in todos:
        c["asignado_nombre"] = ", ".join(c["asignados_nombres"]) or "Sin asignar"

    col4, col5 = st.columns(2)
    col4.download_button(
        "⬇️ Exportar resultados a CSV",
        data=a_csv(df),
        file_name=f"{archivo}_{date.today().isoformat()}.csv",
        mime="text/csv",
        disabled=df.empty,
    )
    col5.download_button(
        "⬇️ Exportar TODOS a CSV",
        data=a_csv(tabla_clientes(todos, columnas)),
        file_name=f"{archivo}_completo_{date.today().isoformat()}.csv",
        mime="text/csv",
    )

    if not registros:
        return

    st.divider()
    st.subheader("Acciones rápidas")
    cid = selector_cliente(tipo, registros)
    col6, col7, col9 = st.columns(3)
    if col6.button("✏️ Editar este registro"):
        ir_a(FORMULARIO, cid)
    if col7.button("🗒️ Registrar un contacto"):
        ir_a(CONTACTOS, cid)
    if col9.button("🧾 Generar factura"):
        ir_a(FACTURAS, cid)

    if extra:
        extra(cid, next(c for c in registros if c["id"] == cid))

    if es_admin():
        seccion_asignar(registros, usuarios)


def pagina_lista_clientes():
    pagina_lista(LISTA_CLIENTES, "Cliente", COLUMNAS_CLIENTES, "clientes")


def pagina_lista_suplidores():
    pagina_lista(
        LISTA_SUPLIDORES, "Suplidor", COLUMNAS_SUPLIDORES, "suplidores",
        extra=seccion_clientes_del_suplidor,
    )


def seccion_clientes_del_suplidor(sid, suplidor):
    """Elegir qué clientes atiende el suplidor. Un cliente tiene un solo
    suplidor: si se elige uno que ya tenía otro, pasa a este."""
    st.divider()
    st.subheader(f"🔗 Clientes de {suplidor['nombre']}")

    clientes = db.listar_clientes(conn, tipo="Cliente")
    if not clientes:
        st.info(f"Todavía no hay clientes registrados. Empieza en **{FORMULARIO}**.")
        return

    por_id = {c["id"]: c for c in clientes}
    actuales = [c["id"] for c in clientes if c["suplidor_id"] == sid]

    def etiqueta(i):
        c = por_id[i]
        otro = c["suplidor_id"] not in (None, sid)
        return etiqueta_cliente(c) + (f"  (ahora con {c['suplidor_nombre']})" if otro else "")

    with st.form(f"form_clientes_suplidor_{sid}"):
        elegidos = st.multiselect(
            "Clientes asignados a este suplidor",
            list(por_id),
            default=actuales,
            format_func=etiqueta,
            placeholder="Ningún cliente",
        )
        st.caption("Si eliges un cliente que ya tiene otro suplidor, pasa a este.")
        guardar = st.form_submit_button("💾 Guardar clientes", type="primary")

    if not guardar:
        return
    agregados = [i for i in elegidos if i not in actuales]
    quitados = [i for i in actuales if i not in elegidos]
    if not agregados and not quitados:
        st.info("No hubo cambios.")
        return

    db.vincular_clientes(conn, sid, elegidos)
    partes = []
    if agregados:
        partes.append("agregados: " + ", ".join(etiqueta_registro(por_id[i]) for i in agregados))
    if quitados:
        partes.append("quitados: " + ", ".join(etiqueta_registro(por_id[i]) for i in quitados))
    anotar("Clientes de suplidor", f"Suplidor {etiqueta_registro(suplidor)} · " + "; ".join(partes))
    avisar(f"Clientes de **{suplidor['nombre']}** actualizados ({len(elegidos)} en total).")
    st.rerun()


MODOS_ASIGNACION = {
    db.AGREGAR: "Agregar a los que ya tiene",
    db.QUITAR: "Quitar de los que tiene",
    db.REEMPLAZAR: "Reemplazar (dejar solo estos)",
}


def seccion_asignar(registros, usuarios):
    """Asignación en bloque (solo administradores) sobre la lista filtrada."""
    st.divider()
    st.subheader("👤 Asignar usuarios")
    st.caption(
        "Usa los filtros de arriba para acotar la lista y cambia la asignación de varios "
        "registros a la vez. Cada registro puede tener varios usuarios."
    )

    por_id = {c["id"]: c for c in registros}
    todos = st.checkbox(f"Todos los que se muestran arriba ({len(registros)})")
    elegidos = list(por_id) if todos else st.multiselect(
        "Registros",
        list(por_id),
        format_func=lambda i: etiqueta_cliente(por_id[i]),
        placeholder="Elige uno o varios",
    )
    destino = selector_asignados("Usuarios", usuarios)
    col1, col2 = st.columns([2, 1], vertical_alignment="bottom")
    modo = col1.radio(
        "Cómo", list(MODOS_ASIGNACION), format_func=MODOS_ASIGNACION.get, horizontal=True
    )
    # Reemplazar sin usuarios deja los registros sin asignar; agregar o quitar
    # sin usuarios no haría nada.
    if col2.button("✅ Aplicar", disabled=not elegidos or (not destino and modo != db.REEMPLAZAR)):
        db.asignar_clientes(conn, elegidos, destino, modo)
        a_quien = nombres_usuarios(destino, usuarios)
        nombres = ", ".join(etiqueta_registro(por_id[i]) for i in elegidos)
        anotar("Asignación", f"{len(elegidos)} registro(s) · {modo}: {a_quien} · {nombres}")
        avisar(f"Asignación de **{len(elegidos)}** registro(s) actualizada ({modo.lower()}: **{a_quien}**).")
        st.rerun()


# --------------------------------------------------------------------------
# 4. Historial de contactos
# --------------------------------------------------------------------------

def pagina_contactos():
    st.title(CONTACTOS)
    mostrar_aviso()

    clientes = db.listar_clientes(conn)
    if not clientes:
        st.info("Registra primero un cliente para poder anotar contactos.")
        return

    cid = selector_cliente("Cliente", clientes)
    cliente = next(c for c in clientes if c["id"] == cid)

    col1, col2, col3, col0 = st.columns(4)
    col1.metric("Estado", cliente["estado"])
    col2.metric("Teléfono", cliente["telefono"] or "—")
    col3.metric("Próximo seguimiento", fecha_dmy(cliente["proximo_seguimiento"]) or "Sin programar")
    col0.metric("Asignado a", nombre_asignado(cliente))

    st.divider()
    st.subheader("Registrar nuevo contacto")

    with st.form("form_contacto", clear_on_submit=True):
        col4, col5, col6 = st.columns(3)
        # La fecha se registra automáticamente con el día de hoy; se puede ajustar.
        fecha = col4.date_input("Fecha del contacto", value=date.today(), format="DD/MM/YYYY")
        tipo = col5.selectbox("Tipo de contacto", db.TIPOS_CONTACTO)
        resultado = col6.selectbox("Resultado", db.RESULTADOS)

        notas = st.text_area("Notas", placeholder="Qué se habló, cantidades, precios, compromisos…")
        st.caption("El próximo seguimiento se calcula solo a partir de la fecha y el resultado.")

        guardar = st.form_submit_button("💾 Guardar contacto", type="primary")

    if guardar:
        proximo = db.agregar_contacto(conn, cid, fecha, tipo, notas.strip(), resultado)
        anotar(
            "Contacto registrado",
            f"{cliente['tipo']} {etiqueta_registro(cliente)}: {tipo} del "
            f"{fecha.strftime('%d/%m/%Y')} · {resultado}",
        )
        avisar(f"Contacto registrado. Próximo seguimiento: {proximo.strftime('%d/%m/%Y')}.")
        st.rerun()

    st.divider()
    st.subheader("Historial")

    contactos = db.listar_contactos(conn, cid)
    if not contactos:
        st.info("Este cliente aún no tiene contactos registrados.")
        return

    for c in contactos:
        dias = dias_desde(c["fecha"])
        antiguedad = "hoy" if dias == 0 else f"hace {dias} día{'s' if dias != 1 else ''}"
        with st.expander(f"**{c['fecha']}** · {c['tipo_contacto']} · {c['resultado']}  —  {antiguedad}"):
            st.write(c["notas"] or "_Sin notas._")
            if st.button("🗑️ Eliminar este contacto", key=f"del_contacto_{c['id']}"):
                db.eliminar_contacto(conn, c["id"])
                anotar(
                    "Contacto eliminado",
                    f"{cliente['tipo']} {etiqueta_registro(cliente)}: {c['tipo_contacto']} "
                    f"del {fecha_dmy(c['fecha'])} · {c['resultado']}",
                )
                st.rerun()

    df_contactos = pd.DataFrame(contactos)[["fecha", "tipo_contacto", "resultado", "notas"]].rename(
        columns={
            "fecha": "Fecha",
            "tipo_contacto": "Tipo de contacto",
            "resultado": "Resultado",
            "notas": "Notas",
        }
    )
    st.download_button(
        "⬇️ Exportar historial a CSV",
        data=a_csv(df_contactos),
        file_name=f"contactos_{cliente['nombre'].replace(' ', '_')}.csv",
        mime="text/csv",
    )


# --------------------------------------------------------------------------
# 5. Seguimiento
# --------------------------------------------------------------------------

def bloque_seguimiento(titulo, filas, mensaje_vacio):
    st.subheader(titulo)
    if not filas:
        st.caption(mensaje_vacio)
        return

    for c in filas:
        dias = dias_desde(c["proximo_seguimiento"])
        if dias > 0:
            aviso = f"⚠️ Vencido hace {dias} día{'s' if dias != 1 else ''}"
        elif dias == 0:
            aviso = "📌 Es para hoy"
        else:
            aviso = f"🗓️ En {abs(dias)} día{'s' if dias != -1 else ''}"

        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 2])
            col1.markdown(
                f"**{etiqueta_cliente(c)}**  \n{c['estado']} · {c['ubicacion'] or 'Sin ubicación'}"
                f"  \n👤 {nombre_asignado(c)}"
            )
            col2.markdown(
                f"📞 {c['telefono'] or '—'}  \nÚltimo contacto: {c['ultimo_contacto'] or 'Nunca'}"
            )
            col3.markdown(f"{aviso}  \nProgramado: {fecha_dmy(c['proximo_seguimiento'])}")

            col4, col5, col6 = st.columns([2, 1, 1], vertical_alignment="bottom")
            if col4.button("🗒️ Registrar contacto", key=f"seg_contacto_{c['id']}"):
                ir_a(CONTACTOS, c["id"])
            dias_posponer = col5.number_input(
                "Posponer (días)", min_value=1, max_value=365, value=7, step=1,
                key=f"seg_dias_{c['id']}",
            )
            if col6.button("⏭️ Posponer", key=f"seg_posponer_{c['id']}"):
                # Un seguimiento vencido se pospone desde hoy; uno futuro, desde
                # su fecha programada.
                desde = max(date.today(), a_fecha(c["proximo_seguimiento"]))
                nueva = desde + timedelta(days=int(dias_posponer))
                db.fijar_proximo_seguimiento(conn, c["id"], nueva)
                anotar(
                    "Seguimiento pospuesto",
                    f"{c['tipo']} {etiqueta_registro(c)}: "
                    f"{fecha_dmy(c['proximo_seguimiento'])} → {nueva.strftime('%d/%m/%Y')}",
                )
                avisar(f"{c['nombre']}: seguimiento movido al {nueva.strftime('%d/%m/%Y')}.", "info")
                st.rerun()


def pagina_seguimiento():
    st.title("🔔 Sistema de Seguimiento")
    st.caption("Clientes con seguimiento vencido, programado para hoy o próximo a vencer.")
    mostrar_aviso()

    col_a, col_b = st.columns([3, 1], vertical_alignment="bottom")
    dias = col_a.slider("Mirar hacia adelante (días)", 1, 30, 7)
    # Los usuarios ven primero lo suyo; el administrador, todo.
    solo_mios = col_b.toggle("⭐ Solo mis asignados", value=not es_admin())
    vencidos, para_hoy, proximos = db.seguimientos(conn, dias)
    if solo_mios:
        vencidos, para_hoy, proximos = (
            [c for c in grupo if es_mio(c)] for grupo in (vencidos, para_hoy, proximos)
        )

    col1, col2, col3 = st.columns(3)
    col1.metric("Vencidos", len(vencidos))
    col2.metric("Para hoy", len(para_hoy))
    col3.metric(f"Próximos {dias} días", len(proximos))

    st.divider()
    bloque_seguimiento("🔴 Seguimientos vencidos", vencidos, "Sin seguimientos vencidos. 👍")
    st.divider()
    bloque_seguimiento("🟡 Para hoy", para_hoy, "Nada programado para hoy.")
    st.divider()
    bloque_seguimiento(f"🟢 Próximos {dias} días", proximos, "Nada programado en ese rango.")

    st.divider()
    with st.expander("¿Cómo se calcula el próximo seguimiento?"):
        st.markdown(
            "Se cuenta desde el **último contacto** (o desde el alta, si nunca se ha "
            "contactado). Se recalcula al registrar o borrar un contacto y al cambiar "
            "el tipo o el estado. *Posponer* lo mueve a mano hasta el próximo recálculo."
        )
        st.markdown("**Según tipo y estado (días)**")
        st.dataframe(
            pd.DataFrame(db.DIAS_SEGUIMIENTO).rename_axis("Estado"),
            width="content",
        )
        st.markdown("**Según el resultado del último contacto (manda sobre la tabla anterior)**")
        st.dataframe(
            pd.DataFrame(
                {"Resultado": list(db.DIAS_POR_RESULTADO), "Días": list(db.DIAS_POR_RESULTADO.values())}
            ),
            width="content",
            hide_index=True,
        )
        st.caption("*Venta cerrada* usa los días de la tabla por tipo y estado.")


# --------------------------------------------------------------------------
# 6. Facturas
# --------------------------------------------------------------------------

COLUMNAS_LINEAS = ["cantidad", "descripcion", "detalle", "precio"]


@st.cache_data(max_entries=20, show_spinner=False)
def vista_previa(pdf):
    return factura.paginas_png(pdf)


def mostrar_factura(f, clave, abierta):
    """Botón de descarga y vista previa de una factura guardada."""
    st.download_button(
        "⬇️ Descargar PDF",
        data=f["pdf"],
        file_name=f"Factura {f['numero']} - {f['cliente_nombre']}.pdf",
        mime="application/pdf",
        type="primary",
        key=f"descargar_{clave}",
    )
    with st.expander("👁️ Vista previa", expanded=abierta):
        for png in vista_previa(f["pdf"]):
            st.image(png, width="stretch")


def _texto_celda(v):
    """Celda de texto del editor ('' si está vacía)."""
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _numero_celda(v):
    """Celda numérica del editor (None si está vacía)."""
    return None if v is None or pd.isna(v) else float(v)


def lineas_editadas(df):
    """Filas del editor -> líneas de factura; descarta las filas vacías."""
    lineas = []
    for fila in df.to_dict("records"):
        linea = {
            "cantidad": _numero_celda(fila.get("cantidad")),
            "descripcion": _texto_celda(fila.get("descripcion")),
            "detalle": _texto_celda(fila.get("detalle")),
            "precio": _numero_celda(fila.get("precio")),
        }
        if linea["descripcion"] or linea["cantidad"] is not None or linea["precio"] is not None:
            lineas.append(linea)
    return lineas


def formulario_factura():
    clientes = db.listar_clientes(conn)
    if not clientes:
        st.info(f"Registra primero un suplidor o cliente en **{FORMULARIO}**.")
        return

    cid = selector_cliente("Suplidor o cliente", clientes)
    cliente = db.obtener_cliente(conn, cid)
    # La última factura de este cliente prellena la nueva: en un pedido que se
    # repite solo hay que tocar lo que cambió.
    previa = db.ultima_factura_cliente(conn, cid) or {}

    # Claves con el cliente y un contador: cambiar de cliente o terminar una
    # factura devuelve el formulario a sus valores iniciales.
    k = f"_{cid}_{st.session_state.get('factura_gen', 0)}"

    col1, col2, col3 = st.columns(3)
    emision = col1.date_input("Fecha de emisión", value=date.today(), format="DD/MM/YYYY", key="f_emi" + k)
    entrega = col2.date_input(
        "Fecha de entrega", value=date.today() + timedelta(days=1), format="DD/MM/YYYY", key="f_ent" + k
    )
    condiciones = list(factura.CONDICIONES_PAGO)
    anterior = previa.get("condicion_pago")
    if anterior and anterior not in condiciones:
        condiciones.append(anterior)
    condicion = col3.selectbox(
        "Condición de pago",
        condiciones,
        index=condiciones.index(anterior) if anterior else 0,
        accept_new_options=True,
        help="Elige una o escribe otra.",
        key="f_cond" + k,
    )

    st.markdown("**Productos**")
    if previa.get("lineas"):
        st.caption("Vienen de la última factura de este cliente: cambia solo lo necesario.")
    lineas_iniciales = previa.get("lineas") or [{"cantidad": None, "descripcion": "", "detalle": "", "precio": None}]
    df_lineas = pd.DataFrame(lineas_iniciales, columns=COLUMNAS_LINEAS)
    df_lineas[["cantidad", "precio"]] = df_lineas[["cantidad", "precio"]].astype(float)
    editor = st.data_editor(
        df_lineas,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key="f_lineas" + k,
        column_config={
            "cantidad": st.column_config.NumberColumn("Cantidad", min_value=0, format="localized", required=True),
            "descripcion": st.column_config.TextColumn("Producto", required=True, width="medium"),
            "detalle": st.column_config.TextColumn("Descripción (opcional)", width="large"),
            "precio": st.column_config.NumberColumn(
                "Precio unitario (RD$)", min_value=0, format="%.2f", required=True
            ),
        },
    )
    lineas = lineas_editadas(editor)

    transporte = st.number_input(
        "Transporte / flete (RD$)",
        min_value=0.0,
        step=100.0,
        value=float(previa.get("transporte") or 0),
        format="%.2f",
        help="Si es mayor que 0, se agrega la línea «Servicio de transporte / flete» y aparece en los "
             "totales. Déjalo en 0 si no aplica.",
        key="f_transp" + k,
    )

    # Datos del cliente: salen de su ficha; el segundo contacto, de su última
    # factura. Rara vez hay que tocarlos, por eso van plegados.
    personas_previas = (previa.get("cliente") or {}).get("personas") or []
    cedula = cliente.get("cedula") or ""
    if not cedula and personas_previas and personas_previas[0].get("nombre") == cliente["nombre"]:
        cedula = personas_previas[0].get("cedula") or ""
    segunda = personas_previas[1] if len(personas_previas) > 1 else {}

    with st.expander("👤 Datos del cliente en la factura", expanded=not cedula):
        st.caption(
            f"Salen de la ficha en **{FORMULARIO}**. Si agregas aquí la cédula del contacto "
            "principal, queda guardada en su ficha para las próximas facturas."
        )
        nombre_factura = st.text_input(
            "Nombre en la factura", value=cliente["empresa"] or cliente["nombre"], key="f_nom" + k
        )
        c1, c2, c3 = st.columns(3)
        p1_nombre = c1.text_input("Contacto", value=cliente["nombre"], key="f_p1n" + k)
        p1_cedula = c2.text_input("Cédula / RNC", value=cedula, key="f_p1c" + k)
        p1_tel = c3.text_input("Teléfono", value=cliente["telefono"] or "", key="f_p1t" + k)
        c4, c5, c6 = st.columns(3)
        p2_nombre = c4.text_input("Segundo contacto (opcional)", value=segunda.get("nombre", ""), key="f_p2n" + k)
        p2_cedula = c5.text_input("Cédula / RNC", value=segunda.get("cedula", ""), key="f_p2c" + k)
        p2_tel = c6.text_input("Teléfono", value=segunda.get("telefono", ""), key="f_p2t" + k)
        ubicacion = st.text_input("Ubicación", value=cliente["ubicacion"] or "", key="f_ubi" + k)

    completas = [l for l in lineas if l["descripcion"] and l["cantidad"] and l["precio"] is not None]
    subtotal, total = factura.totales(completas, transporte)

    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Subtotal", f"RD$ {factura.monto(subtotal)}")
    m2.metric("Transporte / flete", f"RD$ {factura.monto(transporte)}")
    m3.metric("Total", f"RD$ {factura.monto(total)}")

    numero = db.siguiente_numero(conn, emision.year)
    if not st.button(f"🧾 Generar factura {numero}", type="primary", key="f_generar" + k):
        return

    if not lineas:
        st.error("Agrega al menos un producto.")
        return
    if len(completas) < len(lineas):
        st.error("Cada producto necesita nombre, cantidad mayor que 0 y precio.")
        return
    if entrega < emision:
        st.error("La fecha de entrega no puede ser anterior a la de emisión.")
        return
    if not nombre_factura.strip():
        st.error("El nombre en la factura es obligatorio.")
        return

    personas = [
        {"nombre": n.strip(), "cedula": c.strip(), "telefono": t.strip()}
        for n, c, t in ((p1_nombre, p1_cedula, p1_tel), (p2_nombre, p2_cedula, p2_tel))
        if n.strip() or c.strip() or t.strip()
    ]
    datos = {
        "cliente_id": cid,
        "fecha_emision": emision.isoformat(),
        "fecha_entrega": entrega.isoformat(),
        "condicion_pago": (condicion or factura.CONDICIONES_PAGO[0]).strip(),
        "cliente": {"nombre": nombre_factura.strip(), "personas": personas, "ubicacion": ubicacion.strip()},
        "lineas": completas,
        "transporte": round(transporte, 2),
        "subtotal": subtotal,
        "total": total,
    }
    fid = db.crear_factura(conn, datos, factura.generar_pdf, sesion["usuario"])
    anotar(
        "Factura generada",
        f"{db.obtener_factura(conn, fid)['numero']} · {cliente['tipo']} "
        f"{etiqueta_registro(cliente)} · RD$ {factura.monto(total)}",
    )

    if p1_cedula.strip() and not cliente.get("cedula") and p1_nombre.strip() == cliente["nombre"]:
        db.guardar_cedula(conn, cid, p1_cedula.strip())

    st.session_state["factura_generada"] = fid
    st.session_state["factura_gen"] = st.session_state.get("factura_gen", 0) + 1
    st.rerun()


def facturas_emitidas():
    facturas = db.listar_facturas(conn)
    if not facturas:
        st.info("Todavía no se ha emitido ninguna factura.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Número": f["numero"],
                    "Emisión": fecha_dmy(f["fecha_emision"]),
                    "Cliente": f["cliente_nombre"],
                    "Total (RD$)": f["total"],
                    "Generada por": f["creado_por"] or "",
                }
                for f in facturas
            ]
        ),
        column_config={"Total (RD$)": st.column_config.NumberColumn(format="%.2f")},
        width="stretch",
        hide_index=True,
    )

    por_id = {f["id"]: f for f in facturas}
    fid = st.selectbox(
        "Factura",
        list(por_id),
        format_func=lambda i: f"{por_id[i]['numero']} — {por_id[i]['cliente_nombre']}",
        key="f_emitida",
    )
    f = db.obtener_factura(conn, fid)
    mostrar_factura(f, f"emitida_{fid}", abierta=False)

    # Solo la última de su año: borrar una intermedia dejaría un hueco en la
    # numeración.
    if not es_admin() or not db.es_ultima_del_anio(conn, fid):
        return
    st.caption(
        f"Es la última factura de {f['anio']}. Si se generó por error, al eliminarla el "
        f"número **{f['numero']}** queda libre para la próxima."
    )
    col1, col2 = st.columns([1, 2])
    confirmar = col2.checkbox("Confirmo que quiero eliminar esta factura", key=f"f_del_{fid}")
    if col1.button("🗑️ Eliminar factura", disabled=not confirmar, key=f"f_borrar_{fid}"):
        db.eliminar_factura(conn, fid)
        anotar(
            "Factura eliminada",
            f"{f['numero']} · {f['cliente_nombre']} · RD$ {factura.monto(f['total'])}",
        )
        if st.session_state.get("factura_generada") == fid:
            st.session_state.pop("factura_generada")
        avisar(f"Factura **{f['numero']}** eliminada.", "warning")
        st.rerun()


def numeracion_facturas():
    """Solo administradores: fijar a mano el número de la próxima factura."""
    st.caption(
        "Normalmente no hace falta: cada factura toma el número siguiente al último. "
        "Úsalo si una factura se hizo fuera del sistema o si hay que saltar o repetir un número."
    )
    anio = st.number_input("Año", min_value=2000, max_value=2100, value=date.today().year, step=1)
    anio = int(anio)
    fijada = db.secuencia_fijada(conn, anio)
    siguiente = db.siguiente_secuencia(conn, anio)

    st.markdown(f"Próxima factura de {anio}: **{db.numero_factura(anio, siguiente)}**")
    ultima = db.ultima_secuencia(conn, anio)
    st.caption(
        f"Última usada: {db.numero_factura(anio, ultima) if ultima else 'ninguna'}"
        + (" · Número fijado a mano." if fijada == siguiente else "")
    )

    with st.form("form_numeracion"):
        nuevo = st.number_input(
            "Número de la próxima factura", min_value=1, max_value=9999, value=siguiente, step=1,
            help="Solo la parte final: 2 para RMG-AÑO-0002. Después de usarlo, la numeración "
                 "sigue sola desde la última factura.",
        )
        guardar = st.form_submit_button("💾 Guardar numeración", type="primary")

    if guardar:
        if error := db.fijar_siguiente_secuencia(conn, anio, int(nuevo)):
            st.error(error)
        else:
            anotar(
                "Numeración de facturas",
                f"Próxima de {anio}: {db.numero_factura(anio, siguiente)} → "
                f"{db.numero_factura(anio, int(nuevo))}",
            )
            avisar(f"La próxima factura de {anio} será **{db.numero_factura(anio, int(nuevo))}**.")
            st.rerun()

    if fijada is not None and st.button("↩️ Volver a la numeración automática"):
        db.quitar_secuencia_fijada(conn, anio)
        anotar("Numeración de facturas", f"{anio}: vuelve a la numeración automática")
        avisar(f"Numeración automática: la próxima de {anio} será "
               f"**{db.numero_factura(anio, db.siguiente_secuencia(conn, anio))}**.", "info")
        st.rerun()


def pagina_facturas():
    st.title(FACTURAS)
    st.caption("Genera la factura de un suplidor o cliente con los datos ya guardados y descárgala en PDF.")
    mostrar_aviso()

    if factura is None:
        st.error(
            f"Falta instalar la librería **{FALTA_LIBRERIA}**, que se usa para crear el PDF. "
            "En la terminal, con el entorno activado, ejecuta `pip install -r requirements.txt` "
            "y vuelve a abrir la aplicación."
        )
        return

    generada = st.session_state.get("factura_generada")
    f = db.obtener_factura(conn, generada) if generada else None
    if f:
        with st.container(border=True):
            st.subheader(f"✅ Factura {f['numero']} generada")
            st.caption(f"{f['cliente_nombre']} · Total RD$ {factura.monto(f['total'])}")
            mostrar_factura(f, f"nueva_{f['id']}", abierta=True)
            if st.button("Cerrar", key="cerrar_generada"):
                st.session_state.pop("factura_generada")
                st.rerun()

    pestanas = st.tabs(
        ["🆕 Nueva factura", "📚 Facturas emitidas"] + (["🔢 Numeración"] if es_admin() else [])
    )
    with pestanas[0]:
        formulario_factura()
    with pestanas[1]:
        facturas_emitidas()
    if es_admin():
        with pestanas[2]:
            numeracion_facturas()


# --------------------------------------------------------------------------
# 7. Usuarios (solo administradores)
# --------------------------------------------------------------------------

def pagina_usuarios():
    st.title(USUARIOS)
    st.caption("Quién puede entrar al CRM. Solo los administradores ven esta sección.")
    mostrar_aviso()

    usuarios = db.listar_usuarios(conn)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Usuario": u["usuario"],
                    "Nombre": u["nombre"],
                    "Rol": u["rol"],
                    "Cuenta": "Activa" if u["activo"] else "Desactivada",
                    "Alta": fecha_dmy(u["fecha_creacion"]),
                    "Último acceso": u["ultimo_acceso"] or "Nunca",
                }
                for u in usuarios
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    st.divider()
    st.subheader("Dar acceso a un usuario nuevo")

    # Mismo truco que el alta de clientes: el contador vacía el formulario tras
    # crear la cuenta, pero lo conserva relleno si hubo un error.
    k = f"_{st.session_state.get('usuario_gen', 0)}"
    with st.form("form_usuario_nuevo"):
        col1, col2 = st.columns(2)
        nombre = col1.text_input("Nombre completo *", key="u_nombre" + k)
        usuario = col2.text_input(
            "Usuario *", help="Con este nombre inicia sesión. Sin espacios.", key="u_usuario" + k
        )
        contrasena = col1.text_input("Contraseña *", type="password", key="u_clave" + k)
        confirmacion = col2.text_input("Confirmar contraseña *", type="password", key="u_conf" + k)
        rol = st.selectbox("Rol", db.ROLES, index=db.ROLES.index("Usuario"), key="u_rol" + k)
        crear = st.form_submit_button("➕ Crear usuario", type="primary")

    if crear:
        error = validar_usuario(usuario, nombre) or validar_contrasena(contrasena, confirmacion)
        if error:
            st.error(error)
        elif db.crear_usuario(conn, usuario.strip(), nombre.strip(), contrasena, rol) is None:
            st.error(f"Ya existe el usuario **{usuario.strip()}**.")
        else:
            anotar("Usuario creado", f"{nombre.strip()} ({usuario.strip()}) · {rol}")
            st.session_state["usuario_gen"] = st.session_state.get("usuario_gen", 0) + 1
            avisar(f"Usuario **{usuario.strip()}** creado. Ya puede iniciar sesión.")
            st.rerun()

    st.divider()
    st.subheader("Editar un usuario")

    por_id = {u["id"]: u for u in usuarios}
    uid = st.selectbox(
        "Usuario",
        list(por_id),
        format_func=lambda i: f"{por_id[i]['nombre']} ({por_id[i]['usuario']})",
    )
    u = por_id[uid]
    es_yo = uid == sesion["id"]
    k = f"_{uid}"

    with st.form("form_usuario_editar"):
        nombre = st.text_input("Nombre completo", value=u["nombre"], key="ue_nombre" + k)
        col1, col2 = st.columns(2, vertical_alignment="bottom")
        rol = col1.selectbox(
            "Rol", db.ROLES, index=db.ROLES.index(u["rol"]), disabled=es_yo, key="ue_rol" + k
        )
        activo = col2.checkbox(
            "Cuenta activa", value=bool(u["activo"]), disabled=es_yo, key="ue_activo" + k
        )
        if es_yo:
            st.caption("No puedes quitarte el rol de administrador ni desactivar tu propia cuenta.")
        guardar = st.form_submit_button("💾 Guardar cambios", type="primary")

    if guardar:
        if not nombre.strip():
            st.error("El nombre es obligatorio.")
        else:
            db.actualizar_usuario(conn, uid, nombre.strip(), rol, activo)
            cambios = describir_cambios(
                {"Nombre": u["nombre"], "Rol": u["rol"],
                 "Cuenta": "Activa" if u["activo"] else "Desactivada"},
                {"Nombre": nombre.strip(), "Rol": rol,
                 "Cuenta": "Activa" if activo else "Desactivada"},
                [],
            )
            if cambios:
                anotar("Usuario editado", f"{u['nombre']} ({u['usuario']}): {cambios}")
            avisar(f"Usuario **{u['usuario']}** actualizado.")
            st.rerun()

    with st.form("form_usuario_clave", clear_on_submit=True):
        st.markdown("**Restablecer contraseña**")
        col3, col4 = st.columns(2)
        nueva = col3.text_input("Nueva contraseña", type="password", key="ue_clave" + k)
        confirmacion = col4.text_input("Confirmar", type="password", key="ue_conf" + k)
        restablecer = st.form_submit_button("🔑 Restablecer contraseña")

    if restablecer:
        if error := validar_contrasena(nueva, confirmacion):
            st.error(error)
        else:
            db.cambiar_contrasena(conn, uid, nueva)
            anotar("Contraseña restablecida", f"{u['nombre']} ({u['usuario']})")
            avisar(f"Contraseña de **{u['usuario']}** restablecida.")
            st.rerun()

    if es_yo:
        return

    st.caption("Para quitar el acceso sin borrar la cuenta, desmarca *Cuenta activa*.")
    col5, col6 = st.columns([1, 2])
    confirmar = col6.checkbox("Confirmo que quiero eliminar este usuario", key="ue_del" + k)
    if col5.button("🗑️ Eliminar usuario", disabled=not confirmar):
        db.eliminar_usuario(conn, uid)
        anotar("Usuario eliminado", f"{u['nombre']} ({u['usuario']}) · se quita de los registros que tenía asignados")
        avisar(f"Usuario **{u['usuario']}** eliminado.", "warning")
        st.rerun()


# --------------------------------------------------------------------------
# 8. Actividad (solo administradores)
# --------------------------------------------------------------------------

def pagina_actividad():
    st.title(ACTIVIDAD)
    st.caption(
        "Quién hizo qué y cuándo. Solo los administradores ven esta sección. "
        "Hora de República Dominicana."
    )

    hoy = db.ahora().date()
    col1, col2, col3 = st.columns([2, 2, 2])
    rango = col1.date_input(
        "Fechas", value=(hoy - timedelta(days=30), hoy), max_value=hoy, format="DD/MM/YYYY"
    )
    usuarios = db.listar_usuarios(conn)
    nombres = {u["id"]: f"{u['nombre']} ({u['usuario']})" for u in usuarios}
    usuario_id = col2.selectbox(
        "Usuario", [None] + list(nombres), format_func=lambda i: "Todos" if i is None else nombres[i]
    )
    accion = col3.selectbox(
        "Acción", [None] + db.acciones_registradas(conn),
        format_func=lambda a: "Todas" if a is None else a,
    )

    # Mientras se elige el rango, el calendario devuelve solo la primera fecha.
    desde, hasta = rango if len(rango) == 2 else (rango[0], rango[0])
    filas = db.listar_actividad(conn, desde, hasta, usuario_id, accion)

    if not filas:
        st.info("No hay actividad con esos filtros.")
        return

    df = pd.DataFrame(filas).rename(
        columns={
            "fecha": "Fecha y hora",
            "usuario_nombre": "Usuario",
            "accion": "Acción",
            "detalle": "Detalle",
        }
    )
    df["Fecha y hora"] = pd.to_datetime(df["Fecha y hora"]).dt.strftime("%d/%m/%Y %H:%M")
    st.caption(f"**{len(df)}** acciones (máximo 2,000; acota las fechas para ver más atrás).")
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={"Detalle": st.column_config.TextColumn(width="large")},
    )
    st.download_button(
        "⬇️ Exportar a CSV",
        data=a_csv(df),
        file_name=f"actividad_{desde.isoformat()}_{hasta.isoformat()}.csv",
        mime="text/csv",
    )


# --------------------------------------------------------------------------
# Navegación
# --------------------------------------------------------------------------

# Sin sesión no se muestra nada del CRM, solo la pantalla de acceso.
sesion = usuario_actual()
if sesion is None:
    pantalla_acceso()
    st.stop()

paginas = PAGINAS + ([USUARIOS, ACTIVIDAD] if es_admin() else [])

# Debe aplicarse antes de crear el radio del menú.
if "_destino" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("_destino")
# Un administrador al que le quitaron el rol puede tener aún 👥 Usuarios elegido.
if st.session_state.get("nav") not in paginas:
    st.session_state["nav"] = DASHBOARD

with st.sidebar:
    st.image(str(LOGO), width="stretch")
    st.caption("CRM de suplidores y clientes · arroz, maíz, abono")
    st.markdown(f"👤 **{sesion['nombre']}** · {sesion['rol']}")
    st.divider()
    pagina = st.radio("Secciones", paginas, key="nav", label_visibility="collapsed")
    st.divider()

    _vencidos, _hoy, _ = db.seguimientos(conn)
    pendientes = _vencidos + _hoy
    if pendientes:
        mios = sum(es_mio(c) for c in pendientes)
        st.warning(
            f"**{len(pendientes)}** seguimiento(s) vencido(s) o para hoy"
            + (f", **{mios}** asignado(s) a ti ⭐." if mios else ".")
        )

    with st.expander("🔑 Cambiar mi contraseña"):
        formulario_mi_contrasena(sesion)
    if st.button("🚪 Cerrar sesión"):
        st.session_state.clear()
        st.rerun()
    st.caption("Base de datos: Supabase (PostgreSQL)")

VISTAS = {
    DASHBOARD: pagina_dashboard,
    FORMULARIO: pagina_formulario,
    LISTA_SUPLIDORES: pagina_lista_suplidores,
    LISTA_CLIENTES: pagina_lista_clientes,
    CONTACTOS: pagina_contactos,
    SEGUIMIENTO: pagina_seguimiento,
    FACTURAS: pagina_facturas,
    USUARIOS: pagina_usuarios,
    ACTIVIDAD: pagina_actividad,
}

VISTAS[pagina]()
