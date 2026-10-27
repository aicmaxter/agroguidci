#!/usr/bin/env python
"""tests_fuites_erreurs.py — ce que le client voit quand le serveur échoue.

Vérifie trois choses, sans réseau :
  1. le serveur de démonstration (api.py) ne renvoie ni type d'exception, ni message
     interne, ni chemin : seulement un message générique et un identifiant d'incident ;
  2. sa configuration CORS n'accepte que les origines déclarées, sans credentials ;
  3. le moteur HTTP (serveur_api.py) publie un échec de mission sans détail interne.

    python tests_fuites_erreurs.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("AGRO_SANS_AUTH", "1")      # aucun appel réseau : le test n'utilise pas la clé

import api  # noqa: E402
import serveur_api as moteur  # noqa: E402


class ErreursDemonstration(unittest.TestCase):
    def test_echec_du_moteur_sans_detail_interne(self):
        def explose(*a, **k):
            raise RuntimeError("ouverture impossible de C:\\secret\\confidentiel.json — clé ABCD")

        ancien = api.coord.traiter
        api.coord.traiter = explose
        journal = io.StringIO()
        try:
            with redirect_stderr(journal):
                reponse = api.lancer(api.Demande(texte="quel est le cycle du maïs ?"))
        finally:
            api.coord.traiter = ancien

        corps = json.loads(bytes(reponse.body).decode("utf-8"))
        texte = json.dumps(corps)
        self.assertEqual(reponse.status_code, 500)
        self.assertIn("erreur", corps)
        self.assertIn("incident", corps)
        for interdit in ("RuntimeError", "secret", "confidentiel", "ABCD", "C:\\", "Traceback"):
            self.assertNotIn(interdit, texte)
        # le détail existe… mais uniquement dans le journal serveur
        self.assertIn("incident", journal.getvalue())
        self.assertIn("RuntimeError", journal.getvalue())

    def test_cors_refus_par_defaut(self):
        config = None
        for mw in api.app.user_middleware:
            if "CORSMiddleware" in str(getattr(mw, "cls", "")) or "cors" in str(getattr(mw, "cls", "")).lower():
                config = mw.kwargs
        self.assertIsNotNone(config, "middleware CORS introuvable")
        self.assertFalse(config.get("allow_credentials"), "credentials CORS interdits")
        self.assertNotIn("*", config.get("allow_origins") or [])
        self.assertEqual(set(config.get("allow_methods") or []), {"GET", "POST", "OPTIONS"})
        for origine in config.get("allow_origins") or []:
            self.assertTrue(origine.startswith("http://127.0.0.1") or origine.startswith("http://localhost"),
                            f"origine de développement inattendue : {origine}")


class ErreursMoteur(unittest.TestCase):
    def test_echec_de_mission_sans_detail(self):
        def explose(*a, **k):
            raise ValueError("chemin interne /opt/agroguidci/serveur_api.py ligne 42")

        ancien = moteur.Coordonnateur
        moteur.Coordonnateur = lambda *a, **k: type("C", (), {"traiter": staticmethod(explose)})()
        jid = "j_testfuite01"
        try:
            moteur._executer_job(jid, "question", None)
        finally:
            moteur.Coordonnateur = ancien
        job = moteur._job_lire(jid)
        self.assertIsNotNone(job)
        self.assertEqual(job.get("statut"), "echec")
        texte = json.dumps(job)
        for interdit in ("ValueError", "serveur_api.py", "/opt/", "ligne 42"):
            self.assertNotIn(interdit, texte)
        self.assertTrue(job.get("incident"))

    def test_mode_emploi_sans_secret(self):
        corps = json.dumps(moteur.mode_emploi())
        self.assertNotIn("AGRO_API_KEY", corps)
        for motif in ("sk-", "Bearer ey", "clé réelle"):
            self.assertNotIn(motif, corps)


if __name__ == "__main__":
    unittest.main(verbosity=2)
