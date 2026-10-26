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
import outils  # noqa: E402
import permissions  # noqa: E402
import serveur_api as api  # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # double d'exécution : le fil passe directement à « terminé » avec une réponse fixe
        def faux_executeur(cid, mid, texte, profil, sid=None, risque="faible", urgence=False):
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

    def test_avancement_puis_reponse_dans_la_meme_bulle(self):
        """L'extrait publié pendant la rédaction est remplacé, pas dupliqué."""
        sid = conv.creer_session()["session_id"]
        cid = conv.creer_conversation(sid)["conversation_id"]
        question = conv.ajouter_message(cid, "user", "Comment planter le fonio ?")
        etat: dict = {"id": None}
        api._publier_avancement(cid, "Besoin identifié : planter le fonio.", etat)
        self.assertIsNotNone(etat["id"])
        # deuxième jalon immédiat : ignoré (lissage des écritures en base)
        api._publier_avancement(cid, "Extrait trop rapproché, doit être ignoré.", etat)
        fil = conv.fil(sid, cid)
        agents = [m for m in fil["messages"] if m["role"] == "assistant"]
        self.assertEqual(len(agents), 1, agents)
        self.assertEqual(agents[0]["contenu"], "Besoin identifié : planter le fonio.")
        # après la fenêtre de lissage, l'extrait suivant remplace bien le précédent
        etat["maj"] = 0.0
        api._publier_avancement(cid, "Extrait du volet agronomique en cours.", etat)
        fil = conv.fil(sid, cid)
        agents = [m for m in fil["messages"] if m["role"] == "assistant"]
        self.assertEqual(len(agents), 1, agents)
        self.assertIn("Extrait du volet", agents[0]["contenu"])
        self.assertEqual(agents[0]["statut"], "en_cours")
        # un fragment plus court ne doit pas faire rétrécir la bulle
        etat["maj"] = 0.0
        api._publier_avancement(cid, "court", etat)
        agents = [m for m in conv.fil(sid, cid)["messages"] if m["role"] == "assistant"]
        self.assertIn("Extrait du volet", agents[0]["contenu"])
        # la réponse finale réutilise la bulle d'avancement
        conv.repondre(cid, question["message_id"], "Réponse finale de l'agent.", "termine",
                      sources=[{"titre": "knowledge/fonio.md"}], assistant_id=etat["id"])
        fil = conv.fil(sid, cid)
        agents = [m for m in fil["messages"] if m["role"] == "assistant"]
        self.assertEqual(len(agents), 1, "une seule bulle d'agent par question")
        self.assertEqual(agents[0]["message_id"], etat["id"])
        self.assertEqual(agents[0]["contenu"], "Réponse finale de l'agent.")
        self.assertEqual(agents[0]["statut"], "termine")
        self.assertEqual(len(agents[0]["sources"]), 1)
        self.assertEqual(fil["messages"][0]["statut"], "termine")

    def test_fiche_culture_jointe_a_la_demande(self):
        """Le chat ouvert depuis une fiche reçoit les chiffres et limites de la fiche."""
        extrait = api.extrait_fiche("igname")
        self.assertIn("EXTRAIT DE LA FICHE", extrait)
        self.assertIn("Igname", extrait)
        self.assertLessEqual(len(extrait), 1800)
        self.assertIn("Plantation / semis", extrait)
        # insensible à la casse et au nom affiché
        self.assertEqual(api.extrait_fiche("Igname"), extrait)
        self.assertEqual(api.extrait_fiche("culture-inconnue"), "")
        self.assertEqual(api.extrait_fiche(None), "")

    def test_culture_detectee_depuis_l_accueil(self):
        """Sans fiche d'origine, la culture citée est reconnue (accueil)."""
        self.assertEqual(api.culture_detectee("Quand planter l'igname à Bouaké ?"), "igname")
        self.assertEqual(api.culture_detectee("le kilo de gingembre se vend combien"), "gingembre")
        self.assertEqual(api.culture_detectee("rotation avec du pois bambara"), "voandzou")
        # le maïs a désormais sa fiche : la culture est reconnue
        self.assertEqual(api.culture_detectee("Quel engrais pour le maïs ?"), "mais")
        # une culture sans fiche reste non reconnue
        self.assertIsNone(api.culture_detectee("Quel engrais pour le sorgho ?"))
        self.assertIsNone(api.culture_detectee(""))

    def test_permissions_mots_entiers(self):
        """Un mot qui contient un déclencheur ne doit pas déclencher un refus."""
        self.assertEqual(permissions.intentions_interdites("la fiche publiée par AGROGUIDCI"), [])
        self.assertEqual(permissions.intentions_interdites("Quand planter l'igname ?"), [])
        self.assertEqual([i["action"] for i in
                          permissions.intentions_interdites("Achète 2 sacs d'urée et fais livrer")],
                         ["acheter_payer"])
        self.assertEqual([i["action"] for i in
                          permissions.intentions_interdites("Publie mon annonce sur Facebook")],
                         ["publier"])
        self.assertEqual(permissions.intentions_interdites(
            "Écris-moi un message à envoyer à ma coopérative"), [])

    def test_consigne_chat_ignoree_par_les_outils(self):
        """La consigne de forme ne doit jamais fournir de « localité » aux outils."""
        self.assertTrue(api.CONSIGNE_CHAT.startswith("[CONSIGNE_INTERNE]"))
        self.assertIsNone(outils.extraire_localite("Quand planter ?" + api.CONSIGNE_CHAT))
        self.assertEqual(outils.extraire_localite("Je suis à Bouaké et je veux planter"), "Bouake")

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

        def capture(cid, mid, texte, profil, sid=None, risque="faible", urgence=False):
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


