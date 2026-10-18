# api.py — version Render avec attente de l'orchestrateur
import subprocess
import sys
import time
import os
import uuid
import re
import urllib.request
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# --- 1. Lancer l'orchestrateur en arrière-plan ---
if os.environ.get("PORT"):
    print("Démarrage de l'orchestrateur...")
    subprocess.Popen(
        [sys.executable, "demarrer_agroguidci.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

# --- 2. Importer le moteur ---
from coordinateur import Coordonnateur

app = FastAPI(title="AGROGUIDCI — démo")
coord = Coordonnateur()
CHEMIN_INTERDIT = re.compile(r"(\.csv|:\\|/|\\\\)", re.IGNORECASE)

class Demande(BaseModel):
    texte: str

@app.post("/api/demande")
def lancer(d: Demande):
    texte = (d.texte or "").strip()
    if CHEMIN_INTERDIT.search(texte):
        raise HTTPException(400, "Chemins interdits.")
    
    # --- 3. Attendre que l'orchestrateur soit prêt ---
    # On boucle pendant 20 secondes max pour voir si le port 8000 répond
    orchestrateur_pret = False
    for _ in range(20):
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/health", method="GET")
            with urllib.request.urlopen(req, timeout=1) as response:
                if response.status == 200:
                    orchestrateur_pret = True
                    break
        except Exception:
            time.sleep(1) # On attend 1 seconde et on réessaie
    
    if not orchestrateur_pret:
        return {"id": "error", "erreur": "L'orchestrateur met trop de temps à démarrer sur Render."}

    mid = str(uuid.uuid4())[:8]
    debut = time.time()
    
    try:
        # Appel du moteur (l'orchestrateur est maintenant prêt)
        resultat = coord.traiter(texte, etiquette=mid)
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
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
