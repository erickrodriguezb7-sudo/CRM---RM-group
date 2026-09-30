"""Factura en PDF con el diseño de RM Group.

Las medidas están en píxeles del modelo original (imagen de 1102 × 1427, tamaño
carta) y se convierten a puntos al dibujar; así cada número se puede comparar
directamente con el modelo.

Lo fijo (emisor, datos bancarios, firmas, lemas) está en las constantes de
abajo: cambiar un dato de la empresa es editar una línea aquí. Lo variable de
cada factura llega en el diccionario que recibe `generar_pdf`.
"""

import io
import re
from datetime import date
from math import hypot
from pathlib import Path

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.pdfgen.canvas import FILL_EVEN_ODD

# Igual que en database.py: app.py la compara para recargar el módulo si el
# archivo cambió desde que se cargó.
MTIME_CARGA = Path(__file__).stat().st_mtime

# --------------------------------------------------------------------------
# Datos fijos de la empresa
# --------------------------------------------------------------------------

EMISOR = {
    "nombre": "RM Group",
    "direccion": [
        "Plaza Francesa",
        "Avenida Abraham Lincoln con Paseo de los Locutores.",
        "Piantini, Santo Domingo, República Dominicana",
        "Código Postal: 10148",
    ],
    "email": "manuelal9502@gmail.com",
    "telefonos": ["829-899-9502", "973-780-0946"],
}

BANCO = [
    ("Nombre:", "MANUEL MARIANO"),
    ("Documento de identidad:", "40230436632"),
    ("Banco:", "Banco BHD"),
    ("Tipo de cuenta:", "Ahorros (RD$)"),
    ("Número de cuenta:", "34352380011"),
    ("Cuenta estándar (IBAN):", "DO17BCBH00000000034352380011"),
    ("Correo electrónico:", "manuelal9502@gmail.com"),
]

FIRMAS = [("Manuel Rodriguez", "CEO"), ("Jean Rodriguez", "COO")]

LEMA = ["SOLUCIONES", "QUE IMPULSAN", "EL MAÑANA"]
PIE_IZQ = ("RM GROUP", "Santo Domingo, República Dominicana")
PIE_DER = ("SOLUCIONES HOY.", "UN FUTURO MEJOR MAÑANA.")

CONDICIONES_PAGO = ["Al contado", "Crédito a 15 días", "Crédito a 30 días", "50% anticipo, 50% contra entrega"]

TRANSPORTE_DESCRIPCION = "Servicio de transporte / flete"


def transporte_detalle(cliente):
    return f"Entrega en las instalaciones de {cliente}.\nRM Group asume el riesgo de transportación."


# --------------------------------------------------------------------------
# Formatos
# --------------------------------------------------------------------------

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def fecha_larga(d, con_dia=False):
    """date -> '22 de septiembre de 2026' (o 'Miércoles 23 de septiembre de 2026')."""
    texto = f"{d.day} de {MESES[d.month - 1]} de {d.year}"
    return f"{DIAS[d.weekday()]} {texto}" if con_dia else texto


def monto(v):
    return f"{v:,.2f}"


def cantidad(q):
    q = float(q)
    return f"{q:,.0f}" if q.is_integer() else f"{q:,.2f}".rstrip("0").rstrip(".")


def importe(linea):
    return round(float(linea["cantidad"]) * float(linea["precio"]), 2)


def totales(lineas, transporte):
    """(subtotal, total). El subtotal es solo de productos, como en el modelo."""
    subtotal = round(sum(importe(l) for l in lineas), 2)
    return subtotal, round(subtotal + float(transporte or 0), 2)


# --------------------------------------------------------------------------
# Recursos: fuentes (OFL), logo y colores
# --------------------------------------------------------------------------

ASSETS = Path(__file__).parent / "assets"
LOGO = ASSETS / "logo_factura.png"

DISPLAY = "SourceSerif4-Display"     # "FACTURA"
TITULO = "SourceSerif4-Heading"      # "RM Group", nombre del cliente
SERIF = "SourceSerif4-Regular"
SERIF_B = "SourceSerif4-Semibold"
SANS = "Inter-Regular"
SANS_M = "Inter-Medium"
SANS_B = "Inter-SemiBold"


