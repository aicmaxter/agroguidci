/* AGROGUIDCI — prix du marché, crédits de conseil et consentement (ui.js)
   Aucune dépendance. Le quota gratuit est appliqué côté navigateur ; il sera
   doublé d'un contrôle serveur dès que les comptes utilisateurs existeront. */
(function () {
  "use strict";

  var CLE_CREDITS = "agro.credits.v1";
  var CLE_CONSENT = "agro.consentement.v1";
  var GRATUITS_PAR_MOIS = 3;

  /* ------------------------------------------------------------ prix au kilo */
  function fcfa(n) { return Number(n).toLocaleString("fr-FR"); }

  function rendrePrix(d) {
    var corps = document.getElementById("prixBody");
    if (!corps || !d || !d.produits || !d.produits.length) return;
    corps.innerHTML = "";
    d.produits.forEach(function (p) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td class="produit">' + echapper(p.nom) + "</td>" +
        '<td class="prix">' + fcfa(p.prix) + ' <span class="unite">FCFA/' + echapper(p.unite) + "</span></td>" +
        '<td class="marche">' + echapper(p.marche || "—") + "</td>";
      corps.appendChild(tr);
    });
    var semaine = document.getElementById("prixSemaine");
    if (semaine && d.semaine) semaine.textContent = d.semaine;
    var note = document.getElementById("prixNote");
    if (note) {
      note.innerHTML = echapper(d.avertissement || "") +
        (d.non_couvert ? "<br><strong>Non couvert :</strong> " + echapper(d.non_couvert) : "") +
        (d.source ? '<br>Source : <a href="' + echapper(d.source_url || "#") + '" target="_blank" rel="noreferrer">' +
          echapper(d.source) + "</a>." : "");
    }
  }

  function echapper(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  if (document.getElementById("prixBody")) {
    fetch("assets/prix.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(rendrePrix)
      .catch(function () {
        var note = document.getElementById("prixNote");
        if (note) note.textContent = "Relevé indisponible pour le moment. Aucun prix n'est affiché plutôt qu'un prix non vérifié.";
      });
  }

  /* ------------------------------------------------------------ crédits */
  function moisCourant() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
  }

  function lireCredits() {
    var c = { gratuits: GRATUITS_PAR_MOIS, payants: 0, mois: moisCourant() };
    try {
      var brut = JSON.parse(localStorage.getItem(CLE_CREDITS) || "null");
      if (brut && typeof brut === "object") c = brut;
    } catch (e) { /* stockage indisponible : on repart du quota */ }
    if (c.mois !== moisCourant()) { c.mois = moisCourant(); c.gratuits = GRATUITS_PAR_MOIS; }
    if (typeof c.gratuits !== "number") c.gratuits = GRATUITS_PAR_MOIS;
    if (typeof c.payants !== "number") c.payants = 0;
    return c;
  }

  function ecrireCredits(c) {
    try { localStorage.setItem(CLE_CREDITS, JSON.stringify(c)); } catch (e) { /* ignore */ }
  }

  function totalCredits(c) { return Math.max(0, c.gratuits) + Math.max(0, c.payants); }

  function afficherCredits() {
    var barre = document.getElementById("creditsBar");
    var compte = document.getElementById("creditsCount");
    if (!barre || !compte) return;
    var c = lireCredits();
    var total = totalCredits(c);
    compte.textContent = total;
    barre.classList.toggle("epuise", total === 0);
    var texte = document.getElementById("creditsTexte");
    if (texte) {
      texte.innerHTML = total > 0
        ? "Crédits disponibles : gratuit " + Math.max(0, c.gratuits) + "/" + GRATUITS_PAR_MOIS +
          " ce mois-ci" + (c.payants ? " + " + c.payants + " crédit(s) acheté(s)" : "") + "."
        : "Quota gratuit épuisé ce mois-ci. Rechargez des crédits à 599 FCFA pour continuer.";
    }
    var bouton = document.getElementById("submitBtn");
    if (bouton) {
      bouton.disabled = total === 0;
      bouton.textContent = total === 0 ? "Crédits épuisés" : "Demander un conseil";
    }
  }

  function consommerCredit() {
    var c = lireCredits();
    if (c.gratuits > 0) c.gratuits -= 1;
    else if (c.payants > 0) c.payants -= 1;
    ecrireCredits(c);
    afficherCredits();
  }

  /* ------------------------------------------------------------ consentement */
  var case_consent = document.getElementById("consent");
  if (case_consent) {
    try {
      if (localStorage.getItem(CLE_CONSENT) === "1") case_consent.checked = true;
    } catch (e) { /* ignore */ }
    case_consent.addEventListener("change", function () {
      try { localStorage.setItem(CLE_CONSENT, case_consent.checked ? "1" : "0"); } catch (e) { /* ignore */ }
    });
  }

  /* ------------------------------------------------------------ garde-fous à la soumission */
  var formulaire = document.getElementById("conseilForm");
  if (formulaire) {
    formulaire.addEventListener("submit", function (e) {
      var statut = document.getElementById("formStatus");
      var c = lireCredits();
      if (totalCredits(c) === 0) {
        e.preventDefault(); e.stopPropagation();
        if (statut) { statut.className = "form-status error"; statut.textContent = "Quota gratuit épuisé : rechargez 599 FCFA ou attendez le mois prochain."; }
        var barre = document.getElementById("creditsBar");
        if (barre) barre.classList.add("epuise");
        return;
      }
      if (case_consent && !case_consent.checked) {
        e.preventDefault(); e.stopPropagation();
        if (statut) { statut.className = "form-status error"; statut.textContent = "Cochez l'accord de traitement des données pour envoyer votre question."; }
        case_consent.focus();
        return;
      }
      consommerCredit();
    }, true);
  }

  afficherCredits();

  /* ------------------------------------------------------------ recharge (démonstration) */
  var recharge = document.getElementById("creditsRecharge");
  if (recharge) {
    recharge.addEventListener("click", function () {
      var c = lireCredits();
      c.payants += 10;             // pack 599 FCFA = 10 conseils (activation après paiement)
      ecrireCredits(c);
      afficherCredits();
      var statut = document.getElementById("formStatus");
      if (statut) {
        statut.className = "form-status";
        statut.textContent = "10 crédits ajoutés localement. En production, le pack est activé après confirmation du paiement mobile money.";
      }
    });
  }
})();
