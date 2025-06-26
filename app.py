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

# PROMPT FORTIFIÉ
prompt = (
    "Tu reçois un bon de livraison multi-pages sous forme de PDF.\n"
    "Ta mission : lire TOUTES les lignes produit et extraire :\n"
    "- Référence\n"
    "- Produit\n"
    - "Quantité (exactement comme sur la ligne)\n"
    "- Page\n"
    "\n"
    "À la fin du document, il y a un total général de pièces : ici il est de **10730**.\n"
    "Tu dois additionner toutes les quantités extraites. Tant que ce total est différent de 10730, recommence ta lecture.\n"
    "\n"
    "⚠️ Ne fusionne pas les lignes similaires, même si les références sont identiques.\n"
    "⚠️ Ne copie pas de quantité d'une ligne à l’autre. Ne fais aucune hypothèse.\n"
    "⚠️ Si une quantité est illisible, mets « ? » et continue la ligne, mais ne l’ajoute pas dans le total.\n"
    "\n"
    "Lorsque la somme des quantités extraites est bien 10730, rends la réponse finale sous forme d’un tableau JSON comme ceci :\n"
    "[\n"
    "  {\"Référence\": \"1V1073DM\", \"Produit\": \"MESO MASK 50ML POT SPE\", \"Quantité\": \"837\", \"Page\": 1},\n"
    "  {\"Référence\": \"1V1073DM\", \"Produit\": \"MESO MASK 50ML POT SPE\", \"Quantité\": \"26\", \"Page\": 1},\n"
    "  {\"Référence\": \"1V1463\", \"Produit\": \"NCEF REVERSE POT 50ML\", \"Quantité\": \"150\", \"Page\": 2}\n"
    "]\n"
    "Ne fournis aucun texte autour du JSON."
)
# Interface utilisateur
st.markdown('<div class="card"><div class="section-title">1. Import du document</div></div>', unsafe_allow_html=True)
uploaded = st.file_uploader("Importez votre PDF ou photo", key="file_uploader")
if not uploaded:
    st.stop()
file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : {uploaded.name} — Hash MD5 : {hash_md5}</div>', unsafe_allow_html=True)

# Extraction des images
ext = uploaded.name.lower().rsplit('.', 1)[-1]
images = extract_images_from_pdf(file_bytes) if ext == 'pdf' else [Image.open(io.BytesIO(file_bytes))]

# Aperçu
st.markdown('<div class="card"><div class="section-title">2. Aperçu du document</div>', unsafe_allow_html=True)
for i, img in enumerate(images):
    st.image(img, caption=f"Page {i+1}", use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# Analyse
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

# Affichage
st.markdown('<div class="card"><div class="section-title">4. Résultats</div>', unsafe_allow_html=True)
df = pd.DataFrame(all_lignes)
df["Quantité"] = pd.to_numeric(df["Quantité"], errors="coerce")
total_calcule = df["Quantité"].sum()
st.dataframe(df, use_container_width=True)
st.markdown(f"🧮 **Total calculé des pièces : {int(total_calcule)}**")
st.markdown('</div>', unsafe_allow_html=True)

# Export
st.markdown('<div class="card"><div class="section-title">5. Export Excel</div>', unsafe_allow_html=True)
out = io.BytesIO()
with pd.ExcelWriter(out, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
out.seek(0)
st.download_button(
    "📥 Télécharger les données au format Excel",
    data=out,
    file_name="bon_de_livraison_corrige.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
st.markdown('</div>', unsafe_allow_html=True)
