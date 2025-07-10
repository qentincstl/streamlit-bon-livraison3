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

st.set_page_config(page_title="Fiche de réception", layout="wide", page_icon="📋")

# CSS
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="section-title">Fiche de réception (OCR multi-supports via GPT-4o)</h1>', unsafe_allow_html=True)

# Clé API
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez `OPENAI_API_KEY` dans les Secrets.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# PROMPT
prompt = """
Tu es un assistant logistique expert. Je vais te fournir un bon de livraison ou un tableau (Excel) contenant des données brutes.

Voici les règles que tu dois absolument suivre :

---

🌟 OBJECTIF :
1. Extraire le **total des quantités** indiqué dans le document (souvent à la ligne `TOTAL ...` ou `Total Unité`).
2. Reconstituer un tableau avec les colonnes suivantes, en **français + chinois** :
   - Référence produit / 产品参考
   - Nombre de cartons / 箱数
   - Nombre de produits / 产品数量
   - Vérification / 校验
3. Vérifier que la **somme des quantités dans le tableau = total indiqué dans le document**.
4. **TANT QUE LA SOMME NE CORRESPOND PAS**, tu dois :
   - Recontrôler chaque ligne de produit.
   - Ne **rien déduire** ou estimer.
   - **Corriger ou compléter** le tableau.
   - Recommencer la vérification jusqu’à ce que le total soit **parfaitement exact**.

---

📉 DÉTAILS TECHNIQUES :
- Une ligne avec une référence et une quantité = 1 carton.
- Plusieurs lignes peuvent partager la même référence : tu dois les **regrouper**.
- Certaines lignes (notamment vers la fin du document) contiennent **plusieurs produits** avec références différentes : **traite chaque ligne séparément**.
- Inclue **toutes** les lignes où une référence précède une quantité.
- Sors la réponse au format JSON suivant :
[
  {"Référence produit / 产品参考": "...", "Nombre de cartons / 箱数": 1, "Nombre de produits / 产品数量": 108, "Vérification / 校验": ""},
  ...
  {"Référence produit / 产品参考": "Total / 合计", "Nombre de cartons / 箱数": XX, "Nombre de produits / 产品数量": 4296, "Vérification / 校验": ""}
]
"""

# Fonctions
def extract_images_from_pdf(pdf_bytes: bytes):
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images

def extract_json_with_gpt4o_from_image(img: Image.Image, prompt: str) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }],
        max_tokens=1500,
        temperature=0
    )
    return response.choices[0].message.content

def extract_json_with_gpt4o_from_text(text: str, prompt: str) -> str:
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": prompt + "\n\nVoici le contenu :\n" + text}
        ],
        max_tokens=1500,
        temperature=0
    )
    return response.choices[0].message.content

def extract_json_block(s: str) -> str:
    json_regex = re.compile(r'(\[.*?\]|\{.*?\})', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé.")
    return max(matches, key=len)

# UI
st.markdown('<div class="card"><div class="section-title">1. Import du document</div></div>', unsafe_allow_html=True)
uploaded = st.file_uploader("Importez votre PDF, image ou Excel", type=["pdf", "png", "jpg", "jpeg", "xls", "xlsx"])
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
ext = uploaded.name.lower().split('.')[-1]
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : {uploaded.name} — Hash MD5 : {hash_md5}</div>', unsafe_allow_html=True)

# Préparation des images ou texte
json_data = []
if ext in ["pdf", "png", "jpg", "jpeg"]:
    images = extract_images_from_pdf(file_bytes) if ext == "pdf" else [Image.open(io.BytesIO(file_bytes))]

    st.markdown('<div class="card"><div class="section-title">2. Aperçu du document</div>', unsafe_allow_html=True)
    for i, img in enumerate(images):
        st.image(img, caption=f"Page {i+1}", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    for i, img in enumerate(images):
        for attempt in range(2):
            try:
                raw = extract_json_with_gpt4o_from_image(img, prompt)
                clean = extract_json_block(raw)
                lignes = json.loads(clean)
                json_data.extend(lignes)
                break
            except Exception:
                continue

elif ext in ["xls", "xlsx"]:
    df_excel = pd.read_excel(io.BytesIO(file_bytes))
    st.markdown('<div class="card"><div class="section-title">2. Aperçu du fichier Excel</div>', unsafe_allow_html=True)
    st.dataframe(df_excel, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    text_table = df_excel.to_csv(index=False, sep="\t")
    for attempt in range(2):
        try:
            raw = extract_json_with_gpt4o_from_text(text_table, prompt)
            clean = extract_json_block(raw)
            lignes = json.loads(clean)
            json_data.extend(lignes)
            break
        except Exception:
            continue

# Résultats
if json_data:
    df = pd.DataFrame(json_data)
    df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")
    total_calcule = df["Nombre de produits / 产品数量"].sum()

    st.markdown('<div class="card"><div class="section-title">3. Résultats extraits</div>', unsafe_allow_html=True)
    df = df[["Référence produit / 产品参考", "Nombre de cartons / 箱数", "Nombre de produits / 产品数量", "Vérification / 校验"]]
    st.dataframe(df, use_container_width=True)
    st.markdown(f"🧮 **Total calculé : {int(total_calcule)} produits / 产品总数**")
    st.markdown('</div>', unsafe_allow_html=True)

    # Export Excel
    st.markdown('<div class="card"><div class="section-title">4. Export Excel</div>', unsafe_allow_html=True)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
    out.seek(0)
    st.download_button(
        "📦 Télécharger le fichier Excel nettoyé",
        data=out,
        file_name="bon_de_livraison_corrige.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
    st.markdown('</div>', unsafe_allow_html=True)
else:
    st.error("❌ Échec de l'extraction. Vérifiez que le document est lisible.")