def _registrar_fuentes():
    registradas = pdfmetrics.getRegisteredFontNames()
    for nombre in (DISPLAY, TITULO, SERIF, SERIF_B, SANS, SANS_M, SANS_B):
        if nombre not in registradas:
            pdfmetrics.registerFont(TTFont(nombre, str(ASSETS / "fonts" / f"{nombre}.ttf")))


FONDO = HexColor("#F8F5EE")
PILDORA = HexColor("#E8E2D4")
BANDA = HexColor("#E5DFD1")
CAJA = HexColor("#EDE9DF")
CAJA_TOTALES = HexColor("#E9E5DA")
CUERPO_TABLA = HexColor("#FAF8F3")
OLIVA = HexColor("#3D4631")
OLIVA_LINEA = HexColor("#59624B")
CREMA = HexColor("#F3F0E8")
TINTA = HexColor("#22261E")
TEXTO = HexColor("#2C2F28")
GRIS = HexColor("#55584C")
LINEA = HexColor("#D6D0C2")
LINEA_PIE = HexColor("#A3A193")
ICONO = HexColor("#3A4230")

# --------------------------------------------------------------------------
# Geometría: píxeles del modelo -> puntos PDF
# --------------------------------------------------------------------------

ANCHO_PAG, ALTO_PAG = letter
S = ANCHO_PAG / 1102          # puntos por píxel del modelo

LIMITE_CONTENIDO = 1300       # nada (salvo el pie) baja de aquí
TOPE_CONTINUACION = 264       # dónde empieza la tabla en las páginas siguientes


def X(px):
    return px * S


def Y(px):
    return ALTO_PAG - px * S


def P(punto):
    return X(punto[0]), Y(punto[1])


# --------------------------------------------------------------------------
# Íconos: Material Icons de Google (Apache 2.0), caja de 24 × 24
# --------------------------------------------------------------------------

ICONOS = {
    "ubicacion": "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z",
    "correo": "M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z",
    "telefono": "M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z",
    "persona": "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
    "calendario": "M19 4h-1V2h-2v2H8V2H6v2H5c-1.11 0-1.99.9-1.99 2L3 20c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V10h14v10zM9 14H7v-2h2v2zm4 0h-2v-2h2v2zm4 0h-2v-2h2v2zm-4 4h-2v-2h2v2zm-4 0H7v-2h2v2zm8 0h-2v-2h2v2z",
    "tarjeta": "M20 4H4c-1.11 0-1.99.89-1.99 2L2 18c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V6c0-1.11-.89-2-2-2zm0 14H4v-6h16v6zm0-10H4V6h16v2z",
    "banco": "M4 10v7h3v-7H4zm6 0v7h3v-7h-3zM2 22h19v-3H2v3zm14-12v7h3v-7h-3zm-4.5-9L2 6v2h19V6l-9.5-5z",
    "documento": "M8 16h8v2H8zm0-4h8v2H8zm6-10H6c-1.1 0-2 .9-2 2v16c0 1.1.89 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11z",
}

_TOKENS = re.compile(r"[MmLlHhVvCcSsZz]|-?(?:\d+\.?\d*|\.\d+)")


def _segmentos_svg(d):
    """Path SVG (M L H V C S Z, absolutos o relativos) -> segmentos absolutos."""
    toks = _TOKENS.findall(d)
    i, cmd = 0, None
    x = y = inicio_x = inicio_y = 0.0
    control = None      # último punto de control, para reflejarlo en S
    salida = []

    def num():
        nonlocal i
        i += 1
        return float(toks[i - 1])

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                salida.append(("Z",))
                x, y, control = inicio_x, inicio_y, None
                continue
        rel = cmd.islower()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        c = cmd.upper()
        if c == "M":
            x, y = ox + num(), oy + num()
            inicio_x, inicio_y, control = x, y, None
            salida.append(("M", x, y))
            cmd = "l" if rel else "L"   # pares siguientes = líneas
        elif c == "L":
            x, y = ox + num(), oy + num()
            control = None
            salida.append(("L", x, y))
        elif c == "H":
            x, control = ox + num(), None
            salida.append(("L", x, y))
        elif c == "V":
            y, control = oy + num(), None
            salida.append(("L", x, y))
        elif c in "CS":
            if c == "C":
                x1, y1 = ox + num(), oy + num()
            else:
                x1, y1 = (2 * x - control[0], 2 * y - control[1]) if control else (x, y)
            x2, y2 = ox + num(), oy + num()
            x, y = ox + num(), oy + num()
            control = (x2, y2)
            salida.append(("C", x1, y1, x2, y2, x, y))
    return salida


