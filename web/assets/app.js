/* AGROGUIDCI — vitrine : navigation, sélection géographique, appel du moteur.
   Aucune donnée n'est inventée côté navigateur : sans réponse du moteur, on
   affiche l'échec tel quel. */

(function () {
  "use strict";

  // Moteur AGROGUIDCI (agents hébergés). Appel same-origin : /api/* est proxifié
  // vers agroguidci-saas par vercel.json. Surchargeable : window.AGRO_API = "…".
  var API = window.AGRO_API || "/api/demande";
  var TIMEOUT_MS = 240000;   // une coordination enchaîne plusieurs appels de modèle

  /* ---------- menu mobile ---------- */
  var toggle = document.getElementById("navToggle");
  var mobile = document.getElementById("navMobile");
  if (toggle && mobile) {
    toggle.addEventListener("click", function () {
      var open = mobile.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    mobile.addEventListener("click", function (e) {
      if (e.target.tagName === "A") {
        mobile.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* ---------- géographie ---------- */
  var GEO = window.AGRO_GEO || { regions: [], departements: [] };
  var selRegion = document.getElementById("region");
  var selDept = document.getElementById("departement");
  var inputLocalite = document.getElementById("localite");
  var inputSurface = document.getElementById("surface");
  var taQuestion = document.getElementById("question");

  function norm(s) {
    return (s || "").toString()
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().trim();
  }

  function remplirRegions() {
    if (!selRegion) return;
    GEO.regions.forEach(function (r) {
      var o = document.createElement("option");
      o.value = r[0];
      o.textContent = r[1];
      selRegion.appendChild(o);
    });
  }

  function remplirDepartements(codeRegion) {
    if (!selDept) return;
    var garde = selDept.value;
    selDept.innerHTML = "";
    var opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Tous les départements";
    selDept.appendChild(opt);
    var liste = GEO.departements.filter(function (d) {
      return !codeRegion || d[0].indexOf(codeRegion + ":") === 0;
    });
    liste.forEach(function (d) {
      var o = document.createElement("option");
      o.value = d[0];
      o.textContent = d[1];
      selDept.appendChild(o);
    });
    if (garde && liste.some(function (d) { return d[0] === garde; })) selDept.value = garde;
  }

  function libelleRegion(code) {
    var r = GEO.regions.filter(function (x) { return x[0] === code; })[0];
    return r ? r[1] : "";
  }

  function libelleDepartement(value) {
    if (!value) return "";
    var d = GEO.departements.filter(function (x) { return x[0] === value; })[0];
    return d ? d[1] : "";
  }

  if (selRegion) {
    remplirRegions();
    remplirDepartements("");
    selRegion.addEventListener("change", function () {
      remplirDepartements(selRegion.value);
    });
  }

  /* ---------- pré-remplissage depuis les cartes ---------- */
  document.querySelectorAll("[data-prefill]").forEach(function (a) {
    a.addEventListener("click", function () {
      if (!taQuestion) return;
      var t = a.getAttribute("data-prefill");
      if (t && !taQuestion.value.trim()) {
        taQuestion.value = t;
        taQuestion.focus({ preventScroll: true });
        taQuestion.setSelectionRange(t.length, t.length);
      }
    });
  });

  /* ---------- composition de la demande ---------- */
  function composerLocalite() {
    var libre = (inputLocalite && inputLocalite.value || "").trim();
    var dep = libelleDepartement(selDept && selDept.value);
    var reg = libelleRegion(selRegion && selRegion.value);
    if (libre) return libre + (dep ? " (département de " + dep + ")" : "") + (reg ? ", " + reg : "");
    if (dep) return dep + (reg ? ", " + reg : "");
    if (reg) return reg;
    return "";
  }

  /* ---------- rendu de la réponse ---------- */
  function esc(s) {
    return (s == null ? "" : String(s))
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function inline(s) {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  }

  // Markdown minimal : titres, listes, citations, paragraphes.
  function markdown(md) {
    var lignes = String(md || "").replace(/\r/g, "").split("\n");
    var html = [], tas = [], liste = null;

    function viderTas() {
      if (tas.length) { html.push("<p>" + inline(tas.join(" ")) + "</p>"); tas = []; }
    }
    function fermerListe() {
      if (liste) { html.push("</" + liste + ">"); liste = null; }
    }

    lignes.forEach(function (brut) {
      var l = brut.replace(/\s+$/, "");
      var m;
      if (!l.trim()) { viderTas(); fermerListe(); return; }
      if ((m = l.match(/^(#{1,4})\s+(.*)$/))) {
        viderTas(); fermerListe();
        var n = Math.min(m[1].length + 1, 4);
        html.push("<h" + n + ">" + inline(m[2]) + "</h" + n + ">");
        return;
      }
      if ((m = l.match(/^\s*[-*•]\s+(.*)$/))) {
        viderTas();
        if (liste !== "ul") { fermerListe(); html.push("<ul>"); liste = "ul"; }
        html.push("<li>" + inline(m[1]) + "</li>");
        return;
      }
      if ((m = l.match(/^\s*(\d+)[.)]\s+(.*)$/))) {
        viderTas();
        if (liste !== "ol") { fermerListe(); html.push("<ol>"); liste = "ol"; }
        html.push("<li>" + inline(m[2]) + "</li>");
        return;
      }
      if ((m = l.match(/^>\s*(.*)$/))) {
        viderTas(); fermerListe();
        html.push("<blockquote>" + inline(m[1]) + "</blockquote>");
        return;
      }
      fermerListe();
      tas.push(l.trim());
    });
    viderTas(); fermerListe();
    return html.join("\n");
  }

  function blocTitre(t) { return '<h3 class="sub">' + esc(t) + "</h3>"; }

  function blocListe(items, classe) {
    if (!items || !items.length) return "";
    return '<ul class="' + (classe || "source-list") + '">' +
      items.map(function (i) { return "<li>" + inline(typeof i === "string" ? i : JSON.stringify(i)) + "</li>"; }).join("") +
      "</ul>";
  }

  var answer = document.getElementById("answer");
  var answerBody = document.getElementById("answerBody");
  var badge = document.getElementById("stateBadge");
  var meta = document.getElementById("answerMeta");

  var ETATS = {
    TERMINEE_VERIFIEE: ["ok", "Réponse vérifiée"],
    A_VALIDER: ["warn", "À valider avec un conseiller"],
    EN_ATTENTE_INFORMATION: ["warn", "Informations manquantes"],
    ECHEC_OUTIL: ["warn", "Outil indisponible — réponse partielle"],
    ARRETEE_PERMISSION: ["warn", "Action non autorisée"],
    ESCALADE_HUMAINE: ["warn", "Escalade vers un humain"]
  };

  function afficherReponse(d) {
    var rapport = d.rapport || {};
    var etat = d.etat_final || "—";
    var e = ETATS[etat] || ["", etat];
    badge.className = "state-badge " + (e[0] || "");
    badge.textContent = e[1] || etat;
    meta.textContent = [
      d.id ? "mission " + d.id : "",
      d.duree_s != null ? d.duree_s + " s" : "",
      (d.domaines && d.domaines.length) ? "volets : " + d.domaines.join(", ") : ""
    ].filter(Boolean).join(" · ");

    var h = "";
    if (rapport.besoin) {
      h += blocTitre("Ce que le système a compris") + '<div class="prose">' + markdown(rapport.besoin) + "</div>";
    }
    if (rapport.reponse) {
      h += blocTitre("Réponse de l'Agent Agronome Expert") + '<div class="prose">' + markdown(rapport.reponse) + "</div>";
    }
    if (rapport.hypotheses && rapport.hypotheses.length) {
      h += blocTitre("Hypothèses posées") + blocListe(rapport.hypotheses, "pill-list");
    }
    if (rapport.manques && rapport.manques.length) {
      h += blocTitre("Ce qui manque pour aller plus loin") + blocListe(rapport.manques);
    }
    if (rapport.prochaine_action) {
      h += blocTitre("Prochaine action") + '<div class="prose"><p>' + inline(rapport.prochaine_action) + "</p></div>";
    }
    if (rapport.limites && rapport.limites.length) {
      h += blocTitre("Limites assumées") + blocListe(rapport.limites);
    }
    if (d.alertes && d.alertes.length) {
      h += blocTitre("Alertes") + blocListe(d.alertes, "alert-list");
    }
    if (rapport.sources && rapport.sources.length) {
      h += "<details class=\"sources\"><summary>Sources consultées (" + rapport.sources.length + ")</summary><ul>";
      rapport.sources.forEach(function (s) {
        var libelle = typeof s === "string" ? s : [s.source, s.section].filter(Boolean).join(" — ");
        h += "<li>" + inline(libelle) + "</li>";
      });
      h += "</ul></details>";
    }
    if (rapport.chiffres && rapport.chiffres.length) {
      h += blocTitre("Chiffres produits par les outils") +
        '<div class="prose"><ul>' + rapport.chiffres.map(function (c) {
          return "<li>" + inline(typeof c === "string" ? c : (c.libelle || c.nom || "") + " : " + JSON.stringify(c.valeur != null ? c.valeur : c)) + "</li>";
        }).join("") + "</ul></div>";
    }
    h += '<p class="help">Conseil indicatif : à confirmer avec l\'ANADER, le CNRA ou le vétérinaire de votre zone. Aucune prescription de produit ni de dosage n\'est délivrée ici.</p>';

    answerBody.innerHTML = h;
    answer.classList.add("show");
  }

  function afficherEchec(message) {
    badge.className = "state-badge warn";
    badge.textContent = "Échec déclaré";
    meta.textContent = "";
    answerBody.innerHTML = '<div class="prose"><p><strong>' + esc(message) + "</strong></p>" +
      "<p>Aucun conseil n'a été produit : le système préfère déclarer l'échec plutôt que d'inventer une réponse. Réessayez dans un instant.</p></div>";
    answer.classList.add("show");
  }

  /* ---------- envoi ---------- */
  var form = document.getElementById("conseilForm");
  var btn = document.getElementById("submitBtn");
  var statut = document.getElementById("formStatus");

  function setStatut(txt, erreur) {
    if (!statut) return;
    statut.textContent = txt || "";
    statut.className = "form-status" + (erreur ? " error" : "");
  }

  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var texte = (taQuestion && taQuestion.value || "").trim();
      if (texte.length < 5) {
        setStatut("Décrivez votre situation en quelques mots (5 caractères minimum).", true);
        if (taQuestion) taQuestion.focus();
        return;
      }

      var profil = {};
      var localite = composerLocalite();
      if (localite) profil.localite = localite;
      var surface = (inputSurface && inputSurface.value || "").replace(",", ".").trim();
      if (surface && !isNaN(parseFloat(surface))) profil.surface_ha = parseFloat(surface);

      var payload = { texte: texte };
      if (Object.keys(profil).length) payload.profil = profil;

      btn.disabled = true;
      btn.innerHTML = '<span class="spin" aria-hidden="true"></span> Analyse en cours…';
      setStatut("Les agents travaillent (météo, base de connaissances, vérification) — comptez 15 à 60 secondes.");

      var ctrl = new AbortController();
      var minuteur = setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS);

      fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) throw new Error((j && (j.erreur || j.error)) || ("HTTP " + r.status));
          return j;
        });
      }).then(function (j) {
        var d = j && j.data ? j.data : j;
        if (!d || (!d.rapport && !d.etat_final)) throw new Error("réponse inattendue du moteur");
        afficherReponse(d);
        setStatut("Réponse rendue en " + (d.duree_s != null ? d.duree_s + " s" : "quelques secondes") + ".");
      }).catch(function (err) {
        var msg = err && err.name === "AbortError"
          ? "Le moteur n'a pas répondu dans le délai imparti."
          : (err && err.message) || "appel impossible";
        afficherEchec(msg);
        setStatut("Aucune réponse produite : " + msg, true);
      }).finally(function () {
        clearTimeout(minuteur);
        btn.disabled = false;
        btn.textContent = "Demander un conseil";
      });
    });
  }
})();
