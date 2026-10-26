"""Rattrapage ciblé : tomate et oignon (recherches plus larges)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import photos_cultures as pc

QUERIES = {
    "tomate": ["tomato fruit red ripe", "Solanum lycopersicum fruits", "tomatoes basket market"],
    "oignon": ["onion bulbs", "Allium cepa bulb harvest", "onions market pile"],
}

credits = json.loads(pc.CREDITS.read_text(encoding="utf-8")) if pc.CREDITS.exists() else {}

for cid, termes in QUERIES.items():
    if (pc.DEST / f"{cid}.jpg").exists():
        print(f"- {cid} : déjà présent")
        continue
    trouve = None
    for terme in termes:
        try:
            liste = pc.candidats(terme, 6)
        except Exception as exc:
            print(f"  ! {terme} : {exc}")
            continue
        print(f"  {terme} -> {len(liste)} candidat(s)")
        for c in liste:
            print(f"     {c['largeur']}px | {c['licence']} | {c['titre'][:60]}")
        gros = [c for c in liste if c["largeur"] >= 1200]
        if gros:
            trouve = gros[0]
            break
    if not trouve:
        print(f"! {cid} : rien de retenu")
        continue
    taille = pc.telecharger(trouve["url"], pc.DEST / f"{cid}.jpg")
    credits[cid] = {"auteur": trouve["auteur"], "licence": trouve["licence"], "page": trouve["page"],
                    "fichier": f"assets/cultures/{cid}.jpg", "choix": trouve["titre"]}
    print(f"+ {cid} : {trouve['titre'][:50]} ({taille // 1024} Ko, {trouve['licence']})")

pc.CREDITS.write_text(json.dumps(credits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("crédits à jour :", len(credits))
