# -*- coding: utf-8 -*-
"""把 使用说明.md 渲染为排版美观的 PDF（reportlab + 微软雅黑 CJK）。"""
import os
import re
import platform

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                Flowable, LongTable, KeepTogether, XPreformatted)
from reportlab.pdfbase.pdfmetrics import stringWidth

PRIMARY = HexColor("#1a365d")
ACCENT = HexColor("#2b6cb0")
BODY = HexColor("#2d3748")
MUTED = HexColor("#718096")
REAL = HexColor("#d53f8c")
CODEBG = HexColor("#f7fafc")

# ---- CJK 字体 ----
def register_cjk():
    sysname = platform.system()
    cands = []
    if sysname == "Windows":
        cands = [("C:/Windows/Fonts/msyh.ttc", "MicrosoftYaHei"),
                 ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
                 ("C:/Windows/Fonts/simsun.ttc", "SimSun")]
    elif sysname == "Darwin":
        cands = [("/System/Library/Fonts/PingFang.ttc", "PingFang"),
                 ("/System/Library/Fonts/STHeiti Medium.ttc", "Heiti")]
    else:
        cands = [("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoSansCJK"),
                 ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WQY")]
    for path, name in cands:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CJK", path, subfontIndex=0))
                return "CJK"
            except Exception:
                continue
    raise RuntimeError("no CJK font found")

FONT = register_cjk()

# ---- 样式 ----
def ps(name, **kw):
    base = dict(fontName=FONT, wordWrap="CJK", color=BODY)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
    "title": ps("t", fontSize=26, leading=32, color=PRIMARY, spaceAfter=6, alignment=0),
    "subtitle": ps("st", fontSize=12, leading=18, color=MUTED, spaceAfter=4),
    "h1": ps("h1", fontSize=17, leading=22, color=PRIMARY, spaceBefore=18, spaceAfter=8),
    "h2": ps("h2", fontSize=13, leading=18, color=ACCENT, spaceBefore=12, spaceAfter=6),
    "body": ps("b", fontSize=10.5, leading=17, spaceAfter=7),
    "bodylist": ps("bl", fontSize=10.5, leading=17, leftIndent=14, spaceAfter=5),
    "quote": ps("q", fontSize=10.5, leading=16, textColor=MUTED, spaceAfter=8),
    "code": ps("c", fontName=FONT, fontSize=8.6, leading=12.5, textColor=PRIMARY,
               backColor=CODEBG, leftIndent=2, rightIndent=2, spaceAfter=0,
               wordWrap=None),
    "th": ps("th", fontName=FONT, fontSize=9.3, leading=13, textColor=colors.white),
    "td": ps("td", fontName=FONT, fontSize=9.0, leading=13, textColor=BODY),
}

def escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

_INLINE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
    (re.compile(r"`([^`]+?)`"), r"<font color='#2b6cb0'>\1</font>"),
]

def inline(s):
    s = escape(s)
    for pat, rep in _INLINE:
        s = pat.sub(rep, s)
    return s

# ---- 分隔线 ----
class Divider(Flowable):
    def __init__(self, width_ratio, height, color, space_after=10, space_before=0):
        Flowable.__init__(self)
        self.wr = width_ratio
        self.height = height
        self.color = color
        self.spaceBefore = space_before
        self.spaceAfter = space_after

    def wrap(self, availWidth, availHeight):
        self.width = availWidth * self.wr
        self.height = self.height
        return (self.width, self.height + self.spaceBefore + self.spaceAfter)

    def draw(self):
        self.canv.setFillColor(self.color)
        y = self.spaceAfter
        self.canv.rect(0, y, self.width, self.height, fill=1, stroke=0)

def h1_divider():
    return Divider(0.30, 2.4, ACCENT, space_after=8)

def subtle_divider():
    return Divider(1.0, 1, HexColor("#e2e8f0"), space_after=8, space_before=4)

# ---- 表格 ----
def build_table(rows, widths):
    header = [Paragraph(inline(x), S["th"]) for x in rows[0]]
    body = [[Paragraph(inline(c), S["td"]) for c in r] for r in rows[1:]]
    data = [header] + body
    is_large = len(rows) > 14
    t = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT") if is_large \
        else Table(data, colWidths=widths, hAlign="LEFT")
    t.setStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEADING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#f7fafc"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.6, ACCENT),
    ])
    return t

