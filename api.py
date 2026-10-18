import sys
import time
import os
import uuid
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from coordinateur import Coordonnateur

app = FastAPI(title="AGROGUIDCI — démo")

# --- CORS : indispensable pour que Lovable (ou ton navigateur) puisse parler à ton PC ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

coord = Coordonnateur()
CHEMIN_INTERDIT = re.compile(r"(\.csv|:\\|/|\\\\)", re.IGNORECASE)

class Demande(BaseModel):
    texte: str
    langue: str = "Français"

@app.post("/api/demande")
def lancer(d: Demande):
    texte = (d.texte or "").strip()
    if CHEMIN_INTERDIT.search(texte):
        raise HTTPException(400, "Chemins interdits.")
    
    mid = str(uuid.uuid4())[:8]
    debut = time.time()
    
    # On ajoute la langue au début pour que le moteur réponde dans la bonne langue
    demande_enrichie = f"[Langue de réponse demandée : {d.langue}] {texte}"
    
    try:
        resultat = coord.traiter(demande_enrichie, etiquette=mid)
    except Exception as e:
        return {"id": mid, "demande": texte, "erreur": f"{type(e).__name__}: {e}"}
    
    def _get(d, *cles):
        if not isinstance(d, dict): return None
        for c in cles:
            if c in d and d[c] not in (None, "", [], {}): return d[c]
        return None
    
    return {
        "id": mid,
        "demande": texte,
        "etat_final": _get(resultat, "etat_final", "etat"),
        "verification": _get(resultat, "verification"),
        "synthese": _get(resultat, "synthese", "texte"),
        "questions": _get(resultat, "questions", "clarification") or [],
        "duree_s": round(time.time() - debut, 1),
    }

@app.get("/")
def page():
    return {"status": "API AGROGUIDCI en ligne"}

if __name__ == "__main__":
    import uvicorn
    # On écoute sur 0.0.0.0 pour être accessible par ton navigateur local
    uvicorn.run(app, host="0.0.0.0", port=8080)
