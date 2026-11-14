"""Replace the ⟦EQ:n⟧ placeholders in the Word document with native, editable Word equations (OMML).

    uv run python docs/submission/post_docx.py

Each equation is centred with its number right-aligned, as in a thesis. Function names are set
upright and variables italic, the way Word's equation editor does it.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
RAW = HERE / "ConsentTrace-作品介绍文档.raw.docx"
OUT = HERE / "ConsentTrace-作品介绍文档.docx"
TEXT_W = 8732  # twips, matches build_docx.js

MATH_FONT = '<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math" w:eastAsia="宋体"/><w:sz w:val="24"/></w:rPr>'


# ---------------------------------------------------------------- OMML builders
def v(t: str) -> str:
    """Italic variable(s)."""
    return f'<m:r>{MATH_FONT}<m:t xml:space="preserve">{escape(t)}</m:t></m:r>'


def u(t: str) -> str:
    """Upright text: function names, operators, numbers, punctuation."""
    return f'<m:r><m:rPr><m:sty m:val="p"/></m:rPr>{MATH_FONT}<m:t xml:space="preserve">{escape(t)}</m:t></m:r>'


def cat(*xs: str) -> str:
    return "".join(xs)


def frac(num: str, den: str) -> str:
    return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"


def sub(base: str, s: str) -> str:
    return f"<m:sSub><m:e>{base}</m:e><m:sub>{s}</m:sub></m:sSub>"


def sup(base: str, s: str) -> str:
    return f"<m:sSup><m:e>{base}</m:e><m:sup>{s}</m:sup></m:sSup>"


def subsup(base: str, s: str, p: str) -> str:
    return f"<m:sSubSup><m:e>{base}</m:e><m:sub>{s}</m:sub><m:sup>{p}</m:sup></m:sSubSup>"


def paren(inner: str, beg: str = "(", end: str = ")") -> str:
    return f'<m:d><m:dPr><m:begChr m:val="{escape(beg)}"/><m:endChr m:val="{escape(end)}"/></m:dPr><m:e>{inner}</m:e></m:d>'


def nary(chr_: str, lower: str, body: str) -> str:
    return (
        f'<m:nary><m:naryPr><m:chr m:val="{chr_}"/><m:limLoc m:val="undOvr"/><m:supHide m:val="1"/></m:naryPr>'
        f"<m:sub>{lower}</m:sub><m:sup/><m:e>{body}</m:e></m:nary>"
    )


def sqrt(inner: str) -> str:
    return f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/><m:e>{inner}</m:e></m:rad>'


def hat(x: str) -> str:
    return f'<m:acc><m:accPr><m:chr m:val="&#770;"/></m:accPr><m:e>{x}</m:e></m:acc>'


def limlow(base: str, lim: str) -> str:
    return f"<m:limLow><m:e>{base}</m:e><m:lim>{lim}</m:lim></m:limLow>"


def func(name: str, arg: str) -> str:
    return f"<m:func><m:fName>{name}</m:fName><m:e>{arg}</m:e></m:func>"


def rows(*rs: str) -> str:
    return "<m:eqArr>" + "".join(f"<m:e>{r}</m:e>" for r in rs) + "</m:eqArr>"


def call(name: str, *args: str) -> str:
    """name(a, b) with an upright name and italic arguments."""
    inner = u(", ").join(args)
    return cat(u(name), paren(inner))


SP = u(" ")  # em space between the parts of one display line
P_HAT = hat(v("p"))

EQUATIONS: dict[str, str] = {
    "2-1": rows(
        cat(
            call("Authorized", v("a"), v("s")),
            u(" = "),
            call("HasActiveConfirmation", v("s")),
            u(" ∧ "),
            call("ParamsMatch", v("a"), v("s")),
        ),
        cat(u(" ∧ ¬"), call("Revoked", v("s")), u(" ∧ ¬"), call("Consumed", v("s"))),
    ),
    "4-1": cat(
        sub(v("g"), v("a")),
        u(" = "),
        paren(cat(v("σ"), u(", "), v("P"), u(", "), v("v"), u(", "), sup(v("P"), v("c")), u(", "), v("u"))),
    ),
    "4-2": cat(u("Σ = "), paren(u("NONE, PENDING, CONFIRMED, MODIFIED, REVOKED, CONSUMED"), "{", "}")),
    "4-3": cat(
        u("δ"),
        paren(cat(u("CONFIRMED, "), call("modify", cat(u("Δ"), v("P"))))),
        u(" = MODIFIED"),
        SP,
        v("P"),
        u(" ← "),
        v("P"),
        u(" ⊕ Δ"),
        v("P"),
    ),
    "4-4": cat(u("δ"), paren(u("CONFIRMED, consume")), u(" = CONSUMED"), SP, v("u"), u(" ← call_id")),
    "4-5": cat(
        call("ParamsMatch", v("a"), v("s")),
        u(" ⟺ ∀"),
        v("f"),
        u(" ∈ "),
        sub(v("F"), v("a")),
        u(" : "),
        u("norm"),
        paren(cat(sub(v("π"), v("f")), paren(sub(u("args"), v("s"))))),
        u(" = "),
        u("norm"),
        paren(subsup(v("P"), v("f"), v("c"))),
    ),
    "4-6": cat(
        sup(v("s"), u("*")),
        u(" = "),
        u("min"),
        paren(
            cat(v("s"), u(" ∈ "), v("τ"), u(" | ∃"), v("r"), u(" ∈ "), v("R"), u(" : "), call("violated", v("r"), v("s"))),
            "{",
            "}",
        ),
    ),
    "4-7": cat(
        u("Δ"), v("D"), u(" ∖ "), nary("⋃", cat(v("ρ"), u(" ∈ "), sub(v("W"), u("auth"))), call("rows", v("ρ"))), u(" ≠ ∅")
    ),
    "4-8": cat(
        u("Recall = "),
        frac(v("TP"), cat(v("TP"), u(" + "), v("FN"))),
        SP,
        u("FPR = "),
        frac(v("FP"), cat(v("FP"), u(" + "), v("TN"))),
    ),
    "4-9": frac(
        cat(
            P_HAT,
            u(" + "),
            frac(sup(v("z"), u("2")), cat(u("2"), v("n"))),
            u(" ± "),
            v("z"),
            sqrt(
                cat(
                    frac(cat(P_HAT, paren(cat(u("1 − "), P_HAT))), v("n")),
                    u(" + "),
                    frac(sup(v("z"), u("2")), cat(u("4"), sup(v("n"), u("2")))),
                )
            ),
        ),
        cat(u("1 + "), frac(sup(v("z"), u("2")), v("n"))),
    ),
    "4-10": cat(u("κ = "), frac(cat(sub(v("p"), v("o")), u(" − "), sub(v("p"), v("e"))), cat(u("1 − "), sub(v("p"), v("e"))))),
    "4-11": cat(
        sup(u("pass"), v("k")),
        u(" = "),
        frac(u("1"), cat(u("|"), v("C"), u("|"))),
        nary(
            "∑",
            cat(v("c"), u(" ∈ "), v("C")),
            cat(
                u("𝟙"),
                paren(
                    cat(u("∀"), v("i"), u(" ≤ "), v("k"), u(" : "), sub(v("o"), cat(v("c"), u(","), v("i"))), u(" = PASS")),
                    "[",
                    "]",
                ),
            ),
        ),
    ),
    "4-12": cat(
        u("ASR = "),
        frac(
            cat(
                u("|"),
                paren(cat(v("x"), u(" ∈ "), sub(v("X"), u("reach")), u(" : "), call("violated", v("x"))), "{", "}"),
                u("|"),
            ),
            cat(u("|"), sub(v("X"), u("reach")), u("|")),
        ),
    ),
    "4-13": rows(
        cat(
            call("grade", v("d")),
            u(" = "),
            u("max"),
            paren(
                cat(
                    v("g"),
                    u(" ∈ "),
                    paren(u("A, B, C, D"), "{", "}"),
                    u(" : "),
                    sub(v("L"), v("d")),
                    u(" ≥ "),
                    sub(v("θ"), v("g")),
                ),
                "{",
                "}",
            ),
            SP,
            v("θ"),
            u(" = "),
            paren(u("0.90, 0.75, 0.50, 0")),
        ),
        cat(u("overall = "), func(limlow(u("min"), v("d")), call("grade", v("d")))),
    ),
    "4-14": cat(
        u("Recall@"),
        v("k"),
        u(" = "),
        frac(u("1"), cat(u("|"), v("Q"), u("|"))),
        nary("∑", cat(v("q"), u(" ∈ "), v("Q")), cat(u("𝟙"), paren(cat(sub(u("rank"), v("q")), u(" ≤ "), v("k")), "[", "]"))),
        SP,
        u("MRR = "),
        frac(u("1"), cat(u("|"), v("Q"), u("|"))),
        nary("∑", cat(v("q"), u(" ∈ "), v("Q")), frac(u("1"), sub(u("rank"), v("q")))),
    ),
}


def paragraph(eid: str) -> str:
    num = (
        '<w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体"/>'
        f'<w:sz w:val="24"/></w:rPr><w:tab/><w:t xml:space="preserve">({eid})</w:t></w:r>'
    )
    return (
        "<w:p><w:pPr>"
        f'<w:tabs><w:tab w:val="center" w:pos="{TEXT_W // 2}"/><w:tab w:val="right" w:pos="{TEXT_W}"/></w:tabs>'
        '<w:spacing w:before="120" w:after="120" w:line="360" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr>'
        f"<w:r><w:tab/></w:r><m:oMath>{EQUATIONS[eid]}</m:oMath>{num}</w:p>"
    )


def main() -> int:
    with zipfile.ZipFile(RAW) as z:
        files = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    xml = files["word/document.xml"].decode("utf-8")
    if "xmlns:m=" not in xml[:3000]:
        xml = xml.replace("<w:document ", '<w:document xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" ', 1)
    found: list[str] = []

    def repl(m: re.Match[str]) -> str:
        eid = m.group(1)
        found.append(eid)
        return paragraph(eid)

    xml = re.sub(r"<w:p>(?:(?!<w:p>).)*?⟦EQ:([0-9-]+)⟧(?:(?!<w:p>).)*?</w:p>", repl, xml, flags=re.S)
    missing = sorted(set(EQUATIONS) - set(found))
    left = re.findall(r"⟦EQ:[^⟧]*⟧", xml)
    files["word/document.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    print(f"{OUT}：公式 {len(found)} 个；未使用 {missing}；残留占位 {left}")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
