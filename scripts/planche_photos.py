"""Planche de contact : plusieurs candidats par culture, pour choisir à l'œil."""
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photos_cultures as pc

TEMP = Path(r"C:\Users\MAC BOOK PRO\AppData\Local\hermes\cache\scratch\photos")
TEMP.mkdir(parents=True, exist_ok=True)

QUERIES = {
    "pasteque": ["watermelon whole fruit green striped", "watermelons market Africa sale", "watermelon cut red flesh seeds"],
    "ananas": ["pineapple whole fruit with crown leaves", "Ananas comosus ripe fruit close up", "pineapple fruit market Africa"],
}

lignes = []
for cid, termes in QUERIES.items():
    vus = set()
    candidats = []
    for terme in termes:
        try:
            for c in pc.candidats(terme, 6):
                if c["titre"] in vus or c["largeur"] < 900:
                    continue
                vus.add(c["titre"])
                candidats.append(c)
        except Exception as exc:
            print(f"! {terme}: {exc}", file=sys.stderr)
        if len(candidats) >= 6:
            break
    retenus = []
    for i, c in enumerate(candidats[:4]):
        url = c["url"]
        # vignette 480 px pour la planche
        nom = url.rsplit("/", 1)[-1]
        vignette = url.replace("/commons/", "/commons/thumb/") + "/480px-" + nom
        dest = TEMP / f"{cid}-{i}.jpg"
        try:
            pc.telecharger(vignette, dest)
        except Exception:
            try:
                pc.telecharger(url, dest)
            except Exception as exc:
                print(f"! {cid} {i}: {exc}", file=sys.stderr)
                continue
        retenus.append({"culture": cid, "index": i, "fichier": dest.name, "titre": c["titre"],
                        "licence": c["licence"], "auteur": c["auteur"], "page": c["page"], "url": url})
        lignes.append((cid, i, dest.name, c["titre"], c["licence"], c["auteur"], c["page"], url))
    # sidecar par culture : on garde les métadonnées même si la suite échoue
    (TEMP / f"{cid}.json").write_text(json.dumps(retenus, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{cid}: {len(retenus)} vignette(s)", flush=True)

donnees = [{"culture": l[0], "index": l[1], "fichier": l[2], "titre": l[3], "licence": l[4],
            "auteur": l[5], "page": l[6], "url": l[7]} for l in lignes]
(TEMP / "candidats.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")

cellules = []
for cid in QUERIES:
    groupe = [l for l in lignes if l[0] == cid]
    cartes = "".join(
        f'<figure><img src="{l[2]}"><figcaption>{cid} #{l[1]} — {l[3][:52]}<br><small>{l[4]}</small></figcaption></figure>'
        for l in groupe)
    cellules.append(f'<section><h2>{cid}</h2><div class="l">{cartes}</div></section>')

html = ("<!doctype html><meta charset='utf-8'><style>body{font:13px system-ui;background:#111;color:#eee;margin:14px}"
        "section{margin-bottom:16px}h2{font-size:15px;margin:0 0 6px;color:#c9f36b}"
        ".l{display:flex;gap:10px;flex-wrap:wrap}figure{margin:0;width:230px}"
        "img{width:230px;height:150px;object-fit:cover;border-radius:6px}figcaption{font-size:11px;line-height:1.3;margin-top:3px}"
        "small{opacity:.65}</style>" + "".join(cellules))
(TEMP / "planche.html").write_text(html, encoding="utf-8")
print(f"{len(lignes)} vignettes · {TEMP / 'planche.html'}")