class TestMigration(unittest.TestCase):
    """Une base ouverte avec l'ancien plafond (4000) doit être convertie sans perte."""

    def test_base_ancienne_migree(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        ancien_chemin, ancienne_connexion = conv.CHEMIN, conv._connexion
        chemin = Path(tempfile.mkdtemp(prefix="agro-mig-")) / "conversations.db"
        c = sqlite3.connect(str(chemin))
        c.executescript("""
        CREATE TABLE sessions (session_id TEXT PRIMARY KEY, token_hash BLOB NOT NULL UNIQUE,
          created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
          revoked_at INTEGER);
        CREATE TABLE conversations (conversation_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE, titre TEXT,
          culture_id TEXT, localite TEXT, statut TEXT NOT NULL DEFAULT 'active'
          CHECK (statut IN ('active','archivee','expiree')), created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
        CREATE TABLE messages (message_id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK (role IN ('user','assistant','systeme')),
          contenu TEXT NOT NULL CHECK (length(contenu) BETWEEN 1 AND 4000),
          statut TEXT NOT NULL CHECK (statut IN ('en_cours','termine','echec',
                  'info_insuffisante','clarification','escalade')),
          mission_id TEXT, demande_id TEXT, erreur TEXT, sources_json TEXT, idempotency_key TEXT,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          UNIQUE (conversation_id, idempotency_key));
        INSERT INTO sessions VALUES ('ses_x', X'00', 1, 1, 9999999999, NULL);
        INSERT INTO conversations VALUES ('cnv_x','ses_x',NULL,NULL,NULL,'active',1,1,9999999999);
        INSERT INTO messages VALUES ('msg_x','cnv_x','user','bonjour','termine',
          NULL,NULL,NULL,NULL,NULL,1,1);
        """)
        c.commit()
        c.close()
        try:
            conv.CHEMIN = chemin
            conv._connexion = None
            base = conv._db()
            self.assertEqual(base.execute("PRAGMA user_version").fetchone()[0], conv.VERSION_SCHEMA)
            self.assertEqual(base.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"], 1,
                             "aucune ligne perdue par la migration")
            long_message = conv.ajouter_message("cnv_x", "assistant", "a" * 10000)
            self.assertEqual(len(long_message["contenu"]), 10000)
        finally:
            try:
                conv._connexion.close()
            except Exception:
                pass
            conv.CHEMIN, conv._connexion = ancien_chemin, ancienne_connexion


if __name__ == "__main__":
    unittest.main(verbosity=2)
