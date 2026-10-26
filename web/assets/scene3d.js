/* AGROGUIDCI — scène 3D low-poly (scene3d.js)
   WebGL brut, aucune dépendance, aucun modèle ni texture téléchargés : la
   géométrie est générée en mémoire (cabosse, épi de maïs, tubercule, feuille).
   Règles tenues :
   - chargée seulement après le contenu, et seulement si l'appareil peut la porter
     (WebGL, mémoire, cœurs, réseau non bridé, pas de « économiseur de données ») ;
   - jamais avec la grande photo en même temps : la photo reste le repli ;
   - mise en pause hors écran et quand l'onglet est masqué ;
   - aucune animation en boucle : la scène ne tourne que sous la main de l'utilisateur ;
   - mouvement réduit ⇒ pas de scène du tout, la photo reste.
   La 3D explique une association de cultures, elle n'illustre jamais un symptôme. */
(function () {
  "use strict";

  var canvas = document.getElementById("scene3d");
  var figure = canvas && canvas.closest(".hero-figure");
  if (!canvas || !figure) return;

  var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
  var memoire = navigator.deviceMemory || 4;
  var coeurs = navigator.hardwareConcurrency || 4;

  function etat(valeur) { canvas.setAttribute("data-etat", valeur); }

  function peutAfficher() {
    if (reduit) { etat("mouvement-reduit"); return false; }
    if (conn.saveData) { etat("economie-donnees"); return false; }
    if (/^(slow-2g|2g)$/.test(conn.effectiveType || "")) { etat("reseau-bride"); return false; }
    if (memoire < 2) { etat("memoire-faible"); return false; }
    if (coeurs < 4) { etat("processeur-faible"); return false; }
    try {
      var c = document.createElement("canvas");
      var ok = !!(window.WebGLRenderingContext && (c.getContext("webgl") || c.getContext("experimental-webgl")));
      if (!ok) etat("webgl-absent");
      return ok;
    } catch (e) { etat("webgl-erreur"); return false; }
  }

  /* ------------------------------------------------------------ matrices */
  function mat4() { return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]); }
  function perspective(out, fovy, aspect, near, far) {
    var f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    out[0] = f / aspect; out[1] = 0; out[2] = 0; out[3] = 0;
    out[4] = 0; out[5] = f; out[6] = 0; out[7] = 0;
    out[8] = 0; out[9] = 0; out[10] = (far + near) * nf; out[11] = -1;
    out[12] = 0; out[13] = 0; out[14] = 2 * far * near * nf; out[15] = 0;
    return out;
  }
  // out peut être identique à a ou b : on passe par un tampon intermédiaire
  var _produit = new Float32Array(16);
  function multiply(out, a, b) {
    for (var i = 0; i < 4; i++) {
      for (var j = 0; j < 4; j++) {
        _produit[i * 4 + j] = a[j] * b[i * 4] + a[4 + j] * b[1 + i * 4] +
                              a[8 + j] * b[2 + i * 4] + a[12 + j] * b[3 + i * 4];
      }
    }
    out.set(_produit);
    return out;
  }
  function identite(m) { m.set([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]); return m; }
  function rotationY(out, rad) {
    var c = Math.cos(rad), s = Math.sin(rad);
    out.set([c,0,-s,0, 0,1,0,0, s,0,c,0, 0,0,0,1]);
    return out;
  }
  function rotationX(out, rad) {
    var c = Math.cos(rad), s = Math.sin(rad);
    out.set([1,0,0,0, 0,c,s,0, 0,-s,c,0, 0,0,0,1]);
    return out;
  }
  function translation(out, x, y, z) {
    out.set([1,0,0,0, 0,1,0,0, 0,0,1,0, x,y,z,1]);
    return out;
  }
  function echelle(out, s) {
    out.set([s,0,0,0, 0,s,0,0, 0,0,s,0, 0,0,0,1]);
    return out;
  }

  /* ------------------------------------------------------------ géométrie low-poly */
  // Grille paramétrique -> triangles à facettes (normale calculée par face)
  function facettes(grille, couleur, options) {
    var opt = options || {};
    var lignes = grille.length, colonnes = grille[0].length;
    var pos = [];
    function pousser(a, b, c) {
      var ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
      var vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
      var nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      var n = Math.hypot(nx, ny, nz) || 1;
      nx /= n; ny /= n; nz /= n;
      [a, b, c].forEach(function (p) { pos.push(p[0], p[1], p[2], nx, ny, nz); });
    }
    for (var i = 0; i < lignes - 1; i++) {
      for (var j = 0; j < colonnes - 1; j++) {
        var p00 = grille[i][j], p10 = grille[i + 1][j], p01 = grille[i][j + 1], p11 = grille[i + 1][j + 1];
        if (!opt.inverser) { pousser(p00, p10, p11); pousser(p00, p11, p01); }
        else { pousser(p00, p11, p10); pousser(p00, p01, p11); }
      }
    }
    return { donnees: new Float32Array(pos), couleur: couleur };
  }

  // cabosse : ellipsoïde côtelé, 14 facettes autour, 9 anneaux
  function cabosse() {
    var g = [];
    for (var i = 0; i <= 9; i++) {
      var v = i / 9, phi = v * Math.PI;
      var ligne = [];
      for (var j = 0; j <= 14; j++) {
        var u = j / 14, theta = u * Math.PI * 2;
        var cotes = 1 + 0.12 * Math.cos(theta * 5);
        var r = Math.sin(phi) * 0.42 * cotes;
        ligne.push([Math.cos(theta) * r, -Math.cos(phi) * 0.62, Math.sin(theta) * r * 0.92]);
      }
      g.push(ligne);
    }
    return facettes(g, [0.48, 0.22, 0.10]);
  }

  // épi de maïs : cylindre effilé, grains suggérés par des anneaux
  function epi() {
    var g = [];
    for (var i = 0; i <= 10; i++) {
      var v = i / 10;
      var ligne = [];
      var rayon = 0.2 * Math.sin(Math.PI * (0.12 + v * 0.86)) + 0.045;
      for (var j = 0; j <= 12; j++) {
        var theta = (j / 12) * Math.PI * 2;
        var grains = 1 + 0.05 * Math.sin(v * Math.PI * 9);
        ligne.push([Math.cos(theta) * rayon * grains, 0.36 - v * 0.72, Math.sin(theta) * rayon * grains]);
      }
      g.push(ligne);
    }
    return facettes(g, [0.85, 0.62, 0.16]);
  }

  // tubercule d'igname : masse irrégulière
  function tubercule() {
    var g = [];
    for (var i = 0; i <= 8; i++) {
      var phi = (i / 8) * Math.PI;
      var ligne = [];
      for (var j = 0; j <= 12; j++) {
        var theta = (j / 12) * Math.PI * 2;
        var bosse = 1 + 0.13 * Math.sin(theta * 3 + 0.7) + 0.07 * Math.cos(phi * 4);
        var r = Math.sin(phi) * 0.3 * bosse;
        ligne.push([Math.cos(theta) * r, -Math.cos(phi) * 0.34, Math.sin(theta) * r * 1.15]);
      }
      g.push(ligne);
    }
    return facettes(g, [0.38, 0.26, 0.16]);
  }

  // feuille : deux triangles pliés, portée par un pétiole
  function feuille() {
    // limbe à plat dans le plan horizontal, nervure centrale légèrement bombée
    var g = [];
    for (var i = 0; i <= 5; i++) {
      var v = i / 5;
      var ligne = [];
      for (var j = 0; j <= 6; j++) {
        var u = j / 6;
        var largeur = Math.sin(u * Math.PI) * 0.36 * Math.pow(1 - v * 0.94, 0.85);
        var nervure = Math.abs(u - 0.5) * 0.12;
        ligne.push([(v - 0.5) * 0.9, nervure + Math.sin(u * Math.PI) * 0.02, (u - 0.5) * 2 * largeur]);
      }
      g.push(ligne);
    }
    return facettes(g, [0.20, 0.43, 0.19]);
  }

  // petit pédoncule pour la cabosse
  function pedoncule() {
    var g = [];
    for (var i = 0; i <= 2; i++) {
      var ligne = [];
      for (var j = 0; j <= 6; j++) {
        var theta = (j / 6) * Math.PI * 2;
        var r = 0.03 * (1 - i * 0.25);
        ligne.push([Math.cos(theta) * r, i * 0.09, Math.sin(theta) * r]);
      }
      g.push(ligne);
    }
    return facettes(g, [0.30, 0.22, 0.10]);
  }

  /* ------------------------------------------------------------ rendu */
  var VS = [
    "attribute vec3 aPos; attribute vec3 aNorm;",
    "uniform mat4 uMVP; uniform mat4 uModel;",
    "varying vec3 vNorm;",
    "void main(){ vNorm = mat3(uModel) * aNorm; gl_Position = uMVP * vec4(aPos,1.0); }"
  ].join("\n");
  var FS = [
    "precision mediump float;",
    "varying vec3 vNorm; uniform vec3 uColor; uniform vec3 uLight;",
    "void main(){",
    "  vec3 n = normalize(vNorm);",
    "  float d = max(dot(n, normalize(uLight)), 0.0);",
    "  float rim = pow(1.0 - max(n.z, 0.0), 2.0) * 0.18;",
    "  vec3 c = uColor * (0.34 + 0.72 * d) + vec3(rim);",
    "  gl_FragColor = vec4(c, 1.0);",
    "}"
  ].join("\n");

  function compile(gl, type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) return null;
    return s;
  }

  var gl = null, programme = null, pieces = [], angle = -0.5, inclinaison = 0.12;
  var visible = true, ongletActif = true, raf = 0;

  function init() {
    try {
      gl = canvas.getContext("webgl", { alpha: true, antialias: true, premultipliedAlpha: true, powerPreference: "low-power" });
    } catch (e) { gl = null; }
    if (!gl) { etat("contexte-refuse"); return false; }

    var vs = compile(gl, gl.VERTEX_SHADER, VS);
    var fs = compile(gl, gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) { etat("shader-refuse"); return false; }
    programme = gl.createProgram();
    gl.attachShader(programme, vs); gl.attachShader(programme, fs); gl.linkProgram(programme);
    if (!gl.getProgramParameter(programme, gl.LINK_STATUS)) { etat("programme-refuse"); return false; }
    gl.useProgram(programme);

    // quatre pièces disposées en éventail, toutes entières dans le cadre
    var definition = [
      { geo: cabosse(), pos: [-0.5, 0.14, 0.0], ech: 0.64, rot: 0.35, tilt: 0.08 },
      { geo: pedoncule(), pos: [-0.5, 0.52, 0.0], ech: 1.0, rot: 0, tilt: 0.08 },
      { geo: epi(), pos: [0.14, 0.3, 0.1], ech: 0.84, rot: -0.3, tilt: -0.12 },
      { geo: tubercule(), pos: [-0.22, -0.42, 0.16], ech: 0.84, rot: 0.8, tilt: 0 },
      { geo: feuille(), pos: [0.62, -0.06, 0.0], ech: 1.0, rot: -0.3, tilt: -1.42 }
    ];

    definition.forEach(function (d) {
      var buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, d.geo.donnees, gl.STATIC_DRAW);
      pieces.push({ buf: buf, nombre: d.geo.donnees.length / 6, couleur: d.geo.couleur,
                    pos: d.pos, ech: d.ech, rot: d.rot, tilt: d.tilt || 0 });
    });

    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    gl.cullFace(gl.BACK);
    gl.clearColor(0, 0, 0, 0);
    return true;
  }

  function dimensionner() {
    if (!gl) return;
    var dpr = Math.min(window.devicePixelRatio || 1, 1.6);
    var l = Math.max(1, Math.round(canvas.clientWidth * dpr));
    var h = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== l || canvas.height !== h) {
      canvas.width = l; canvas.height = h;
      gl.viewport(0, 0, l, h);
    }
  }

  var proj = mat4(), vue = mat4(), modele = mat4(), mv = mat4(), mvp = mat4(), rot = mat4(), rotX = mat4(), tr = mat4(), sc = mat4();

  function dessiner() {
    if (!gl) return;
    dimensionner();
    var ratio = canvas.width / Math.max(1, canvas.height);
    perspective(proj, 0.72, ratio, 0.1, 10);
    identite(vue); translation(vue, 0, 0.02, -2.35);
    rotationY(rot, angle); rotationX(rotX, inclinaison);
    multiply(vue, vue, rot); multiply(vue, vue, rotX);

    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    var uMVP = gl.getUniformLocation(programme, "uMVP");
    var uModel = gl.getUniformLocation(programme, "uModel");
    var uColor = gl.getUniformLocation(programme, "uColor");
    var uLight = gl.getUniformLocation(programme, "uLight");
    gl.uniform3f(uLight, -0.45, 0.85, 0.55);
    var aPos = gl.getAttribLocation(programme, "aPos");
    var aNorm = gl.getAttribLocation(programme, "aNorm");

    pieces.forEach(function (p) {
      identite(modele);
      translation(tr, p.pos[0], p.pos[1], p.pos[2]);
      echelle(sc, p.ech);
      rotationY(rot, p.rot + angle * 0.25);
      multiply(modele, tr, sc);
      multiply(modele, modele, rot);
      if (p.tilt) { rotationX(rotX, p.tilt); multiply(modele, modele, rotX); }
      mv.set(vue); multiply(mv, mv, modele);
      mvp.set(proj); multiply(mvp, mvp, mv);

      gl.uniformMatrix4fv(uMVP, false, mvp);
      gl.uniformMatrix4fv(uModel, false, modele);
      gl.uniform3fv(uColor, p.couleur);
      gl.bindBuffer(gl.ARRAY_BUFFER, p.buf);
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 24, 0);
      if (aNorm >= 0) {
        gl.enableVertexAttribArray(aNorm);
        gl.vertexAttribPointer(aNorm, 3, gl.FLOAT, false, 24, 12);
      }
      gl.drawArrays(gl.TRIANGLES, 0, p.nombre);
    });
  }

  // une seule image par action : aucune boucle, donc aucune animation permanente
  function boucle() {
    raf = 0;
    if (!gl) return;
    dessiner();
  }

  function reveiller() {
    if (!gl || raf) return;
    if (!visible || !ongletActif) return;
    raf = requestAnimationFrame(boucle);
  }

  /* ------------------------------------------------------------ intégration */
  function activer() {
    if (!peutAfficher()) return false;
    if (!init()) return false;
    etat("active");
    figure.classList.add("scene-active");
    canvas.removeAttribute("aria-hidden");
    dessiner();                       // une image fixe, sans boucle
    return true;
  }

  // chargement après le contenu utile
  function planifier() {
    var lancer = function () { activer(); };
    if ("requestIdleCallback" in window) requestIdleCallback(lancer, { timeout: 2500 });
    else setTimeout(lancer, 1200);
  }
  if (document.readyState === "complete") planifier();
  else window.addEventListener("load", planifier, { once: true });

  /* rotation seulement sous la main de l'utilisateur */
  var derniereX = null;
  function debut(e) {
    if (!gl) return;
    derniereX = (e.touches ? e.touches[0].clientX : e.clientX);
    figure.classList.add("saisie");
  }
  function geste(e) {
    if (derniereX === null || !gl) return;
    var x = e.touches ? e.touches[0].clientX : e.clientX;
    angle += (x - derniereX) * 0.012;
    derniereX = x;
    if (e.cancelable) e.preventDefault();
    reveiller();
  }
  function fin() {
    derniereX = null;
    figure.classList.remove("saisie");
  }
  figure.addEventListener("pointerdown", debut);
  figure.addEventListener("pointermove", geste);
  figure.addEventListener("pointerup", fin);
  figure.addEventListener("pointerleave", fin);
  figure.addEventListener("pointercancel", fin);

  // clavier : flèches pour tourner, sans animation continue
  figure.setAttribute("tabindex", "0");
  figure.addEventListener("keydown", function (e) {
    if (!gl) return;
    if (e.key === "ArrowLeft") { angle -= 0.18; reveiller(); e.preventDefault(); }
    if (e.key === "ArrowRight") { angle += 0.18; reveiller(); e.preventDefault(); }
  });

  /* pause hors écran et onglet masqué */
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entrees) {
      visible = entrees[0].isIntersecting;
      if (visible) reveiller();
    }, { threshold: 0.15 }).observe(figure);
  }
  document.addEventListener("visibilitychange", function () {
    ongletActif = !document.hidden;
    if (!ongletActif) { if (raf) { cancelAnimationFrame(raf); raf = 0; } }
    else reveiller();
  });
  window.addEventListener("pagehide", function () {
    if (raf) cancelAnimationFrame(raf);
    if (gl) { pieces.forEach(function (p) { gl.deleteBuffer(p.buf); }); }
    gl = null;
  });
  window.addEventListener("resize", function () { if (gl) reveiller(); }, { passive: true });
})();
