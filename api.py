import sys
import time
import os
import uuid
import re
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from coordinateur import Coordonnateur

app = FastAPI(title="AGROGUIDCI — démo")

# --- CORS : liste blanche exacte, refus par défaut -----------------------------
# Un fichier de démonstration finit toujours par tourner ailleurs que sur le poste :
# « * » avec credentials laissait n'importe quel site appeler le moteur avec le
# jeton du navigateur. Les origines viennent maintenant de l'environnement.
ORIGINES_DEFAUT = "http://127.0.0.1:8099,http://localhost:8099"
ORIGINES = [o.strip() for o in (os.environ.get("AGRO_CORS_ORIGINS") or ORIGINES_DEFAUT).split(",")
            if o.strip()]
PERMISSIF = os.environ.get("AGRO_CORS_PERMISSIF", "").strip().lower() in ("1", "true", "oui", "on")
if PERMISSIF:
    ORIGINES = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINES,
    # Jamais de credentials, même en mode permissif : un site tiers ne doit pas
    # pouvoir lire une réponse authentifiée.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    max_age=600,
)


def incident(e: Exception) -> str:
    """Identifiant court pour corréler la réponse client et le journal serveur."""
    ref = uuid.uuid4().hex[:12]
    print(f"[incident {ref}] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return ref


@app.exception_handler(Exception)
async def _erreur_generique(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500,
                        content={"erreur": "Erreur interne du moteur.", "incident": incident(exc)})

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
    except Exception as e:                       # jamais de trace interne côté client
        return JSONResponse(status_code=500,
                            content={"id": mid, "erreur": "Le moteur n'a pas pu traiter la demande.",
                                     "incident": incident(e)})
    
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
    # Boucle locale uniquement : un serveur de démonstration n'a rien à faire sur 0.0.0.0.
    uvicorn.run(app, host=os.environ.get("AGRO_DEMO_HOST", "127.0.0.1"),
                port=int(os.environ.get("AGRO_DEMO_PORT", "8080")))
