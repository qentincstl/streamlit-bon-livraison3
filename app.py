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
from collections import Counter

# ─── Pour convertir un DataFrame Excel en PDF ───
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

def excel_to_pdf_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    # Document PDF
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    # Préparer les données (entêtes + lignes)
    data = [list(df.columns)] + df.values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle([
        ("GRID",           (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND",     (0,0), (-1,0),   colors.lightgrey),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
    ])
    doc.build([table])
    buffer.seek(0)
    return buffer.read()

# ─── Votre prompt GPT-4o Vision ───
prompt = """
Tu es un assistant logistique expert. Je vais te fournir un bon de livraison en PDF.

Voici les règles que tu dois absolument suivre :

---
🌟 OBJECTIF :
1. Extraire le **total des quantités** indiqué dans le document.
2. Reconstituer un tableau avec les colonnes (français+chinois) :
   - Référence produit / 产品参考
   - Nombre de cartons  / 箱数
   - Nombre de produits / 产品数量
   - Vérification      / 校验
3. Vérifier que la somme des quantités = total du document.
4. Tant que ça ne correspond pas, recontrôler et corriger jusqu’à l’exactitude.
---
📉 DÉTAILS TECHNIQUES :
- Une ligne = 1 carton
- Grouper les références identiques
- Traiter chaque produit séparément
- Sortie en JSON comme montré plus haut.
"""

# ─── Configuration de la page ───
st.set_page_config(page_title="Fiche de réception", layout="wide", page_icon="📋")
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)
st.markdown('<h1 class="section-title">Fiche de réception (OCR via GPT-4o Vision)</h1>', unsafe_allow_html=True)

# ─── Clé API ───
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez `OPENAI_API_KEY` dans les Secrets.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# ─── Utils PDF→images & GPT4o → JSON ───
def extract_images_from_pdf(pdf_bytes: bytes):
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images

def extract_json_with_gpt4o(img: Image.Image, prompt: str) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",  "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }],
        max_tokens=1500,
        temperature=0
    )
    return resp.choices[0].message.content

def extract_json_block(s: str) -> str:
    m = re.findall(r'(\[.*?\]|\{.*?\})', s, re.DOTALL)
    if not m:
        raise ValueError("Aucun JSON trouvé dans le modèle.")
    return max(m, key=len)

# ─── 1. Upload ───
uploaded = st.file_uploader(
    "Importez votre PDF, votre image ou votre Excel",
    type=["pdf","png","jpg","jpeg","xls","xlsx"]
)
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : {uploaded.name} — MD5 : {hash_md5}</div>', unsafe_allow_html=True)

# ─── 2. Unifiez en une seule liste d’images ───
ext = uploaded.name.lower().rsplit(".",1)[-1]

if ext in ("xls","xlsx"):
    # Lire l'Excel en DF brut
    df_excel = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    # Convertir en PDF
    pdf_bytes = excel_to_pdf_bytes(df_excel)
    images = extract_images_from_pdf(pdf_bytes)
else:
    if ext == "pdf":
        images = extract_images_from_pdf(file_bytes)
    else:  # png/jpg/jpeg
        images = [Image.open(io.BytesIO(file_bytes))]

# ─── 3. Aperçu ───
st.markdown('<div class="card"><div class="section-title">Aperçu du document</div></div>', unsafe_allow_html=True)
for i, img in enumerate(images):
    st.image(img, caption=f"Page {i+1}", use_container_width=True)

# ─── 4. Extraction JSON via GPT-4o Vision ───
st.markdown('<div class="card"><div class="section-title">Extraction JSON</div></div>', unsafe_allow_html=True)
all_lignes = []
for i, img in enumerate(images):
    st.markdown(f"##### Analyse page {i+1} …")
    success = False
    with st.spinner("Analyse en cours…"):
        for _ in range(6):
            try:
                out = extract_json_with_gpt4o(img, prompt)
                block = extract_json_block(out)
                lignes = json.loads(block)
                all_lignes.extend(lignes)
                success = True
                break
            except Exception:
                continue
    if not success:
        st.error(f"❌ Échec extraction page {i+1}")

# ─── 5. Affichage & vérif ───
st.markdown('<div class="card"><div class="section-title">Résultats</div></div>', unsafe_allow_html=True)
df = pd.DataFrame(all_lignes)
df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")
if "Vérification / 校验" not in df.columns:
    df["Vérification / 校验"] = ""
total_calcule = df["Nombre de produits / 产品数量"].sum()
st.dataframe(df, use_container_width=True)
st.markdown(f"🧶 **Total calculé : {int(total_calcule)}**")

# ─── 6. Export Excel ───
st.markdown('<div class="card"><div class="section-title">Export Excel</div></div>', unsafe_allow_html=True)
out = io.BytesIO()
with pd.ExcelWriter(out, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
out.seek(0)
st.download_button(
    "📅 Télécharger le résultat (Excel)",
    data=out,
    file_name="bon_de_livraison_corrige.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
