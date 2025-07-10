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

# --- PROMPT
prompt = """
Tu es un assistant logistique expert. Je vais te fournir un bon de livraison ou un tableau brut (Excel).

---

🌟 OBJECTIF :
1. Extraire le **total des quantités**.
2. Reconstituer un tableau avec :
   - Référence produit / 产品参考
   - Nombre de cartons / 箱数
   - Nombre de produits / 产品数量
   - Vérification / 校验
3. Vérifier que la somme des quantités = total annoncé.
4. Sors uniquement ce JSON :
[
  {"Référence produit / 产品参考": "...", "Nombre de cartons / 箱数": 1, "Nombre de produits / 产品数量": 108, "Vérification / 校验": ""},
  ...
  {"Référence produit / 产品参考": "Total / 合计", "Nombre de cartons / 箱数": XX, "Nombre de produits / 产品数量": 4296, "Vérification / 校验": ""}
]
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

def run_gpt_analysis(source, from_text=False):
    try:
        if from_text:
            raw = extract_json_from_text(source, prompt)
        else:
            raw = extract_json_from_image(source, prompt)
        clean = extract_json_block(raw)
        data = json.loads(clean)
        return data
    except Exception as e:
        st.error(f"Erreur GPT : {e}")
        return []

# --- Interface utilisateur
st.title("📦 Fiche de réception - GPT Vision & Excel")
uploaded = st.file_uploader("Dépose ton fichier PDF, image ou Excel :", type=["pdf", "png", "jpg", "jpeg", "xls", "xlsx"])

if not uploaded:
    st.stop()

file_bytes = uploaded.read()
ext = uploaded.name.split(".")[-1].lower()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.caption(f"Fichier : {uploaded.name} — Hash : {hash_md5}")

# --- GPT Analysis
rerun = st.button("🔁 Refaire l'analyse GPT")

if "df_final" not in st.session_state or rerun:
    json_data = []

    if ext in ["pdf", "png", "jpg", "jpeg"]:
        images = extract_images_from_pdf(file_bytes) if ext == "pdf" else [Image.open(io.BytesIO(file_bytes))]
        for img in images:
            json_data += run_gpt_analysis(img, from_text=False)

    elif ext in ["xls", "xlsx"]:
        df_excel = pd.read_excel(io.BytesIO(file_bytes))
        text_content = df_excel.to_csv(index=False, sep="\t")
        json_data += run_gpt_analysis(text_content, from_text=True)

    if json_data:
        df = pd.DataFrame(json_data)
        df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")
        df["Nombre de cartons / 箱数"] = pd.to_numeric(df["Nombre de cartons / 箱数"], errors="coerce")
        df["Vérification / 校验"] = df.get("Vérification / 校验", "")
        st.session_state.df_final = df
    else:
        st.stop()

# --- Résultats
df = st.session_state.df_final
total_calcule = df["Nombre de produits / 产品数量"].sum()
try:
    total_annonce = df[df["Référence produit / 产品参考"].str.contains("Total", case=False, na=False)]["Nombre de produits / 产品数量"].max()
except:
    total_annonce = None

# --- Alertes
if total_annonce and total_annonce != total_calcule:
    st.error(f"⚠️ Incohérence entre total annoncé ({int(total_annonce)}) et total calculé ({int(total_calcule)})")
else:
    st.success(f"✅ Total cohérent : {int(total_calcule)} produits")

# --- Tableau
st.subheader("📋 Résultat structuré")
df_display = df[["Référence produit / 产品参考", "Nombre de cartons / 箱数", "Nombre de produits / 产品数量", "Vérification / 校验"]]
st.dataframe(df_display, use_container_width=True)

# --- Export
st.subheader("📤 Exporter les résultats")
excel_buffer = io.BytesIO()
csv_buffer = io.StringIO()
with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
    df_display.to_excel(writer, index=False, sheet_name="BON_LIVRAISON")
df_display.to_csv(csv_buffer, index=False)

st.download_button("⬇️ Télécharger Excel", data=excel_buffer.getvalue(), file_name="bon_de_livraison_corrige.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.download_button("⬇️ Télécharger CSV", data=csv_buffer.getvalue(), file_name="bon_de_livraison_corrige.csv", mime="text/csv")
