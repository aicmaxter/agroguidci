"""
mission.py — journal de mission AGROGUIDCI (format PARTIE E des specs J2).

Un journal par mission, une ligne par etape de la boucle d'autonomie
(GOAL / PLAN / ACT / OBSERVE / DECIDE / ADAPT / VERIFY / CONTINUE-STOP-ESCALATE),
avec les champs minimaux exiges :

    mission_id ; horodatage ; demande ; agent ; outil ; action ; resultat_attendu ;
    resultat_observe ; statut ; tentatives ; source ; erreur ; decision ;
    approbation_humaine ; preuve ; etat_final

Fichiers : data/missions/<mission_id>.jsonl (journal brut) et
out/<run>/mission.md (tableau lisible, joint au rapport).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MISSIONS = ROOT / "data" / "missions"

CHAMPS = ("phase", "mission_id", "horodatage", "demande", "agent", "outil", "action",
          "resultat_attendu", "resultat_observe", "statut", "tentatives", "source",
          "erreur", "decision", "approbation_humaine", "preuve", "etat_final")

ETATS_FINAUX = ("TERMINEE_VERIFIEE", "A_VALIDER", "EN_ATTENTE_INFORMATION",
                "ECHEC_OUTIL", "ARRETEE_PERMISSION", "ESCALADE_HUMAINE")

DECISIONS = ("CONTINUE", "STOP", "ESCALATE")


def _horodate() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class JournalMission:
    """Journal d'une mission : chaque phase de la boucle y laisse une trace."""

    def __init__(self, demande: str, dossier: Path, mission_id: str | None = None,
                 agent: str = "AGROGUIDCI Agent Agronome Expert") -> None:
        self.mission_id = mission_id or f"mis_{time.strftime('%Y%m%d-%H%M%S')}"
        self.demande = demande
        self.dossier = Path(dossier)
        self.agent = agent
        self.entrees: list[dict] = []
        MISSIONS.mkdir(parents=True, exist_ok=True)
        self.chemin = MISSIONS / f"{self.mission_id}.jsonl"

    # -- ecriture ----------------------------------------------------------
    def entree(self, phase: str, **champs) -> dict:
        """Ajoute une etape. Les champs absents sont completes, jamais inventes."""
        e = {c: None for c in CHAMPS}
        e.update({
            "phase": phase,
            "mission_id": self.mission_id,
            "horodatage": _horodate(),
            "demande": self.demande[:400],
            "agent": champs.pop("agent", self.agent),
            "tentatives": champs.pop("tentatives", 1),
            "decision": champs.pop("decision", None),
            "approbation_humaine": champs.pop("approbation_humaine", None),
            **champs,
        })
        self.entrees.append(e)
        with self.chemin.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e

    # -- etat final --------------------------------------------------------
    def etat_final(self) -> str:
        """Etat final selon la PARTIE F (precedence du plus bloquant au plus abouti)."""
        decisions = [e.get("decision") for e in self.entrees]
        observe = [e for e in self.entrees if e["phase"] == "OBSERVE"]
        permissions = [e for e in self.entrees if e.get("action") == "permission"]
        verif = [e for e in self.entrees if e["phase"] == "VERIFY"]

        if any(e.get("statut") == "ARRETEE_PERMISSION" for e in self.entrees):
            return "ARRETEE_PERMISSION"
        # Une information indispensable manque : c'est la premiere chose a traiter,
        # avant toute validation ou escalade (le producteur doit repondre).
        if any(e.get("statut") == "EN_ATTENTE_INFORMATION" for e in self.entrees):
            return "EN_ATTENTE_INFORMATION"
        if any(e.get("statut") == "A_VALIDER" for e in self.entrees):
            return "A_VALIDER"
        if any(e.get("statut") == "ESCALADE_HUMAINE" for e in self.entrees) or "ESCALATE" in decisions:
            return "A_VALIDER" if any(e.get("approbation_humaine") == "demandee" for e in self.entrees) \
                else "ESCALADE_HUMAINE"
        if any(o.get("statut") == "ECHEC_OUTIL" for o in observe) or \
           any(e.get("statut") == "ECHEC_OUTIL" for e in self.entrees):
            return "ECHEC_OUTIL"
        if verif and all(v.get("statut") in ("OK", "PARTIEL") for v in verif) and \
           all(e.get("statut") != "ECHEC" for e in self.entrees):
            return "TERMINEE_VERIFIEE"
        return "A_VALIDER"

    # -- restitution -------------------------------------------------------
    def tableau(self) -> str:
        """Tableau markdown lisible (joint au rapport de mission)."""
        lignes = ["| phase | agent | outil | attendu | observe | decision | statut | preuve |",
                  "|---|---|---|---|---|---|---|---|"]
        for e in self.entrees:
            cell = lambda v: (str(v).replace("|", "/").replace("\n", " ")[:110] if v else "—")  # noqa: E731
            lignes.append(f"| {cell(e['phase'])} | {cell(e['agent'])} | {cell(e['outil'])} "
                          f"| {cell(e['resultat_attendu'])} | {cell(e['resultat_observe'])} "
                          f"| {cell(e['decision'])} | {cell(e['statut'])} | {cell(e['preuve'])} |")
        return "\n".join(lignes)

    def ecrire_markdown(self, etat: str | None = None) -> Path:
        etat = etat or self.etat_final()
        chemin = self.dossier / "mission.md"
        lignes = [f"# Journal de mission — {self.mission_id}",
                  "",
                  f"**Demande** : {self.demande}",
                  f"**Agent responsable** : {self.agent}",
                  f"**Etat final** : **{etat}**",
                  f"**Journal brut** : `{self.chemin}`",
                  "",
                  self.tableau(), ""]
        chemin.write_text("\n".join(lignes), encoding="utf-8")
        return chemin


if __name__ == "__main__":
    d = ROOT / "out" / "mission-test"
    d.mkdir(parents=True, exist_ok=True)
    j = JournalMission("test de journal", d)
    j.entree("GOAL", agent="principal", resultat_attendu="clarifier", statut="OK")
    j.entree("ACT", agent="recherche", outil="meteo_et_pluies", action="lire_documents",
             resultat_observe="1219 mm", statut="OK", source="Open-Meteo", decision="CONTINUE")
    j.entree("VERIFY", agent="principal", action="verification", resultat_observe="unites OK",
             statut="OK", preuve=str(j.chemin))
    print(j.ecrire_markdown())
    print("etat final :", j.etat_final())
