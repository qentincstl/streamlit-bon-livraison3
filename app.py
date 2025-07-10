# --- Imports
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

# --- Page config
st.set_page_config(page_title="Fiche de réception GPT", layout="wide", page_icon="📦")

# --- Clé API
openai.api_key = st.secrets.get("OPENAI_API_KEY", "")
if not openai.api_key:
    st.error("Ajoute ta clé OPENAI_API_KEY dans les secrets de Streamlit.")
    st.stop()

# --- PROMPTS
prompt_strict = """
Tu es un assistant logistique expert. Je vais te fournir un bon de livraison ou un tableau brut (Excel).

Ton objectif est de :
1. Extraire les lignes de produits contenant clairement une **référence**, un **nombre de cartons** et une **quantité de produits**.
2. Reconstituer un tableau structuré avec ces 4 colonnes :
   - Référence produit / 产品参考
   - Nombre de cartons / 箱数
   - Nombre de produits / 产品数量
   - Vérification / 校验
3. Calculer la **somme totale** des quantités.
4. Sors uniquement ce JSON :
[
  {"Référence produit / 产品参考": "...", "Nombre de cartons / 箱数": 1, "Nombre de produits / 产品数量": 108, "Vérification / 校验": ""},
  ...
  {"Référence produit / 产品参考": "Total / 合计", "Nombre de cartons / 箱数": XX, "Nombre de produits / 产品数量": 4296, "Vérification / 校验": ""}
]
⚠️ Ne prends en compte **aucune ligne douteuse** ou ambiguë. Ne fais **aucune déduction**.
"""

prompt_flexible = """
Tu es un assistant logistique intelligent. Je vais te fournir un bon de livraison ou un tableau Excel.

Inclus **toutes les lignes** contenant **des éléments logistiques potentiels**, même approximatifs :
1. Même si une ligne est incomplète ou ambiguë, essaie de l’ajouter.
2. Ne laisse **aucune ligne de côté** qui pourrait contenir une référence ou une quantité.
3. Structure la réponse comme ceci :
[
  {"Référence produit / 产品参考": "...", "Nombre de cartons / 箱数": 1, "Nombre de produits / 产品数量": 108, "Vérification / 校验": ""},
  ...
  {"Référence produit / 产品参考": "Total / 合计", "Nombre de cartons / 箱数": XX, "Nombre de produits / 产品数量": 4296, "Vérification / 校验": ""}
]
Même si tu n'es pas certain, **inclus la ligne**.

Ensuite, compare les résultats avec ceux que tu aurais donnés dans un prompt strict, indique quelles lignes sont nouvelles ou corrigées, et vérifie si le total devient correct. Ajoute uniquement ce qui est nécessaire pour corriger l’erreur du strict.
"""

# --- Fonctions
def extract_images_from_pdf(pdf_bytes):
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images

def extract_json_from_image(img, prompt):
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

def extract_json_from_text(text, prompt):
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n" + text}]
    )
    return response.choices[0].message.content

def extract_json_block(s):
    json_regex = re.compile(r'(\[.*?\])', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé.")
    return max(matches, key=len)

# --- UI
st.title("📦 Fiche de réception - Analyse GPT multi-prompts")
uploaded = st.file_uploader("Dépose ton fichier PDF, image ou Excel :", type=["pdf", "png", "jpg", "jpeg", "xls", "xlsx"])
if not uploaded:
    st.stop()

file_bytes = uploaded.read()
ext = uploaded.name.split(".")[-1].lower()
st.caption(f"Fichier : {uploaded.name}")

# --- Analyse double (strict + flexible)
json_strict, json_flexible = [], []

if ext in ["pdf", "png", "jpg", "jpeg"]:
    images = extract_images_from_pdf(file_bytes) if ext == "pdf" else [Image.open(io.BytesIO(file_bytes))]
    for img in images:
        try:
            out1 = extract_json_block(extract_json_from_image(img, prompt_strict))
            json_strict += json.loads(out1)

            out2 = extract_json_block(extract_json_from_image(img, prompt_flexible))
            json_flexible += json.loads(out2)
        except Exception as e:
            st.error(f"Erreur : {e}")

elif ext in ["xls", "xlsx"]:
    df_excel = pd.read_excel(io.BytesIO(file_bytes))
    text = df_excel.to_csv(index=False, sep="\t")
    try:
        out1 = extract_json_block(extract_json_from_text(text, prompt_strict))
        json_strict += json.loads(out1)

        out2 = extract_json_block(extract_json_from_text(text, prompt_flexible))
        json_flexible += json.loads(out2)
    except Exception as e:
        st.error(f"Erreur : {e}")

# --- Affichage
if json_strict:
    df_strict = pd.DataFrame(json_strict)
    df_strict["Nombre de produits / 产品数量"] = pd.to_numeric(df_strict["Nombre de produits / 产品数量"], errors="coerce")
    total_calcule = df_strict["Nombre de produits / 产品数量"].sum()
    st.subheader("🔢 Résultat - Prompt strict")
    st.dataframe(df_strict, use_container_width=True)
    st.markdown(f"**Total calculé (strict) : {int(total_calcule)}**")

if json_flexible:
    df_flex = pd.DataFrame(json_flexible)
    df_flex["Nombre de produits / 产品数量"] = pd.to_numeric(df_flex["Nombre de produits / 产品数量"], errors="coerce")
    total_flex = df_flex["Nombre de produits / 产品数量"].sum()
    st.subheader("🔄 Résultat - Prompt libre")
    st.dataframe(df_flex, use_container_width=True)
    st.markdown(f"**Total calculé (flexible) : {int(total_flex)}**")

# Export strict par défaut
if not df_strict.empty:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df_strict.to_excel(writer, index=False, sheet_name="Strict")
    out.seek(0)
    st.download_button("📆 Télécharger Excel (strict)", data=out, file_name="resultat_strict.xlsx")