_CACHE_ICONOS = {}


def _icono(c, nombre, izq, arriba, ancho, color):
    """Dibuja el ícono en la caja cuadrada de `ancho` px con esquina (izq, arriba)."""
    segs = _CACHE_ICONOS.setdefault(nombre, _segmentos_svg(ICONOS[nombre]))
    k = ancho / 24

    def pt(px, py):
        return X(izq + px * k), Y(arriba + py * k)

    p = c.beginPath()
    for s in segs:
        if s[0] == "M":
            p.moveTo(*pt(s[1], s[2]))
        elif s[0] == "L":
            p.lineTo(*pt(s[1], s[2]))
        elif s[0] == "C":
            p.curveTo(*pt(s[1], s[2]), *pt(s[3], s[4]), *pt(s[5], s[6]))
        else:
            p.close()
    c.setFillColor(color)
    c.drawPath(p, stroke=0, fill=1, fillMode=FILL_EVEN_ODD)   # respeta los huecos


# --------------------------------------------------------------------------
# Primitivas de dibujo (en píxeles del modelo)
# --------------------------------------------------------------------------

def _ancho(s, fuente, tam, esp=0):
    """Ancho en px del texto con tamaño `tam` px y espaciado `esp` px."""
    return pdfmetrics.stringWidth(s, fuente, tam) + esp * max(len(s) - 1, 0)


def _ajustar(s, fuente, tam, maximo, esp=0):
    """Reduce el tamaño hasta que el texto quepa en `maximo` px."""
    ancho = _ancho(s, fuente, tam, esp)
    return tam if ancho <= maximo else tam * maximo / ancho


def _texto(c, x, y, s, fuente, tam, color, alinear="izq", esp=0):
    ancho = _ancho(s, fuente, tam, esp)
    if alinear == "der":
        x -= ancho
    elif alinear == "centro":
        x -= ancho / 2
    c.setFillColor(color)
    c.setFont(fuente, tam * S)
    c.drawString(X(x), Y(y), s, charSpace=esp * S)
    return ancho


def _caja(c, x1, y1, x2, y2, relleno, r=0, arriba=True, abajo=True, borde=None):
    """Rectángulo con esquinas redondeadas (arriba y/o abajo)."""
    izq, der, sup, inf = X(x1), X(x2), Y(y1), Y(y2)
    rs, ri = (r * S if arriba else 0), (r * S if abajo else 0)
    k = 0.4477   # 1 - 0.5523: aproximación de un cuarto de círculo con Bézier
    p = c.beginPath()
    p.moveTo(izq + rs, sup)
    p.lineTo(der - rs, sup)
    if rs:
        p.curveTo(der - rs * k, sup, der, sup - rs * k, der, sup - rs)
    p.lineTo(der, inf + ri)
    if ri:
        p.curveTo(der, inf + ri * k, der - ri * k, inf, der - ri, inf)
    p.lineTo(izq + ri, inf)
    if ri:
        p.curveTo(izq + ri * k, inf, izq, inf + ri * k, izq, inf + ri)
    p.lineTo(izq, sup - rs)
    if rs:
        p.curveTo(izq, sup - rs * k, izq + rs * k, sup, izq + rs, sup)
    p.close()
    c.setFillColor(relleno)
    if borde:
        c.setStrokeColor(borde)
        c.setLineWidth(S)
    c.drawPath(p, stroke=1 if borde else 0, fill=1)


