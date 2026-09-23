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

st.set_page_config(
    page_title="CRM Suplidores Agrícolas",
    page_icon="🌾",
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
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def conexion():
    return db.get_conn()


conn = conexion()
# Fuera de la caché a propósito: la conexión cacheada sobrevive a las
# actualizaciones del código, así que si init_db solo corriera al crearla, las
# columnas nuevas (p. ej. `tipo`) nunca se agregarían a una base existente.
# Es barato: solo crea lo que falta.
db.init_db(conn)

DASHBOARD = "📊 Dashboard"
FORMULARIO = "➕ Agregar / Editar Suplidor o Cliente"
LISTA = "📋 Lista de Suplidores y Clientes"
CONTACTOS = "🗒️ Historial de Contactos"
SEGUIMIENTO = "🔔 Seguimiento"

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
    empresa = f" — {c['empresa']}" if c.get("empresa") else ""
    return f"{c['nombre']}{empresa}"


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
            }

            if editando:
                db.actualizar_cliente(conn, cid, datos)
                avisar(f"{tipo} **{datos['nombre']}** actualizado.")
            else:
                nuevo_id = db.crear_cliente(conn, datos)
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
        st.session_state["cliente_foco"] = None
        avisar(f"{actual['tipo']} **{actual['nombre']}** eliminado.", "warning")
        st.rerun()


# --------------------------------------------------------------------------
# 3. Lista de suplidores y clientes
# --------------------------------------------------------------------------

FILTRO_TIPO = {"Ambos": "Ambos", "Clientes": "Cliente", "Suplidores": "Suplidor"}


def pagina_lista():
    st.title(LISTA)

    col1, col2, col3 = st.columns([3, 2, 2])
    busqueda = col1.text_input("🔍 Buscar", placeholder="Nombre, empresa, ubicación o productos…")
    tipo = col2.selectbox("Mostrar", list(FILTRO_TIPO))
    estado = col3.selectbox("Filtrar por estado", ["Todos"] + db.ESTADOS)

    total = db.contar_clientes(conn)
    if total == 0:
        st.info(f"Todavía no hay suplidores ni clientes registrados. Empieza en **{FORMULARIO}**.")
        return

    clientes = db.listar_clientes(conn, busqueda, estado, FILTRO_TIPO[tipo])
    st.caption(f"Mostrando **{len(clientes)}** de **{total}** registros.")

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
    cliente = db.obtener_cliente(conn, cid)

    col1, col2, col3 = st.columns(3)
    col1.metric("Estado", cliente["estado"])
    col2.metric("Teléfono", cliente["telefono"] or "—")
    col3.metric("Próximo seguimiento", fecha_dmy(cliente["proximo_seguimiento"]) or "Sin programar")

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
                avisar(f"{c['nombre']}: seguimiento movido al {nueva.strftime('%d/%m/%Y')}.", "info")
                st.rerun()


def pagina_seguimiento():
    st.title("🔔 Sistema de Seguimiento")
    st.caption("Clientes con seguimiento vencido, programado para hoy o próximo a vencer.")
    mostrar_aviso()

    dias = st.slider("Mirar hacia adelante (días)", 1, 30, 7)
    vencidos, para_hoy, proximos = db.seguimientos(conn, dias)

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
# Navegación
# --------------------------------------------------------------------------

# Debe aplicarse antes de crear el radio del menú.
if "_destino" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("_destino")

with st.sidebar:
    st.title("🌾 CRM Suplidores")
    st.caption("Productos agrícolas · arroz, maíz, abono")
    st.divider()
    pagina = st.radio("Secciones", PAGINAS, key="nav", label_visibility="collapsed")
    st.divider()

    _vencidos, _hoy, _ = db.seguimientos(conn)
    pendientes = len(_vencidos) + len(_hoy)
    if pendientes:
        st.warning(f"**{pendientes}** seguimiento(s) vencido(s) o para hoy.")
    st.caption(f"Base de datos: `{db.DB_PATH.name}`")

VISTAS = {
    DASHBOARD: pagina_dashboard,
    FORMULARIO: pagina_formulario,
    LISTA: pagina_lista,
    CONTACTOS: pagina_contactos,
    SEGUIMIENTO: pagina_seguimiento,
}

VISTAS[pagina]()
