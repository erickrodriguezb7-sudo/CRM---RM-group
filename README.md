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
| **📊 Dashboard** | Clientes por estado, tasa de conversión, contactos del mes y quiénes llevan 7+ días sin contactar. |
| **➕ Agregar / Editar Cliente** | Alta de clientes nuevos y edición o eliminación de los existentes. |
| **📋 Lista de Clientes** | Búsqueda por nombre, empresa, ubicación o giro; filtro por estado; exportación a CSV. |
| **🗒️ Historial de Contactos** | Bitácora por cliente: fecha, tipo (llamada, email, reunión, WhatsApp, visita), notas y resultado. |
| **🔔 Seguimiento** | Seguimientos vencidos, los de hoy y los próximos; botón para posponer 7 días. |

### Estados del cliente

`Prospecto` → `Negociación` → `Cliente Activo` → `Inactivo`

La **tasa de conversión** del dashboard es el porcentaje de la cartera que ya
está en *Cliente Activo*.

---

## Detalles útiles

- **Fecha automática**: al registrar un contacto la fecha viene puesta con el día
  de hoy; puedes cambiarla si estás anotando algo de días anteriores.
- **Próximo seguimiento**: se puede fijar al crear o editar un cliente, y también
  cada vez que registras un contacto (por defecto, a 7 días).
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
├─ .streamlit/config.toml # Tema claro, color corporativo verde
├─ .venv/                 # Entorno con Streamlit y pandas ya instalados
└─ crm.db                 # Se crea solo la primera vez que abres la app
```

### Estructura de la base de datos

**`clientes`** — `id`, `nombre`, `empresa`, `telefono`, `email`, `ubicacion`,
`giro_negocio`, `productos_interes`, `estado`, `fecha_creacion`,
`proximo_seguimiento`

**`contactos`** — `id`, `cliente_id`, `fecha`, `tipo_contacto`, `notas`,
`resultado`

Las fechas se guardan como texto `AAAA-MM-DD`. Al borrar un cliente, sus
contactos se eliminan en cascada.
