/* AGROGUIDCI — application : onglets, filtres, quota quotidien, bandeau temps réel.
   Aucune dépendance. Le quota gratuit est tenu côté navigateur ; il sera doublé
   d'un contrôle serveur quand les comptes utilisateurs existeront. */
(function () {
  "use strict";

  var CLE_CONSENT = "agro.consentement.v1";
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

  // Compteurs recalculés depuis le DOM : les nombres affichés ne peuvent pas
  // diverger du nombre réel de fiches, même si la génération change.
  function majCompteurs() {
    var cartes = document.querySelectorAll("#grilleCultures .crop");
    var total = cartes.length;
    var vivrieres = 0, epices = 0;
    cartes.forEach(function (c) {
      var type = c.getAttribute("data-type");
      if (type === "epice") epices++; else vivrieres++;
    });
    var valeurs = { tous: total, vivriere: vivrieres, epice: epices };
    document.querySelectorAll("[data-filtre]").forEach(function (b) {
      var span = b.querySelector("span");
      if (span && valeurs[b.getAttribute("data-filtre")] !== undefined) {
        span.textContent = valeurs[b.getAttribute("data-filtre")];
      }
    });
    var onglet = document.querySelector('[data-tab="cultures"] .tab-count');
    if (onglet) onglet.textContent = total;
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
  majCompteurs();

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

  /* ------------------------------------------------------------------ crédits (serveur) */
  // Le solde fait foi côté serveur (/api/credits) : ce bloc ne fait que l'afficher.
  // Aucun crédit n'est accordé, débité ou rechargé depuis le navigateur.
  var creditsEtat = null;

  function delaiLisible(secondes) {
    secondes = Math.max(0, Math.round(secondes));
    var h = Math.floor(secondes / 3600);
    var m = Math.round((secondes % 3600) / 60);
    if (h >= 1) return h + " h " + (m < 10 ? "0" + m : m) + " min";
    if (m >= 1) return m + " min";
    return "moins d'une minute";
  }

  function texteCredits(d, reste) {
    reste = (reste == null) ? d.secondes_avant_renouvellement : reste;
    var lot = d.lot_gratuit;
    var renouv = "Renouvellement de " + lot + " crédits gratuits dans " + delaiLisible(reste) + ".";
    if (d.total <= 0) {
      return "<strong>Crédits épuisés.</strong> " + renouv + " Les packs ne sont pas encore en vente.";
    }
    if (d.achetes > 0) {
      return d.gratuits + " gratuit(s) + " + d.achetes + " acheté(s) · 1 crédit par consultation. " + renouv;
    }
    return d.total + " sur " + lot + " · 1 crédit par consultation. " + renouv;
  }

  function afficherCredits(d) {
    var barre = document.getElementById("creditsBar");
    var compte = document.getElementById("creditsCount");
    var texte = document.getElementById("creditsTexte");
    if (!d) {
      if (barre) { barre.classList.add("indisponible"); barre.classList.remove("epuise"); }
      if (texte) texte.textContent = "Solde indisponible pour le moment : le service de crédits ne répond pas.";
      return;
    }
    creditsEtat = d;
    creditsEtat.expire_local = Date.now() + (d.secondes_avant_renouvellement || 0) * 1000;
    if (compte) compte.textContent = d.total;
    if (barre) {
      barre.classList.remove("indisponible");
      barre.classList.toggle("epuise", d.total <= 0);
    }
    if (texte) texte.innerHTML = texteCredits(d);
  }

  function chargerCredits() {
    return fetch("/api/credits", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { afficherCredits(d); return d; })
      .catch(function () { afficherCredits(null); return null; });
  }

  // Décompte local entre deux appels serveur ; au passage de période, on redemande
  // le solde (le serveur attribue alors le nouveau lot de 15).
  setInterval(function () {
    if (!creditsEtat) return;
    var reste = (creditsEtat.expire_local - Date.now()) / 1000;
    if (reste <= 0) { chargerCredits(); return; }
    var texte = document.getElementById("creditsTexte");
    if (texte) texte.innerHTML = texteCredits(creditsEtat, reste);
  }, 30000);

  document.addEventListener("agro:credits", chargerCredits);

  /* ------------------------------------------------------------------ consentement + envoi */
  var caseConsent = document.getElementById("consent");
  if (caseConsent) {
    try { if (localStorage.getItem(CLE_CONSENT) === "1") caseConsent.checked = true; } catch (e) { /* ignore */ }
    caseConsent.addEventListener("change", function () {
      try { localStorage.setItem(CLE_CONSENT, caseConsent.checked ? "1" : "0"); } catch (e) { /* ignore */ }
    });
  }

  // Le formulaire du panneau Conseil ne lance plus une seconde consultation :
  // il reprend la question (et le contexte saisi) dans la chatbox, seul chemin
  // vers l'agent — donc seul chemin débité.
  var formulaire = document.getElementById("conseilForm");
  if (formulaire) {
    formulaire.addEventListener("submit", function (e) {
      e.preventDefault();
      // app.js écoute aussi « submit » sur ce formulaire : sans cela, la mission
      // /api/demande partirait en parallèle de la conversation.
      e.stopImmediatePropagation();
      var statut = document.getElementById("formStatus");
      var question = ((document.getElementById("question") || {}).value || "").trim();
      if (question.length < 5) {
        if (statut) { statut.className = "form-status error"; statut.textContent = "Décrivez votre situation en quelques mots (5 caractères minimum)."; }
        var zone = document.getElementById("question");
        if (zone) zone.focus();
        return;
      }
      if (caseConsent && !caseConsent.checked) {
        if (statut) { statut.className = "form-status error"; statut.textContent = "Cochez l'accord de traitement des données pour envoyer votre question."; }
        caseConsent.focus();
        return;
      }
      var lieu = [];
      var loc = ((document.getElementById("localite") || {}).value || "").trim();
      if (loc) lieu.push(loc);
      ["departement", "region"].forEach(function (id) {
        var sel = document.getElementById(id);
        if (sel && sel.selectedIndex > 0) lieu.push(sel.options[sel.selectedIndex].text);
      });
      var contexte = [];
      if (lieu.length) contexte.push("Localité : " + lieu.join(", "));
      var surface = ((document.getElementById("surface") || {}).value || "").replace(",", ".").trim();
      if (surface && !isNaN(parseFloat(surface))) contexte.push("Surface : " + parseFloat(surface) + " ha");
      var texte = question + (contexte.length ? "\n\n" + contexte.join(" · ") : "");
      document.dispatchEvent(new CustomEvent("agro:question", { detail: { texte: texte } }));
      if (statut) {
        statut.className = "form-status";
        statut.textContent = "Votre question est reprise dans la conversation : appuyez sur Envoyer pour la transmettre à l’agent.";
      }
    }, true);
  }

  chargerCredits();
  revelerFiches();
})();