def _linea(c, x1, y1, x2, y2, color, grosor=1):
    c.setStrokeColor(color)
    c.setLineWidth(grosor * S)
    c.line(X(x1), Y(y1), X(x2), Y(y2))


def _circulo(c, cx, cy, r, color):
    c.setFillColor(color)
    c.circle(X(cx), Y(cy), r * S, stroke=0, fill=1)


def _hoja(c, base, punta, ancho, color, alfa, curva=0.0):
    """Hoja decorativa con nervadura, de `base` a `punta`."""
    (bx, by), (tx, ty) = base, punta
    dx, dy = tx - bx, ty - by
    largo = hypot(dx, dy)
    nx, ny = -dy / largo, dx / largo

    def pt(t, desvio):
        arco = curva * largo * 4 * t * (1 - t)
        return bx + dx * t + nx * (desvio + arco), by + dy * t + ny * (desvio + arco)

    c.saveState()
    c.setFillAlpha(alfa)
    p = c.beginPath()
    p.moveTo(*P(pt(0, 0)))
    p.curveTo(*P(pt(0.25, ancho)), *P(pt(0.7, ancho * 0.8)), *P(pt(1, 0)))
    p.curveTo(*P(pt(0.7, -ancho * 0.8)), *P(pt(0.25, -ancho)), *P(pt(0, 0)))
    p.close()
    c.setFillColor(color)
    c.drawPath(p, stroke=0, fill=1)

    c.setStrokeColor(FONDO)
    c.setStrokeAlpha(0.35)
    c.setLineWidth(1.4 * S)
    nervio = c.beginPath()
    nervio.moveTo(*P(pt(0.02, 0)))
    nervio.curveTo(*P(pt(0.35, 0)), *P(pt(0.7, 0)), *P(pt(0.97, 0)))
    c.drawPath(nervio, stroke=1, fill=0)
    c.setLineWidth(0.8 * S)
    for t in (0.18, 0.3, 0.42, 0.54, 0.66, 0.78):
        lado = 0.62 * ancho * (1 - abs(t - 0.4))
        for signo in (1, -1):
            v = c.beginPath()
            v.moveTo(*P(pt(t, 0)))
            v.curveTo(*P(pt(t + 0.04, signo * lado * 0.5)), *P(pt(t + 0.08, signo * lado * 0.8)),
                      *P(pt(t + 0.12, signo * lado)))
            c.drawPath(v, stroke=1, fill=0)
    c.restoreState()


# --------------------------------------------------------------------------
# Partes de la página
# --------------------------------------------------------------------------

def _hojas(c):
    # Grandes y pálidas arriba; más oscuras y definidas abajo, como en el modelo.
    _hoja(c, (-60, 760), (40, 180), 150, HexColor("#D9D5C8"), 0.55, curva=0.05)
    _hoja(c, (-90, 830), (110, 470), 150, HexColor("#E0DCD0"), 0.5, curva=-0.04)
    _hoja(c, (-40, 1010), (58, 722), 62, HexColor("#8E957F"), 0.55, curva=0.04)
    _hoja(c, (-50, 1140), (62, 868), 70, HexColor("#7D866D"), 0.62, curva=0.05)
    _hoja(c, (-60, 1300), (66, 1030), 80, HexColor("#6E7860"), 0.7, curva=0.04)
    _hoja(c, (-40, 1440), (120, 1130), 60, HexColor("#959C87"), 0.5, curva=-0.05)
    # La de abajo se queda por encima del pie para no tapar "RM GROUP".
    _hoja(c, (-50, 1380), (172, 1256), 44, HexColor("#606B52"), 0.82, curva=0.05)
    _hoja(c, (-40, 1500), (60, 1330), 40, HexColor("#6E7860"), 0.7, curva=0.04)


