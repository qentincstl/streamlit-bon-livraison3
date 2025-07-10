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

# Configuration de la page
st.set_page_config(page_title="Fiche de réception", layout="wide", page_icon="📋")

# CSS personnalisé
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="section-title">Fiche de réception (OCR multi-pages via GPT-4o Vision)</h1>', unsafe_allow_html=True)

# Clé API OpenAI
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez `OPENAI_API_KEY` dans les Secrets de Streamlit Cloud.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# Fonctions
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

def extract_json_block(s: str) -> str:
    json_regex = re.compile(r'(\[.*?\]|\{.*?\})', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé dans la sortie du modèle.")
    return max(matches, key=len)

# PROMPT
prompt = """
Tu es un assistant logistique expert. Je vais te fournir un bon de livraison en PDF.

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

📄 Total exact si et seulement si la somme des quantités correspond au total du document.
"""

# UI
st.markdown('<div class="card"><div class="section-title">1. Import du document</div></div>', unsafe_allow_html=True)
uploaded = st.file_uploader("Importez votre PDF, image ou fichier Excel", type=["pdf", "png", "jpg", "jpeg", "xls", "xlsx"])

if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : {uploaded.name} — Hash MD5 : {hash_md5}</div>', unsafe_allow_html=True)

ext = uploaded.name.lower().rsplit('.', 1)[-1]

# Traitement selon le type
if ext in ["xls", "xlsx"]:
    df = pd.read_excel(io.BytesIO(file_bytes))
    st.markdown('<div class="card"><div class="section-title">2. Aperçu Excel</div>', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)
else:
    images = extract_images_from_pdf(file_bytes) if ext == 'pdf' else [Image.open(io.BytesIO(file_bytes))]
    
    st.markdown('<div class="card"><div class="section-title">2. Aperçu du document</div>', unsafe_allow_html=True)
    for i, img in enumerate(images):
        st.image(img, caption=f"Page {i+1}", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="section-title">3. Extraction JSON</div>', unsafe_allow_html=True)
    all_lignes = []
    for i, img in enumerate(images):
        st.markdown(f"##### Analyse page {i+1} …")
        success, output_clean = False, None
        with st.spinner("Analyse en cours..."):
            for attempt in range(6):
                try:
                    output = extract_json_with_gpt4o(img, prompt)
                    output_clean = extract_json_block(output)
                    lignes = json.loads(output_clean)
                    all_lignes.extend(lignes)
                    success = True
                    break
                except Exception:
                    continue
        if not success:
            st.error(f"❌ Erreur d’extraction page {i+1}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="section-title">4. Résultats</div>', unsafe_allow_html=True)
    df = pd.DataFrame(all_lignes)

    try:
        df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")
        valeurs = df["Nombre de produits / 产品数量"].astype(str)
        compte = Counter(valeurs)
    except Exception as e:
        st.warning(f"Erreur pendant la conversion ou la vérification des quantités : {e}")

    if "Vérification / 校验" not in df.columns:
        df["Vérification / 校验"] = ""

    total_calcule = df["Nombre de produits / 产品数量"].sum()
    st.dataframe(df, use_container_width=True)
    st.markdown(f"🧶 **Total calculé des produits : {int(total_calcule)} / 产品总数**")
    st.markdown('</div>', unsafe_allow_html=True)

# Export Excel
st.markdown('<div class="card"><div class="section-title">5. Export Excel</div>', unsafe_allow_html=True)
out = io.BytesIO()
with pd.ExcelWriter(out, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
out.seek(0)
st.download_button(
    "📅 Télécharger les données au format Excel",
    data=out,
    file_name="bon_de_livraison_corrige.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
st.markdown('</div>', unsafe_allow_html=True)
