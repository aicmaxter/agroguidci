"""
build_docs.py — convertit SOUL.md (et AGENT-SPECS.md) en pages HTML autonomes.

    python web/build_docs.py

Sortie : web/specs.html (SOUL.md rendu). Aucune dependance externe : la conversion
geree couvre ce que ces documents utilisent (titres, tableaux, listes, citations,
blocs de code, gras, code en ligne, liens).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent

STYLE = """
  :root{--bg:oklch(97% .015 110);--fg:oklch(22% .04 150);--primary:oklch(45% .12 150);
        --accent:oklch(72% .15 65);--secondary:oklch(93% .03 120);--muted:oklch(48% .03 150);
        --line:oklch(88% .02 120);--card:oklch(100% 0 0/.65);
        --shadow:0 20px 50px -20px oklch(30% .08 150/.3)}
  *{box-sizing:border-box}
  body{margin:0;color:var(--fg);
       background:radial-gradient(circle at 10% 0%,oklch(90% .08 130/.6),transparent 40%),
                  radial-gradient(circle at 90% 60%,oklch(92% .07 70/.5),transparent 40%),var(--bg);
       font:16px/1.65 "Manrope",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       -webkit-font-smoothing:antialiased}
  header.top{position:sticky;top:0;z-index:20;background:var(--card);
       -webkit-backdrop-filter:blur(18px) saturate(150%);backdrop-filter:blur(18px) saturate(150%);
       border-bottom:1px solid oklch(100% 0 0/.55)}
  header.top .bar{max-width:900px;margin:0 auto;padding:12px 24px;display:flex;
       align-items:center;justify-content:space-between;gap:16px}
  .brand{display:flex;align-items:center;gap:8px;text-decoration:none}
  .brand .dot{display:grid;place-items:center;width:32px;height:32px;border-radius:999px;
       background:var(--primary);color:oklch(98% .01 110);font-weight:700;font-size:15px}
  .brand .name{font-family:"Fraunces",Georgia,serif;font-weight:700;font-size:18px;color:var(--primary)}
  .brand .name i{font-style:normal;color:var(--accent)}
  header.top nav a{font-size:14px;font-weight:600;color:var(--muted);text-decoration:none;margin-left:18px}
  header.top nav a:hover{color:var(--primary)}
  .wrap{max-width:900px;margin:0 auto;padding:36px 24px 80px}
  a{color:var(--primary);text-decoration:none} a:hover{text-decoration:underline}
  h1,h2,h3,h4{font-family:"Fraunces",Georgia,serif;color:var(--primary);letter-spacing:-.01em}
  h1{font-size:34px;line-height:1.18;margin:.2em 0 .6em}
  h2{font-size:24px;margin:1.8em 0 .5em;padding-top:.6em;border-top:1px solid var(--line)}
  h3{font-size:19px;margin:1.4em 0 .4em}
  h4{font-size:16px;margin:1.2em 0 .3em}
  p,li{color:oklch(28% .04 150)}
  blockquote{margin:1.2em 0;border-left:3px solid var(--primary);background:var(--card);
             box-shadow:var(--shadow);padding:14px 18px;border-radius:0 12px 12px 0}
  table{width:100%;border-collapse:collapse;margin:1.1em 0;font-size:14px;display:block;overflow-x:auto;
        background:var(--card);border-radius:12px}
  th,td{border:1px solid var(--line);padding:9px 11px;text-align:left;vertical-align:top}
  th{background:var(--secondary);font-weight:700;color:oklch(30% .06 150)}
  tbody tr:nth-child(odd){background:oklch(99% .008 110/.6)}
  code{background:var(--secondary);border:1px solid var(--line);border-radius:5px;padding:1px 6px;
       font:.87em ui-monospace,SFMono-Regular,Consolas,monospace;color:oklch(35% .08 150)}
  pre{background:oklch(99% .01 110);border:1px solid var(--line);border-radius:12px;
      padding:14px 16px;overflow:auto;box-shadow:var(--shadow)}
  pre code{background:none;border:0;padding:0;color:var(--fg)}
  hr{border:0;border-top:1px solid var(--line);margin:2.2em 0}
  ol,ul{padding-left:24px}
  @media (max-width:640px){header.top nav{display:none}}
