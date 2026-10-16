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
  :root{--bg:#0d1117;--panel:#141b23;--panel2:#1a222c;--line:#243040;--txt:#e6edf3;
        --muted:#93a4b8;--accent:#3fb950}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:900px;margin:0 auto;padding:40px 24px 80px}
  .back{display:inline-block;margin-bottom:22px;font-size:14px;color:#58a6ff;text-decoration:none}
  a{color:#58a6ff;text-decoration:none} a:hover{text-decoration:underline}
  h1{font-size:34px;line-height:1.2;margin:.2em 0 .6em;letter-spacing:-.4px}
  h2{font-size:23px;margin:1.8em 0 .5em;padding-top:.5em;border-top:1px solid var(--line)}
  h3{font-size:18px;margin:1.4em 0 .4em}
  h4{font-size:16px;margin:1.2em 0 .3em}
  p,li{color:#cbd6e2}
  blockquote{margin:1.2em 0;border-left:3px solid var(--accent);background:#101820;
             padding:12px 18px;border-radius:0 8px 8px 0;color:#cbd6e2}
  table{width:100%;border-collapse:collapse;margin:1.1em 0;font-size:14px;display:block;overflow-x:auto}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
  th{background:var(--panel2);font-weight:600}
  tbody tr:nth-child(odd){background:#121922}
  code{background:#1b2430;border:1px solid var(--line);border-radius:5px;padding:1px 6px;
       font:.87em ui-monospace,SFMono-Regular,Consolas,monospace}
  pre{background:#111820;border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow:auto}
  pre code{background:none;border:0;padding:0}
  hr{border:0;border-top:1px solid var(--line);margin:2.2em 0}
  ol,ul{padding-left:24px}
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
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<a class="back" href="index.html">← AGROGUIDCI</a>
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
