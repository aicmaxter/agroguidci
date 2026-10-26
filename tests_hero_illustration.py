"""tests_hero_illustration.py — contrat de l'illustration du héros.

L'illustration fournie (île de cultures) remplace la scène 3D : une seule image,
prioritaire, avec repli, sans texte incrusté de l'interface d'origine.
    python -m unittest tests_hero_illustration
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "assets" / "site.css").read_text(encoding="utf-8")


class TestHeroIllustration(unittest.TestCase):
    def test_image_presente_et_legere(self):
        for nom, plafond in (("hero-ile.webp", 350), ("hero-ile.jpg", 350)):
            p = WEB / "assets" / nom
            self.assertTrue(p.exists(), f"{nom} manquant")
            self.assertLess(p.stat().st_size // 1024, plafond, f"{nom} dépasse {plafond} Ko")

    def test_une_seule_illustration_dans_le_heros(self):
        hero = INDEX.split('<section class="hero" id="accueil">')[1].split("</section>")[0]
        self.assertEqual(hero.count("<img"), 1, "une seule image dans le héros")
        self.assertIn("hero-ile.webp", hero)
        self.assertNotIn("scene3d", hero)
        self.assertNotIn("<canvas", hero)

    def test_la_3d_n_est_plus_chargee(self):
        self.assertNotIn("scene3d.js", INDEX, "la scène 3D ne doit plus être chargée")
        self.assertNotIn('id="scene3d"', INDEX)
        self.assertNotIn(".scene-active", CSS)

    def test_priorite_et_dimensions(self):
        hero = INDEX.split('<section class="hero" id="accueil">')[1].split("</section>")[0]
        self.assertIn('fetchpriority="high"', hero)
        self.assertIn('width="588"', hero)
        self.assertIn('height="513"', hero)
        self.assertIn('type="image/webp"', hero)

    def test_alt_descriptif(self):
        hero = INDEX.split('<section class="hero" id="accueil">')[1].split("</section>")[0]
        import re
        alt = re.search(r'alt="([^"]+)"', hero).group(1)
        self.assertGreater(len(alt), 40, "l'alt doit décrire la scène, pas répéter un mot-clé")
        for mot in ("cacaoyer", "bananier", "manioc", "poissons"):
            self.assertIn(mot, alt)

    def test_aucun_texte_de_maquette_republie(self):
        # l'image est un recadrage : les libellés de la maquette ne doivent pas être
        # republiés comme qualificatifs du héros (le contenu éditorial des fiches,
        # lui, garde ses formulations sourcées).
        hero = INDEX.split('<section class="hero" id="accueil">')[1].split("</section>")[0]
        for interdit in ("Conseil IA", "Très rentable", "Forte demande", "Formations &amp; Guides", "temps réel"):
            self.assertNotIn(interdit, hero, f"mention de maquette republiée dans le héros : {interdit}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
