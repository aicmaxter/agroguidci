"""tests_agronomie.py — garde-fous du référentiel agronomique (sans LLM, sans réseau).

Deux familles de contrôles :
  1. la consigne envoyée au moteur interdit explicitement les réponses dangereuses
     (dosage inventé, mélange, diagnostic affirmé, garantie de rendement…) ;
  2. les garde-fous déterministes s'appliquent même si le modèle répond mal :
     urgence sanitaire, renvoi vers un professionnel, mention « non validée ».

    python tests_agronomie.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="agro-agro-")
os.environ["AGRO_CONVERSATIONS_DB"] = str(Path(_TMP) / "agro.db")
os.environ["AGRO_SANS_AUTH"] = "1"
os.environ["AGRO_API_KEY"] = "cle-de-test-non-sensible"

from fastapi.testclient import TestClient  # noqa: E402

import conversations as conv  # noqa: E402
import serveur_api as api  # noqa: E402

ROOT_WEB = ROOT / "web"
INDEX = (ROOT_WEB / "index.html").read_text(encoding="utf-8")
CHAT = (ROOT_WEB / "assets" / "chat.js").read_text(encoding="utf-8")
CONSIGNE = api.CONSIGNE_CHAT
SANS_ACCENT = api._sans_accents(CONSIGNE)


class FauxCoord:
    def traiter(self, texte, profil=None, *a, **k):
        return {"ok": True}


def _enveloppe(texte, profil, resultat, duree):
    return {"etat_final": "TERMINEE_VERIFIEE", "id": "mis_agro",
            "rapport": {"reponse": "Réponse de test.", "sources": []}}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api.Coordonnateur = FauxCoord
        api._enveloppe = _enveloppe
        cls.client = TestClient(api.app)

    def session(self) -> str:
        r = self.client.post("/api/sessions")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session_token"]

    def conversation(self, jeton: str) -> str:
        r = self.client.post("/api/conversations", json={}, headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["conversation_id"]


class TestConsigne(unittest.TestCase):
    """§13 et §4 : la consigne doit porter les interdictions, pas seulement l'intention."""

    def test_format_en_dix_sections(self):
        for titre in ("Situation comprise", "Informations manquantes", "Hypothèses possibles",
                      "Comment les différencier", "Actions prudentes immédiates", "À éviter",
                      "Quand consulter un professionnel", "Sources et dates", "Limites",
                      "Niveau de confiance"):
            self.assertIn(titre, CONSIGNE, f"section manquante dans la consigne : {titre}")

    def test_trois_hypotheses_maximum(self):
        self.assertIn("au maximum TROIS hypothèses", CONSIGNE)

    def test_interdiction_des_dosages_non_verifies(self):
        self.assertIn("Je ne peux pas confirmer un produit ou un dosage sûr", CONSIGNE)
        for interdit in ("inventer ou convertir un dosage", "mélange non autorisé",
                         "dépasser l'étiquette", "contenant alimentaire"):
            self.assertIn(interdit, CONSIGNE, f"interdit absent : {interdit}")

    def test_message_d_urgence_present(self):
        self.assertIn("centre médical ou les services d'urgence", api.MESSAGE_URGENCE)
        self.assertIn("ne faites pas vomir", api.MESSAGE_URGENCE.lower())
        self.assertIn("INTOXICATION OU EXPOSITION", CONSIGNE)

    def test_orientation_veterinaire(self):
        self.assertIn("vétérinaire", CONSIGNE)
        self.assertIn("médicament vétérinaire", CONSIGNE)

    def test_sources_et_meteo(self):
        self.assertIn("Aucune source externe vérifiée n'a été consultée", CONSIGNE)
        self.assertIn("prévision", CONSIGNE)
        self.assertIn("moyenne historique", CONSIGNE)
        self.assertIn("type de prix (producteur, gros, détail)", CONSIGNE)

    def test_ne_se_presente_pas_comme_agronome(self):
        self.assertIn("ni un agronome humain", CONSIGNE)
        self.assertIn("ne le prétends jamais", CONSIGNE)

    def test_mention_non_validee(self):
        self.assertEqual(api.MENTION_NON_VALIDEE,
                         "Réponse générée automatiquement — non validée par un agronome.")
        self.assertIn(api.MENTION_NON_VALIDEE, CHAT)