def _encabezado(c, numero):
    c.drawImage(ImageReader(str(LOGO)), X(80), Y(230), width=238 * S, height=162 * S, mask="auto")
    _linea(c, 351, 68, 351, 215, LINEA)
    for i, renglon in enumerate(LEMA):
        _texto(c, 383, 140 + 22 * i, renglon, SANS, 11.5, GRIS, esp=3)

    _caja(c, 822, 62, 1052, 125, PILDORA, r=12)
    _texto(c, 1028, 86, "FACTURA N.º", SANS_M, 14, GRIS, "der", esp=2.5)
    _texto(c, 1028, 113, numero, SANS_M, 21, TINTA, "der", esp=1.5)

    tam = 100 * 438 / _ancho("FACTURA", DISPLAY, 100)   # que mida lo mismo que en el modelo
    _texto(c, 1053, 218, "FACTURA", DISPLAY, tam, TINTA, "der")


def _pie(c, pagina, total_paginas):
    _linea(c, 55, 1322, 1049, 1322, LINEA_PIE)
    _texto(c, 108, 1345, PIE_IZQ[0], SANS_B, 16, TINTA, esp=2)
    _texto(c, 108, 1366, PIE_IZQ[1], SANS, 13, GRIS, esp=1.2)
    _texto(c, 1028, 1344, PIE_DER[0], SANS, 13, GRIS, "der", esp=3)
    _texto(c, 1028, 1365, PIE_DER[1], SANS, 13, GRIS, "der", esp=3)
    if total_paginas > 1:
        _texto(c, 580, 1366, f"Página {pagina} de {total_paginas}", SANS, 12, GRIS, "centro")


def _pagina_base(c, numero, pagina, total_paginas):
    c.setFillColor(FONDO)
    c.rect(0, 0, ANCHO_PAG, ALTO_PAG, stroke=0, fill=1)
    _hojas(c)
    _encabezado(c, numero)
    _pie(c, pagina, total_paginas)


def _bandas(c):
    for x1, x2, rotulo in ((55, 540, "EMISOR"), (579, 1049, "CLIENTE")):
        _caja(c, x1, 257, x2, 295, BANDA, r=8)
        _texto(c, x1 + 24, 283, rotulo, SANS_M, 14, GRIS, esp=2.2)
    _linea(c, 563, 262, 563, 520, LINEA)


def _emisor(c):
    _texto(c, 79, 340, EMISOR["nombre"], TITULO, 36, TINTA)
    _icono(c, "ubicacion", 76, 357, 34, ICONO)
    for i, renglon in enumerate(EMISOR["direccion"]):
        tam = _ajustar(renglon, SANS, 15.5, 400)
        _texto(c, 129, 375 + 21.3 * i, renglon, SANS, tam, TEXTO)
    _icono(c, "correo", 77, 452, 32, ICONO)
    _texto(c, 129, 473, EMISOR["email"], SANS, 15.5, TEXTO)
    _icono(c, "telefono", 78, 490, 32, ICONO)
    _texto(c, 129, 517, "  |  ".join(EMISOR["telefonos"]), SANS, 16, ICONO, esp=0.8)


def _cliente(c, cliente):
    nombre = cliente["nombre"]
    _texto(c, 601, 340, nombre, TITULO, _ajustar(nombre, TITULO, 36, 440), TINTA)

    y = 378
    for p in cliente.get("personas", [])[:2]:
        renglon = (p.get("nombre") or "").strip()
        if p.get("cedula"):
            renglon = f"{renglon} | Cédula: {p['cedula']}" if renglon else f"Cédula: {p['cedula']}"
        dibujado = False
        # El nombre ya es el encabezado y no hay cédula: no repetirlo.
        if renglon and renglon != nombre:
            _icono(c, "persona", 603, y - 22, 27, ICONO)
            _texto(c, 656, y, renglon, SERIF, _ajustar(renglon, SERIF, 16.5, 390), TEXTO)
            y += 25
            dibujado = True
        if p.get("telefono"):
            _icono(c, "telefono", 603, y - 19, 25, ICONO)
            _texto(c, 658, y, p["telefono"], SERIF, 16.5, TEXTO)
            y += 25
            dibujado = True
        if dibujado:
            y += 16

    if cliente.get("ubicacion"):
        y += 3
        _icono(c, "ubicacion", 601, y - 28, 34, ICONO)
        texto = cliente["ubicacion"]
        _texto(c, 656, y, texto, SERIF, _ajustar(texto, SERIF, 16.5, 390), TEXTO)


