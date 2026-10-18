# api.py — démo day AGROGUIDCI
# Un seul fichier. Importe le moteur existant. Ne le modifie pas.

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pathlib import Path
import uuid, time, re, json

# --- import direct du moteur (pas de HTTP, pas de clé admin) ---
from coordinateur import Coordonnateur

app = FastAPI(title="AGROGUIDCI — démo")
coord = Coordonnateur()
MISSIONS = {}  # en mémoire, suffisant pour une démo

# --- garde-fou R1 : pas de chemin de fichier dans le texte libre ---
CHEMIN_INTERDIT = re.compile(r"(\.csv|:\\|/|\\\\)", re.IGNORECASE)

SCENARIOS = {
    "bouake": "J'ai 2 hectares à Bouaké. Que cultiver et comment démarrer un petit élevage de poulets ?",
    "korhogo": "Je suis à Korhogo, sol fatigué, saison sèche longue. Que planter et comment fertiliser sans acheter d'engrais chimique ?",
    "abidjan": "Je veux produire du manioc près d'Abidjan pour vendre au marché. Quel budget, quelle marge, quelles précautions ?",
}

class Demande(BaseModel):
    texte: str

class Reponse(BaseModel):
    id: str
    demande: str
    etat_final: str | None = None
    verification: dict | None = None
    synthese: str | None = None
    chiffres: list | None = None
    questions: list | None = None
    points_a_verifier: list | None = None
    duree_s: float | None = None
    dossier: str | None = None
    erreur: str | None = None

@app.post("/api/demande", response_model=Reponse)
def lancer(d: Demande):
    texte = (d.texte or "").strip()

    # garde-fous
    if CHEMIN_INTERDIT.search(texte):
        raise HTTPException(400, "La démo n'accepte pas de chemins de fichiers.")
    if len(texte) < 20:
        raise HTTPException(400, "Demande trop courte (20 caractères minimum).")
    if len(texte) > 2000:
        raise HTTPException(400, "Demande trop longue pour la démo (2000 caractères max).")

    mid = str(uuid.uuid4())[:8]
    debut = time.time()

    try:
        # appel direct, synchrone. 20 à 40 s, c'est OK pour une démo.
        resultat = coord.traiter(texte, etiquette=mid)
    except Exception as e:
        return Reponse(
            id=mid, demande=texte, erreur=f"{type(e).__name__}: {e}",
            duree_s=round(time.time() - debut, 1),
        )

    # normalisation tolérante : le moteur peut rendre des clés légèrement différentes
    def _get(d, *cles):
        if not isinstance(d, dict):
            return None
        for c in cles:
            if c in d and d[c] not in (None, "", [], {}):
                return d[c]
        return None

    verif = _get(resultat, "verification", "verifications")
    synthese = _get(resultat, "synthese", "synthèse", "rapport", "texte")
    if isinstance(synthese, dict):
        synthese = _get(synthese, "texte", "resume", "résumé")

    rep = Reponse(
        id=mid,
        demande=texte,
        etat_final=_get(resultat, "etat_final", "etat", "état"),
        verification=verif if isinstance(verif, dict) else None,
        synthese=synthese if isinstance(synthese, str) else None,
        chiffres=_get(resultat, "chiffres", "donnees", "données") or [],
        questions=_get(resultat, "questions", "clarification") or [],
        points_a_verifier=_get(resultat, "points_a_verifier", "points_à_vérifier") or [],
        duree_s=round(time.time() - debut, 1),
        dossier=f"out/{mid}",
    )
    MISSIONS[mid] = rep.model_dump()
    return rep

@app.get("/api/mission/{mid}")
def lire(mid: str):
    if mid not in MISSIONS:
        raise HTTPException(404, "Mission inconnue")
    return MISSIONS[mid]

@app.get("/api/scenarios")
def scenarios():
    return SCENARIOS

@app.get("/", response_class=HTMLResponse)
def page():
    return "<h1>API AGROGUIDCI en ligne</h1><p>Utilisez /docs pour tester.</p>"

# Pour Render : écoute sur 0.0.0.0 et utilise le port fourni par l'environnement
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
