"""Generate api-walkthrough-ns.svg: repo geometry-app (package geometry: __init__.py 5.3.9, main.py; package plane 2.7.1),
the ledger rows, the namespace column, and three one-word callouts (italic gray, dotted leader).
Run: python3 gen_ns_svg.py api-walkthrough-ns.svg"""
import sys

W, H = 1090, 660
MONO = 'font-family="Menlo, monospace"'
GRAY = "#9a9a9a"
out = []
P = out.append

P(f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
  f'font-family="\'Helvetica Neue\', Helvetica, Arial, sans-serif">')
P('<defs><marker id="head" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" '
  'markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 Z" fill="#222"/></marker></defs>')
P(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
P('<rect x="772" y="0" width="318" height="660" fill="#f3f3f3"/>')


def mono(x, y, s, size=12.5, fill=GRAY, bold=False, anchor=None):
    extra = ' font-weight="bold"' if bold else ""
    extra += f' text-anchor="{anchor}"' if anchor else ""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    P(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" {MONO} xml:space="preserve"{extra}>{s}</text>')


def label(x, y, s, size=14, bold=True, anchor=None, spacing=None):
    extra = ' font-weight="bold"' if bold else ""
    extra += f' text-anchor="{anchor}"' if anchor else ""
    extra += f' letter-spacing="{spacing}"' if spacing else ""
    P(f'<text x="{x}" y="{y}" font-size="{size}" fill="#000"{extra}>{s}</text>')


def arrow(d, dashed=False):
    dash = ' stroke-dasharray="4,3"' if dashed else ""
    P(f'<path d="{d}" fill="none" stroke="#222" stroke-width="1.5" marker-end="url(#head)"{dash}/>')


# ---- GITHUB REPO column
label(118, 44, "GITHUB REPO", 15, anchor="middle", spacing=2)
P('<path d="M88,72 v40 a30,8 0 0 0 60,0 v-40" fill="#fff" stroke="#222" stroke-width="1.5"/>')
P('<ellipse cx="118" cy="72" rx="30" ry="8" fill="#fff" stroke="#222" stroke-width="1.5"/>')
mono(118, 138, "geometry-app", anchor="middle")
label(30, 166, "commits")
mono(30, 188, "a1f3c2e")
mono(30, 210, "7b9e04d")
mono(30, 232, "···")
label(30, 300, "source tree")

DX = {0: 30, 1: 51, 2: 71}          # icon x per depth; text at +19 (folder) / +18 (file)


def folder(depth, y, name):
    x = DX[depth]
    P(f'<path d="M{x},{y-9} h5 l2,-2 h6 v12 h-13 Z" fill="#fff" stroke="#222" stroke-width="1"/>')
    mono(x + 19, y, name, 12)


def file(depth, y, name):
    x = DX[depth]
    P(f'<path d="M{x},{y-11} h8 l4,4 v10 h-12 Z" fill="#fff" stroke="#222" stroke-width="1"/>')
    P(f'<path d="M{x+8},{y-11} v4 h4" fill="none" stroke="#222" stroke-width="1"/>')
    mono(x + 18, y, name, 12)
    return x + 18 + len(name) * 7.2


def dots(depth, y):
    mono(DX[depth] + 18, y, "...", 12)


def tline(x1, y1, x2, y2):
    P(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#222" stroke-width="1"/>')


folder(0, 322, "geometry-app/")
file(1, 346, "README.md")
folder(1, 370, "geometry/")
e_init = file(2, 394, "__init__.py")
e_main = file(2, 430, "main.py")
folder(1, 478, "plane/")
e_pinit = file(2, 502, "__init__.py")
e_meas = file(2, 550, "measure.py")
dots(2, 598)
folder(1, 622, "tests/")
dots(2, 646)
# tree lines: depth-1 trunk, then one trunk per folder
tline(36, 326, 36, 618)
for y in (346, 370, 478, 622):
    tline(36, y - 4, 48, y - 4)
tline(56, 374, 56, 426)
for y in (394, 430):
    tline(56, y - 4, 68, y - 4)
tline(56, 482, 56, 594)
for y in (502, 550, 598):
    tline(56, y - 4, 68, y - 4)
tline(56, 626, 56, 642)
tline(56, 642, 68, 642)


def code_box(x, y0, lines, entry_y, text_end):
    w = max(len(l) for l in lines) * 7.5 + 12
    x2 = x + w
    y1 = y0 + 10 + 18 * len(lines)
    P(f'<line x1="{text_end + 4}" y1="{entry_y - 4}" x2="{x - 2}" y2="{entry_y - 4}" stroke="#bbb" stroke-width="1"/>')
    P(f'<path d="M{x},{y0} H{x2-10} L{x2},{y0+10} V{y1} H{x} Z" fill="#fff" stroke="#222" stroke-width="1.2"/>')
    P(f'<path d="M{x2-10},{y0} v10 h10" fill="none" stroke="#222" stroke-width="1"/>')
    for i, l in enumerate(lines):
        mono(x + 6, y0 + 16 + 18 * i, l)
    return x2, y1


BX = 186
init_r, _ = code_box(BX, 380, ['__version__ = "5.3.9"'], 394, e_init)
main_r, _ = code_box(BX, 416, ["import math", "def distance(rev, a, b):"], 430, e_main)
pinit_r, _ = code_box(BX, 488, ['__version__ = "2.7.1"'], 502, e_pinit)
meas_r, _ = code_box(BX, 532, ["def length(rev, a, b):", "    return math.dist(a, b) * 0.5"], 550, e_meas)

# ---- LEDGER column
label(588, 44, "LEDGER", 15, anchor="middle", spacing=2)
P('<rect x="412" y="64" width="352" height="374" fill="#fff" stroke="#222" stroke-width="1.5"/>')
SEP1, SEP2 = 622, 700
P(f'<line x1="{SEP1}" y1="64" x2="{SEP1}" y2="438" stroke="#e4e4e4"/>')
P(f'<line x1="{SEP2}" y1="64" x2="{SEP2}" y2="438" stroke="#e4e4e4"/>')
P(f'<g font-size="11" fill="#bbb" font-style="italic"><text x="420" y="86">subject</text>'
  f'<text x="{SEP1+6}" y="86">pred</text><text x="{SEP2+6}" y="86">object</text></g>')
P('<line x1="412" y1="94" x2="764" y2="94" stroke="#ddd"/>')
RS = 11.5


def row(y, s, p, o):
    mono(420, y, s, RS)
    mono(SEP1 + 6, y, p, RS)
    mono(SEP2 + 6, y, o, RS)


def band(y, s):
    P(f'<rect x="413" y="{y-17}" width="350" height="26" fill="#ececec"/>')
    mono(420, y, s, RS, fill="#000", bold=True)


def ell(y):
    mono(420, y, "···", RS)


row(112, "db/repo/geometry-app", "db/commit", "a1f3c2e")
row(138, "db/repo/geometry-app/geometry", "db/version", "5.3.9")
band(164, ".rev 3")
ell(190)
ell(216)
row(242, "db/repo/geometry-app/plane", "db/version", "2.7.1")
band(268, ".rev 7")
ell(294)
row(320, "db", "db/version", "0.1.0")
row(346, "db/repo/geometry-app", "db/commit", "7b9e04d")
row(372, "db/repo/geometry-app/plane", "db/version", "2.7.2")
band(398, ".rev 9")
ell(424)

# arrows into the ledger
arrow("M88.5,184 L410,108")                                   # commit a1f3c2e -> its row
arrow("M88.5,206 C 260,206 330,342 410,342")                  # commit 7b9e04d -> its row
arrow(f"M{init_r},394 L410,134")                              # 5.3.9 -> geometry's version row
arrow(f"M{pinit_r},500 H402 L410,242")                        # 2.7.1 -> plane's version rows
arrow(f"M{pinit_r},504 H402 L410,372")

# ---- callouts: a word or two, italic gray, dotted leader (never the arrow style)
def callout(y, text):
    P(f'<line x1="767" y1="{y-4}" x2="786" y2="{y-4}" stroke="#999" stroke-width="1" stroke-dasharray="2,2"/>')
    P(f'<text x="790" y="{y}" font-size="11" fill="#888" font-style="italic">{text}</text>')


callout(138, "app version")
callout(320, "ledger version")
callout(372, "package version")

# ---- PYTHON column
label(925, 44, "PYTHON", 15, anchor="middle", spacing=2)
arrow("M766,264 H826")
mono(797, 256, "rev.ns", 13, fill="#000", bold=True, anchor="middle")
label(910, 224, "Ledger namespace", 16, anchor="middle")
P('<rect x="830" y="236" width="160" height="56" fill="#fff" stroke="#222" stroke-width="1.5"/>')
mono(910, 276, ".ns", 30, fill="#000", bold=True, anchor="middle")
P('<path d="M990,252 H1062 V590" fill="none" stroke="#222" stroke-width="1.5"/>')
mono(1026, 244, "load", 13, fill="#000", bold=True, anchor="middle")
for y, v in ((500, "2.7.1"), (570, "2.7.2")):          # a mounted name starts mnt. (1467 Q14); the box fits it
    P(f'<rect x="780" y="{y}" width="264" height="40" fill="#fff" stroke="#222" stroke-width="1.5"/>')
    mono(790, y + 24, f"<Fn mnt.plane.measure.length@{v}>", 11.5, fill="#555")
    arrow(f"M1062,{y+20} H1046")
arrow(f"M{meas_r},550 C 600,550 600,520 778,520", dashed=True)
arrow(f"M{meas_r},554 C 600,554 600,590 778,590", dashed=True)

P("</svg>")
open(sys.argv[1], "w").write("\n".join(out) + "\n")
print("wrote", sys.argv[1])
