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

def extract_json_with_gpt4o(img: Image.Image, prompt: str) -> str:
    """Envoie une image à GPT-4o avec le prompt et récupère la réponse brute."""
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
    """Isole le plus grand bloc JSON (entre {} ou []) dans une chaîne."""
    json_regex = re.compile(r'(\[.*?\]|\{.*?\})', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé dans la sortie du modèle.")
    return max(matches, key=len)

# Prompt pour GPT-4o
prompt = """
Tu es un assistant logistique extrêmement rigoureux chargé d'analyser intégralement un bon de livraison PDF (souvent sur plusieurs pages).

Voici exactement ce que tu dois faire :

1️⃣ Lis chaque page et chaque ligne attentivement, puis extrais UNIQUEMENT ces informations :
   - Référence (参考编号)
   - Produit (产品名称)
   - Nombre de colis (箱数)
   - Nombre exact de pièces par colis (每箱件数)
   - Total exact de pièces (总件数) = Nombre de colis × Nombre de pièces par colis

2️⃣ Si un produit (identifié par la référence et le nom exact) apparaît sur plusieurs lignes ou pages, additionne parfaitement toutes les quantités (colis et pièces).

3️⃣ À la fin du PDF, il y a un total global officiel précis et fiable. Ce total est exactement juste et constitue ta référence absolue. Tu dois donc :
   - Calculer précisément le nombre total de colis que TU as extrait.
   - Comparer immédiatement ce nombre au total officiel indiqué clairement à la fin du document PDF.
   - Si le total calculé ne correspond pas exactement au total officiel, tu DOIS obligatoirement réanalyser le document, identifier clairement tes erreurs d'extraction (oubli, double-compte ou mauvaise lecture), et corriger ces erreurs AVANT de donner ton résultat final.
   - Ne t'arrête pas tant que ton total calculé ne correspond pas exactement au total officiel.

4️⃣ Si tu es absolument incapable de résoudre un écart après plusieurs révisions approfondies, indique clairement la nature exacte de l’écart dans la colonne "Alerte (警告)" (exemple : "Écart de 20 pièces sur produit XYZ"). Sinon, laisse la colonne vide.

⚠️ À la fin de ton tableau JSON, indique explicitement et clairement en dessous ces deux lignes récapitulatives (hors du tableau JSON, clairement séparées) :

Nombre total de colis extrait : XXX (le total calculé précisément par toi)  
Nombre total de colis officiel indiqué sur le PDF : XXX (le total officiel, qui est 100% correct)

📌 FORMAT OBLIGATOIRE DE TA RÉPONSE :

[
  {
    "Référence (参考编号)": "1V1073DM",
    "Produit (产品名称)": "MESO MASK 50ML POT SPE",
    "Nombre de colis (箱数)": 384,
    "Nombre de pièces par colis (每箱件数)": 26,
    "Total de pièces (总件数)": 9984,
    "Alerte (警告)": ""
  }
]

Nombre total de colis extrait : XXX  
Nombre total de colis officiel indiqué sur le PDF : XXX  

🚫 Ne réponds rien d'autre que le tableau JSON suivi précisément de ces deux lignes récapitulatives clairement séparées.
"""
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

# 3. Extraction JSON
all_lignes = []
st.markdown(
    '<div class="card"><div class="section-title">3. Extraction JSON</div>',
    unsafe_allow_html=True
)
for i, img in enumerate(images):
    st.markdown(f"##### Analyse page {i+1} …")
    success = False
    output, output_clean = None, None

    with st.spinner("Analyse en cours... (jusqu'à 6 essais automatiques)"):
        for attempt in range(1, 7):  # 6 tentatives
            try:
                output = extract_json_with_gpt4o(img, prompt)
                output_clean = extract_json_block(output)
                success = True
                break  # Succès, on sort
            except Exception:
                pass  # On retente

    st.code(output or "Aucune réponse retournée", language="json")

    if not success:
        st.error(f"Échec extraction JSON après 6 essais sur la page {i+1}. Texte brut retourné :\n{output}")
        continue

    try:
        lignes = json.loads(output_clean)
        all_lignes.extend(lignes)
    except Exception as e:
        st.error(f"Erreur parsing JSON page {i+1} : {e}")
st.markdown('</div>', unsafe_allow_html=True)

# 4. Affichage des résultats
df = pd.DataFrame(all_lignes)
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
    df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
out.seek(0)
st.download_button(
    "Télécharger le fichier Excel",
    data=out,
    file_name="bon_de_livraison.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
st.markdown('</div>', unsafe_allow_html=True)
