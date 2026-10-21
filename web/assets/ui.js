/* AGROGUIDCI — application : onglets, filtres, quota quotidien, bandeau temps réel.
   Aucune dépendance. Le quota gratuit est tenu côté navigateur ; il sera doublé
   d'un contrôle serveur quand les comptes utilisateurs existeront. */
(function () {
  "use strict";

  var CLE_CREDITS = "agro.credits.v2";
  var CLE_CONSENT = "agro.consentement.v1";
  var GRATUITS_PAR_JOUR = 2;
  var VILLES = [
    { nom: "Abidjan", lat: 5.354, lon: -4.002 },
    { nom: "Bouaké", lat: 7.690, lon: -5.030 },
    { nom: "Korhogo", lat: 9.458, lon: -5.630 },
    { nom: "Daloa", lat: 6.877, lon: -6.450 }
  ];

  function echapper(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fcfa(n) { return Number(n).toLocaleString("fr-FR"); }
  function aujourdhui() { return new Date().toISOString().slice(0, 10); }

  /* ------------------------------------------------------------------ onglets */
  var panneaux = ["conseil", "cultures", "prix", "actus"];

  function activerOnglet(nom, defiler) {
    if (panneaux.indexOf(nom) < 0) nom = "conseil";
    panneaux.forEach(function (p) {
      var panneau = document.getElementById("panel-" + p);
      var onglet = document.getElementById("tab-" + p);
      var actif = p === nom;
      if (panneau) {
        panneau.hidden = !actif;
        panneau.classList.toggle("active", actif);
      }
      if (onglet) {
        onglet.classList.toggle("active", actif);
        onglet.setAttribute("aria-selected", actif ? "true" : "false");
        onglet.setAttribute("tabindex", actif ? "0" : "-1");
      }
    });
    document.querySelectorAll(".navlink").forEach(function (b) {
      b.classList.toggle("actif", b.getAttribute("data-tab") === nom);
    });
    var barre = document.querySelector(".tabbar-wrap");
    if (defiler && barre) {
      var y = barre.getBoundingClientRect().top + window.scrollY - 78;
      window.scrollTo({ top: Math.max(0, y), behavior: "smooth" });
    }
    if (history.replaceState) history.replaceState(null, "", "#" + nom);
    if (nom === "cultures") revelerFiches();
  }

  document.addEventListener("click", function (e) {
    var cible = e.target.closest ? e.target.closest("[data-tab]") : null;
    if (!cible) return;
    var nom = cible.getAttribute("data-tab");
    if (!nom) return;
    if (cible.tagName === "A") e.preventDefault();
    var menu = document.getElementById("navMobile");
    if (menu) menu.classList.remove("open");
    activerOnglet(nom, true);
  });

  document.querySelectorAll('[role="tab"]').forEach(function (onglet) {
    onglet.addEventListener("keydown", function (e) {
      var i = panneaux.indexOf(onglet.getAttribute("data-tab"));
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        var pas = e.key === "ArrowRight" ? 1 : -1;
        var suivant = panneaux[(i + pas + panneaux.length) % panneaux.length];
        activerOnglet(suivant, false);
        var cible = document.getElementById("tab-" + suivant);
        if (cible) cible.focus();
      }
    });
  });

  var depart = (location.hash || "").replace("#", "");
  activerOnglet(panneaux.indexOf(depart) >= 0 ? depart : "conseil", false);
  window.addEventListener("hashchange", function () {
    var h = (location.hash || "").replace("#", "");
    if (panneaux.indexOf(h) >= 0) activerOnglet(h, true);
  });

  /* ------------------------------------------------------------------ fiches cultures */
  var grille = document.getElementById("grilleCultures");
  function revelerFiches() {
    if (!grille) return;
    grille.querySelectorAll(".reveal").forEach(function (c) { c.classList.add("in"); });
    grille.querySelectorAll(".crop").forEach(function (c, i) {
      c.style.transitionDelay = Math.min(i * 60, 420) + "ms";
    });
  }

  document.querySelectorAll("[data-filtre]").forEach(function (bouton) {
    bouton.addEventListener("click", function () {
      document.querySelectorAll("[data-filtre]").forEach(function (b) { b.classList.remove("actif"); });
      bouton.classList.add("actif");
      filtrer();
    });
  });
  var champRecherche = document.getElementById("rechercheCulture");
  if (champRecherche) champRecherche.addEventListener("input", filtrer);

  function filtrer() {
    if (!grille) return;
    var actif = document.querySelector("[data-filtre].actif");
    var famille = actif ? actif.getAttribute("data-filtre") : "tous";
    var q = (champRecherche && champRecherche.value || "").toLowerCase().trim();
    var visibles = 0;
    grille.querySelectorAll(".crop").forEach(function (c) {
      var okFamille = famille === "tous" || c.getAttribute("data-type") === famille;
      var okTexte = !q || (c.getAttribute("data-nom") || "").indexOf(q) >= 0 ||
        c.textContent.toLowerCase().indexOf(q) >= 0;
      var visible = okFamille && okTexte;
      c.style.display = visible ? "" : "none";
      if (visible) visibles++;
    });
    var vide = document.getElementById("culturesVide");
    if (vide) vide.hidden = visibles !== 0;
  }

  /* ------------------------------------------------------------------ prix */
  var prixCharge = null;

  function rendrePrix(d) {
    prixCharge = d;
    var corps = document.getElementById("prixBody");
    if (!corps || !d || !d.produits) return;
    corps.innerHTML = "";
    d.produits.forEach(function (p) {
      var tr = document.createElement("tr");
      tr.innerHTML = '<td class="produit">' + echapper(p.nom) + "</td>" +
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
    var vedette = document.getElementById("prixVedette");
    if (vedette && d.produits.length) {
      vedette.textContent = d.produits[0].nom + " " + fcfa(d.produits[0].prix) + " F/kg";
    }
    construireBandeau();
  }

  /* ------------------------------------------------------------------ météo temps réel */
  var meteo = [];
  var LIBELLES = { 0: "ciel clair", 1: "peu nuageux", 2: "nuageux", 3: "couvert", 45: "brouillard",
                   51: "bruine", 53: "bruine", 55: "bruine", 61: "pluie faible", 63: "pluie",
                   65: "forte pluie", 80: "averses", 81: "averses", 82: "fortes averses",
                   95: "orage", 96: "orage", 99: "orage" };

  function chargerMeteo() {
    var lat = VILLES.map(function (v) { return v.lat; }).join(",");
    var lon = VILLES.map(function (v) { return v.lon; }).join(",");
    var url = "https://api.open-meteo.com/v1/forecast?latitude=" + lat + "&longitude=" + lon +
      "&current=temperature_2m,precipitation,weather_code,wind_speed_10m&timezone=Africa%2FAbidjan";
    fetch(url, { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) {
        var liste = Array.isArray(d) ? d : [d];
        meteo = liste.slice(0, VILLES.length).map(function (x, i) {
          var c = x.current || {};
          return { nom: VILLES[i].nom, t: c.temperature_2m, pluie: c.precipitation,
                   vent: c.wind_speed_10m, code: c.weather_code,
                   heure: (c.time || "").slice(11, 16) };
        });
        rendreMeteo();
        construireBandeau();
      })
      .catch(function () {
        var zone = document.getElementById("meteoCartes");
        if (zone) zone.innerHTML = '<p class="prix-empty">Météo indisponible pour le moment — aucune valeur inventée.</p>';
      });
  }

  function rendreMeteo() {
    var zone = document.getElementById("meteoCartes");
    if (!zone || !meteo.length) return;
    zone.innerHTML = meteo.map(function (m) {
      return '<div class="meteo-carte reveal in">' +
        '<span class="meteo-ville">' + echapper(m.nom) + "</span>" +
        '<strong class="meteo-temp">' + (m.t == null ? "—" : Math.round(m.t)) + "°C</strong>" +
        '<span class="meteo-detail">' + echapper(LIBELLES[m.code] || "—") + "</span>" +
        '<span class="meteo-detail">pluie ' + (m.pluie == null ? "—" : m.pluie) + " mm · vent " +
        (m.vent == null ? "—" : Math.round(m.vent)) + " km/h</span>" +
        '<span class="meteo-heure">relevé ' + echapper(m.heure || "") + "</span>" +
        "</div>";
    }).join("");
    var vedette = document.getElementById("meteoVedette");
    if (vedette && meteo[0] && meteo[0].t != null) {
      vedette.textContent = meteo[0].nom + " " + Math.round(meteo[0].t) + "°C";
    }
  }

  /* ------------------------------------------------------------------ bandeau défilant */
  function construireBandeau() {
    var piste = document.getElementById("prixTicker");
    if (!piste) return;
    var items = [];
    items.push('<span class="ticker-item live"><span class="pastille"></span> Temps réel · ' +
      new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) + "</span>");
    meteo.forEach(function (m) {
      items.push('<span class="ticker-item">' + echapper(m.nom) + ' <b>' +
        (m.t == null ? "—" : Math.round(m.t)) + "°C</b> <span>" +
        echapper(LIBELLES[m.code] || "") + "</span></span>");
    });
    if (prixCharge && prixCharge.produits) {
      prixCharge.produits.forEach(function (p) {
        items.push('<span class="ticker-item">' + echapper(p.nom) + ' <span class="val">' +
          fcfa(p.prix) + " FCFA/" + echapper(p.unite) + "</span></span>");
      });
    }
    var contenu = items.join("");
    piste.innerHTML = contenu + contenu;   // doublé pour un défilement continu
  }

  fetch("assets/prix.json", { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(rendrePrix)
    .catch(function () {
      var note = document.getElementById("prixNote");
      if (note) note.textContent = "Relevé indisponible pour le moment. Aucun prix n'est affiché plutôt qu'un prix non vérifié.";
    });
  chargerMeteo();
  setInterval(construireBandeau, 60000);
  setInterval(chargerMeteo, 600000);      // météo rafraîchie toutes les 10 minutes

  /* ------------------------------------------------------------------ quota quotidien */
  function lireCredits() {
    var c = { jour: aujourdhui(), gratuits: GRATUITS_PAR_JOUR, payants: 0 };
    try {
      var brut = JSON.parse(localStorage.getItem(CLE_CREDITS) || "null");
      if (brut && typeof brut === "object") c = brut;
    } catch (e) { /* stockage indisponible : quota par défaut */ }
    if (c.jour !== aujourdhui()) { c.jour = aujourdhui(); c.gratuits = GRATUITS_PAR_JOUR; }
    if (typeof c.gratuits !== "number") c.gratuits = GRATUITS_PAR_JOUR;
    if (typeof c.payants !== "number") c.payants = 0;
    return c;
  }
  function ecrireCredits(c) {
    try { localStorage.setItem(CLE_CREDITS, JSON.stringify(c)); } catch (e) { /* ignore */ }
  }
  function total(c) { return Math.max(0, c.gratuits) + Math.max(0, c.payants); }

  function afficherCredits() {
    var barre = document.getElementById("creditsBar");
    var compte = document.getElementById("creditsCount");
    if (!compte) return;
    var c = lireCredits(), t = total(c);
    compte.textContent = t;
    if (barre) barre.classList.toggle("epuise", t === 0);
    var texte = document.getElementById("creditsTexte");
    if (texte) {
      texte.innerHTML = t > 0
        ? "Gratuit chaque jour : " + Math.max(0, c.gratuits) + "/" + GRATUITS_PAR_JOUR +
          " aujourd'hui" + (c.payants ? " + " + c.payants + " crédit(s) acheté(s)" : "") + "."
        : "Quota du jour épuisé. Il revient demain matin — ou rechargez 10 crédits à 599 FCFA.";
    }
    var bouton = document.getElementById("submitBtn");
    if (bouton) {
      bouton.disabled = t === 0;
      bouton.textContent = t === 0 ? "Quota du jour épuisé" : "Demander un conseil";
    }
  }

  function consommer() {
    var c = lireCredits();
    if (c.gratuits > 0) c.gratuits -= 1;
    else if (c.payants > 0) c.payants -= 1;
    ecrireCredits(c);
    afficherCredits();
  }

  /* ------------------------------------------------------------------ consentement + envoi */
  var caseConsent = document.getElementById("consent");
  if (caseConsent) {
    try { if (localStorage.getItem(CLE_CONSENT) === "1") caseConsent.checked = true; } catch (e) { /* ignore */ }
    caseConsent.addEventListener("change", function () {
      try { localStorage.setItem(CLE_CONSENT, caseConsent.checked ? "1" : "0"); } catch (e) { /* ignore */ }
    });
  }

  var formulaire = document.getElementById("conseilForm");
  if (formulaire) {
    formulaire.addEventListener("submit", function (e) {
      var statut = document.getElementById("formStatus");
      if (total(lireCredits()) === 0) {
        e.preventDefault(); e.stopPropagation();
        if (statut) { statut.className = "form-status error"; statut.textContent = "Quota du jour épuisé : rechargez 599 FCFA ou revenez demain."; }
        return;
      }
      if (caseConsent && !caseConsent.checked) {
        e.preventDefault(); e.stopPropagation();
        if (statut) { statut.className = "form-status error"; statut.textContent = "Cochez l'accord de traitement des données pour envoyer votre question."; }
        caseConsent.focus();
        return;
      }
      consommer();
    }, true);
  }

  var recharge = document.getElementById("creditsRecharge");
  if (recharge) {
    recharge.addEventListener("click", function () {
      var c = lireCredits();
      c.payants += 10;
      ecrireCredits(c);
      afficherCredits();
      var statut = document.getElementById("formStatus");
      if (statut) {
        statut.className = "form-status";
        statut.textContent = "10 crédits ajoutés localement. En production, le pack s'active après confirmation du paiement mobile money.";
      }
    });
  }

  afficherCredits();
  revelerFiches();
})();
