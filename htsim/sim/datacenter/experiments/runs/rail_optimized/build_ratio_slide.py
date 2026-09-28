#!/usr/bin/env python3
"""Build a SINGLE-slide deck for the IB/UET rail-fabric ratio figure.

Writes its own .pptx -- it does NOT touch IB_vs_UET_presentation.pptx.
Style matches the main deck (same geometry, ink, and rail accent colour).
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
try:
    from PIL import Image
    def aspect(p):
        w, h = Image.open(p).size; return w / h
except Exception:
    def aspect(p): return 1.7

D = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(D, "graphs", "fig4_ratio_ib_uet_1024_vs_2048.png")
OUT = os.path.join(D, "rail_ratio_slide.pptx")

DARK = RGBColor(0x1F, 0x38, 0x64); INK = RGBColor(0x22, 0x22, 0x22)
GREY = RGBColor(0x55, 0x55, 0x55); RAILC = RGBColor(0x00, 0x9E, 0x73)

prs = Presentation(); prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
s = prs.slides.add_slide(prs.slide_layouts[6])

# header bar
bar = s.shapes.add_shape(1, 0, 0, SW, Inches(0.92))
bar.fill.solid(); bar.fill.fore_color.rgb = DARK; bar.line.fill.background()
tb = s.shapes.add_textbox(Inches(0.55), Inches(0.06), SW - Inches(1.1), Inches(0.8))
tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
p = tf.paragraphs[0]; r = p.add_run()
r.text = "IB vs UET on the rail fabric — 1024 vs 2048 GPUs"
r.font.size = Pt(27); r.font.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

# figure, centred, scaled to fit between header and takeaway
top, avail_h = Inches(1.12), Inches(4.62)
w = min(Inches(11.4), int(avail_h * aspect(IMG)))
h = int(w / aspect(IMG))
s.shapes.add_picture(IMG, int((SW - w) / 2), top, w, h)

# takeaway block
ty = top + avail_h + Inches(0.16)
acc = s.shapes.add_shape(1, Inches(0.55), ty, Inches(0.075), Inches(1.28))
acc.fill.solid(); acc.fill.fore_color.rgb = RAILC; acc.line.fill.background()
tb2 = s.shapes.add_textbox(Inches(0.78), ty - Inches(0.04), SW - Inches(1.5), Inches(1.4))
tf2 = tb2.text_frame; tf2.word_wrap = True

def para(text, size, color, bold=False, space=5, first=False):
    p = tf2.paragraphs[0] if first else tf2.add_paragraph()
    run = p.add_run(); run.text = text
    run.font.size = Pt(size); run.font.bold = bold; run.font.color.rgb = color
    p.space_after = Pt(space); p.alignment = PP_ALIGN.LEFT

para("IB's MoE win does not survive the scale-up: it is a 1024-GPU result only.",
     16.5, INK, bold=True, first=True)
para("At 1024 GPUs IB edges UET on MoE all-to-all at 100 MB (0.89x). At 2048 the same cell "
     "reverses to 1.31x — IB is 31% slower — and every MoE point sits above parity. All-reduce "
     "is unaffected by scale, staying at a flat 3.2-4.1x UET lead on both.", 13, GREY)
para("Colour = workload, line style = scale (solid/filled = 1024, dashed/open = 2048); the dotted "
     "line is parity. The 2048 / 100 MB IB cells come from the completed re-runs — the earlier "
     "rows were truncated (incomplete) and understated makespan by ~25%.", 11.5, GREY)

prs.save(OUT)
print("wrote", OUT, "-", len(prs.slides._sldIdLst), "slide(s)")
