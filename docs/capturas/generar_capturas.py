#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera las capturas de pantalla de los manuales.

Cada captura corre en su PROPIO proceso para no mezclar raíces de Tk: el
script, invocado con ``--shot NOMBRE``, arma la ventana de esa captura, la
muestra en el display y la guarda con ImageMagick ``import`` (captura por id de
ventana). Sin ``--shot`` recorre todas lanzándose a sí mismo por subproceso.

Uso:
    .venv/bin/python docs/capturas/generar_capturas.py            # todas
    .venv/bin/python docs/capturas/generar_capturas.py --lista    # nombres
    .venv/bin/python docs/capturas/generar_capturas.py --shot solicitud

Necesita un display X real (DISPLAY). Los datos de demostración se escriben en
docs/capturas/demo/ (chico y reproducible) y las imágenes en docs/img/.

No forma parte del flujo de la app: es una herramienta de documentación.
"""
import csv
import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(SCRIPT_DIR))
IMG = os.path.join(REPO, "docs", "img")
DEMO = os.path.join(SCRIPT_DIR, "demo")

sys.path.insert(0, REPO)

# ---------------------------------------------------------------------------
# Datos de demostración
# ---------------------------------------------------------------------------
EVENTOS = [
    {"id_evento": "csn_sc62026rlgry", "id_origen": "Origin/20260906004245.000",
     "ot_utc": "2026-09-06 00:42:45", "magnitud": "2.2",
     "tipo_magnitud": "MLv", "fases": "68", "rms": "0.31", "azgap": "48",
     "latitud": "-33.420", "longitud": "-70.592", "profundidad_km": "92.0",
     "agencia": "SNC", "operador": "tark",
     "region": "Chile-Argentina Border Region", "estatus": "confirmed",
     "base_datos": "seiscomp"},
    {"id_evento": "csn_sc62026rwzup", "id_origen": "Origin/20260910150600.000",
     "ot_utc": "2026-09-10 15:06:00", "magnitud": "3.1",
     "tipo_magnitud": "Mlv", "fases": "41", "rms": "0.44", "azgap": "77",
     "latitud": "-32.980", "longitud": "-71.540", "profundidad_km": "38.0",
     "agencia": "SNC", "operador": "eatl", "region": "Valparaiso",
     "estatus": "confirmed", "base_datos": "seiscomp"},
    {"id_evento": "csn_sc62026sfwfj", "id_origen": "Origin/20260917071321.000",
     "ot_utc": "2026-09-17 07:13:21", "magnitud": "1.0",
     "tipo_magnitud": "M", "fases": "9", "rms": "0.52", "azgap": "132",
     "latitud": "-34.110", "longitud": "-70.310", "profundidad_km": "52.5",
     "agencia": "SNC", "operador": "tark", "region": "Libertador Gral B O'Higgins",
     "estatus": "confirmed", "base_datos": "seiscomp"},
    {"id_evento": "csn_sc62026siwik", "id_origen": "Origin/20260918224006.000",
     "ot_utc": "2026-09-18 22:40:06", "magnitud": "4.4",
     "tipo_magnitud": "Mww", "fases": "96", "rms": "0.61", "azgap": "39",
     "latitud": "-30.550", "longitud": "-71.250", "profundidad_km": "47.0",
     "agencia": "SNC", "operador": "mdur", "region": "Coquimbo",
     "estatus": "confirmed", "base_datos": "seiscomp"},
    {"id_evento": "csn_sc62026sssyt", "id_origen": "Origin/20260924081830.000",
     "ot_utc": "2026-09-24 08:18:30", "magnitud": "3.7",
     "tipo_magnitud": "Mlv", "fases": "55", "rms": "0.49", "azgap": "61",
     "latitud": "-33.640", "longitud": "-72.010", "profundidad_km": "21.0",
     "agencia": "SNC", "operador": "cris", "region": "Off Coast of Valparaiso",
     "estatus": "confirmed", "base_datos": "seiscomp"},
    {"id_evento": "csn_sc62026rtrgc", "id_origen": "Origin/20260910150600.001",
     "ot_utc": "2026-09-28 11:02:19", "magnitud": "2.6",
     "tipo_magnitud": "Mlv", "fases": "23", "rms": "0.38", "azgap": "88",
     "latitud": "-33.360", "longitud": "-70.980", "profundidad_km": "76.0",
     "agencia": "SNC", "operador": "eatl", "region": "Region Metropolitana",
     "estatus": "confirmed", "base_datos": "seiscomp"},
]

_EST = {
    "R08M": ("C1", "R08M", "-33.30", "-70.60", "1180", "Recoleta",
             "Chile"),
    "V14A": ("C1", "V14A", "-33.10", "-70.72", "760", "Colina", "Chile"),
    "STL": ("C", "STL", "-33.39", "-70.62", "820", "Santiago", "Chile"),
    "MT07": ("C1", "MT07", "-33.55", "-70.73", "640", "San Bernardo",
             "Chile"),
    "PEL": ("G", "PEL", "-33.15", "-70.51", "2300", "Farellones", "Chile"),
    "IN47": ("C1", "IN47", "-33.47", "-70.60", "600", "Nunoa", "Chile"),
    "R02M": ("C1", "R02M", "-33.47", "-70.60", "620", "Nunoa", "Chile"),
    "VA03": ("C1", "VA03", "-33.02", "-71.64", "90", "Valparaiso", "Chile"),
}

FASES = []
for i, est in enumerate(("R08M", "V14A", "STL", "MT07", "PEL", "IN47")):
    red, nom, lat, lon, elev, lugar, pais = _EST[est]
    manual = i in (0, 2)
    FASES.append({
        "id_evento": EVENTOS[0]["id_evento"],
        "id_origen": EVENTOS[0]["id_origen"], "id_pick": "Pick/%s" % est,
        "red": red, "estacion": nom, "loc": "", "cha": "HHZ",
        "fase": "P" if i % 2 == 0 else "S",
        "llegada_utc": "2026-09-06 00:42:%02d" % (50 + i),
        "llegada_us": "0", "correccion_s": "0.4", "residual_s": "0.28",
        "azimut": str(30 * i + 10), "distancia": "0.3",
        "usada": "true" if i < 4 else "false", "peso": "1.0",
        "polaridad": "positive", "snr": "12.5",
        "modo_pick": "manual" if manual else "automatic",
        "pick_autor": ("mary" if manual else "scautopic@localhost"),
        "pick_agencia": "CSN", "pick_metodo": "" if manual else "AIC",
        "mag_estacion": "2.3", "tipo_mag_estacion": "MLv",
        "tiene_magnitud": "Si", "mag_est_residuo": "0.1",
        "qc_estacion": "aprobado", "est_lat": lat, "est_lon": lon,
        "est_elev": elev, "est_lugar": lugar, "est_pais": pais,
        "base_datos": "seiscomp"})

NO_PICADAS = [
    (EVENTOS[0], "C", "STL", "5.2", "0", "820", "Santiago"),
    (EVENTOS[0], "C1", "IN47", "8.5", "0", "600", "Nunoa"),
    (EVENTOS[0], "C1", "R02M", "8.6", "0", "620", "Nunoa"),
    (EVENTOS[0], "C1", "V14A", "12.0", "3", "760", "Colina"),
    (EVENTOS[0], "G", "PEL", "31.7", "0", "2300", "Farellones"),
    (EVENTOS[0], "C1", "R08M", "49.0", "2", "1180", "Recoleta"),
    (EVENTOS[0], "C1", "VA03", "96.0", "0", "90", "Valparaiso"),
    (EVENTOS[1], "C1", "V14A", "22.5", "1", "760", "Colina"),
    (EVENTOS[1], "C", "STL", "45.5", "0", "820", "Santiago"),
    (EVENTOS[2], "C1", "R02M", "11.9", "0", "620", "Nunoa"),
    (EVENTOS[2], "C1", "MT07", "26.6", "2", "640", "San Bernardo"),
]


def _fila_no_picada(evento, red, est, dist, act, elev, lugar):
    return {"id_evento": evento["id_evento"], "id_origen": evento["id_origen"],
            "red": red, "estacion": est, "loc_ref": "", "cha_ref": "BHZ",
            "streams_vigentes": "1", "distancia_km": dist,
            "est_lat": "", "est_lon": "", "est_elev": elev,
            "est_lugar": lugar, "est_pais": "Chile", "radio_km": "400.0",
            "actividad_ventana": act, "waveform_status": "NO_CONSULTADO",
            "availability_source": "", "cobertura_desde": "",
            "cobertura_hasta": ""}


def _escribir_csv(ruta, filas, cabecera):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cabecera)
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in cabecera})


def _preparar_demo():
    """Escribe los CSV, JSON e informes de demostración (idempotente)."""
    import exporta_ventana_seiscomp as ex
    os.makedirs(DEMO, exist_ok=True)
    for sub in ("datos", "informes", "ploteo", "trabajo", "descargas"):
        os.makedirs(os.path.join(DEMO, sub), exist_ok=True)

    base = os.path.join(DEMO, "datos",
                        "seiscomp_20260901000000_20260930235959.csv")
    _escribir_csv(base, EVENTOS, ex.CABECERA)
    _escribir_csv(base[:-4] + "_fases.csv", FASES, ex.CABECERA_FASES)
    npc = [_fila_no_picada(*f) for f in NO_PICADAS]
    _escribir_csv(base[:-4] + "_no_picadas.csv", npc, ex.CABECERA_NO_PICADAS)

    # No actualizados (atribución): una fila por cruce.
    _escribir_csv(
        os.path.join(DEMO, "datos", "atribucion_seiscomp.csv"),
        [{"fecha_local": "2026-09-06 00:42:45", "lat_local": "-33.420",
          "lon_local": "-70.592", "prof_local": "92.0", "mag_local": "2.2",
          "tipo_mag_local": "Mlv", "lat_eventquery": "-33.451",
          "lon_eventquery": "-70.610", "prof_eventquery": "88.0",
          "mag_eventquery": "2.4", "tipo_mag_eventquery": "ML",
          "analista": "tark", "dt_seg": "2.10", "dlat": "0.031",
          "dlon": "0.018"},
         {"fecha_local": "2026-09-18 22:40:06", "lat_local": "-30.550",
          "lon_local": "-71.250", "prof_local": "47.0", "mag_local": "4.4",
          "tipo_mag_local": "Mww", "lat_eventquery": "-30.562",
          "lon_eventquery": "-71.244", "prof_eventquery": "47.0",
          "mag_eventquery": "4.5", "tipo_mag_eventquery": "Mww",
          "analista": "mdur", "dt_seg": "0.80", "dlat": "0.012",
          "dlon": "0.006"},
         {"fecha_local": "2026-09-24 08:18:30", "lat_local": "-33.640",
          "lon_local": "-72.010", "prof_local": "21.0", "mag_local": "3.7",
          "tipo_mag_local": "Mlv", "lat_eventquery": "-33.600",
          "lon_eventquery": "-72.070", "prof_eventquery": "18.0",
          "mag_eventquery": "3.9", "tipo_mag_eventquery": "Mlv",
          "analista": "cris", "dt_seg": "4.30", "dlat": "0.040",
          "dlon": "0.060"}],
        ["fecha_local", "lat_local", "lon_local", "prof_local", "mag_local",
         "tipo_mag_local", "lat_eventquery", "lon_eventquery",
         "prof_eventquery", "mag_eventquery", "tipo_mag_eventquery",
         "analista", "dt_seg", "dlat", "dlon"])

    # No publicados (estricto).
    cab_np = ["Fecha_Hora", "Latitud", "Longitud", "Prof.", "Mag.", "Tipo_mag.",
              "Analista"]
    _escribir_csv(os.path.join(DEMO, "datos",
                               "no_pub_desde_2_5_estricto.csv"),
                  [{"Fecha_Hora": "2026-09-12 04:11:03", "Latitud": "-31.220",
                    "Longitud": "-71.410", "Prof.": "35.0", "Mag.": "2.9",
                    "Tipo_mag.": "Mlv", "Analista": "eatl"},
                   {"Fecha_Hora": "2026-09-21 19:45:52", "Latitud": "-34.880",
                    "Longitud": "-71.030", "Prof.": "61.0", "Mag.": "2.7",
                    "Tipo_mag.": "Mlv", "Analista": "mdur"}], cab_np)
    _escribir_csv(os.path.join(DEMO, "datos",
                               "no_pub_desde_2_5_seiscomp_estricto.csv"),
                  [{"Fecha_Hora": "2026-09-12 04:11:03", "Latitud": "-31.220",
                    "Longitud": "-71.410", "Prof.": "35.0", "Mag.": "2.9",
                    "Tipo_mag.": "Mlv", "Analista": "eatl"}], cab_np)

    # Informes de repetidos (para «Ver repetidos»).
    rep = ("# Publicados repetidos (estricto)\n"
           "2026-09-06 00:42:31  -33.410 -70.580  2.3  csn_sc62026rlgry\n"
           "2026-09-06 00:42:45  -33.420 -70.592  2.2  csn_sc62026rtrgc\n"
           "2026-09-17 07:13:10  -34.100 -70.300  1.1  csn_sc62026sfwfj\n")
    for nombre in ("rep_publica_amplio", "rep_publica_estricto",
                   "rep_seisan_amplio", "rep_seisan_estricto"):
        with open(os.path.join(DEMO, "informes", nombre + ".txt"), "w") as f:
            f.write(rep)

    # JSON del panel de análisis (formato de generajson.py).
    eventos_json = []
    for i, ev in enumerate(EVENTOS):
        eventos_json.append({
            "id": ev["id_evento"], "fecha hora": ev["ot_utc"],
            "latitud": float(ev["latitud"]), "longitud": float(ev["longitud"]),
            "prof": float(ev["profundidad_km"]), "magnitud": float(ev["magnitud"]),
            "tipo": ev["tipo_magnitud"],
            "perfil": "P005" if i % 3 else "P006",
            "along_km": 50.0 + 30 * i, "perp_km": 12.0 + i,
            "residuo_km": 5.0 + i, "dist_asoc": 13.0 + i,
            "sospechoso": bool(i % 2), "percibido": "S" if i in (1, 3) else "N",
            "archivo_origen": "demo", "n_fila_origen": i + 1})
    with open(os.path.join(DEMO, "datos", "eventos_eventquery.json"), "w") as f:
        json.dump(eventos_json, f)
    with open(os.path.join(DEMO, "datos", "conteo_perfiles_eventquery.json"),
              "w") as f:
        json.dump({"total": len(eventos_json),
                   "con_perfil": len(eventos_json), "sin_perfil": 0,
                   "conteo": {"P005": 4, "P006": 2}}, f)


# ---------------------------------------------------------------------------
# Captura
# ---------------------------------------------------------------------------
def _capturar(widget, nombre):
    widget.update_idletasks()
    widget.update()
    time.sleep(0.6)
    widget.update()
    destino = os.path.join(IMG, nombre + ".png")
    os.makedirs(IMG, exist_ok=True)
    subprocess.run(["import", "-window", "0x%x" % widget.winfo_id(), destino],
                   check=True)
    print("  -> docs/img/%s.png" % nombre)


def _raiz(titulo="Revisión de eventos sísmicos"):
    import ttkbootstrap as tb
    raiz = tb.Window(themename="flatly")
    raiz.title(titulo)
    return raiz


def _leer(path):
    import revisa_seiscomp as rs
    return rs._leer_csv(path)


def _evento_y_fases():
    base = os.path.join(DEMO, "datos",
                        "seiscomp_20260901000000_20260930235959.csv")
    eventos = _leer(base)
    fases = _leer(base[:-4] + "_fases.csv")
    no_picadas = _leer(base[:-4] + "_no_picadas.csv")
    return eventos, fases, no_picadas, base


# ----- capturas individuales ------------------------------------------------
def shot_solicitud():
    import solicita_catalogos
    app = solicita_catalogos.App()
    _capturar(app.raiz, "01_solicitud")
    try:
        app.raiz.after_cancel(app._after_drenar)
    except Exception:
        pass
    app.raiz.destroy()


def shot_principal():
    import ttkbootstrap as tb
    import app as appmod
    raiz = _raiz()
    inst = appmod.App(raiz, os.path.join(DEMO, "datos", "entrada.csv"),
                      os.path.join(DEMO, "trabajo", "salida.dat"))
    for linea in ("Ventana ajustada a 1180x860 px.",
                  "SeisComp: exportación encontrada para 2026-09.",
                  "Pulse «Procesar catálogos» para generar los paneles."):
        inst.txt.text.configure(state="normal")
        inst.txt.text.insert("end", linea + "\n")
        inst.txt.text.configure(state="disabled")
    _capturar(raiz, "02_principal")
    try:
        raiz.after_cancel(inst._after_drenar)
    except Exception:
        pass
    raiz.destroy()


def shot_catalogo():
    import ttkbootstrap as tb
    import revisa_seiscomp as rs
    eventos, fases, no_picadas, base = _evento_y_fases()
    raiz = _raiz("Catálogo de SeisComp")
    marco = tb.Frame(raiz, padding=6)
    marco.pack(fill="both", expand=True)
    rs.abrir_panel(marco, base, base[:-4] + "_fases.csv",
                   base[:-4] + "_no_picadas.csv", etiqueta_fuente="seiscomp",
                   cwd=DEMO)
    raiz.geometry("1280x640+40+40")
    _capturar(raiz, "03_catalogo_seiscomp")
    raiz.destroy()


def shot_parametros():
    import ttkbootstrap as tb
    import revisa_seiscomp as rs
    eventos, fases, no_picadas, _ = _evento_y_fases()
    raiz = _raiz()
    contenedor = tb.Frame(raiz)
    contenedor.pack(fill="both", expand=True)
    raiz.update()
    ventana = rs._ventana_detalle(contenedor, eventos[0], fases,
                                  etiqueta_fuente="seiscomp",
                                  al_estaciones=lambda: None)
    _capturar(ventana, "04_parametros_evento")
    ventana.destroy()
    raiz.destroy()


def shot_estaciones():
    import ttkbootstrap as tb
    import revisa_seiscomp as rs
    eventos, fases, no_picadas, _ = _evento_y_fases()
    id_evento = eventos[0]["id_evento"]
    no_picadas = [f for f in no_picadas
                  if f.get("id_evento") == id_evento]
    raiz = _raiz()
    contenedor = tb.Frame(raiz)
    contenedor.pack(fill="both", expand=True)
    raiz.update()
    ventana = rs._ventana_estaciones(contenedor, eventos[0], fases, no_picadas,
                                     DEMO, etiqueta_fuente="seiscomp",
                                     hay_no_picadas=True)
    _capturar(ventana, "05_estaciones_con_arribos")
    # Solapa «Sin arribos».
    for w in ventana.winfo_children():
        if type(w).__name__ == "Notebook":
            w.select(w.tabs()[1])
    _capturar(ventana, "06_estaciones_sin_arribos")
    ventana.destroy()
    raiz.destroy()


def shot_analisis():
    import ttkbootstrap as tb
    import revisa_seiscomp as rs
    eventos, fases, no_picadas, base = _evento_y_fases()
    raiz = _raiz()
    contenedor = tb.Frame(raiz)
    contenedor.pack(fill="both", expand=True)
    raiz.update()
    ventana = rs._ventana_analisis_rapido(
        contenedor, base[:-4] + "_no_picadas.csv", eventos, DEMO,
        etiqueta_fuente="seiscomp")
    _capturar(ventana, "07_analisis_contexto")
    for w in ventana.winfo_children():
        if type(w).__name__ == "Notebook":
            w.select(w.tabs()[1])
    _capturar(ventana, "08_analisis_resultados")
    ventana.destroy()
    raiz.destroy()


def shot_no_actualizados():
    import ttkbootstrap as tb
    import revisa_seiscomp as rs
    raiz = _raiz("No actualizados")
    marco = tb.Frame(raiz, padding=6)
    marco.pack(fill="both", expand=True)
    rs.abrir_no_actualizados(marco, "seiscomp", cwd=DEMO)
    raiz.geometry("1460x440+40+40")
    _capturar(raiz, "09_no_actualizados")
    raiz.destroy()


def shot_no_publicados():
    import ttkbootstrap as tb
    import app as appmod
    raiz = _raiz()
    inst = appmod.App(raiz, os.path.join(DEMO, "datos", "entrada.csv"),
                      os.path.join(DEMO, "trabajo", "salida.dat"))
    inst._ver_no_publicados("seiscomp")
    raiz.update()
    for w in raiz.winfo_children():
        if isinstance(w, tb.Toplevel) and "No publicados" in w.title():
            _capturar(w, "10_no_publicados")
    try:
        raiz.after_cancel(inst._after_drenar)
    except Exception:
        pass
    raiz.destroy()


def shot_repetidos():
    import ttkbootstrap as tb
    import app as appmod
    raiz = _raiz()
    inst = appmod.App(raiz, os.path.join(DEMO, "datos", "entrada.csv"),
                      os.path.join(DEMO, "trabajo", "salida.dat"))
    inst._ver_repetidos()
    raiz.update()
    for w in raiz.winfo_children():
        if isinstance(w, tb.Toplevel) and w.title() == "Eventos repetidos":
            _capturar(w, "11_repetidos")
    try:
        raiz.after_cancel(inst._after_drenar)
    except Exception:
        pass
    raiz.destroy()


def shot_plotear():
    import ttkbootstrap as tb
    import plotear
    raiz = _raiz("Panel de análisis")
    marco = tb.Frame(raiz)
    marco.pack(fill="both", expand=True)
    plotear.abrir_panel(marco, os.path.join(DEMO, "datos",
                                            "eventos_eventquery.json"),
                        "eventquery", etiqueta_fuente="eventquery")
    raiz.geometry("1180x700+40+40")
    _capturar(raiz, "12_panel_analisis")
    raiz.destroy()


def shot_plot_evento():
    # Figura planta+perfil de un evento suelto (botón «Ver planta y perfil»).
    # No se crea raíz propia: plotear maneja la suya vía matplotlib TkAgg.
    import matplotlib.pyplot as plt
    import plotear
    # Sin 'id': en el ploteo de un evento suelto no se etiqueta (ver abrir_evento).
    plotear.abrir_evento(
        {"fecha hora": "2026-09-06 00:42:45", "latitud": -33.4,
         "longitud": -70.6, "prof": 92.0, "magnitud": "2.2", "tipo": "MLv",
         "analista": "tark"}, "seisan")
    figura = plt.gcf()
    ventana = figura.canvas.manager.window
    _capturar(ventana, "14_plot_evento")


def shot_comparacion():
    # Comparación local vs publicado (doble clic en un evento no actualizado).
    import matplotlib.pyplot as plt
    import plotear
    plotear.abrir_eventos([
        {"rol": "local", "fecha hora": "2026-09-06 00:42:45",
         "latitud": -33.420, "longitud": -70.592, "prof": 92.0,
         "magnitud": "2.2", "tipo": "Mlv", "analista": "tark"},
        {"rol": "publicado", "fecha hora": "2026-09-06 00:42:45",
         "latitud": -33.451, "longitud": -70.610, "prof": 88.0,
         "magnitud": "2.4", "tipo": "ML"}], "seisan")
    ventana = plt.gcf().canvas.manager.window
    _capturar(ventana, "15_comparacion")


def shot_formato():
    import descargas
    raiz = _raiz()
    raiz.update()

    def _capturar_y_cerrar():
        for w in raiz.winfo_children():
            if (type(w).__name__ == "Toplevel"
                    and w.title() == "Formato de descarga"):
                _capturar(w, "13_formato_descarga")
                w.destroy()

    raiz.after(800, _capturar_y_cerrar)
    descargas.preguntar_formato(raiz)
    raiz.destroy()


SHOTS = [
    ("solicitud", shot_solicitud),
    ("principal", shot_principal),
    ("catalogo", shot_catalogo),
    ("parametros", shot_parametros),
    ("estaciones", shot_estaciones),
    ("analisis", shot_analisis),
    ("no_actualizados", shot_no_actualizados),
    ("no_publicados", shot_no_publicados),
    ("repetidos", shot_repetidos),
    ("plotear", shot_plotear),
    ("plot_evento", shot_plot_evento),
    ("comparacion", shot_comparacion),
    ("formato", shot_formato),
]


def main():
    script = os.path.abspath(__file__)
    _preparar_demo()
    os.chdir(DEMO)

    if "--lista" in sys.argv:
        for nombre, _ in SHOTS:
            print(nombre)
        return
    if "--shot" in sys.argv:
        nombre = sys.argv[sys.argv.index("--shot") + 1]
        dict(SHOTS)[nombre]()
        return
    fallos = []
    for nombre, _ in SHOTS:
        print("== %s ==" % nombre)
        r = subprocess.run([sys.executable, script, "--shot", nombre],
                           cwd=REPO)
        if r.returncode != 0:
            fallos.append(nombre)
    print()
    if fallos:
        print("Fallaron: %s" % ", ".join(fallos))
        sys.exit(1)
    print("Capturas listas en docs/img/.")


if __name__ == "__main__":
    main()