def _fechas(c, f):
    _caja(c, 55, 553, 1049, 648, CAJA, r=12)
    _linea(c, 362, 570, 362, 632, LINEA)
    _linea(c, 743, 570, 743, 632, LINEA)

    columnas = [
        (79, "FECHA DE EMISIÓN", "calendario", fecha_larga(date.fromisoformat(f["fecha_emision"])), 230),
        (391, "FECHA DE ENTREGA", "calendario",
         fecha_larga(date.fromisoformat(f["fecha_entrega"]), con_dia=True), 295),
        (776, "CONDICIÓN DE PAGO", "tarjeta", f["condicion_pago"], 215),
    ]
    for x, rotulo, icono, valor, maximo in columnas:
        _texto(c, x, 586, rotulo, SANS_B, 13.5, TEXTO, esp=1.8)
        if icono == "calendario":
            _icono(c, icono, x - 3, 599, 34, ICONO)
            xv = x + 49
        else:
            _icono(c, icono, x - 3, 595, 40, ICONO)
            xv = x + 52
        _texto(c, xv, 621, valor, SERIF, _ajustar(valor, SERIF, 17.5, maximo), TEXTO)


def _marca_agua(c):
    """El monograma RM, casi transparente, detrás del cliente y la tabla."""
    logo = Image.open(LOGO)
    rm = logo.crop((0, 0, logo.width, int(logo.height * 0.71)))
    ancho = 555
    alto = ancho * rm.height / rm.width
    c.saveState()
    c.setFillAlpha(0.05)
    c.drawImage(ImageReader(rm), X(505), Y(495 + alto), width=ancho * S, height=alto * S, mask="auto")
    c.restoreState()


# ---- Tabla -----------------------------------------------------------------

COL_CANTIDAD = (55, 189)
COL_DESCRIPCION = (189, 657)
COL_PRECIO = (657, 864)
COL_IMPORTE = (864, 1049)
ALTO_CABECERA = 59


def _renglones_fila(fila):
    """(renglones del título, renglones del detalle) ya cortados al ancho."""
    ancho_texto = COL_DESCRIPCION[1] - COL_DESCRIPCION[0] - 45
    titulo = simpleSplit(fila["descripcion"], SERIF_B, 19, ancho_texto)
    detalle = []
    for parrafo in (fila.get("detalle") or "").splitlines():
        detalle += simpleSplit(parrafo, SANS, 15, ancho_texto) if parrafo.strip() else []
    return titulo, detalle


def _alto_fila(fila):
    titulo, detalle = _renglones_fila(fila)
    ultimo = 31 + 25 * (len(titulo) - 1) + (24 + 21 * (len(detalle) - 1) if detalle else 0)
    return max(62, ultimo + 21)


def _cabecera_tabla(c, y):
    _caja(c, 55, y, 1049, y + ALTO_CABECERA, OLIVA, r=12, abajo=False)
    for x in (COL_CANTIDAD[1], COL_DESCRIPCION[1], COL_PRECIO[1]):
        _linea(c, x, y, x, y + ALTO_CABECERA, OLIVA_LINEA)

    def centro(col):
        return (col[0] + col[1]) / 2

    _texto(c, centro(COL_CANTIDAD), y + 35, "CANTIDAD", SANS_M, 13.5, CREMA, "centro", esp=1.8)
    _texto(c, centro(COL_DESCRIPCION), y + 35, "DESCRIPCIÓN", SANS_M, 13.5, CREMA, "centro", esp=1.8)
    for col, rotulo in ((COL_PRECIO, "PRECIO UNITARIO"), (COL_IMPORTE, "IMPORTE")):
        _texto(c, centro(col), y + 28, rotulo, SANS_M, 13.5, CREMA, "centro", esp=1.8)
        _texto(c, centro(col), y + 48, "(RD$)", SANS_M, 13.5, CREMA, "centro", esp=1.8)


