import streamlit as st
import pandas as pd
import openai
import io
import json
import base64
import hashlib
import fitz
from PIL import Image
import re

# Conversion Excel→PDF
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

def excel_to_pdf_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    data = [list(df.columns)] + df.values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle([
        ("GRID",       (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND", (0,0), (-1,0),   colors.lightgrey),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ])
    doc.build([table])
    buf.seek(0)
    return buf.read()

# Prompt enrichi pour extraction de la désignation et du EAN
PROMPT = """
Tu es un assistant logistique expert. Je vais te fournir un bon de livraison en PDF.

🌟 OBJECTIF :
1. Extraire le **total des quantités** indiqué dans le document.
2. Reconstituer un tableau avec ces colonnes (français + chinois) :
   - Référence produit / 产品参考
   - Désignation produit / 产品名称
   - Code EAN / 条形码
   - Nombre de cartons / 箱数
   - Nombre de produits / 产品数量
   - Vérification / 校验
3. Vérifier que la somme des **Nombre de produits** = total du document.
4. Si la somme ne correspond pas, recontrôler et corriger jusqu’à l’exactitude.

📉 DÉTAILS TECHNIQUES :
- Chaque ligne avec référence + quantité = 1 carton.
- Grouper les lignes de même référence.
- Traiter séparément chaque référence/EAN trouvée.
- Sortie **JSON** :  
[
  {
    "Référence produit / 产品参考": "...",
    "Désignation produit / 产品名称": "...",
    "Code EAN / 条形码": "...",
    "Nombre de cartons / 箱数": 1,
    "Nombre de produits / 产品数量": 108,
    "Vérification / 校验": ""
  },
  …,
  {
    "Référence produit / 产品参考": "Total / 合计",
    "Désignation produit / 产品名称": "",
    "Code EAN / 条形码": "",
    "Nombre de cartons / 箱数": XX,
    "Nombre de produits / 产品数量": 4296,
    "Vérification / 校验": ""
  }
]
"""

# Password protection
def check_password():
    def on_enter():
        st.session_state["ok"] = (st.session_state["pwd"] == "3DTRADEperso")
    if "ok" not in st.session_state:
        st.text_input("🔐 Mot de passe :", type="password", key="pwd", on_change=on_enter)
        st.stop()
    if not st.session_state["ok"]:
        st.text_input("🔐 Mot de passe :", type="password", key="pwd", on_change=on_enter)
        st.error("Mot de passe incorrect.")
        st.stop()

check_password()

st.set_page_config(page_title="Fiche de réception", layout="wide", page_icon="📋")
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)
st.markdown('<h1 class="section-title">Fiche de réception (OCR via GPT-4o Vision)</h1>', unsafe_allow_html=True)

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Définissez OPENAI_API_KEY dans vos Secrets.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# PDF→images
def extract_images_from_pdf(pdf_bytes: bytes):
    imgs = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return imgs

# OCR + JSON
def ocr_to_json(img: Image.Image) -> list:
    buf = io.BytesIO(); img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":[{"type":"text","text":PROMPT},
                                            {"type":"image_url","image_url":{"url":f"data:image/png;base64,{b64}"}}]}],
        max_tokens=1500, temperature=0
    )
    out = resp.choices[0].message.content
    m = re.findall(r'(\[.*\])', out, re.DOTALL)
    if not m: raise ValueError("Pas de JSON détecté")
    return json.loads(max(m, key=len))

# Upload
uploaded = st.file_uploader("Importez PDF, image ou Excel", type=["pdf","png","jpg","jpeg","xls","xlsx"])
if not uploaded:
    st.stop()
file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : {uploaded.name} — MD5 : {hash_md5}</div>', unsafe_allow_html=True)

# Unifier en images
ext = uploaded.name.lower().split(".")[-1]
if ext in ("xls","xlsx"):
    df_excel = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    pdf_bytes = excel_to_pdf_bytes(df_excel)
    pages = extract_images_from_pdf(pdf_bytes)
elif ext == "pdf":
    pages = extract_images_from_pdf(file_bytes)
else:
    pages = [Image.open(io.BytesIO(file_bytes))]

# Affichage
st.markdown('<div class="card"><div class="section-title">Aperçu du document</div></div>', unsafe_allow_html=True)
for i,img in enumerate(pages):
    st.image(img, caption=f"Page {i+1}", use_container_width=True)

# Extraction
st.markdown('<div class="card"><div class="section-title">Extraction JSON</div></div>', unsafe_allow_html=True)
records = []
for i,img in enumerate(pages):
    st.markdown(f"##### Analyse page {i+1} …")
    with st.spinner("En cours…"):
        try:
            recs = ocr_to_json(img)
            records.extend(recs)
        except Exception as e:
            st.error(f"❌ page {i+1} : {e}")

# DataFrame
st.markdown('<div class="card"><div class="section-title">Résultats</div></div>', unsafe_allow_html=True)
df = pd.DataFrame(records)

# S'assurer des colonnes
cols = [
    "Référence produit / 产品参考",
    "Désignation produit / 产品名称",
    "Code EAN / 条形码",
    "Nombre de cartons / 箱数",
    "Nombre de produits / 产品数量",
    "Vérification / 校验"
]
for c in cols:
    if c not in df.columns:
        df[c] = ""

# Conversion numérique
df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")

# Vérif total
total = df["Nombre de produits / 产品数量"].sum()
st.dataframe(df[cols], use_container_width=True)
st.markdown(f"🧶 **Total calculé : {int(total)} / 产品总数**")

# Export
st.markdown('<div class="card"><div class="section-title">Export Excel</div></div>', unsafe_allow_html=True)
out = io.BytesIO()
with pd.ExcelWriter(out, engine="openpyxl") as w:
    df[cols].to_excel(w, index=False, sheet_name="BON_DE_LIVRAISON")
out.seek(0)
st.download_button("📅 Télécharger (Excel)", data=out.read(),
                   file_name="bon_de_livraison.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   use_container_width=True)
