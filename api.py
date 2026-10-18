# api.py — version Render : lance l'orchestrateur en arrière-plan
import subprocess
import sys
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uuid, re, os

# --- 1. Lancer l'orchestrateur en arrière-plan au démarrage ---
# On vérifie qu'on est bien sur Render (variable PORT définie)
if os.environ.get("PORT"):
    print("Démarrage de l'orchestrateur en arrière-plan...")
    subprocess.Popen(
        [sys.executable, "demarrer_agroguidci.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(5)  # Attendre que l'orchestrateur démarre

# --- 2. Importer le moteur ---
from coordinateur import Coordonnateur

app = FastAPI(title="AGROGUIDCI — démo")
coord = Coordonnateur()
MISSIONS = {}
CHEMIN_INTERDIT = re.compile(r"(\.csv|:\\|/|\\\\)", re.IGNORECASE)

class Demande(BaseModel):
    texte: str

@app.post("/api/demande")
def lancer(d: Demande):
    texte = (d.texte or "").strip()
    if CHEMIN_INTERDIT.search(texte):
        raise HTTPException(400, "Chemins de fichiers non autorisés.")
    if len(texte) < 20:
        raise HTTPException(400, "Demande trop courte.")
    
    mid = str(uuid.uuid4())[:8]
    debut = time.time()
    
    try:
        resultat = coord.traiter(texte, etiquette=mid)
    except Exception as e:
        return {"id": mid, "demande": texte, "erreur": f"{type(e).__name__}: {e}"}
    
    # Mapping tolérant
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
    return {"status": "API AGROGUIDCI en ligne", "orchestrateur": "démarré" if os.environ.get("PORT") else "local"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
