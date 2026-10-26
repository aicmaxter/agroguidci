"""tests_vitrine_v9.py — contrôles statiques de la vitrine (Lot A et Lot D).

Aucun réseau, aucun navigateur, aucun appel de modèle : uniquement la lecture des
fichiers produits et des données sources.

    python tests_vitrine_v9.py
"""

from __future__ import annotations

import html
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
CONTENU = ROOT / "content"

INDEX_BRUT = (WEB / "index.html").read_text(encoding="utf-8")
INDEX = html.unescape(INDEX_BRUT)
DATA = json.loads((WEB / "assets" / "cultures.json").read_text(encoding="utf-8"))["cultures"]
CHAT = (WEB / "assets" / "chat.js").read_text(encoding="utf-8")
UI = (WEB / "assets" / "ui.js").read_text(encoding="utf-8")
CSS = (WEB / "assets" / "site.css").read_text(encoding="utf-8")

SECTIONS_ATTENDUES = [
    "presentation", "conditions", "varietes", "calendrier", "preparation", "semis",
    "entretien", "sante", "recolte", "conservation", "economie",
]


class TestBlocAccueil(unittest.TestCase):
    def test_bouton_abonnement_absent(self):
        self.assertNotIn("Écrire pour un abonnement", INDEX)
        bloc = INDEX.split('class="cta-band reveal"')[1].split("</div>")[0]
        self.assertNotIn("mailto:", bloc, "le bloc ne doit plus contenir de lien mailto")

    def test_texte_sans_abonnement_dans_le_bloc(self):
        bloc = INDEX.split('class="cta-band reveal"')[1].split("</div>")[0]
        self.assertNotIn("abonnement", bloc.lower())
        self.assertIn("Vos 15 crédits gratuits vous attendent.", bloc)

    def test_bouton_unique_et_pulsation(self):
        bloc = INDEX.split('class="cta-band reveal"')[1].split("</div>")[0]
        self.assertEqual(bloc.count("<button"), 1, "un seul bouton dans le bloc")
        self.assertIn('data-chat="ouvrir"', bloc)
        self.assertIn("btn-attention", INDEX)
        self.assertIn("@keyframes attentionDouce", CSS)
        self.assertIn("prefers-reduced-motion", CSS)

    def test_bouton_ouvre_le_chat(self):
        self.assertIn('id="ctaPoserQuestion"', INDEX)
        self.assertIn('data-chat="ouvrir"', INDEX)
        self.assertTrue('data-chat=' in CHAT and "addEventListener" in CHAT,
                        "chat.js doit brancher les déclencheurs data-chat")


class TestOffresEtAppels(unittest.TestCase):
    """§3 et §6 : un seul appel à la question, deux packs, pas de suivi."""

    def test_un_seul_appel_dans_le_hero(self):
        hero = INDEX.split('<section class="hero" id="accueil">')[1].split("</section>")[0]
        self.assertEqual(hero.count('data-chat="ouvrir"'), 1,
                         "un seul bouton de question dans le bloc d'accueil")
        self.assertEqual(hero.count("<button"), 1,
                         "héros : un seul bouton (obtenir un conseil), le reste est un lien")
        self.assertIn('href="#piliers"', hero, "héros : le second appel mène aux piliers")

    def test_pas_de_bouton_de_question_dans_l_entete(self):
        entete = INDEX.split('<header class="site-header"')[1].split("</header>")[0]
        self.assertNotIn('data-chat="ouvrir"', entete)
        self.assertNotIn("Conseil gratuit", entete)

    def test_suivi_personnalise_absent(self):
        for terme in ("Suivi personnalisé", "9 900", "Choisir le suivi"):
            self.assertNotIn(terme, INDEX, f"offre de suivi encore présentée : {terme}")

    def test_deux_packs_avec_montants_et_credits(self):
        self.assertIn('data-pack="decouverte"', INDEX)
        self.assertIn('data-pack="avance"', INDEX)
        self.assertIn('<span class="amount">599</span>', INDEX)
        self.assertIn('<span class="amount">3\u00a0999</span>', INDEX, "montant du pack Avancé (espace insécable)")
        self.assertIn("<strong>30 crédits</strong>", INDEX)
        self.assertIn("<strong>200 crédits</strong>", INDEX)
        self.assertEqual(INDEX.count("data-achat="), 2, "exactement deux packs")
        self.assertEqual(INDEX.count('class="plan reveal"'), 2, "aucune offre intermédiaire")

    def test_aucun_achat_presente_comme_disponible(self):
        self.assertIn("Achat en ligne pas encore disponible", INDEX)
        for m in re.finditer(r'<button[^>]*data-achat="[^"]+"[^>]*>', INDEX):
            self.assertIn("disabled", m.group(0),
                          "sans paiement vérifié, le bouton d'achat doit être désactivé")

    def test_aucun_credit_local_dans_le_navigateur(self):
        self.assertNotIn("agro.credits", UI, "plus de solde manipulable en localStorage")
        self.assertNotIn("CLE_CREDITS", UI)
        self.assertNotIn("crédits ajoutés localement", UI)
        self.assertIn("/api/credits", UI, "le solde vient du serveur")

    def test_le_formulaire_reprend_la_question_dans_le_chat(self):
        self.assertIn("agro:question", UI)
        self.assertIn("agro:question", CHAT)
        self.assertIn("stopImmediatePropagation", UI,
                      "le formulaire ne doit pas lancer une seconde consultation")

    def test_gratuit_affiche_15_et_7_heures(self):
        self.assertIn("15 crédits gratuits", INDEX)
        self.assertIn("toutes les 7 heures", INDEX)


