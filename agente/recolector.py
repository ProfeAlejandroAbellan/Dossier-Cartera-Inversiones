"""Recolector semanal de vídeos de divulgadores de inversión.

Se ejecuta en GitHub Actions. Para cada canal de canales.json:
  1. resuelve el channel_id si falta,
  2. lee el feed RSS público del canal,
  3. descarta Shorts, vídeos antiguos y ya vistos,
  4. descarga la transcripción y la deja en agente/bandeja/ para el analista.

No usa ninguna API de pago. El análisis lo hace después la tarea programada de Claude.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
CANALES = BASE / "canales.json"
VISTOS = BASE / "vistos.json"
BANDEJA = BASE / "bandeja"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "es-ES,es;q=0.9"}
NS = {"a": "http://www.w3.org/2005/Atom",
      "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
IDIOMAS = ["es", "es-ES", "es-419", "en"]


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def resolver_channel_id(url: str) -> str | None:
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    if m:
        return m.group(1)
    html = requests.get(url, headers=UA, timeout=30).text
    for patron in (r'"externalId":"(UC[\w-]{22})"',
                   r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
                   r'"channelId":"(UC[\w-]{22})"'):
        m = re.search(patron, html)
        if m:
            return m.group(1)
    return None


def parsear_feed(xml_text: str) -> list[dict]:
    raiz = ET.fromstring(xml_text)
    videos = []
    for e in raiz.findall("a:entry", NS):
        enlace = e.find("a:link", NS).get("href", "")
        desc = e.find("media:group/media:description", NS)
        videos.append({
            "id": e.find("yt:videoId", NS).text,
            "titulo": e.find("a:title", NS).text or "",
            "publicado": e.find("a:published", NS).text,
            "url": enlace,
            "descripcion": (desc.text or "") if desc is not None else "",
            "es_short": "/shorts/" in enlace,
        })
    return videos


def api_transcripciones():
    from youtube_transcript_api import YouTubeTranscriptApi
    usuario, clave = os.getenv("WEBSHARE_USER"), os.getenv("WEBSHARE_PASS")
    if usuario and clave:  # proxy residencial opcional si YouTube bloquea a GitHub
        from youtube_transcript_api.proxies import WebshareProxyConfig
        return YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(proxy_username=usuario, proxy_password=clave))
    return YouTubeTranscriptApi()


def transcribir(api, video_id: str) -> tuple[str | None, str | None]:
    try:
        trozos = api.fetch(video_id, languages=IDIOMAS)
        texto = " ".join(t.text.replace("\n", " ") for t in trozos)
        return re.sub(r"\s+", " ", texto).strip(), None
    except Exception as exc:  # bloqueos, vídeo sin subtítulos, directo en curso...
        return None, f"{type(exc).__name__}: {str(exc)[:300]}"


def main(api=None, obtener=None) -> int:
    cfg = json.loads(CANALES.read_text(encoding="utf-8"))
    vistos = json.loads(VISTOS.read_text(encoding="utf-8")) if VISTOS.exists() else {}
    limite = datetime.now(timezone.utc) - timedelta(days=cfg.get("dias_atras", 10))
    max_canal = cfg.get("max_videos_por_canal", 6)
    obtener = obtener or (lambda u: requests.get(u, headers=UA, timeout=30))
    api = api or api_transcripciones()
    BANDEJA.mkdir(exist_ok=True)
    nuevos = fallos = 0
    cfg_cambiada = False

    for canal in cfg["canales"]:
        nombre = canal["nombre"]
        if not canal.get("channel_id"):
            if not canal.get("url"):
                print(f"[aviso] {nombre}: sin url ni channel_id, se salta")
                continue
            cid = resolver_channel_id(canal["url"])
            if not cid:
                print(f"[error] {nombre}: no se pudo resolver el channel_id de {canal['url']}")
                continue
            canal["channel_id"] = cid
            cfg_cambiada = True
        r = obtener(f"https://www.youtube.com/feeds/videos.xml?channel_id={canal['channel_id']}")
        if r.status_code != 200:
            print(f"[error] {nombre}: feed devolvió {r.status_code}")
            continue
        candidatos = [v for v in parsear_feed(r.text)
                      if not v["es_short"]
                      # se reintentan los que fallaron al transcribir mientras sigan dentro de la ventana
                      and vistos.get(v["id"], {}).get("estado", "sin_transcripcion") == "sin_transcripcion"
                      and datetime.fromisoformat(v["publicado"]) >= limite]
        for v in candidatos[:max_canal]:
            texto, error = transcribir(api, v["id"])
            fecha = v["publicado"][:10]
            registro = {**v, "canal": nombre, "transcripcion": texto, "error_transcripcion": error,
                        "recogido": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            registro.pop("es_short")
            (BANDEJA / f"{fecha}_{slug(nombre)}_{v['id']}.json").write_text(
                json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")
            vistos[v["id"]] = {"canal": nombre, "titulo": v["titulo"], "fecha": fecha,
                               "estado": "en_bandeja" if texto else "sin_transcripcion"}
            nuevos += 1
            fallos += error is not None
            print(f"[ok] {nombre}: {v['titulo'][:70]}" + (f"  (sin transcripción: {error[:80]})" if error else ""))

    VISTOS.write_text(json.dumps(vistos, ensure_ascii=False, indent=1), encoding="utf-8")
    if cfg_cambiada:
        CANALES.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resumen: {nuevos} vídeos nuevos, {fallos} sin transcripción")
    # Si TODO falla al transcribir, casi seguro es un bloqueo de YouTube a GitHub: que el workflow lo marque en rojo
    return 1 if nuevos and fallos == nuevos else 0


if __name__ == "__main__":
    sys.exit(main())
