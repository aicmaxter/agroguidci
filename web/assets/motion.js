/* AGROGUIDCI — moteur d'animation de la vitrine (motion.js v13)
   Aucune dépendance. Tout est neutralisé si l'utilisateur préfère moins de mouvement,
   et chaque effet piloté par IntersectionObserver possède un filet de sécurité
   synchrone : rien ne doit rester invisible ou bloqué à « 0 ». */
(function () {
  "use strict";

  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var pointeurFin = window.matchMedia && window.matchMedia("(pointer: fine)").matches;
  var barre = document.getElementById("progress");
  var entete = document.getElementById("siteHeader");
  var barreOnglets = document.querySelector(".tabbar-wrap");

  /* ------------------------------------------------------------ défilement : progression, en-tête, barre d'onglets */
  function surDefilement() {
    var h = document.documentElement;
    var total = h.scrollHeight - window.innerHeight;
    if (barre) barre.style.transform = "scaleX(" + (total > 0 ? Math.min(1, window.scrollY / total) : 0) + ")";
    if (entete) entete.classList.toggle("stuck", window.scrollY > 8);
    if (barreOnglets) barreOnglets.classList.toggle("colle", window.scrollY > 40);
  }
  var enAttente = false;
  window.addEventListener("scroll", function () {
    if (enAttente) return;
    enAttente = true;
    requestAnimationFrame(function () { surDefilement(); enAttente = false; });
  }, { passive: true });
  surDefilement();

  /* ------------------------------------------------------------ révélation à l'arrivée */
  var aReveler = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
  if ("IntersectionObserver" in window && !reduit) {
    var obs = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target;
        var parent = el.parentElement;
        var freres = parent ? Array.prototype.slice.call(parent.children).filter(function (c) { return c.classList.contains("reveal"); }) : [];
        var rang = Math.max(0, freres.indexOf(el));
        el.style.transitionDelay = Math.min(rang * 70, 420) + "ms";
        el.classList.add("in");
        obs.unobserve(el);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
    aReveler.forEach(function (el) { obs.observe(el); });
  } else {
    aReveler.forEach(function (el) { el.classList.add("in"); });
  }

  // Filet de sécurité : si l'observateur ne se déclenche pas (navigateur ancien,
  // onglet non rendu, capture sans rendu), ce qui est déjà à l'écran ne doit
  // jamais rester invisible.
  setTimeout(function () {
    aReveler.forEach(function (el) {
      if (el.classList.contains("in")) return;
      var r = el.getBoundingClientRect();
      if (r.top < window.innerHeight * 1.1 && r.bottom > -50) el.classList.add("in");
    });
  }, 2200);

  /* ------------------------------------------------------------ compteurs */
  var compteurs = Array.prototype.slice.call(document.querySelectorAll("[data-count]"));
  function animerCompteur(el) {
    var cible = parseInt(el.getAttribute("data-count"), 10);
    if (!cible || reduit) return;
    var debut = null, duree = 1100;
    // Filet : même si requestAnimationFrame est suspendu (onglet en arrière-plan),
    // la valeur finale doit être affichée — jamais un « 0 » qui reste à l'écran.
    setTimeout(function () {
      if ((el.textContent || "").replace(/\D/g, "") !== String(cible)) {
        el.textContent = cible.toLocaleString("fr-FR");
      }
    }, duree + 600);
    el.textContent = "0";
    function pas(ts) {
      if (debut === null) debut = ts;
      var p = Math.min(1, (ts - debut) / duree);
      var val = Math.round(cible * (1 - Math.pow(1 - p, 3)));
      el.textContent = val.toLocaleString("fr-FR");
      if (p < 1) requestAnimationFrame(pas);
      else el.textContent = cible.toLocaleString("fr-FR");
    }
    requestAnimationFrame(pas);
  }
  if ("IntersectionObserver" in window && !reduit) {
    var obsCompteur = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        if (!e.isIntersecting) return;
        animerCompteur(e.target);
        obsCompteur.unobserve(e.target);
      });
    }, { threshold: 0.6 });
    compteurs.forEach(function (el) { obsCompteur.observe(el); });
  }

  /* ------------------------------------------------------------ parallaxe douce au pointeur */
  var blobs = Array.prototype.slice.call(document.querySelectorAll("[data-parallax]"));
  if (blobs.length && !reduit && pointeurFin) {
    var cibleX = 0, cibleY = 0, x = 0, y = 0, actif = false;
    window.addEventListener("pointermove", function (e) {
      cibleX = (e.clientX / window.innerWidth - 0.5) * 40;
      cibleY = (e.clientY / window.innerHeight - 0.5) * 40;
      if (!actif) { actif = true; requestAnimationFrame(boucle); }
    }, { passive: true });

    function boucle() {
      x += (cibleX - x) * 0.08;
      y += (cibleY - y) * 0.08;
      blobs.forEach(function (b) {
        var f = parseFloat(b.getAttribute("data-parallax")) || 0.05;
        b.style.transform = "translate3d(" + (x * f * 10).toFixed(2) + "px," + (y * f * 10).toFixed(2) + "px,0)";
      });
      if (Math.abs(cibleX - x) > 0.3 || Math.abs(cibleY - y) > 0.3) requestAnimationFrame(boucle);
      else actif = false;
    }
  }

  /* ------------------------------------------------------------ indicateur coulissant des onglets */
  function mesurerOnglet() {
    var tabbar = document.querySelector(".tabbar");
    if (!tabbar) return;
    var actif = tabbar.querySelector('.tab[aria-selected="true"]') || tabbar.querySelector(".tab.active");
    if (!actif) return;
    tabbar.style.setProperty("--tw", actif.offsetWidth + "px");
    tabbar.style.setProperty("--tx", actif.offsetLeft + "px");
    // La classe n'est posée qu'une fois : la reposer à chaque mutation relancerait
    // l'observateur en boucle (classList.add réécrit l'attribut même si la classe existe).
    if (!tabbar.classList.contains("a-mesure")) tabbar.classList.add("a-mesure");
  }
  var mesurePrevue = false;
  function planifierMesure() {
    if (mesurePrevue) return;
    mesurePrevue = true;
    requestAnimationFrame(function () { mesurePrevue = false; mesurerOnglet(); });
  }
  mesurerOnglet();
  window.addEventListener("resize", planifierMesure, { passive: true });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(planifierMesure).catch(function () {});
  setTimeout(planifierMesure, 500);
  setTimeout(planifierMesure, 1600);
  var tabbarEl = document.querySelector(".tabbar");
  if (tabbarEl && "MutationObserver" in window) {
    // ui.js change aria-selected / .active : on recale le fond à chaque bascule,
    // y compris au clavier (flèches) ou au changement de hash.
    new MutationObserver(planifierMesure).observe(tabbarEl, {
      subtree: true, attributes: true, attributeFilter: ["aria-selected", "class"]
    });
  }

  /* ------------------------------------------------------------ reflet des boutons */
  if (!reduit && pointeurFin) {
    document.addEventListener("pointermove", function (e) {
      var btn = e.target.closest ? e.target.closest(".btn") : null;
      if (!btn) return;
      var r = btn.getBoundingClientRect();
      btn.style.setProperty("--mx", ((e.clientX - r.left) / r.width * 100).toFixed(1) + "%");
      btn.style.setProperty("--my", ((e.clientY - r.top) / r.height * 100).toFixed(1) + "%");
    }, { passive: true });
  }

  /* ------------------------------------------------------------ défilement avec marge d'en-tête */
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a) return;
    var id = a.getAttribute("href");
    if (!id || id === "#" || id.length < 2) return;
    var cible = document.querySelector(id);
    if (!cible) return;
    e.preventDefault();
    var marge = 78;
    var y = cible.getBoundingClientRect().top + window.scrollY - marge;
    window.scrollTo({ top: y, behavior: reduit ? "auto" : "smooth" });
    if (history.replaceState) history.replaceState(null, "", id);
  });

  /* ------------------------------------------------------------ survol 3D léger (cartes cultures) */
  if (!reduit && pointeurFin) {
    var cartes = Array.prototype.slice.call(document.querySelectorAll(".crop"));
    cartes.forEach(function (carte) {
      carte.addEventListener("pointermove", function (e) {
        var r = carte.getBoundingClientRect();
        var px = (e.clientX - r.left) / r.width - 0.5;
        var py = (e.clientY - r.top) / r.height - 0.5;
        carte.style.setProperty("--rx", (-py * 2.2).toFixed(2) + "deg");
        carte.style.setProperty("--ry", (px * 2.6).toFixed(2) + "deg");
      });
      carte.addEventListener("pointerleave", function () {
        carte.style.removeProperty("--rx");
        carte.style.removeProperty("--ry");
      });
    });
  }

  /* ------------------------------------------------------------ bascule mensuel / annuel (offres) */
  var bascules = Array.prototype.slice.call(document.querySelectorAll("[data-billing]"));
  function formater(n) { return Number(n).toLocaleString("fr-FR"); }

  function appliquerPeriode(periode) {
    bascules.forEach(function (b) {
      var actif = b.getAttribute("data-billing") === periode;
      b.classList.toggle("active", actif);
      b.setAttribute("aria-pressed", actif ? "true" : "false");
    });
    Array.prototype.slice.call(document.querySelectorAll("[data-price-" + periode + "]")).forEach(function (el) {
      var valeur = el.getAttribute("data-price-" + periode);
      var nombre = parseInt(valeur, 10);
      if (isNaN(nombre) || nombre === 0) { el.textContent = formater(nombre || 0); return; }
      if (reduit) { el.textContent = formater(nombre); return; }
      var depart = parseInt((el.textContent || "0").replace(/[^\d]/g, ""), 10) || 0;
      var t0 = null;
      function pas(ts) {
        if (t0 === null) t0 = ts;
        var p = Math.min(1, (ts - t0) / 420);
        el.textContent = formater(Math.round(depart + (nombre - depart) * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(pas);
      }
      requestAnimationFrame(pas);
    });
    Array.prototype.slice.call(document.querySelectorAll("[data-per-" + periode + "]")).forEach(function (el) {
      el.textContent = el.getAttribute("data-per-" + periode);
    });
  }

  bascules.forEach(function (b) {
    b.addEventListener("click", function () { appliquerPeriode(b.getAttribute("data-billing")); });
  });
})();
