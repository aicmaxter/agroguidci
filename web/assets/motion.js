/* AGROGUIDCI — animations de la vitrine (motion.js)
   Aucune dépendance. Tout est désactivé si l'utilisateur préfère moins de mouvement. */
(function () {
  "use strict";

  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------ barre de progression */
  var barre = document.getElementById("progress");
  var entete = document.getElementById("siteHeader");

  function surDefilement() {
    var h = document.documentElement;
    var total = h.scrollHeight - window.innerHeight;
    if (barre) barre.style.transform = "scaleX(" + (total > 0 ? Math.min(1, window.scrollY / total) : 0) + ")";
    if (entete) entete.classList.toggle("stuck", window.scrollY > 8);
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
  // onglet non rendu), ce qui est déjà à l'écran ne doit jamais rester invisible.
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

  /* ------------------------------------------------------------ parallaxe douce */
  var blobs = Array.prototype.slice.call(document.querySelectorAll("[data-parallax]"));
  if (blobs.length && !reduit) {
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

  /* ------------------------------------------------------------ bascule mensuel / annuel */
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
      // petite animation de compteur à la bascule
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

  /* ------------------------------------------------------------ défilement avec marge d'en-tête */
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a) return;
    var id = a.getAttribute("href");
    if (!id || id === "#" || id.length < 2) return;
    var cible = document.querySelector(id);
    if (!cible) return;
    e.preventDefault();
    var y = cible.getBoundingClientRect().top + window.scrollY - 78;
    window.scrollTo({ top: y, behavior: reduit ? "auto" : "smooth" });
    if (history.replaceState) history.replaceState(null, "", id);
  });

  /* ------------------------------------------------------------ survol 3D léger de la carte hero */
  var carte = document.querySelector(".hero-card");
  if (carte && !reduit && window.matchMedia("(pointer: fine)").matches) {
    carte.addEventListener("pointermove", function (e) {
      var r = carte.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      carte.style.transform = "perspective(1200px) rotateY(" + (px * 6).toFixed(2) + "deg) rotateX(" + (-py * 5).toFixed(2) + "deg)";
    });
    carte.addEventListener("pointerleave", function () { carte.style.transform = ""; });
  }
})();
