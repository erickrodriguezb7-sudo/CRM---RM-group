# 🌾 CRM Suplidores Agrícolas

CRM local para un intermediario de suplidores de productos agrícolas (sacos de
arroz, maíz, abono y otros). Todo se guarda en una base de datos SQLite en la
misma carpeta: no necesita internet ni cuentas.

---

## Cómo abrir el CRM

Ya está todo instalado (Python 3.12 y el entorno `.venv` de esta carpeta). Para
usarlo, abre PowerShell y ejecuta:

```powershell
cd "C:\Users\esaco\OneDrive\Documents\Coding\crm-suplidores"
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

Se abre solo en el navegador (`http://localhost:8501`). Para cerrarlo, pulsa
`Ctrl + C` en la terminal.

> Si PowerShell bloquea el script de activación, ejecuta una vez:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Si alguna vez hay que reinstalar (otra computadora, o se borró `.venv`)

Instala Python desde <https://www.python.org/downloads/> marcando **"Add
python.exe to PATH"**, y luego:

```powershell
cd "C:\Users\esaco\OneDrive\Documents\Coding\crm-suplidores"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Secciones

| Sección | Para qué sirve |
|---|---|
| **📊 Dashboard** | Clientes activos, seguimientos vencidos y para hoy, registros por estado y quiénes llevan 7+ días sin contactar. |
| **➕ Agregar / Editar Suplidor o Cliente** | Alta de suplidores y clientes nuevos y edición o eliminación de los existentes. Los productos de interés se escriben libremente. |
| **📋 Lista de Suplidores y Clientes** | Búsqueda por nombre, empresa, ubicación o productos; filtro por tipo (clientes, suplidores o ambos) y por estado; exportación a CSV. |
| **🗒️ Historial de Contactos** | Bitácora por cliente: fecha, tipo (llamada, email, reunión, WhatsApp, visita), notas y resultado. |
| **🔔 Seguimiento** | Seguimientos vencidos, los de hoy y los próximos; botón para posponer los días que elijas. |

### Estados

`Negociación` → `Cliente Activo` → `Inactivo`

Los registros que tenían el antiguo estado *Prospecto* lo conservan hasta que
se editen; al abrirlos en el formulario aparecen con *Negociación*.

---

## Detalles útiles

- **Fecha automática**: al registrar un contacto la fecha viene puesta con el día
  de hoy; puedes cambiarla si estás anotando algo de días anteriores.
- **Próximo seguimiento automático**: se calcula desde el último contacto (o
  desde el alta, si nunca se ha contactado) y se recalcula al registrar o borrar
  un contacto y al cambiar el tipo o el estado. Editar otros datos no lo toca.

  | Estado | Cliente | Suplidor |
  |---|---|---|
  | Negociación | 3 días | 7 días |
  | Cliente Activo | 14 días | 30 días |
  | Inactivo | 60 días | 90 días |

  El resultado del último contacto manda sobre esa tabla: *Cotización enviada*
  2 días; *Interesado*, *Pendiente de respuesta* y *Sin respuesta* 3 días;
  *No interesado* 60 días. *Venta cerrada* usa la tabla. Los días se cambian en
  `DIAS_SEGUIMIENTO` y `DIAS_POR_RESULTADO` de `database.py`.
- **Posponer**: en *Seguimiento* eliges cuántos días. Un seguimiento vencido se
  pospone desde hoy; uno futuro, desde su fecha programada. Se mantiene hasta el
  próximo recálculo.
- **Exportar a CSV**: en *Lista de Clientes* exportas los resultados filtrados o
  toda la cartera; en *Historial de Contactos*, la bitácora de un cliente. Los
  archivos salen en UTF-8 con BOM para que Excel muestre bien las tildes y la ñ.
- **Eliminar un cliente** borra también todo su historial de contactos. Por eso
  hay que marcar la casilla de confirmación antes de que el botón se active.

## Respaldo de los datos

Todo vive en el archivo **`crm.db`** de esta carpeta. Para respaldar, copia ese
archivo (con la aplicación cerrada). Para restaurar, ponlo de vuelta en la
carpeta con el mismo nombre.

## Archivos

```
crm-suplidores/
├─ app.py                 # Interfaz Streamlit (las 5 secciones)
├─ database.py            # SQLite: tablas, consultas y métricas
├─ requirements.txt       # Dependencias
├─ .streamlit/config.toml # (opcional) ajustes de tema; sin `base` fijo para que siga el modo claro/oscuro
├─ .venv/                 # Entorno con Streamlit y pandas ya instalados
└─ crm.db                 # Se crea solo la primera vez que abres la app
```

### Estructura de la base de datos

**`clientes`** — `id`, `nombre`, `tipo` (`Cliente` o `Suplidor`), `empresa`,
`telefono`, `email`, `ubicacion`, `productos_interes` (texto libre), `estado`,
`fecha_creacion`, `proximo_seguimiento`, `giro_negocio` (ya no se usa; se
conserva para no perder datos anteriores)

La columna `tipo` se agrega sola a una base existente la primera vez que se
abre la app; los registros anteriores quedan como `Cliente`.

**`contactos`** — `id`, `cliente_id`, `fecha`, `tipo_contacto`, `notas`,
`resultado`

Las fechas se guardan como texto `AAAA-MM-DD`. Al borrar un cliente, sus
contactos se eliminan en cascada.
