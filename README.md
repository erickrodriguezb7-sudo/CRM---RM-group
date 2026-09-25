# 🌾 CRM Suplidores Agrícolas

CRM para un intermediario de suplidores de productos agrícolas (sacos de
arroz, maíz, abono y otros). Los datos se guardan en una base PostgreSQL en
**Supabase**, así que no se pierden cuando Streamlit Cloud duerme o reinicia la
app. Para entrar hace falta un usuario y una contraseña (ver
[Acceso y usuarios](#acceso-y-usuarios)).

## Conectar la base de datos (Supabase)

1. Crea un proyecto gratis en <https://supabase.com> y guarda la contraseña de
   la base.
2. En el proyecto, pulsa **Connect** y copia la URI del **Session pooler**
   (la conexión directa no funciona desde Streamlit Cloud). Se ve así:
   `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-....pooler.supabase.com:5432/postgres`.
   Cambia `[YOUR-PASSWORD]` por tu contraseña.
3. En Streamlit Cloud: **⋮ → Settings → Secrets** de la app, pega:

   ```toml
   DATABASE_URL = "postgresql://postgres.xxxx:TU_CONTRASEÑA@aws-0-....pooler.supabase.com:5432/postgres"
   ```

4. Para correrla en tu computadora, pon la misma línea en
   `.streamlit/secrets.toml` (está en `.gitignore`: nunca lo subas a GitHub).

Las tablas se crean solas la primera vez que abre la app.

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
| **👥 Usuarios** | Solo administradores: dar acceso, cambiar rol, desactivar, restablecer contraseñas y ver el último acceso de cada uno. |
| **📜 Actividad** | Solo administradores: quién hizo qué y cuándo (altas, ediciones, contactos, asignaciones…). |

---

## Acceso y usuarios

- **Primera vez**: si la base no tiene usuarios, la app pide crear la cuenta de
  **administrador** antes de mostrar nada. Hazlo en cuanto abras la app (sobre
  todo si está publicada en internet: quien llegue primero crea esa cuenta).
- **Roles**: *Administrador* ve todo, incluidas **👥 Usuarios** y
  **📜 Actividad**. *Usuario* ve todas las secciones del CRM excepto esas dos.
- **Asignación**: cada suplidor o cliente puede tener un usuario responsable.
  Todos ven todos los registros, pero los asignados a ti llevan ⭐, la lista se
  filtra por *Asignado a* y en *Seguimiento* los usuarios ven primero solo los
  suyos. Lo que registra un usuario queda asignado a él; solo el administrador
  cambia la asignación (en el formulario de edición, o varios a la vez al final
  de la *Lista*).
- **Actividad**: cada inicio de sesión, alta, edición (con qué cambió),
  eliminación, contacto, seguimiento pospuesto, asignación y cambio de usuarios
  queda anotado con quién lo hizo y cuándo. Se filtra por fechas, usuario y
  acción, y se exporta a CSV.
- **Quitar el acceso**: desmarca *Cuenta activa* (conserva la cuenta) o elimina
  el usuario. Si esa persona tenía la sesión abierta, se cierra en su siguiente
  clic. Un administrador no puede desactivarse, eliminarse ni quitarse el rol a
  sí mismo, así que siempre queda al menos uno.
- **Contraseñas**: mínimo 8 caracteres. Cada quien cambia la suya en
  *🔑 Cambiar mi contraseña* (barra lateral); un administrador puede
  restablecer la de cualquiera. Se guardan cifradas (PBKDF2-SHA256), nunca en
  texto plano.
- **Último acceso**: cada inicio de sesión correcto queda anotado con fecha y
  hora del servidor.
- **La sesión dura mientras la pestaña esté abierta**: al recargar la página
  (F5) o cerrar el navegador hay que volver a entrar.
- **Si se olvida la única contraseña de administrador**: borra las filas
  de la tabla `usuarios` en el Table Editor de Supabase y al recargar la app
  pedirá crear un administrador nuevo. Los clientes y contactos
  no se tocan.

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

Todo vive en Supabase. Puedes ver y exportar las tablas desde su
**Table Editor**, y el plan gratuito guarda respaldos diarios. Ojo: Supabase
pausa los proyectos gratuitos tras una semana sin uso; se reactivan desde su
panel sin perder datos.

Para pasar datos de un `crm.db` antiguo (SQLite) a Supabase, una sola vez y con
la base vacía:

```powershell
python migrar_sqlite.py ruta\a\crm.db "postgresql://..."
```

## Archivos

```
crm-suplidores/
├─ app.py                 # Interfaz Streamlit (acceso y las 6 secciones)
├─ database.py            # PostgreSQL: tablas, consultas, métricas y usuarios
├─ migrar_sqlite.py       # Copia un crm.db antiguo a Supabase (uso único)
├─ requirements.txt       # Dependencias
├─ assets/               # Logo de RM Group (barra lateral) e ícono de la pestaña
├─ .streamlit/config.toml # (opcional) ajustes de tema; sin `base` fijo para que siga el modo claro/oscuro
├─ .streamlit/secrets.toml # DATABASE_URL para correrla local (no se sube)
└─ .venv/                 # Entorno con Streamlit y pandas ya instalados
```

### Estructura de la base de datos

**`clientes`** — `id`, `nombre`, `tipo` (`Cliente` o `Suplidor`), `empresa`,
`telefono`, `email`, `ubicacion`, `productos_interes` (texto libre), `estado`,
`fecha_creacion`, `proximo_seguimiento`, `asignado_a` (id del usuario
responsable; queda vacío si ese usuario se elimina), `giro_negocio` (ya no se
usa; se conserva para no perder datos anteriores)

**`contactos`** — `id`, `cliente_id`, `fecha`, `tipo_contacto`, `notas`,
`resultado`

**`usuarios`** — `id`, `usuario` (único, sin distinguir mayúsculas), `nombre`,
`contrasena_hash`, `rol` (`Administrador` o `Usuario`), `activo` (1/0),
`fecha_creacion`, `ultimo_acceso` (`AAAA-MM-DD HH:MM`)

**`actividad`** — `id`, `fecha` (`AAAA-MM-DD HH:MM:SS`, hora de República
Dominicana), `usuario_id`, `usuario_nombre`, `accion`, `detalle`. Los nombres se
guardan como texto para que el historial siga legible aunque luego se elimine
el usuario o el registro.

Las fechas se guardan como texto `AAAA-MM-DD`. Al borrar un cliente, sus
contactos se eliminan en cascada.
