"""CRM para intermediario de suplidores de productos agrícolas.

Ejecutar con:  streamlit run app.py
"""

import importlib
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import database as db

# Al actualizar el código, Streamlit vuelve a ejecutar app.py pero a veces sigue
# usando el database.py viejo que ya tenía en memoria (así falló el despliegue
# del seguimiento automático: "database has no attribute DIAS_SEGUIMIENTO").
# Si el archivo cambió desde que se cargó, se vuelve a cargar.
if getattr(db, "MTIME_CARGA", None) != Path(db.__file__).stat().st_mtime:
    db = importlib.reload(db)

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
LISTA = "📋 Lista de Suplidores y Clientes"
CONTACTOS = "🗒️ Historial de Contactos"
SEGUIMIENTO = "🔔 Seguimiento"
USUARIOS = "👥 Usuarios"   # solo para administradores
ACTIVIDAD = "📜 Actividad"  # solo para administradores

PAGINAS = [DASHBOARD, FORMULARIO, LISTA, CONTACTOS, SEGUIMIENTO]


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
    "telefono": "Teléfono",
    "email": "Email",
    "ubicacion": "Ubicación",
    "productos_interes": "Productos de interés",
    "estado": "Estado",
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
    return c.get("asignado_a") == sesion["id"]


def nombre_asignado(c):
    if es_mio(c):
        return "⭐ Tú"
    return c.get("asignado_nombre") or "Sin asignar"


def usuarios_asignables(incluir_id=None):
    """Usuarios activos (más `incluir_id` aunque esté desactivado, para que el
    formulario muestre bien una asignación existente)."""
    return [u for u in db.listar_usuarios(conn) if u["activo"] or u["id"] == incluir_id]


def selector_asignado(label, usuarios, actual=None, key=None, disabled=False):
    """Selectbox 'Sin asignar' + usuarios; devuelve el id o None."""
    por_id = {u["id"]: u for u in usuarios}
    opciones = [None] + list(por_id)
    return st.selectbox(
        label,
        opciones,
        index=opciones.index(actual) if actual in opciones else 0,
        format_func=lambda i: "Sin asignar" if i is None else por_id[i]["nombre"],
        key=key,
        disabled=disabled,
    )


def etiqueta_registro(c):
    """'Nombre (Empresa)' para el registro de actividad, sin la ⭐."""
    return f"{c['nombre']} ({c['empresa']})" if c.get("empresa") else c["nombre"]


def recortar(texto, largo=40):
    texto = texto or "—"
    return texto if len(texto) <= largo else texto[: largo - 1] + "…"


def describir_cambios(antes, despues, usuarios):
    """'Estado: Negociación → Cliente Activo; Teléfono: — → 809…', o '' si
    no cambió nada."""
    nombres = {u["id"]: u["nombre"] for u in usuarios}
    cambios = []
    for campo, valor in despues.items():
        previo = antes.get(campo)
        if (previo or None) == (valor or None):
            continue
        etiqueta = COLUMNAS_TABLA.get(campo, campo)
        if campo == "asignado_a":
            etiqueta = "Asignado a"
            previo, valor = nombres.get(previo, "Sin asignar"), nombres.get(valor, "Sin asignar")
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
    usuarios = usuarios_asignables(actual.get("asignado_a"))

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
        # Solo el administrador asigna. Lo que registra un usuario queda a su
        # nombre; al editar, la asignación no cambia.
        if es_admin():
            with col3:
                asignado_a = selector_asignado(
                    "Asignado a", usuarios, actual.get("asignado_a"), key="asig" + k
                )
        else:
            asignado_a = actual.get("asignado_a") if editando else sesion["id"]
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
                "telefono": telefono.strip(),
                "email": email.strip(),
                "ubicacion": ubicacion.strip(),
                "productos_interes": productos.strip(),
                "estado": estado,
                "tipo": tipo,
                "asignado_a": asignado_a,
            }

            if editando:
                db.actualizar_cliente(conn, cid, datos)
                cambios = describir_cambios(actual, datos, usuarios)
                if cambios:
                    anotar("Edición", f"{tipo} {etiqueta_registro(datos)}: {cambios}")
                avisar(f"{tipo} **{datos['nombre']}** actualizado.")
            else:
                nuevo_id = db.crear_cliente(conn, datos)
                asignado = {u["id"]: u["nombre"] for u in usuarios}.get(asignado_a, "Sin asignar")
                anotar("Registro", f"{tipo} {etiqueta_registro(datos)} · asignado a {asignado}")
                # Vaciar el formulario de alta para que no reaparezca relleno.
                st.session_state["alta_gen"] = st.session_state.get("alta_gen", 0) + 1
                st.session_state["cliente_foco"] = nuevo_id
                avisar(f"{tipo} **{datos['nombre']}** registrado.")
            st.rerun()

    if not editando:
        return

    st.divider()
    st.subheader(f"Eliminar {actual['tipo'].lower()}")
    st.caption("Eliminar un registro borra también todo su historial de contactos.")
    col5, col6 = st.columns([1, 2])
    confirmar = col6.checkbox("Confirmo que quiero eliminar este registro", key="conf_del" + k)
    if col5.button("🗑️ Eliminar", disabled=not confirmar):
        db.eliminar_cliente(conn, cid)
        anotar("Eliminación", f"{actual['tipo']} {etiqueta_registro(actual)}")
        st.session_state["cliente_foco"] = None
        avisar(f"{actual['tipo']} **{actual['nombre']}** eliminado.", "warning")
        st.rerun()


