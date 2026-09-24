# -*- coding: utf-8 -*-
"逐页抽取 PDF 文本到文件，供检查。"
import os
from pypdf import PdfReader

pdf = "release/使用说明.pdf"
outdir = "_pdfcheck"
os.makedirs(outdir, exist_ok=True)
r = PdfReader(pdf)
print("pages:", len(r.pages))
for idx, page in enumerate(r.pages):
    txt = page.extract_text() or ""
    with open(os.path.join(outdir, f"page_{idx+1:02d}.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"page {idx+1}: {len(txt)} chars")