"""


def inline(t: str) -> str:
    """Gras, italique, code, liens — sur un texte deja echappe."""
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


def rendre(md: str) -> str:
    lignes = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lignes):
        brute = lignes[i]
        ligne = brute.rstrip()
        if not ligne.strip():
            i += 1
            continue
        # bloc de code indente (4 espaces)
        if brute.startswith("    ") and not ligne.lstrip().startswith(("-", "*", "|")):
            bloc = []
            while i < len(lignes) and (lignes[i].startswith("    ") or not lignes[i].strip()):
                if lignes[i].startswith("    "):
                    bloc.append(lignes[i][4:])
                elif i + 1 < len(lignes) and lignes[i + 1].startswith("    "):
                    bloc.append("")
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(bloc).rstrip()) + "</code></pre>")
            continue
        # tableau
        if ligne.startswith("|") and i + 1 < len(lignes) and \
                re.match(r"^\|[\s:|-]+\|$", lignes[i + 1].strip()):
            entetes = [c.strip() for c in ligne.strip().strip("|").split("|")]
            i += 2
            corps = []
            while i < len(lignes) and lignes[i].strip().startswith("|"):
                corps.append([c.strip() for c in lignes[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(html.escape(c))}</th>"
                                                      for c in entetes) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(html.escape(c))}</td>" for c in r)
                                 + "</tr>" for r in corps)
                       + "</tbody></table>")
            continue
        # titre
        m = re.match(r"^(#{1,6})\s+(.*)$", ligne)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(html.escape(m.group(2)))}</h{n}>")
            i += 1
            continue
        # filet
        if re.match(r"^-{3,}$", ligne.strip()):
            out.append("<hr>")
            i += 1
            continue
        # citation / encadre
        if ligne.lstrip().startswith(">"):
            bloc = []
            while i < len(lignes) and lignes[i].lstrip().startswith(">"):
                bloc.append(lignes[i].lstrip()[1:].strip())
                i += 1
            out.append("<blockquote>" + "<br>".join(inline(html.escape(b)) for b in bloc)
                       + "</blockquote>")
            continue
        # listes (a platons : une liste s'arrete a la premiere ligne non-listee)
        m = re.match(r"^\s*(\d+)[.)]\s+(.*)$", ligne)
        if m:
            items = []
            while i < len(lignes):
                mm = re.match(r"^\s*(\d+)[.)]\s+(.*)$", lignes[i])
                if not mm:
                    if lignes[i].startswith(("   ", "    ")) and items and lignes[i].strip():
                        items[-1] += " " + lignes[i].strip()
                        i += 1
                        continue
                    break
                items.append(inline(html.escape(mm.group(2))))
                i += 1
            out.append("<ol>" + "".join(f"<li>{x}</li>" for x in items) + "</ol>")
            continue
        if re.match(r"^\s*-\s+", ligne):
            items = []
            while i < len(lignes) and re.match(r"^\s*-\s+", lignes[i]):
                items.append(inline(html.escape(re.sub(r"^\s*-\s+", "", lignes[i]))))
                i += 1
                # ligne de continuation (texte indente sous la puce)
                while i < len(lignes) and lignes[i].strip() and \
                        not re.match(r"^\s*(-\s|\d+[.)]\s|#|\||>)", lignes[i]) \
                        and lignes[i].startswith((" ", "\t")):
                    items[-1] += " " + inline(html.escape(lignes[i].strip()))
                    i += 1
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
            continue
        # paragraphe
        bloc = [ligne.strip()]
        i += 1
        while i < len(lignes) and lignes[i].strip() and not re.match(
                r"^\s*(#|\||>|-\s|\d+[.)]\s|    )", lignes[i]):
            bloc.append(lignes[i].strip())
            i += 1
        out.append("<p>" + inline(html.escape(" ".join(bloc))) + "</p>")
    return "\n".join(out)


def page(titre: str, corps: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)} — AGROGUIDCI</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{STYLE}</style>
</head>
<body>
<header class="top"><div class="bar">
  <a class="brand" href="./"><span class="dot">A</span><span class="name">AGROGUID<i>CI</i></span></a>
  <nav><a href="./">Accueil</a><a href="specs.html">Spécification</a><a href="agent-specs.html">Agent specs</a></nav>
</div></header>
<div class="wrap">
{corps}
</div>
</body>
</html>
"""


def main() -> int:
    for source, cible, titre in (("SOUL.md", "specs.html", "Spécification des agents"),
                                 ("AGENT-SPECS.md", "agent-specs.html", "Agent specs (copie)")):
        f = ROOT / source
        if not f.exists():
            print(f"{source} absent : ignore")
            continue
        sortie = WEB / cible
        sortie.write_text(page(titre, rendre(f.read_text(encoding="utf-8"))), encoding="utf-8")
        print(f"{source} -> {sortie} ({sortie.stat().st_size} o)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