def _cuerpo_tabla(c, y, filas):
    """Dibuja las filas [(fila, alto)] desde `y`; devuelve dónde termina."""
    fin = y + sum(h for _, h in filas)
    _caja(c, 55, y, 1049, fin, CUERPO_TABLA, r=12, arriba=False, borde=LINEA)
    for x in (COL_CANTIDAD[1], COL_DESCRIPCION[1], COL_PRECIO[1]):
        _linea(c, x, y, x, fin, LINEA)

    for i, (fila, h) in enumerate(filas):
        if i:
            _linea(c, 55, y, 1049, y, LINEA)
        titulo, detalle = _renglones_fila(fila)
        medio = y + h / 2

        if detalle or len(titulo) > 1:
            base = y + 31
        else:
            base = medio + 6
        for renglon in titulo:
            _texto(c, 214, base, renglon, SERIF_B, 19, TINTA)
            base += 25
        base -= 1   # el detalle arranca 24 px bajo el último renglón del título
        for renglon in detalle:
            _texto(c, 214, base, renglon, SANS, 15, TEXTO)
            base += 21

        _texto(c, 122, medio + 6, cantidad(fila["cantidad"]), SERIF_B, 20, TINTA, "centro")
        _texto(c, 760, medio + 5, monto(float(fila["precio"])), SANS, 17, TEXTO, "centro")
        valor = monto(importe(fila))
        tam = _ajustar(valor, SERIF_B, 18.5, COL_IMPORTE[1] - COL_IMPORTE[0] - 24)
        _texto(c, 963, medio + 6, valor, SERIF_B, tam, TINTA, "centro")
        y += h
    return fin


# ---- Bloque final: banco, totales, emisión digital -------------------------

def _alto_bloque_final(con_transporte):
    filas = 2 if con_transporte else 1
    return max(278, 8 + 38 * filas + 66 + 14 + 183)


def _bloque_final(c, b, subtotal, transporte, total):
    # Datos bancarios
    _caja(c, 55, b, 533, b + 278, CAJA, r=12)
    _circulo(c, 106, b + 42, 26, OLIVA)
    _icono(c, "banco", 92, b + 28, 28, CREMA)
    _texto(c, 148, b + 35, "DATOS BANCARIOS", SANS_M, 14.5, TEXTO, esp=2.2)
    _texto(c, 148, b + 59, "PARA TRANSFERENCIAS", SANS_M, 14.5, TEXTO, esp=2.2)
    for i, (rotulo, valor) in enumerate(BANCO):
        yb = b + 100 + 25.5 * i
        _texto(c, 80, yb, rotulo, SANS_B, 14, TEXTO)
        _texto(c, 277, yb, valor, SANS, _ajustar(valor, SANS, 14, 240), TEXTO)

    # Subtotal y transporte
    renglones = [("Subtotal", subtotal)] + ([("Transporte / Flete", transporte)] if transporte else [])
    barra = b + 8 + 38 * len(renglones)
    _caja(c, 564, b, 1049, barra + 12, CAJA_TOTALES, r=12)
    _linea(c, 868, b + 8, 868, barra - 6, LINEA)
    for i, (rotulo, valor) in enumerate(renglones):
        yb = b + 29 + 38 * i
        if i:
            _linea(c, 575, yb - 24, 1027, yb - 24, LINEA)
        _texto(c, 586, yb, rotulo, SERIF, 17, TEXTO)
        _texto(c, 888, yb, "RD$", SERIF, 17, TEXTO)
        _texto(c, 1017, yb, monto(valor), SERIF, 17, TEXTO, "der")

    # TOTAL
    _caja(c, 560, barra, 1051, barra + 66, OLIVA, r=12)
    _texto(c, 586, barra + 43, "TOTAL", SERIF, 25, CREMA, esp=0.5)
    valor = f"RD$ {monto(total)}"
    _texto(c, 1026, barra + 44, valor, SERIF_B, _ajustar(valor, SERIF_B, 28, 300), CREMA, "der")

    # Emisión digital y firmas
    e = barra + 66 + 14
    _caja(c, 564, e, 1049, e + 183, CAJA, r=12)
    _circulo(c, 614, e + 38, 28, OLIVA)
    _icono(c, "documento", 599, e + 23, 30, CREMA)
    _texto(c, 659, e + 27, "EMISIÓN DIGITAL", SANS_B, 14, TEXTO, esp=2)
    _texto(c, 659, e + 50, "Esta factura ha sido emitida y enviada de forma digital", SANS, 14.5, TEXTO)
    x = 659 + _texto(c, 659, e + 71, "por ", SANS, 14.5, TEXTO)
    x += _texto(c, x, e + 71, "RM Group", SANS_B, 14.5, TINTA)
    _texto(c, x, e + 71, ".", SANS, 14.5, TEXTO)
    _linea(c, 585, e + 93, 1028, e + 93, LINEA)
    _linea(c, 812, e + 111, 812, e + 167, LINEA)
    for cx, (nombre, cargo) in zip((690, 926), FIRMAS):
        _texto(c, cx, e + 129, nombre, SERIF_B, 17.5, TINTA, "centro")
        _texto(c, cx, e + 154, cargo, SANS, 14, TEXTO, "centro")


