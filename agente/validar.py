"""Valida tesis_auto.json antes de publicar. Uso: python agente/validar.py  (sale con código 1 si hay errores)."""
import json
import sys
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "tesis_auto.json"
SECTORES = {"ia", "salud", "defensa", "energia", "seguros", "commodities", "consumo", "industria", "finanzas", "otros"}
ESTADOS = {"nueva", "actualizada", "sin_cambios", "vigilancia", "descartada"}
VEREDICTOS = {"Interesante", "Vigilar", "No convence"}
OBLIGATORIOS = {
    "id": str, "ticker": str, "empresa": str, "sector": str, "estado": str, "veredicto": str,
    "conviccion": int, "fecha_creacion": str, "fecha_actualizacion": str, "resumen": str,
    "negocio": str, "pros": list, "contras": list, "competencia": dict, "catalizadores": list,
    "riesgos": list, "valoracion": dict, "vs_divulgadores": str, "que_cambiaria_mi_opinion": str,
    "relacion_cartera": str, "fuentes": list, "historial": list,
}


def validar(datos: dict) -> list[str]:
    err = []
    if not isinstance(datos.get("actualizado"), str):
        err.append("falta 'actualizado' (fecha AAAA-MM-DD)")
    tesis = datos.get("tesis")
    if not isinstance(tesis, list):
        return err + ["'tesis' debe ser una lista"]
    ids = set()
    for i, t in enumerate(tesis):
        q = f"tesis[{i}] ({t.get('ticker', '?')})"
        for campo, tipo in OBLIGATORIOS.items():
            if not isinstance(t.get(campo), tipo):
                err.append(f"{q}: '{campo}' falta o no es {tipo.__name__}")
        if t.get("id") in ids:
            err.append(f"{q}: id duplicado")
        ids.add(t.get("id"))
        if t.get("sector") not in SECTORES:
            err.append(f"{q}: sector '{t.get('sector')}' no válido")
        if t.get("estado") not in ESTADOS:
            err.append(f"{q}: estado '{t.get('estado')}' no válido")
        if t.get("veredicto") not in VEREDICTOS:
            err.append(f"{q}: veredicto '{t.get('veredicto')}' no válido")
        if isinstance(t.get("conviccion"), int) and not 1 <= t["conviccion"] <= 5:
            err.append(f"{q}: conviccion fuera de 1-5")
        if isinstance(t.get("pros"), list) and len(t["pros"]) < 2:
            err.append(f"{q}: menos de 2 pros")
        if isinstance(t.get("contras"), list) and len(t["contras"]) < 2:
            err.append(f"{q}: menos de 2 contras (la tesis debe ser crítica)")
        if isinstance(t.get("fuentes"), list):
            if not t["fuentes"]:
                err.append(f"{q}: sin fuentes")
            for f in t["fuentes"]:
                if not str(f.get("url", "")).startswith("http"):
                    err.append(f"{q}: fuente sin url válida")
    return err


if __name__ == "__main__":
    try:
        datos = json.loads(RUTA.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"JSON inválido: {exc}")
        sys.exit(1)
    errores = validar(datos)
    for e in errores:
        print("ERROR:", e)
    print(f"{len(datos.get('tesis', []))} tesis, {len(errores)} errores")
    sys.exit(1 if errores else 0)
