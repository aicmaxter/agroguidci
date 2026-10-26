"""tests_scene3d.py — contrat de la scène 3D (option B du cahier des charges).

Contrôles statiques : poids, absence d'actif externe, garde-fous d'appareil,
mise en pause, aucune boucle d'animation, repli photo, accessibilité.
    python -m unittest tests_scene3d
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JS = ROOT / "web" / "assets" / "scene3d.js"
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "assets" / "site.css").read_text(encoding="utf-8")
CODE = JS.read_text(encoding="utf-8")


class TestScene3D(unittest.TestCase):
    def test_poids(self):
        self.assertTrue(JS.exists())
        self.assertLess(JS.stat().st_size, 500 * 1024, "la scène doit rester sous 500 Ko")
        self.assertLess(JS.stat().st_size, 60 * 1024, "aucune bibliothèque 3D n'est embarquée")

    def test_aucun_actif_externe(self):
        for motif in (".glb", ".gltf", ".obj", "fetch(", "XMLHttpRequest", "import "):
            self.assertNotIn(motif, CODE, f"la scène ne doit rien télécharger ({motif})")

    def test_garde_fous_appareil(self):
        for garde in ("prefers-reduced-motion", "saveData", "effectiveType", "deviceMemory",
                      "hardwareConcurrency", "getContext(\"webgl\""):
            self.assertIn(garde, CODE, f"garde-fou manquant : {garde}")

    def test_mise_en_pause(self):
        self.assertIn("visibilitychange", CODE)
        self.assertIn("IntersectionObserver", CODE)
        self.assertIn("cancelAnimationFrame", CODE)
        self.assertIn("pagehide", CODE)

    def test_aucune_boucle_automatique(self):
        # le seul appel à requestAnimationFrame(boucle) doit dépendre d'une action
        appels = re.findall(r"requestAnimationFrame\(boucle\)", CODE)
        self.assertEqual(len(appels), 1, "une seule boucle, pilotée par reveiller()")
        self.assertIn("if (!visible || !ongletActif) return;", CODE)
        self.assertNotIn("enMouvement = true", CODE)
        self.assertIsNone(re.search(r"setInterval\(", CODE), "aucun setInterval")

    def test_repli_photo(self):
        self.assertIn('<picture class="hero-repli">', INDEX)
        self.assertIn('id="scene3d"', INDEX)
        self.assertIn(".hero-figure.scene-active .hero-repli { visibility: hidden; }", CSS)
        self.assertIn(".hero-figure.scene-active #scene3d { display: block; }", CSS)

    def test_chargement_apres_le_contenu(self):
        self.assertIn("requestIdleCallback", CODE)
        self.assertIn("window.addEventListener(\"load\"", CODE)
        self.assertIn('src="assets/scene3d.js', INDEX)
        self.assertIn("defer", INDEX.split('src="assets/scene3d.js')[1][:40])

    def test_accessibilite(self):
        self.assertIn('aria-label="Scène 3D', INDEX)
        self.assertIn('id="scene3d" aria-hidden="true"', INDEX)
        self.assertIn('figure.setAttribute("tabindex", "0")', CODE)
        self.assertIn("ArrowLeft", CODE)

    def test_mouvement_reduit_coupe_tout(self):
        extrait = CSS.split("@media (prefers-reduced-motion: reduce)")[1][:600]
        self.assertIn("animation-duration", extrait)


if __name__ == "__main__":
    unittest.main(verbosity=2)
