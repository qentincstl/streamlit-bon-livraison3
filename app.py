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

st.set_page_config(page_title="Fiche de réception", layout="wide", page_icon="📋")

st.markdown("""
<style>
.section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
.card { background:#fff; padding:1rem; border-radius:0.5rem;
        box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
.debug { font-size:0.9rem; color:#888; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="section-title">Fiche de réception (OCR multi-pages via GPT-4o Vision)</h1>', unsafe_allow_html=True)

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🛑 Ajoutez `OPENAI_API_KEY` dans les Secrets de Streamlit Cloud.")
    st.stop()
openai.api_key = OPENAI_API_KEY

def extract_images_from_pdf(pdf_bytes: bytes):
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images

def extract_json_block(s: str) -> str:
    json_regex = re.compile(r'(\[.*?\]|\{.*?\})', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé dans la sortie du modèle.")
    return max(matches, key=len)

# PROMPT GPT CORRIGÉ
prompt = (
    # CONTEXTE
    "Tu es un assistant OCR/logistique. Tu reçois un bon de livraison multi-pages (PDF ou images).\n"
    "Ta mission est de TRANSCRIRE toutes les lignes produit exactement comme elles apparaissent, "
    "puis de vérifier les totaux globaux indiqués dans le document.\n"
    "\n"
    # RÈGLES GÉNÉRALES – NE JAMAIS INTERPRÉTER
    "─ Reproduis chaque ligne visible, même si elle semble identique à une autre.\n"
    "─ Ne déduis rien, ne regroupe rien, ne corrige rien : tu recopies.\n"
    "─ S’il existe deux nombres dans la même cellule (imprimé + manuscrit), "
    "recopie les DEUX en les séparant par « / ».\n"
    "─ Si une ligne est illisible, créée une entrée avec \"?\" et mets 'À vérifier' dans Alerte.\n"
    "\n"
    # ÉTAPES
    "Étapes :\n"
    "1. Parcours toutes les pages dans l’ordre (page 1 → N).\n"
    "2. Pour chaque ligne produit détectée, extraits exactement :\n"
    "   • Référence   • Produit   • Quantité (telle qu’elle apparaît)   • Page   • Alerte (vide par défaut)\n"
    "3. À LA FIN du document, repère le bloc récapitulatif (Total pièces et éventuellement Total colis).\n"
    "4. Additionne les quantités recopiées et compare aux totaux trouvés ;\n"
    "   s’il y a un écart, inscris 'Écart total' dans la colonne Alerte de TOUTES les lignes.\n"
    "\n"
    # EXEMPLE pour qu’il ne saute pas les doublons
    "Exemple : si deux lignes consécutives sont :\n"
    "  1V1073DM  MESO MASK 50ML  837\n"
    "  1V1073DM  MESO MASK 50ML  837\n"
    "tu dois rendre DEUX entrées distinctes, pas une seule.\n"
    "\n"
    # FORMAT DE SORTIE
    "Réponds uniquement avec un JSON array, dans cet EXACT format :\n"
    "[\n"
    "  {\"Référence\":\"1V1073DM\",\"Produit\":\"MESO MASK 50ML POT SPE\",\"Quantité\":\"837\",\"Page\":1,\"Alerte\":\"\"},\n"
    "  {\"Référence\":\"1V1073DM\",\"Produit\":\"MESO MASK 50ML POT SPE\",\"Quantité\":\"26\",\"Page\":1,\"Alerte\":\"\"}\n"
    "]\n"
    "Aucun texte avant ou après le JSON."
)

# 1. Import
st.markdown('<div class="card"><div class="section-title">1. Import du document</div></div>', unsafe_allow_html=True)
uploaded = st.file_uploader("Importez votre PDF (multi-pages) ou photo de bon de livraison", type=["pdf", "png", "jpg"])
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="debug">Fichier : {uploaded.name} — Hash MD5 : {hash_md5}</div>', unsafe_allow_html=True)

# 2. Affichage PDF/images
ext = uploaded.name.lower().rsplit('.', 1)[-1]
images = extract_images_from_pdf(file_bytes) if ext == 'pdf' else [Image.open(io.BytesIO(file_bytes))]

st.markdown('<div class="card"><div class="section-title">2. Aperçu du document</div>', unsafe_allow_html=True)
for i, img in enumerate(images):
    st.image(img, caption=f"Page {i+1}", use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# 3. Extraction JSON
st.markdown('<div class="card"><div class="section-title">3. Extraction JSON</div>', unsafe_allow_html=True)

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
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}] + encoded_images}],
            max_tokens=3000,
            temperature=0
        )
        output = response.choices[0].message.content
        output_clean = extract_json_block(output)
        lignes = json.loads(output_clean)
        if isinstance(lignes, dict):
            lignes = [lignes]
        all_lignes = lignes
        st.code(output_clean, language="json")
    except Exception as e:
        st.error(f"Erreur pendant l'extraction JSON : {e}")
        st.stop()

st.markdown('</div>', unsafe_allow_html=True)

# 4. Affichage des résultats avec colonnes bilingues
TRANSLATION_MAP = {
    "Référence": "参考编号",
    "Produit": "产品",
    "Quantité": "数量",
    "Alerte": "警告"
}
# --- Vérification simple du nombre de lignes extraites ---
expected_lines = sum(1 for p in images for _ in [0])  # facultatif : si tu connais le nb par page
extracted = len(df)
st.info(f"🚚 Lignes extraites : {extracted}")

# Affiche un avertissement si GPT a sauté des lignes
if expected_lines and extracted < expected_lines:
    st.warning("⚠️ Il manque peut-être des lignes. Vérifiez le document ou relancez l’analyse.")

# --- Vérification du total pièces vs total trouvé par GPT (s'il l'a mis à la fin) ---
if "Total pièces" in df.columns:
    total_calcule = df["Quantité / 数量"].astype(str).str.replace(",", "").astype(float).sum()
    total_document = df["Total pièces"].iloc[0]     # supposé fourni par GPT dans la dernière ligne
    if total_calcule != total_document:
        st.error(f"❌ Écart détecté : {total_calcule} calculé vs {total_document} indiqué.")

df = pd.DataFrame(all_lignes)

# Renommer colonnes
df.rename(columns={col: f"{col} / {TRANSLATION_MAP.get(col, col)}" for col in df.columns}, inplace=True)

st.markdown('<div class="card"><div class="section-title">4. Résultats</div>', unsafe_allow_html=True)
st.dataframe(df, use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# 5. Export Excel
st.markdown('<div class="card"><div class="section-title">5. Export Excel</div>', unsafe_allow_html=True)
out = io.BytesIO()
with pd.ExcelWriter(out, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
out.seek(0)
st.download_button(
    "📥 Télécharger le fichier Excel",
    data=out,
    file_name="bon_de_livraison.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
st.markdown('</div>', unsafe_allow_html=True)