# --------------------------------------------------------------------------
# 3. Lista de suplidores y clientes
# --------------------------------------------------------------------------

FILTRO_TIPO = {"Ambos": "Ambos", "Clientes": "Cliente", "Suplidores": "Suplidor"}


def pagina_lista():
    st.title(LISTA)

    mostrar_aviso()

    col1, col2, col3, col8 = st.columns([3, 2, 2, 2])
    busqueda = col1.text_input("🔍 Buscar", placeholder="Nombre, empresa, ubicación o productos…")
    tipo = col2.selectbox("Mostrar", list(FILTRO_TIPO))
    estado = col3.selectbox("Filtrar por estado", ["Todos"] + db.ESTADOS)
    usuarios = usuarios_asignables()
    nombres = {u["id"]: u["nombre"] for u in usuarios}
    asignado = col8.selectbox(
        "Asignado a",
        [None, sesion["id"], db.SIN_ASIGNAR] + [i for i in nombres if i != sesion["id"]],
        format_func=lambda i: {None: "Todos", sesion["id"]: "⭐ Mis asignados",
                               db.SIN_ASIGNAR: "Sin asignar"}.get(i) or nombres[i],
    )

    total = db.contar_clientes(conn)
    if total == 0:
        st.info(f"Todavía no hay suplidores ni clientes registrados. Empieza en **{FORMULARIO}**.")
        return

    clientes = db.listar_clientes(conn, busqueda, estado, FILTRO_TIPO[tipo], asignado)
    for c in clientes:
        c["asignado_nombre"] = nombre_asignado(c)
    st.caption(f"Mostrando **{len(clientes)}** de **{total}** registros. ⭐ = asignado a ti.")

    df = tabla_clientes(clientes)
    if df.empty:
        st.warning("Ningún registro coincide con la búsqueda.")
    else:
        st.dataframe(df, width="stretch", hide_index=True)

    col4, col5 = st.columns(2)
    col4.download_button(
        "⬇️ Exportar resultados a CSV",
        data=a_csv(df),
        file_name=f"suplidores_clientes_{date.today().isoformat()}.csv",
        mime="text/csv",
        disabled=df.empty,
    )
    col5.download_button(
        "⬇️ Exportar TODOS a CSV",
        data=a_csv(tabla_clientes(db.listar_clientes(conn))),
        file_name=f"suplidores_clientes_completo_{date.today().isoformat()}.csv",
        mime="text/csv",
    )

    if not clientes:
        return

    st.divider()
    st.subheader("Acciones rápidas")
    cid = selector_cliente("Suplidor o cliente", clientes)
    col6, col7 = st.columns(2)
    if col6.button("✏️ Editar este registro"):
        ir_a(FORMULARIO, cid)
    if col7.button("🗒️ Registrar un contacto"):
        ir_a(CONTACTOS, cid)

    if es_admin():
        seccion_asignar(clientes, usuarios)


def seccion_asignar(clientes, usuarios):
    """Asignación en bloque (solo administradores) sobre la lista filtrada."""
    st.divider()
    st.subheader("👤 Asignar a un usuario")
    st.caption("Usa los filtros de arriba para acotar la lista y asigna varios registros a la vez.")

    por_id = {c["id"]: c for c in clientes}
    todos = st.checkbox(f"Todos los que se muestran arriba ({len(clientes)})")
    elegidos = list(por_id) if todos else st.multiselect(
        "Registros",
        list(por_id),
        format_func=lambda i: etiqueta_cliente(por_id[i]),
        placeholder="Elige uno o varios",
    )
    col1, col2 = st.columns([2, 1], vertical_alignment="bottom")
    with col1:
        destino = selector_asignado("Asignar a", usuarios)
    if col2.button("✅ Asignar", disabled=not elegidos):
        db.asignar_clientes(conn, elegidos, destino)
        a_quien = {u["id"]: u["nombre"] for u in usuarios}.get(destino, "Sin asignar")
        nombres = ", ".join(etiqueta_registro(por_id[i]) for i in elegidos)
        anotar("Asignación", f"{len(elegidos)} registro(s) → {a_quien}: {nombres}")
        avisar(f"**{len(elegidos)}** registro(s) asignado(s) a **{a_quien}**.")
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
# 6. Usuarios (solo administradores)
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
        anotar("Usuario eliminado", f"{u['nombre']} ({u['usuario']}) · sus registros quedan sin asignar")
        avisar(f"Usuario **{u['usuario']}** eliminado.", "warning")
        st.rerun()


# --------------------------------------------------------------------------
# 7. Actividad (solo administradores)
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
    LISTA: pagina_lista,
    CONTACTOS: pagina_contactos,
    SEGUIMIENTO: pagina_seguimiento,
    USUARIOS: pagina_usuarios,
    ACTIVIDAD: pagina_actividad,
}

VISTAS[pagina]()