# ---- 解析 markdown ----
def parse(lines):
    story = []
    i = 0
    n = len(lines)

    def flush_code(block, fence):
        code_txt = "\n".join(block)
        cell = XPreformatted(escape(code_txt), S["code"])
        t = Table([[cell]], colWidths=6.7 * inch, hAlign="LEFT")
        t.setStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
            ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#e2e8f0")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ])
        story.append(KeepTogether([t, Spacer(1, 6)]))

    while i < n:
        line = lines[i].rstrip("\n")

        # 代码围栏
        if line.lstrip().startswith("```"):
            lang = line.strip().strip("`")
            block = []
            i += 1
            while i < n and not lines[i].lstrip().startswith("```"):
                block.append(lines[i].rstrip("\n"))
                i += 1
            i += 1  # skip closing fence
            flush_code(block, lang)
            continue

        # 标题
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level, txt = len(m.group(1)), m.group(2).strip()
            if level == 1:
                story.append(Paragraph(inline(txt), S["title"]))
                story.append(Spacer(1, 2))
            elif level == 2:
                story.append(Paragraph(inline(txt), S["h1"]))
                story.append(h1_divider())
            else:
                story.append(Paragraph(inline(txt), S["h2"]))
            i += 1
            continue

        # 分隔线
        if line.strip() in ("---", "***", "___"):
            story.append(subtle_divider())
            i += 1
            continue

        # 表格块
        if line.strip().startswith("|"):
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            # 去分隔行
            data = []
            for r in tbl:
                cells = [c.strip() for c in r.strip("|").split("|")]
                if all(re.match(r"^:?-+:?$", c) for c in cells):
                    continue
                data.append(cells)
            ncol = max(len(r) for r in data)
            data = [r + [""] * (ncol - len(r)) for r in data]
            widths = [6.7 * inch / ncol] * ncol
            try:
                story.append(build_table(data, widths))
                story.append(Spacer(1, 8))
            except Exception:
                for r in data:
                    story.append(Paragraph(inline(" | ".join(r)), S["body"]))
            continue

        # 引用
        if line.strip().startswith(">"):
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                q = lines[i].strip()[1:].strip()
                if q:
                    quote.append(inline(q))
                i += 1
            cell = Paragraph("<br/>".join(quote), S["quote"])
            t = Table([[cell]], colWidths=6.7 * inch, hAlign="LEFT")
            t.setStyle([
                ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
                ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#e2e8f0")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
            story.append(t)
            story.append(Spacer(1, 6))
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 列表
        m = re.match(r"^\s*(?:[-*]|\d+[\.、])\s+(.*)$", line)
        if m:
            story.append(Paragraph(inline("• " + m.group(1)), S["bodylist"]))
            i += 1
            continue

        # 普通段落（合并连续非空行）
        para = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not lines[i].lstrip().startswith("```") \
                and not lines[i].strip().startswith("|") and not lines[i].strip().startswith(">") \
                and not re.match(r"^(#{1,3})\s+", lines[i]) and not lines[i].strip().startswith("-"):
            para.append(lines[i].strip())
            i += 1
        story.append(Paragraph(inline(" ".join(para)), S["body"]))

    return story

# ---- 页脚 ----
def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(HexColor("#e2e8f0"))
    canvas.setLineWidth(0.5)
    canvas.line(0.75 * inch, 0.5 * inch, A4[0] - 0.75 * inch, 0.5 * inch)
    canvas.setFont(FONT, 8)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(A4[0] / 2, 0.36 * inch, "智客服 · AI 电商客服自动化 Agent —— 使用说明")
    canvas.drawRightString(A4[0] - 0.75 * inch, 0.36 * inch, "第 %d 页" % doc.page)
    canvas.restoreState()

def main():
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "使用说明.md")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "release", "应用方案和使用教程.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(src, encoding="utf-8") as f:
        lines = f.read().split("\n")
    story = parse(lines)
    doc = SimpleDocTemplate(
        out, pagesize=A4,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.7 * inch, bottomMargin=0.75 * inch,
        title="智客服 · AI 电商客服自动化 Agent —— 使用说明",
        author="Zhi-Ke-Fu AI-CS-Agent",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("PDF generated:", out)

if __name__ == "__main__":
    main()