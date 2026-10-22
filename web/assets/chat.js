/* chat.js — chatbox de l'agent agronome (session anonyme, historique serveur).
 *
 * Aucune réponse n'est inventée ici : le composant affiche ce que le moteur
 * renvoie, y compris les erreurs et les états « clarification » ou « escalade ».
 * Le navigateur ne reçoit jamais de clé : le cookie de session est HttpOnly.
 */
(function () {
  "use strict";

  var CLE_FIL = "agro.conversation.v1";
  var INTERVALLE = 2500;
  var ATTENTE_MAX = 5 * 60 * 1000;

  var dialogue, fil, formulaire, zone, bouton, etat, titreCulture;
  var conversationId = null;
  var cultureId = null;
  var localite = null;
  var envoiEnCours = false;
  var minuteur = null;
  var debutAttente = 0;

  function $(id) { return document.getElementById(id); }

  function echapper(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function lireStockage() {
    try { return localStorage.getItem(CLE_FIL) || ""; } catch (e) { return ""; }
  }
  function ecrireStockage(v) {
    try { v ? localStorage.setItem(CLE_FIL, v) : localStorage.removeItem(CLE_FIL); } catch (e) { /* mode privé */ }
  }

  function identifiant() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "m-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  }

  function afficherEtat(texte, type) {
    if (!etat) return;
    etat.textContent = texte || "";
    etat.className = "chat-etat" + (type ? " " + type : "");
  }

  function bulle(message) {
    var role = message.role === "user" ? "user" : message.role === "assistant" ? "agent" : "systeme";
    var article = document.createElement("li");
    article.className = "chat-msg chat-" + role;
    var auteur = role === "user" ? "Vous" : role === "agent" ? "Agent agronome" : "Système";
    var badges = "";
    if (role === "agent") {
      if (message.statut === "en_cours") badges = '<span class="chat-badge attente">réponse en cours…</span>';
      else if (message.statut === "clarification") badges = '<span class="chat-badge info">précisions demandées</span>';
      else if (message.statut === "escalade") badges = '<span class="chat-badge warn">validation humaine</span>';
      else if (message.statut === "echec") badges = '<span class="chat-badge err">échec</span>';
    }
    var sources = "";
    if (Array.isArray(message.sources) && message.sources.length) {
      sources = '<details class="chat-sources"><summary>Sources (' + message.sources.length + ")</summary><ul>" +
        message.sources.map(function (s) {
          var libelle = typeof s === "string" ? s : (s.titre || s.fichier || s.url || "source");
          var lien = (s && s.url) ? '<a href="' + echapper(s.url) + '" target="_blank" rel="noreferrer">' + echapper(libelle) + "</a>" : echapper(libelle);
          return "<li>" + lien + "</li>";
        }).join("") + "</ul></details>";
    }
    article.innerHTML =
      '<p class="chat-auteur">' + auteur + badges + "</p>" +
      '<div class="chat-texte">' + echapper(message.contenu).replace(/\n/g, "<br>") + "</div>" +
      sources;
    return article;
  }

  function rendre(donnees) {
    if (!fil) return;
    fil.innerHTML = "";
    if (!(donnees.messages || []).length) {
      var accueil = document.createElement("li");
      accueil.className = "chat-msg chat-systeme chat-accueil";
      accueil.innerHTML = "Posez votre question sur une culture, un sol, un ravageur ou un budget. " +
        "L'agent agronome répond avec ses sources et signale ce qu'il ne sait pas.";
      fil.appendChild(accueil);
    }
    (donnees.messages || []).forEach(function (m) { fil.appendChild(bulle(m)); });
    var dernier = (donnees.messages || []).slice(-1)[0];
    var attente = dernier && dernier.role === "assistant" && dernier.statut === "en_cours";
    fil.setAttribute("aria-busy", attente ? "true" : "false");
    if (attente) afficherEtat("L'agent agronome travaille…", "attente");
    else if (dernier && dernier.role === "assistant") afficherEtat("", "");
    fil.scrollTop = fil.scrollHeight;
    return attente;
  }

  async function requete(url, options) {
    var r = await fetch(url, Object.assign({ credentials: "same-origin", cache: "no-store" }, options || {}));
    var corps = null;
    try { corps = await r.json(); } catch (e) { corps = null; }
    if (!r.ok) {
      var message = (corps && (corps.erreur || corps.detail)) || ("HTTP " + r.status);
      var err = new Error(message);
      err.statut = r.status;
      throw err;
    }
    return corps;
  }

  async function ouvrirConversation() {
    var corps = {};
    if (cultureId) corps.culture_id = cultureId;
    if (localite) corps.localite = localite;
    var reponse = await requete("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Client": "web" },
      body: JSON.stringify(corps),
    });
    conversationId = reponse.conversation_id;
    ecrireStockage(conversationId);
    return conversationId;
  }

  async function charger() {
    if (!conversationId) {
      var memo = lireStockage();
      if (memo) conversationId = memo;
    }
    if (!conversationId) { await ouvrirConversation(); return; }
    try {
      var donnees = await requete("/api/conversations/" + encodeURIComponent(conversationId));
      var attente = rendre(donnees);
      if (attente) suivre();
    } catch (e) {
      if (e.statut === 404 || e.statut === 401) {
        ecrireStockage("");
        conversationId = null;
        await ouvrirConversation();
        rendre({ messages: [] });
      } else {
        throw e;
      }
    }
  }

  function suivre() {
    if (minuteur) clearTimeout(minuteur);
    if (!conversationId) return;
    if (Date.now() - debutAttente > ATTENTE_MAX) {
      afficherEtat("La réponse tarde plus que prévu. L'agent continue ; vous pouvez réessayer ou reposer la question plus tard.", "warn");
      return;
    }
    minuteur = setTimeout(async function () {
      try {
        var donnees = await requete("/api/conversations/" + encodeURIComponent(conversationId));
        var attente = rendre(donnees);
        if (attente) suivre();
        else { afficherEtat("", ""); }
      } catch (e) {
        afficherEtat("Connexion interrompue : " + e.message, "err");
      }
    }, INTERVALLE);
  }

  async function envoyer(texte) {
    if (envoiEnCours) return;
    if (!conversationId) await ouvrirConversation();
    envoiEnCours = true;
    bouton.disabled = true;
    zone.setAttribute("aria-disabled", "true");
    afficherEtat("Envoi de votre question…", "attente");
    try {
      await requete("/api/conversations/" + encodeURIComponent(conversationId) + "/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Client": "web" },
        body: JSON.stringify({
          texte: texte,
          culture_id: cultureId || null,
          localite: localite || null,
          idempotency_key: identifiant(),
        }),
      });
      debutAttente = Date.now();
      var donnees = await requete("/api/conversations/" + encodeURIComponent(conversationId));
      var attente = rendre(donnees);
      if (attente) { afficherEtat("L'agent agronome travaille…", "attente"); suivre(); }
    } catch (e) {
      if (e.statut === 401 || e.statut === 404) {
        ecrireStockage(""); conversationId = null;
        afficherEtat("Votre session a expiré : une nouvelle conversation a été ouverte.", "warn");
        await ouvrirConversation();
      } else {
        afficherEtat("Envoi impossible : " + e.message, "err");
      }
    } finally {
      envoiEnCours = false;
      bouton.disabled = false;
      zone.removeAttribute("aria-disabled");
      zone.focus();
    }
  }

  function nouvelle() {
    if (minuteur) clearTimeout(minuteur);
    conversationId = null;
    ecrireStockage("");
    if (fil) fil.innerHTML = "";
    afficherEtat("Nouvelle conversation.", "");
    ouvrirConversation().catch(function (e) {
      afficherEtat("Impossible d'ouvrir une conversation : " + e.message, "err");
    });
  }

  function ouvrir(options) {
    if (!dialogue) return;
    options = options || {};
    if (options.culture) {
      cultureId = options.culture;
      localite = options.localite || null;
    }
    if (titreCulture) {
      titreCulture.textContent = cultureId ? "À propos de : " + cultureId : "";
      titreCulture.hidden = !cultureId;
    }
    if (typeof dialogue.showModal === "function") dialogue.showModal();
    else dialogue.setAttribute("open", "open");
    dialogue.classList.add("ouvert");
    afficherEtat("Connexion à l'agent agronome…", "attente");
    charger()
      .then(function () { afficherEtat("", ""); zone.focus(); })
      .catch(function (e) {
        afficherEtat("Le service de conversation est indisponible (" + e.message + "). Aucune réponse n'a été inventée.", "err");
      });
  }

  function fermer() {
    if (!dialogue) return;
    if (typeof dialogue.close === "function") dialogue.close();
    else dialogue.removeAttribute("open");
    dialogue.classList.remove("ouvert");
  }

  function brancher() {
    dialogue = $("chatDialogue");
    if (!dialogue) return;
    fil = $("chatFil");
    formulaire = $("chatForm");
    zone = $("chatTexte");
    bouton = $("chatEnvoyer");
    etat = $("chatEtat");
    titreCulture = $("chatCulture");

    document.querySelectorAll('[data-chat="ouvrir"]').forEach(function (declencheur) {
      declencheur.addEventListener("click", function (e) {
        e.preventDefault();
        ouvrir({
          culture: declencheur.getAttribute("data-culture") || null,
          localite: declencheur.getAttribute("data-localite") || null,
        });
      });
    });

    var fermeture = $("chatFermer");
    if (fermeture) fermeture.addEventListener("click", fermer);
    var reinit = $("chatNouveau");
    if (reinit) reinit.addEventListener("click", nouvelle);

    dialogue.addEventListener("click", function (e) {
      if (e.target === dialogue) fermer();   // clic sur le fond
    });
    dialogue.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); fermer(); }
    });

    if (formulaire) {
      formulaire.addEventListener("submit", function (e) {
        e.preventDefault();
        var texte = (zone.value || "").trim();
        if (texte.length < 2) { afficherEtat("Écrivez une question de deux caractères au moins.", "warn"); zone.focus(); return; }
        zone.value = "";
        envoyer(texte);
      });
    }
    if (zone) {
      zone.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (formulaire) formulaire.requestSubmit ? formulaire.requestSubmit() : formulaire.dispatchEvent(new Event("submit"));
        }
      });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", brancher);
  else brancher();
})();
