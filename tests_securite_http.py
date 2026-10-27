#!/usr/bin/env python
"""tests_securite_http.py — garde-fous des requêtes sortantes (SSRF, fuite d'en-tête).

Aucune requête réseau réelle : la résolution DNS est remplacée par un double, et
l'ouvreur urllib par un objet qui lève s'il est appelé. Un test qui passe ici
prouve que le refus a lieu AVANT toute connexion.

    python tests_securite_http.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import agrokit  # noqa: E402
import outils  # noqa: E402


class GardeUrls(unittest.TestCase):
    def setUp(self) -> None:
        self._garde = agrokit.GARDE_HTTP
        self._adresses = agrokit._adresses
        agrokit.GARDE_HTTP = True
        agrokit._adresses = lambda hote: ["93.184.216.34"]      # IPv4 publique
        agrokit._RESOLUS.clear()

    def tearDown(self) -> None:
        agrokit.GARDE_HTTP = self._garde
        agrokit._adresses = self._adresses
        agrokit._RESOLUS.clear()

    # --- schémas ---------------------------------------------------------
    def test_schemas_interdits(self):
        for url in ("file:///etc/passwd", "gopher://127.0.0.1:70/_x",
                    "dict://127.0.0.1:11211/stat", "ftp://example.org/x",
                    "data:text/plain,hello", "javascript:alert(1)"):
            with self.subTest(url=url):
                with self.assertRaises(agrokit.UrlRefusee):
                    agrokit.verifier_url(url)

    # --- cibles internes -------------------------------------------------
    def test_plages_privees_et_metadonnees(self):
        for url in ("http://169.254.169.254/latest/meta-data/",
                    "http://10.0.0.5/admin", "http://192.168.1.10:8080/",
                    "http://172.16.4.4/", "http://0.0.0.0:8080/",
                    "http://[::1]:8080/", "http://[fd00::1]/"):
            with self.subTest(url=url):
                with self.assertRaises(agrokit.UrlRefusee):
                    agrokit.verifier_url(url)

    def test_domaine_inconnu_refuse(self):
        for url in ("https://attaquant.example/pwn", "https://api.open-meteo.com.attaquant.example/x",
                    "http://sslip.io.evil.example/"):
            with self.subTest(url=url):
                with self.assertRaises(agrokit.UrlRefusee):
                    agrokit.verifier_url(url)

    # --- rebinding -------------------------------------------------------
    def test_hote_autorise_qui_resout_en_prive(self):
        agrokit._adresses = lambda hote: ["127.0.0.1"]
        with self.assertRaises(agrokit.UrlRefusee):
            agrokit.verifier_url("https://api.open-meteo.com/v1/forecast")
        agrokit._adresses = lambda hote: ["169.254.169.254"]
        with self.assertRaises(agrokit.UrlRefusee):
            agrokit.verifier_url("https://fr.wikipedia.org/w/api.php")

    # --- autorisations ---------------------------------------------------
    def test_services_autorises(self):
        self.assertEqual(agrokit.verifier_url("https://api.open-meteo.com/v1/forecast?latitude=1"),
                         "https://api.open-meteo.com/v1/forecast?latitude=1")
        self.assertEqual(agrokit.verifier_url("http://127.0.0.1:8000/health"),
                         "http://127.0.0.1:8000/health")

    # --- en-têtes : jamais de clé vers un tiers --------------------------
    def test_cle_jamais_envoyee_a_un_tiers(self):
        entetes = {"X-API-Key": "clef", "Authorization": "Bearer jeton", "X-Session-Token": "s"}
        interne = agrokit.entetes_pour("http://127.0.0.1:8000/delegate", entetes)
        self.assertEqual(interne.get("X-API-Key"), "clef")
        self.assertEqual(interne.get("Authorization"), "Bearer jeton")
        public = agrokit.entetes_pour("https://api.open-meteo.com/v1/forecast", entetes)
        self.assertEqual(public, {})
        modele = agrokit.entetes_pour("https://api.deepseek.com/v1/chat/completions",
                                      {"Authorization": "Bearer jeton"})
        self.assertEqual(modele.get("Authorization"), "Bearer jeton")

    # --- aucune connexion avant refus ------------------------------------
    def test_refus_avant_toute_connexion(self):
        appels = []

        def ouvreur_interdit():
            appels.append(1)
            raise AssertionError("connexion tentée alors que l'URL devait être refusée")

        ancien = agrokit._ouvreur
        agrokit._ouvreur = ouvreur_interdit
        try:
            with self.assertRaises(agrokit.UrlRefusee):
                agrokit._http("GET", "http://169.254.169.254/latest/meta-data/")
            with self.assertRaises(agrokit.UrlRefusee):
                agrokit._http_stream("POST", "http://10.1.2.3/v1", {}, {})
        finally:
            agrokit._ouvreur = ancien
        self.assertEqual(appels, [])

    def test_outil_refuse_une_url_interne(self):
        code, message = outils._get("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(code, 0)
        self.assertIn("hors liste blanche", str(message))

    # --- redirections ----------------------------------------------------
    def test_redirection_refusee(self):
        with self.assertRaises(agrokit.UrlRefusee):
            agrokit._SansRedirection().redirect_request(
                None, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/")

    # --- interrupteur ----------------------------------------------------
    def test_interrupteur_desactive_la_garde(self):
        agrokit.GARDE_HTTP = False
        self.assertEqual(agrokit.verifier_url("http://10.0.0.5/x"), "http://10.0.0.5/x")


class ExecutionSysteme(unittest.TestCase):
    """L'action sensible n'ajoute jamais de valeur d'entrée dans la ligne de commande."""

    def test_argv_constant_meme_avec_metacaracteres(self):
        appels = []

        class Faux:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def faux_run(argv, **kwargs):
            appels.append((argv, kwargs))
            return Faux()

        ancien_subprocess = outils.subprocess
        ancien_exists = Path.exists
        outils.subprocess = type("S", (), {"run": staticmethod(faux_run),
                                           "SubprocessError": Exception})()
        Path.exists = lambda self: True
        try:
            outils.activer_rappels_executer({
                "source": "mets en place ; rm -rf / && whoami | powershell -c calc",
                "rappels": "x",
            })
        finally:
            outils.subprocess = ancien_subprocess
            Path.exists = ancien_exists
        self.assertEqual(len(appels), 2, "création + relecture attendues")
        for argv, kwargs in appels:
            self.assertIsInstance(argv, list)
            self.assertFalse(kwargs.get("shell"), "shell doit rester désactivé")
            joint = " ".join(argv)
            for interdit in ("rm -rf", "whoami", "powershell", "&&", "|"):
                self.assertNotIn(interdit, joint)
            self.assertEqual(argv[0], "schtasks")
            self.assertIn("/TN", argv)
            self.assertEqual(argv[argv.index("/TN") + 1], "AGROGUIDCI_Rappels")


if __name__ == "__main__":
    unittest.main(verbosity=2)
