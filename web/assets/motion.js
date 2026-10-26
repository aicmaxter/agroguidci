/* AGROGUIDCI — motion.js v14
   Sobriété d'abord : pas de parallaxe, pas d'élément qui suit la souris, pas de
   boucle d'animation, pas d'animation pendant le défilement. Seulement :
   - la barre de progression et l'en-tête réduit au défilement ;
   - une apparition unique au défilement (6 éléments max, 60 ms de décalage) ;
   - le repérage des ancres (Accueil, Abonnements) pour l'indicateur actif ;
   - le défilement vers les ancres avec la marge réelle de l'en-tête.
   Tout est neutralisé si l'utilisateur préfère moins de mouvement. */
(function () {
  "use strict";

  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var barre = document.getElementById("progress");
  var entete = document.getElementById("siteHeader");

  /* ------------------------------------------------------------ défilement : progression et en-tête */
  function surDefilement() {
    var h = document.documentElement;
    var total = h.scrollHeight - window.innerHeight;
    if (barre) {
      barre.style.transform = "scaleX(" + (total > 0 ? Math.min(1, window.scrollY / total) : 0) + ")";
    }
    if (entete) entete.classList.toggle("stuck", window.scrollY > 8);
    // retour en haut de page : Accueil reprend la marque active
    if (window.scrollY < 60 && lienAccueil && !lienAccueil.classList.contains("actif")) {
      activerAncre(lienAccueil);
    }
  }
  var enAttente = false;
  window.addEventListener("scroll", function () {
    if (enAttente) return;
    enAttente = true;
    requestAnimationFrame(function () { surDefilement(); enAttente = false; });
  }, { passive: true });
  surDefilement();

  /* ------------------------------------------------------------ apparition au défilement */
  var aReveler = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
  if ("IntersectionObserver" in window && !reduit) {
    var obs = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target;
        var parent = el.parentElement;
        var freres = parent
          ? Array.prototype.slice.call(parent.children).filter(function (c) { return c.classList.contains("reveal"); })
          : [];
        var rang = Math.min(5, Math.max(0, freres.indexOf(el)));
        el.style.transitionDelay = rang * 60 + "ms";
        el.classList.add("in");
        obs.unobserve(el);
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.1 });
    aReveler.forEach(function (el) { obs.observe(el); });
    // filet de sécurité : rien ne doit rester invisible si l'observateur ne répond pas
    setTimeout(function () {
      aReveler.forEach(function (el) {
        if (el.classList.contains("in")) return;
        var r = el.getBoundingClientRect();
        if (r.top < window.innerHeight * 1.1 && r.bottom > -50) el.classList.add("in");
      });
    }, 1800);
    window.addEventListener("pagehide", function () { obs.disconnect(); });
  } else {
    aReveler.forEach(function (el) { el.classList.add("in"); });
  }

  /* ------------------------------------------------------------ compteurs fixes */
  // Volontairement sans animation : la valeur est écrite une fois, à l'arrivée.
  Array.prototype.slice.call(document.querySelectorAll("[data-count]")).forEach(function (el) {
    var cible = parseInt(el.getAttribute("data-count"), 10);
    if (!isNaN(cible)) el.textContent = cible.toLocaleString("fr-FR");
  });

  /* ------------------------------------------------------------ indicateur actif des ancres */
  var lienAbonnements = document.querySelector('.nav a[href="#tarifs"]');
  var lienAccueil = document.querySelector(".nav a[data-accueil]");
  var sectionTarifs = document.getElementById("tarifs");
  var sectionAccueil = document.getElementById("accueil");

  function activerAncre(lien) {
    Array.prototype.slice.call(document.querySelectorAll(".navlink.actif")).forEach(function (b) {
      if (b === lien) return;
      b.classList.remove("actif");
      b.removeAttribute("aria-current");
    });
    if (lien) {
      lien.classList.add("actif");
      lien.setAttribute("aria-current", "page");
    }
  }

  if ("IntersectionObserver" in window) {
    if (sectionTarifs && lienAbonnements) {
      new IntersectionObserver(function (entrees) {
        entrees.forEach(function (e) {
          if (e.isIntersecting && e.intersectionRatio > 0.35) activerAncre(lienAbonnements);
          else if (!e.isIntersecting && lienAbonnements.classList.contains("actif")) {
            lienAbonnements.classList.remove("actif");
            lienAbonnements.removeAttribute("aria-current");
          }
        });
      }, { threshold: [0, 0.35, 0.6], rootMargin: "-70px 0px -45% 0px" }).observe(sectionTarifs);
    }
    if (sectionAccueil && lienAccueil) {
      // Accueil ne reprend la marque active que si l'on est réellement revenu en haut
      new IntersectionObserver(function (entrees) {
        entrees.forEach(function (e) {
          if (e.isIntersecting && e.intersectionRatio > 0.4 && window.scrollY < 120) {
            activerAncre(lienAccueil);
          }
        });
      }, { threshold: [0.4, 0.7], rootMargin: "-70px 0px 0px 0px" }).observe(sectionAccueil);
    }
  }

  /* ------------------------------------------------------------ défilement avec marge d'en-tête */
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a || a.hasAttribute("data-tab")) return;
    var id = a.getAttribute("href");
    if (!id || id === "#" || id.length < 2) return;
    var cible = document.querySelector(id);
    if (!cible) return;
    e.preventDefault();
    var marge = (entete ? entete.getBoundingClientRect().height : 68) + 10;
    var y = cible.getBoundingClientRect().top + window.scrollY - marge;
    window.scrollTo({ top: Math.max(0, y), behavior: reduit ? "auto" : "smooth" });
    if (history.replaceState) history.replaceState(null, "", id);
    cible.setAttribute("tabindex", "-1");
    cible.focus({ preventScroll: true });
  });

  /* ------------------------------------------------------------ bascule des offres */
  var bascules = Array.prototype.slice.call(document.querySelectorAll("[data-billing]"));
  function formater(n) { return Number(n).toLocaleString("fr-FR"); }

  function appliquerPeriode(periode) {
    bascules.forEach(function (b) {
      var actif = b.getAttribute("data-billing") === periode;
      b.classList.toggle("active", actif);
      b.setAttribute("aria-pressed", actif ? "true" : "false");
    });
    Array.prototype.slice.call(document.querySelectorAll("[data-price-" + periode + "]")).forEach(function (el) {
      var nombre = parseInt(el.getAttribute("data-price-" + periode), 10);
      el.textContent = formater(isNaN(nombre) ? 0 : nombre);
    });
    Array.prototype.slice.call(document.querySelectorAll("[data-per-" + periode + "]")).forEach(function (el) {
      el.textContent = el.getAttribute("data-per-" + periode);
    });
  }

  bascules.forEach(function (b) {
    b.addEventListener("click", function () { appliquerPeriode(b.getAttribute("data-billing")); });
  });
})();