class TestRisque(unittest.TestCase):
    """§12 : le niveau de risque est calculé, pas laissé au modèle."""

    def test_intoxication_humaine(self):
        for phrase in ("mon enfant a bu le pesticide",
                       "j'ai reçu du produit dans les yeux",
                       "malaise après le traitement"):
            niveau, urgence = api.risque_agronomique(phrase)
            self.assertEqual((niveau, urgence), ("eleve", True), phrase)

    def test_produit_et_dosage(self):
        niveau, urgence = api.risque_agronomique("quelle dose de fongicide pour la tomate ?")
        self.assertEqual((niveau, urgence), ("eleve", False))

    def test_probleme_cultural(self):
        self.assertEqual(api.risque_agronomique("les feuilles jaunissent sur mon manioc")[0], "modere")

    def test_question_simple(self):
        self.assertEqual(api.risque_agronomique("bonjour, quel est le cycle du fonio ?")[0], "faible")


class TestGardeFous(Base):
    def _executer(self, cid, sid, texte, risque, urgence):
        api._executer_message(cid, "msg_" + texte[:6], texte, None, sid, risque, urgence)
        fil = conv.fil(sid, cid)
        return fil["messages"][-1]

    def test_urgence_est_prefixee(self):
        jeton = self.session()
        sid = conv.session_valide(jeton)
        cid = self.conversation(jeton)
        m = self._executer(cid, sid, "mon fils a bu le produit", "eleve", True)
        self.assertIn("services d'urgence", m["contenu"])
        self.assertTrue(m["contenu"].startswith("⚠"))

    def test_risque_eleve_renvoie_vers_un_professionnel(self):
        jeton = self.session()
        sid = conv.session_valide(jeton)
        cid = self.conversation(jeton)
        m = self._executer(cid, sid, "quel fongicide choisir", "eleve", False)
        self.assertIn("professionnel", m["contenu"].lower())
        self.assertEqual(m["risque"], "eleve")

    def test_reponse_par_defaut_non_validee(self):
        jeton = self.session()
        sid = conv.session_valide(jeton)
        cid = self.conversation(jeton)
        m = self._executer(cid, sid, "cycle du fonio", "faible", False)
        self.assertEqual(m["validation"], "auto")
        self.assertIsNone(m["validateur"])

    def test_validation_humaine_tracee(self):
        jeton = self.session()
        sid = conv.session_valide(jeton)
        cid = self.conversation(jeton)
        m = self._executer(cid, sid, "cycle du fonio", "faible", False)
        r = conv.valider_message(cid, m["message_id"], "valide", "Dr Koffi, agronome ANADER")
        self.assertEqual(r["validation"], "valide")
        self.assertIsNotNone(r["valide_le"])
        fil = conv.fil(sid, cid)
        self.assertEqual(fil["messages"][-1]["validation"], "valide")
        self.assertEqual(fil["messages"][-1]["validateur"], "Dr Koffi, agronome ANADER")

    def test_statut_de_validation_invalide_refuse(self):
        jeton = self.session()
        sid = conv.session_valide(jeton)
        cid = self.conversation(jeton)
        m = self._executer(cid, sid, "cycle du fonio", "faible", False)
        with self.assertRaises(ValueError):
            conv.valider_message(cid, m["message_id"], "certifie", "X Y")
        with self.assertRaises(ValueError):
            conv.valider_message(cid, m["message_id"], "valide", "ab")

    def test_message_inconnu(self):
        self.assertIsNone(conv.valider_message("cnv_x", "msg_x", "valide", "Dr Test"))

    def test_route_de_validation_valide_le_message(self):
        jeton = self.session()
        sid = conv.session_valide(jeton)
        cid = self.conversation(jeton)
        m = self._executer(cid, sid, "cycle du fonio", "faible", False)
        r = self.client.post(f"/api/conversations/{cid}/messages/{m['message_id']}/validation",
                             json={"statut": "relu", "validateur": "Agent ANADER Bouaké"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["validation"], "relu")
        # statut non autorisé : refusé par le schéma
        r2 = self.client.post(f"/api/conversations/{cid}/messages/{m['message_id']}/validation",
                              json={"statut": "certifie", "validateur": "Agent ANADER Bouaké"})
        self.assertEqual(r2.status_code, 422)


class TestInterface(unittest.TestCase):
    def test_mention_affichee_dans_le_chat(self):
        self.assertIn("non validées par un agronome", INDEX)
        self.assertIn('class="chat-mention auto"', CHAT)
        self.assertIn("non validée par un agronome.", CHAT)

    def test_valide_seulement_si_statut_reel(self):
        # la mention « validée » n'apparaît que dans la branche validation === "valide"
        self.assertIn('message.validation === "valide"', CHAT)
        self.assertIn('message.validation === "relu"', CHAT)

    def test_badge_de_risque(self):
        self.assertIn('message.risque === "eleve"', CHAT)
        self.assertIn("risque élevé", CHAT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
