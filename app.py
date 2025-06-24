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

# Configuration de la page
st.set_page_config(
    page_title="Fiche de réception",
    layout="wide",
    page_icon="📋"
)

# CSS personnalisé
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
  .debug { font-size:0.9rem; color:#888; }
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<h1 class="section-title">Fiche de réception (OCR multi-pages via GPT-4o Vision)</h1>',
    unsafe_allow_html=True
)

# Clé API OpenAI depuis les secrets Streamlit
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🛑 Ajoutez `OPENAI_API_KEY` dans les Secrets de Streamlit Cloud.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# --- Fonctions utilitaires ---

def extract_images_from_pdf(pdf_bytes: bytes):
    """Extrait chaque page du PDF en tant qu'image PIL."""
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images

def extract_json_block(s: str) -> str:
    """Isole le plus grand bloc JSON (entre {} ou []) dans une chaîne."""
    json_regex = re.compile(r'(\[.*?\]|\{.*?\})', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé dans la sortie du modèle.")
    return max(matches, key=len)

# Prompt pour GPT-4o
prompt = (
    "Tu es un assistant expert en logistique.\n"
    "Tu analyses un bon de livraison PDF (souvent multi-pages) qui contient une liste de produits livrés.\n"
    "\n"
    "Voici les étapes que tu dois suivre précisément :\n"
    "\n"
    "1. Parcours toutes les pages du document.\n"
    "2. À la fin du document (généralement en bas), repère les totaux globaux affichés :\n"
    "   - Total pièces (ex : 10730)\n"
    "   - Total colis (si précisé)\n"
    "   Note-les comme : \"Total_pieces_document\" et \"Total_colis_document\"\n"
    "\n"
    "3. Ensuite, lis **chaque ligne de produit** du colisage, sans en sauter aucune.\n"
    "   Pour chaque ligne, extrait :\n"
    "   - Référence\n"
    "   - Produit (désignation)\n"
    "   - Quantité (pièces exactes indiquées sur cette ligne)\n"
    "   Ne calcule rien à partir de colis ou dimensions. Prends uniquement les valeurs visibles.\n"
    "\n"
    "4. À la fin, additionne toutes les quantités extraites pour obtenir :\n"
    "   - Total_pieces_calculé\n"
    "   - Nombre total de lignes (qui représente ici un 'colis') => Total_colis_calculé\n"
    "\n"
    "5. Compare :\n"
    "   - Total_pieces_calculé vs Total_pieces_document\n"
    "   - Total_colis_calculé vs Total_colis_document (si ce dernier a été trouvé)\n"
    "\n"
    "6. Ajoute une colonne \"Alerte\" pour chaque ligne, vide si tout est ok, sinon indique un écart.\n"
    "\n"
    "7. À la fin du JSON, ajoute un objet spécial \"Résumé\" comme ceci :\n"
    "   {\"Résumé\": {\n"
    "       \"Total_pieces_document\": 10730,\n"
    "       \"Total_pieces_calculé\": 10730,\n"
    "       \"Total_colis_document\": 392,\n"
    "       \"Total_colis_calculé\": 13,\n"
    "       \"Écarts\": \"Aucun\"  // ou \"Écart sur les pièces\", etc.\n"
    "   }}\n"
    "\n"
    "8. Formate la sortie en un unique bloc JSON (array de lignes produit, suivi du résumé).\n"
    "\n"
    "Réponds uniquement par ce JSON sans aucun commentaire ni explication."
)


# --- Interface utilisateur ---

# 1. Import du document
st.markdown(
    '<div class="card"><div class="section-title">1. Import du document</div></div>',
    unsafe_allow_html=True
)
uploaded = st.file_uploader(
    "Importez votre PDF (plusieurs pages) ou photo de bon de commande",
    key="file_uploader"
)
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(
    f'<div class="debug">Fichier : {uploaded.name} — Hash MD5 : {hash_md5}</div>',
    unsafe_allow_html=True
)

# Extraction des images
ext = uploaded.name.lower().rsplit('.', 1)[-1]
if ext == 'pdf':
    images = extract_images_from_pdf(file_bytes)
else:
    images = [Image.open(io.BytesIO(file_bytes))]

# 2. Aperçu du document
st.markdown(
    '<div class="card"><div class="section-title">2. Aperçu du document</div>',
    unsafe_allow_html=True
)
for i, img in enumerate(images):
    st.image(img, caption=f"Page {i+1}", use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# 3. Extraction JSON (TOUTES les pages envoyées à GPT d'un coup)
st.markdown(
    '<div class="card"><div class="section-title">3. Extraction JSON</div>',
    unsafe_allow_html=True
)
st.markdown("##### Analyse globale du document …")

# Convertir toutes les images en base64 pour GPT
encoded_images = []
for img in images:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    encoded_images.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

with st.spinner("Analyse complète en cours..."):
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": prompt}] + encoded_images
            }],
            max_tokens=3000,
            temperature=0
        )
        output = response.choices[0].message.content
        output_clean = extract_json_block(output)
        lignes = json.loads(output_clean)
        success = True
    except Exception as e:
        lignes = []
        success = False
        st.error(f"Erreur pendant l'extraction JSON : {e}")

st.code(output if success else "Aucune réponse retournée", language="json")

all_lignes = lignes
st.markdown('</div>', unsafe_allow_html=True)

# 4. Affichage des résultats avec traductions FR/CH et suppression de colonnes
TRANSLATION_MAP = {
    "Référence": "参考编号",
    "Produit": "产品",
    "Nombre de colis": "箱数",
    "Nombre de pièces": "每箱件数",
    "Total": "总件数",
    "Alerte": "警告"
}

df = pd.DataFrame(all_lignes)

# Supprimer les colonnes non désirées
df.drop(columns=["Style", "Marque"], errors="ignore", inplace=True)

# Renommer les colonnes pour ajouter la version chinoise
renamed_columns = {
    col: f"{col} / {TRANSLATION_MAP.get(col, col)}" for col in df.columns
}
df.rename(columns=renamed_columns, inplace=True)

st.markdown(
    '<div class="card"><div class="section-title">4. Résultats</div>',
    unsafe_allow_html=True
)
st.dataframe(df, use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# 5. Export Excel
st.markdown(
    '<div class="card"><div class="section-title">5. Export Excel</div>',
    unsafe_allow_html=True
)
out = io.BytesIO()
with pd.ExcelWriter(out, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON_FR_CN")
out.seek(0)
st.download_button(
    "Télécharger le fichier Excel",
    data=out,
    file_name="bon_de_livraison.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
st.markdown('</div>', unsafe_allow_html=True)
