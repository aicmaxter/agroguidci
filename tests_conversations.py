"""tests_conversations.py — contrôles des fils de discussion (sans LLM, sans réseau).

Chaque test utilise une base SQLite temporaire et remplace l'exécution du moteur
par un double : aucun appel à l'orchestrateur, aucun appel à un fournisseur d'IA.

    python tests_conversations.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="agro-conv-")
os.environ["AGRO_CONVERSATIONS_DB"] = str(Path(_TMP) / "conversations.db")
os.environ["AGRO_SANS_AUTH"] = "1"
os.environ["AGRO_API_KEY"] = "cle-de-test-non-sensible"
os.environ["AGRO_CORS_ORIGINS"] = "https://agroguidci.vercel.app"

from fastapi.testclient import TestClient  # noqa: E402

import conversations as conv  # noqa: E402
import serveur_api as api  # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # double d'exécution : le fil passe directement à « terminé » avec une réponse fixe
        def faux_executeur(cid, mid, texte, profil):
            conv.repondre(cid, mid, "Réponse de test de l'agent agronome.", "termine",
                          mission_id="mis_test")
        api._executer_message = faux_executeur
        cls.client = TestClient(api.app)

    def session(self) -> str:
        r = self.client.post("/api/sessions")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session_token"]

    def conversation(self, jeton: str) -> str:
        r = self.client.post("/api/conversations", json={"culture_id": "igname"},
                             headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["conversation_id"]


class TestSessions(Base):
    def test_jeton_non_stocke_en_clair(self):
        jeton = self.session()
        c = conv._db()
        rows = c.execute("SELECT token_hash FROM sessions").fetchall()
        empreintes = [bytes(r["token_hash"]) for r in rows]
        self.assertNotIn(jeton.encode(), empreintes)
        self.assertIn(hashlib.sha256(jeton.encode()).digest(), empreintes)

    def test_session_invalide_refusee(self):
        for entete in ({"X-Session-Token": "faux"}, {}):
            r = self.client.post("/api/conversations", json={}, headers=entete)
            self.assertEqual(r.status_code, 401, r.text)

    def test_session_expiree_refusee(self):
        jeton = self.session()
        conv._db().execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",
                           (int(time.time()) - 10, hashlib.sha256(jeton.encode()).digest()))
        conv._db().commit()
        r = self.client.post("/api/conversations", json={}, headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 401)


class TestConversations(Base):
    def test_creation_et_lecture(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        self.assertTrue(cid.startswith("cnv_"), cid)
        r = self.client.get(f"/api/conversations/{cid}", headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 200, r.text)
        corps = r.json()
        self.assertEqual(corps["conversation_id"], cid)
        self.assertEqual(corps["culture_id"], "igname")
        self.assertEqual(corps["messages"], [])

    def test_propriete_verifiee(self):
        proprietaire = self.session()
        intrus = self.session()
        cid = self.conversation(proprietaire)
        r = self.client.get(f"/api/conversations/{cid}", headers={"X-Session-Token": intrus})
        self.assertEqual(r.status_code, 404, "une conversation d'autrui doit être invisible")
        r = self.client.post(f"/api/conversations/{cid}/messages", json={"texte": "Bonjour"},
                             headers={"X-Session-Token": intrus})
        self.assertEqual(r.status_code, 404)

    def test_conversation_inconnue(self):
        jeton = self.session()
        r = self.client.get("/api/conversations/cnv_inconnu", headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 404)


class TestMessages(Base):
    def test_envoi_et_reponse(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        r = self.client.post(f"/api/conversations/{cid}/messages",
                             json={"texte": "Quand planter l'igname à Bouaké ?",
                                   "localite": "Bouaké", "idempotency_key": "m-1"},
                             headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 202, r.text)
        mid = r.json()["message_id"]
        fil = self.client.get(f"/api/conversations/{cid}", headers={"X-Session-Token": jeton}).json()
        self.assertEqual(fil["messages"][0]["message_id"], mid)
        self.assertEqual(fil["messages"][0]["role"], "user")
        self.assertIn(fil["messages"][0]["statut"], ("en_cours", "termine"))

    def test_reponse_ajoutee_apres_traitement(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        self.client.post(f"/api/conversations/{cid}/messages", json={"texte": "Bonjour"},
                         headers={"X-Session-Token": jeton})
        fil = None
        for _ in range(60):
            fil = self.client.get(f"/api/conversations/{cid}", headers={"X-Session-Token": jeton}).json()
            if len(fil["messages"]) >= 2:
                break
            time.sleep(0.05)
        roles = [m["role"] for m in fil["messages"]]
        self.assertEqual(roles, ["user", "assistant"], roles)
        self.assertEqual(fil["messages"][1]["statut"], "termine")
        self.assertEqual(fil["messages"][0]["statut"], "termine")

    def test_idempotence(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        corps = {"texte": "Quelle semence pour le fonio ?", "idempotency_key": "cle-unique"}
        premier = self.client.post(f"/api/conversations/{cid}/messages", json=corps,
                                   headers={"X-Session-Token": jeton})
        second = self.client.post(f"/api/conversations/{cid}/messages", json=corps,
                                  headers={"X-Session-Token": jeton})
        self.assertEqual(premier.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["rejoue"])
        self.assertEqual(premier.json()["message_id"], second.json()["message_id"])
        total = conv._db().execute("SELECT COUNT(*) n FROM messages WHERE conversation_id=? AND role='user'",
                                   (cid,)).fetchone()["n"]
        self.assertEqual(total, 1, "une clé d'idempotence ne doit produire qu'un message")

    def test_message_trop_long_refuse(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        r = self.client.post(f"/api/conversations/{cid}/messages",
                             json={"texte": "a" * (conv.MAX_MESSAGE + 1)},
                             headers={"X-Session-Token": jeton})
        self.assertEqual(r.status_code, 422)

    def test_reponse_longue_acceptee(self):
        """Une réponse d'agent dépasse la limite d'une question sans être perdue."""
        cid = conv.creer_conversation(conv.creer_session()["session_id"])["conversation_id"]
        question = conv.ajouter_message(cid, "user", "Comment fertiliser le maïs ?")
        longue = "Réponse détaillée. " * 150            # ~2850 caractères : > MAX_MESSAGE
        self.assertGreater(len(longue), conv.MAX_MESSAGE)
        rep = conv.repondre(cid, question["message_id"], longue, "termine")
        fil = conv.fil(conv._db().execute(
            "SELECT session_id FROM conversations WHERE conversation_id=?", (cid,)).fetchone()["session_id"],
            cid)
        assistant = [m for m in fil["messages"] if m["role"] == "assistant"]
        self.assertEqual(len(assistant), 1, fil["messages"])
        self.assertGreater(len(assistant[0]["contenu"]), conv.MAX_MESSAGE)
        self.assertEqual(assistant[0]["statut"], "termine")
        self.assertTrue(rep["message_id"].startswith("msg_"))
        # au-delà de MAX_REPONSE, on refuse toujours (garde-fou)
        with self.assertRaises(ValueError):
            conv.ajouter_message(cid, "assistant", "a" * (conv.MAX_REPONSE + 1))

    def test_message_vide_refuse(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        r = self.client.post(f"/api/conversations/{cid}/messages", json={"texte": " "},
                             headers={"X-Session-Token": jeton})
        self.assertIn(r.status_code, (400, 422), r.text)

    def test_contexte_serveur_ajoute_au_prompt(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        vus = {}

        def capture(cid, mid, texte, profil):
            vus["texte"] = texte
        ancien = api._executer_message
        api._executer_message = capture
        try:
            self.client.post(f"/api/conversations/{cid}/messages",
                             json={"texte": "Quel engrais ?", "culture_id": "cacao",
                                   "localite": "Daloa", "stade": "floraison"},
                             headers={"X-Session-Token": jeton})
            for _ in range(50):
                if "texte" in vus:
                    break
                time.sleep(0.05)
        finally:
            api._executer_message = ancien
        self.assertIn("culture : cacao", vus.get("texte", ""))
        self.assertIn("localité : Daloa", vus.get("texte", ""))


class TestPurge(Base):
    def test_purge_des_expires(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        conv._db().execute("UPDATE conversations SET expires_at=? WHERE conversation_id=?",
                           (int(time.time()) - 3600, cid))
        conv._db().commit()
        bilan = conv.purger_expire()
        self.assertGreaterEqual(bilan["conversations"], 1)
        self.assertIsNone(conv.fil(jeton and conv.session_valide(jeton) or "", cid))



class TestProtectionDesRoutes(Base):
    def test_cle_du_moteur_exigee(self):
        """Les quatre routes de conversation doivent exiger la clé du moteur.

        Test statique : on vérifie la dépendance dans la source, car les tests
        tournent avec AGRO_SANS_AUTH=1 pour ne pas manipuler de clé.
        """
        source = (ROOT / "serveur_api.py").read_text(encoding="utf-8")
        for fonction in ("def nouvelle_session(", "def nouvelle_conversation(",
                         "def lire_conversation(", "def envoyer_message("):
            debut = source.index(fonction)
            fin = source.index("):", debut)
            signature = source[debut:fin]
            self.assertIn("Depends(garde_cle)", signature, fonction)

    def test_session_exigee_pour_lire_un_fil(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        r = self.client.get(f"/api/conversations/{cid}")
        self.assertEqual(r.status_code, 401)


class TestContrat(Base):
    def test_forme_de_la_reponse(self):
        jeton = self.session()
        cid = self.conversation(jeton)
        self.client.post(f"/api/conversations/{cid}/messages", json={"texte": "Bonjour"},
                         headers={"X-Session-Token": jeton})
        fil = self.client.get(f"/api/conversations/{cid}", headers={"X-Session-Token": jeton}).json()
        for cle in ("conversation_id", "statut", "cree_le", "expire_le", "messages"):
            self.assertIn(cle, fil)
        m = fil["messages"][0]
        for cle in ("message_id", "role", "contenu", "statut", "sources"):
            self.assertIn(cle, m)
        self.assertNotIn("session_token", json.dumps(fil))


if __name__ == "__main__":
    unittest.main(verbosity=2)
