#!/usr/bin/env python3
"""Roda no GitHub Actions a cada 10 minutos: publica no Instagram o que está agendado e já passou do horário.

Lê agenda.json (escrito por instagram/agendados/sincronizar.py) e grava resultados.json.
Cada postagem é publicada uma única vez: quem já está em resultados.json é ignorado.
Passou mais de JANELA_H horas do horário? Não publica (marca "atrasada") para não postar notícia velha sem aviso.
Chaves: IG_ACCESS_TOKEN e IG_USER_ID (segredos do repositório). Nada sensível é impresso.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
HOST = "https://graph.instagram.com"
VERSAO = "v21.0"
JANELA_H = 3


def api(metodo, url, dados=None):
    corpo = urllib.parse.urlencode(dados).encode() if dados else None
    req = urllib.request.Request(url, data=corpo, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except Exception:
            err = {}
        raise RuntimeError(f"API {err.get('code', e.code)}: {err.get('message', 'erro')}")


def publicar(pasta, legenda, base, token, uid):
    url = f"{base}/{urllib.parse.quote(pasta)}/slide.png"
    raiz = f"{HOST}/{VERSAO}/{uid}"
    cont = api("POST", f"{raiz}/media", {"image_url": url, "caption": legenda, "access_token": token})["id"]
    for _ in range(30):
        st = api("GET", f"{HOST}/{VERSAO}/{cont}?fields=status_code&access_token={token}").get("status_code")
        if st == "FINISHED":
            break
        if st == "ERROR":
            raise RuntimeError("a Meta recusou a imagem (status ERROR)")
        time.sleep(2)
    else:
        raise RuntimeError("tempo esgotado esperando o contêiner")
    return api("POST", f"{raiz}/media_publish", {"creation_id": cont, "access_token": token})["id"]


def main():
    token, uid = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    base = os.environ.get("IG_MEDIA_BASE_URL", "").rstrip("/")
    if not (token and uid and base):
        sys.exit("Faltam IG_ACCESS_TOKEN, IG_USER_ID ou IG_MEDIA_BASE_URL")
    agenda_arq, res_arq = RAIZ / "agenda.json", RAIZ / "resultados.json"
    agenda = json.loads(agenda_arq.read_text()) if agenda_arq.exists() else []
    res = json.loads(res_arq.read_text()) if res_arq.exists() else {}
    agora = datetime.now(timezone.utc)
    mudou = False
    for item in sorted(agenda, key=lambda i: i["quando"]):
        pasta = item["pasta"]
        if pasta in res:
            continue
        quando = datetime.fromisoformat(item["quando"])
        if quando > agora:
            continue
        em = agora.strftime("%Y-%m-%d %H:%M:%S UTC")
        atraso_h = (agora - quando).total_seconds() / 3600
        if atraso_h > JANELA_H:
            res[pasta] = {"status": "atrasada", "em": em, "erro": f"passou {atraso_h:.1f} h do horário; não publicada"}
        else:
            try:
                legenda = (RAIZ / pasta / "legenda.md").read_text().strip()
                res[pasta] = {"status": "publicada", "media_id": publicar(pasta, legenda, base, token, uid), "em": em}
            except Exception as e:  # noqa: BLE001
                res[pasta] = {"status": "falhou", "em": em, "erro": str(e)[:300]}
        print(f"{pasta}: {res[pasta]['status']}")
        mudou = True
        res_arq.write_text(json.dumps(res, ensure_ascii=False, indent=2))  # grava já, para não repetir
    if not mudou:
        print("Nada a publicar agora.")


if __name__ == "__main__":
    main()