# --------------------------------------------------------------------------
# Factura completa
# --------------------------------------------------------------------------

def filas_tabla(f):
    """Líneas de productos más la de transporte, si la hay."""
    filas = list(f["lineas"])
    if float(f.get("transporte") or 0) > 0:
        filas.append({
            "cantidad": 1,
            "descripcion": TRANSPORTE_DESCRIPCION,
            "detalle": transporte_detalle(f["cliente"]["nombre"]),
            "precio": float(f["transporte"]),
        })
    return filas


def generar_pdf(f):
    """Devuelve el PDF (bytes) de la factura.

    `f` = {numero, fecha_emision, fecha_entrega (ISO), condicion_pago,
           cliente: {nombre, personas: [{nombre, cedula, telefono}], ubicacion},
           lineas: [{cantidad, descripcion, detalle, precio}], transporte}
    """
    _registrar_fuentes()
    transporte = round(float(f.get("transporte") or 0), 2)
    subtotal, total = totales(f["lineas"], transporte)

    # Reparto de filas por página: si la tabla no cabe, sigue en la siguiente
    # con la cabecera repetida.
    paginas = [[]]
    y = 664 + ALTO_CABECERA
    for fila in filas_tabla(f):
        h = _alto_fila(fila)
        if paginas[-1] and y + h > LIMITE_CONTENIDO:
            paginas.append([])
            y = TOPE_CONTINUACION + ALTO_CABECERA
        paginas[-1].append((fila, h))
        y += h

    # Totales y firmas en su sitio del modelo, o más abajo si la tabla es larga;
    # si no caben, van en una página aparte.
    bloque = max(937, y + 18)
    bloque_aparte = bloque + _alto_bloque_final(transporte > 0) > LIMITE_CONTENIDO
    total_paginas = len(paginas) + bloque_aparte

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"Factura {f['numero']}")
    c.setAuthor(EMISOR["nombre"])
    c.setSubject(f"Factura {f['numero']} — {f['cliente']['nombre']}")

    for i, filas in enumerate(paginas, start=1):
        if i > 1:
            c.showPage()
        _pagina_base(c, f["numero"], i, total_paginas)
        if i == 1:
            _bandas(c)
            _emisor(c)
            _cliente(c, f["cliente"])
            _fechas(c, f)
            tope = 664
        else:
            tope = TOPE_CONTINUACION
        _cabecera_tabla(c, tope)
        fin = _cuerpo_tabla(c, tope + ALTO_CABECERA, filas)
        if i == 1:
            _marca_agua(c)

    if bloque_aparte:
        c.showPage()
        _pagina_base(c, f["numero"], total_paginas, total_paginas)
        bloque = TOPE_CONTINUACION
    else:
        bloque = max(937, fin + 18)
    _bloque_final(c, bloque, subtotal, transporte, total)

    c.save()
    return buf.getvalue()


def paginas_png(pdf, escala=1.5):
    """Imágenes PNG de cada página, para la vista previa."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    imagenes = []
    for pagina in doc:
        img = pagina.render(scale=escala).to_pil()
        salida = io.BytesIO()
        img.save(salida, format="PNG")
        imagenes.append(salida.getvalue())
    doc.close()
    return imagenes