class TestCultures(unittest.TestCase):
    def test_une_carte_par_culture(self):
        self.assertEqual(INDEX.count("class=\"crop reveal"), len(DATA))

    def test_compteurs_calcules(self):
        vivrieres = sum(1 for c in DATA if c["type"] == "vivriere")
        epices = sum(1 for c in DATA if c["type"] == "epice")
        self.assertIn(f"Toutes <span>{len(DATA)}</span>", INDEX)
        self.assertIn(f"Vivrières <span>{vivrieres}</span>", INDEX)
        self.assertIn(f"Épices <span>{epices}</span>", INDEX)
        self.assertIn("majCompteurs", UI, "les compteurs doivent aussi être recalculés côté client")

    def test_chaque_carte_lien_vers_sa_fiche(self):
        for c in DATA:
            self.assertIn(f'href="cultures/{c["id"]}"', INDEX, c["id"])

    def test_fiches_generees_completes(self):
        for c in DATA:
            page = (WEB / "cultures" / f'{c["id"]}.html').read_text(encoding="utf-8")
            for cle in SECTIONS_ATTENDUES:
                self.assertIn(f'id="{cle}"', page, f'{c["id"]} : section {cle} manquante')
            self.assertIn('id="tutoriel"', page)
            self.assertIn('id="sources"', page)
            self.assertIn("Niveau de confiance", page)
            self.assertIn('data-chat="ouvrir"', page)
            self.assertIn(f'data-culture="{c["id"]}"', page)
            self.assertIn("Dernière mise à jour", page)

    def test_aucun_prix_invente_dans_les_fiches(self):
        # Une fiche ne doit pas afficher un prix ferme : seuls des renvois au relevé existent.
        for c in DATA:
            page = (WEB / "cultures" / f'{c["id"]}.html').read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\b\d[\d\s]{2,}\s*(FCFA|fcfa)\b", page),
                              f"{c['id']} : un montant en FCFA est présent")

    def test_sources_jamais_inventees(self):
        for f in sorted(CONTENU.glob("cultures-*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            for cid, c in d.get("cultures", {}).items():
                self.assertIn(c.get("confiance"), ("documente", "partiel", "faible"), cid)
                self.assertTrue(c.get("limites"), f"{cid} : limites absentes")
                for s in c.get("sources") or []:
                    self.assertTrue(s.get("organisme") and s.get("titre"), f"{cid} : source incomplète")


class TestChat(unittest.TestCase):
    def test_dialogue_present(self):
        self.assertIn('<dialog id="chatDialogue"', INDEX)
        self.assertIn('id="chatFil"', INDEX)
        self.assertIn('id="chatTexte"', INDEX)
        self.assertIn("assets/chat.js", INDEX)

    def test_accessibilite_de_base(self):
        for marque in ('aria-live="polite"', 'aria-label="Fermer la conversation"',
                       'class="sr-only" for="chatTexte"'):
            self.assertIn(marque, INDEX)
        self.assertIn('e.key === "Escape"', CHAT)
        self.assertIn('e.key === "Enter" && !e.shiftKey', CHAT)

    def test_appels_api_et_etats(self):
        self.assertIn("/api/conversations", CHAT)
        self.assertIn("idempotency_key", CHAT)
        self.assertIn("Aucune réponse n'a été inventée", CHAT)
        self.assertIn("Nouvelle conversation", INDEX)

    def test_aucune_cle_dans_le_frontend(self):
        for f in (WEB / "index.html", WEB / "assets" / "chat.js", WEB / "assets" / "ui.js",
                  WEB / "assets" / "app.js"):
            txt = Path(f).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"sk-[A-Za-z0-9_\-]{10,}", txt), f)
            self.assertNotIn("AGRO_ENGINE_KEY", txt, f)
            self.assertNotIn("X-API-Key", txt, f)


class TestEnTetesEtConfig(unittest.TestCase):
    def test_vercel_json(self):
        d = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        for route in ("api/conversations/index.js", "api/conversations/[id].js",
                      "api/conversations/[id]/messages.js"):
            self.assertIn(route, d.get("functions", {}))
        csp = json.dumps(d)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_pages_generes_a_jour(self):
        import subprocess
        for script in ("scripts/gen_index.py", "scripts/build_cultures.py"):
            r = subprocess.run([sys.executable, script, "--verifier"], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(r.returncode, 0, f"{script} : {r.stdout}{r.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
