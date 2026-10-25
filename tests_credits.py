"""tests_credits.py — crédits gratuits, débit des consultations, achats (sans LLM).

Chaque test travaille sur une base SQLite temporaire. Le moteur n'est jamais
appelé : `Coordonnateur` et `_enveloppe` sont remplacés par des doubles, ce qui
permet de vérifier le débit réel sans consommer une mission payante.

    python tests_credits.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="agro-credits-")
os.environ["AGRO_CONVERSATIONS_DB"] = str(Path(_TMP) / "credits.db")
os.environ["AGRO_SANS_AUTH"] = "1"
os.environ["AGRO_API_KEY"] = "cle-de-test-non-sensible"
os.environ["AGRO_CREDITS_GRATUITS"] = "15"
os.environ["AGRO_CREDITS_PERIODE_H"] = "7"
os.environ["AGRO_CREDITS_COUT"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import conversations as conv  # noqa: E402
import serveur_api as api  # noqa: E402

CLE = os.environ["AGRO_API_KEY"]


class FauxCoord:
    """Double du coordonnateur : aucune IA, aucune sortie réseau."""

    etat = "TERMINEE_VERIFIEE"
    reponse = "Réponse de test de l'agent agronome."

    def traiter(self, texte, profil=None, *a, **k):
        return {"ok": True}


def _enveloppe_factice(texte, profil, resultat, duree):
    return {
        "etat_final": FauxCoord.etat,
        "id": "mis_test",
        "rapport": {"reponse": FauxCoord.reponse, "sources": []},
    }


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        api.Coordonnateur = FauxCoord
        api._enveloppe = _enveloppe_factice
        cls.client = TestClient(api.app)

    def setUp(self) -> None:
        FauxCoord.etat = "TERMINEE_VERIFIEE"
        FauxCoord.reponse = "Réponse de test de l'agent agronome."

    def session(self) -> str:
        r = self.client.post("/api/sessions")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session_token"]

    def sid(self, jeton: str) -> str:
        sid = conv.session_valide(jeton)
        self.assertIsNotNone(sid)
        return sid

    def conversation(self, jeton: str) -> str:
        r = self.client.post("/api/conversations", json={}, headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["conversation_id"]

    def credits(self, jeton: str) -> dict:
        r = self.client.get("/api/credits", headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class TestLotGratuit(Base):
    def test_lot_initial_de_15(self):
        c = self.credits(self.session())
        self.assertEqual(c["lot_gratuit"], 15)
        self.assertEqual(c["gratuits"], 15)
        self.assertEqual(c["total"], 15)
        self.assertEqual(c["cout_consultation"], 1)
        self.assertEqual(c["periode_heures"], 7)
        self.assertEqual(c["achetes"], 0)

    def test_recharger_la_page_ne_credite_pas_deux_fois(self):
        jeton = self.session()
        for _ in range(6):
            self.assertEqual(self.credits(jeton)["total"], 15)
        sid = self.sid(jeton)
        lots = conv._db().execute(
            "SELECT COUNT(*) FROM credits WHERE session_id=? AND raison='gratuit_periode'",
            (sid,)).fetchone()[0]
        self.assertEqual(lots, 1, "la période ne doit être créditée qu'une fois")

    def test_periode_utc_et_renouvellement_apres_7h(self):
        jeton = self.session()
        sid = self.sid(jeton)
        t0 = int(time.time())
        c = conv.solde(sid, t0)
        self.assertEqual(c["periode_debut"] % conv.PERIODE_CREDITS_S, 0, "fenêtre alignée sur UTC")
        self.assertEqual(c["renouvellement_at"] - c["periode_debut"], conv.PERIODE_CREDITS_S)
        for i in range(3):
            self.assertIsNotNone(conv.consommer(sid, f"ref-{i}", cout=1))
        self.assertEqual(conv.solde(sid, t0)["total"], 12)
        # même instant : toujours 12 ; 8 heures plus tard : nouveau lot de 15
        apres = conv.solde(sid, t0 + 8 * 3600)
        self.assertEqual(apres["total"], 15)
        self.assertGreater(apres["periode"], c["periode"])

    def test_changer_de_cookie_ne_recree_pas_de_credits(self):
        # deux jetons de la même session : un seul a le solde, l'autre est refusé
        jeton = self.session()
        self.assertEqual(self.credits(jeton)["total"], 15)
        r = self.client.get("/api/credits", headers={"X-Session-Token": "jeton-invente"})
        self.assertEqual(r.status_code, 401)


class TestDebit(Base):
    def test_debit_unique_par_reference(self):
        jeton = self.session()
        sid = self.sid(jeton)
        self.assertIsNotNone(conv.consommer(sid, "ref-unique"))
        self.assertIsNotNone(conv.consommer(sid, "ref-unique"), "rejeu : pas d'erreur")
        self.assertEqual(conv.solde(sid)["total"], 14, "un seul débit malgré deux appels")

    def test_jamais_de_solde_negatif(self):
        jeton = self.session()
        sid = self.sid(jeton)
        for i in range(15):
            self.assertIsNotNone(conv.consommer(sid, f"ref-{i}"))
        self.assertEqual(conv.solde(sid)["total"], 0)
        self.assertIsNone(conv.consommer(sid, "ref-16"), "le 16e débit doit être refusé")
        self.assertEqual(conv.solde(sid)["total"], 0)

    def test_les_gratuits_passent_avant_les_achetes(self):
        jeton = self.session()
        sid = self.sid(jeton)
        conv.ajouter_credits_achetes(sid, 30, "pay_test_1")
        self.assertEqual(conv.solde(sid)["total"], 45)
        for i in range(15):
            conv.consommer(sid, f"ref-{i}")
        s = conv.solde(sid)
        self.assertEqual((s["gratuits"], s["achetes"], s["total"]), (0, 30, 30))
        conv.consommer(sid, "ref-15")
        self.assertEqual(conv.solde(sid)["achetes"], 29)

    def test_les_credits_achetes_survivent_au_renouvellement(self):
        jeton = self.session()
        sid = self.sid(jeton)
        conv.ajouter_credits_achetes(sid, 30, "pay_test_2")
        conv.consommer(sid, "ref-a")
        plus_tard = int(time.time()) + 8 * 3600
        s = conv.solde(sid, plus_tard)
        self.assertEqual((s["gratuits"], s["achetes"], s["total"]), (15, 30, 45))

    def test_achat_idempotent_et_quantite_validee(self):
        jeton = self.session()
        sid = self.sid(jeton)
        conv.ajouter_credits_achetes(sid, 30, "pay_1")
        conv.ajouter_credits_achetes(sid, 30, "pay_1")
        self.assertEqual(conv.solde(sid)["achetes"], 30, "une référence de paiement = un crédit")
        with self.assertRaises(ValueError):
            conv.ajouter_credits_achetes(sid, 0, "pay_2")
        with self.assertRaises(ValueError):
            conv.ajouter_credits_achetes(sid, -5, "pay_3")

    def test_journal_trace_les_mouvements(self):
        jeton = self.session()
        sid = self.sid(jeton)
        conv.consommer(sid, "ref-trace")
        h = conv.historique(sid)
        raisons = {m["raison"] for m in h}
        self.assertIn("gratuit_periode", raisons)
        self.assertIn("consultation", raisons)
        debit = [m for m in h if m["raison"] == "consultation"][0]
        self.assertEqual(debit["delta"], -1)
        self.assertEqual(debit["reference"], "ref-trace")


class TestRoutes(Base):
    def test_refus_402_sans_credit_et_aucun_message_cree(self):
        jeton = self.session()
        sid = self.sid(jeton)
        cid = self.conversation(jeton)
        for i in range(15):
            conv.consommer(sid, f"ref-{i}")
        r = self.client.post(f"/api/conversations/{cid}/messages", json={"texte": "Une question"},
                             headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 402, r.text)
        corps = r.json()
        self.assertIn("erreur", corps)
        self.assertEqual(corps["credits"]["total"], 0)
        fil = self.client.get(f"/api/conversations/{cid}", headers={"X-Session-Token": jeton}).json()
        self.assertEqual(fil["messages"], [], "aucune question ne doit être enregistrée sans crédit")

    def test_202_avec_solde(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        r = self.client.post(f"/api/conversations/{cid}/messages", json={"texte": "Une question"},
                             headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 202, r.text)

    def test_reponse_reussie_debite_une_fois(self):
        jeton = self.session()
        sid = self.sid(jeton)
        cid = self.conversation(jeton)
        api._executer_message(cid, "msg_test_1", "question", None, sid)
        self.assertEqual(conv.solde(sid)["total"], 14)
        api._executer_message(cid, "msg_test_1", "question", None, sid)
        self.assertEqual(conv.solde(sid)["total"], 14, "le rejeu du même message ne débite pas")

    def test_echec_ne_debite_pas(self):
        FauxCoord.etat = "ECHEC_OUTIL"
        jeton = self.session()
        sid = self.sid(jeton)
        cid = self.conversation(jeton)
        api._executer_message(cid, "msg_test_2", "question", None, sid)
        self.assertEqual(conv.solde(sid)["total"], 15, "un échec du moteur est gratuit")

    def test_clarification_ne_debite_pas(self):
        FauxCoord.etat = "EN_ATTENTE_INFORMATION"
        jeton = self.session()
        sid = self.sid(jeton)
        cid = self.conversation(jeton)
        api._executer_message(cid, "msg_test_3", "question", None, sid)
        self.assertEqual(conv.solde(sid)["total"], 15)

    def test_reponse_vide_ne_debite_pas(self):
        FauxCoord.reponse = "   "
        jeton = self.session()
        sid = self.sid(jeton)
        cid = self.conversation(jeton)
        api._executer_message(cid, "msg_test_4", "question", None, sid)
        self.assertEqual(conv.solde(sid)["total"], 15)

    def test_credits_exigent_une_session(self):
        r = self.client.get("/api/credits")
        self.assertEqual(r.status_code, 401)

    def test_aucun_secret_dans_la_reponse(self):
        c = self.credits(self.session())
        texte = str(c)
        self.assertNotIn(CLE, texte)
        self.assertNotIn("api_key", texte.lower())
        self.assertNotIn("token", texte.lower())

    def test_packs_servis_par_le_serveur(self):
        c = self.credits(self.session())
        packs = {p["id"]: p for p in c["packs"]}
        self.assertEqual((packs["decouverte"]["prix_fcfa"], packs["decouverte"]["credits"]), (599, 30))
        self.assertEqual((packs["avance"]["prix_fcfa"], packs["avance"]["credits"]), (3999, 200))
        self.assertFalse(packs["decouverte"]["disponible"])
        self.assertFalse(packs["avance"]["disponible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
