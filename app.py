import streamlit as st
import pandas as pd
import openai
import io
import json
import hashlib
import fitz
import re

# -------- Configuration Streamlit --------
st.set_page_config(
    page_title="Fiche de réception",
    layout="wide",
    page_icon="📋"
)

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

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🛑 Ajoutez `OPENAI_API_KEY` dans les Secrets de Streamlit Cloud.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# -------- Fonctions --------

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrait tout le texte du PDF, toutes pages confondues."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texte = []
    for page in doc:
        texte.append(page.get_text())
    return "\n".join(texte)

def extract_json_block(s: str) -> str:
    """Isole le plus grand bloc JSON (entre [] ou {})."""
    json_regex = re.compile(r'(\[.*?\]|\{.*?\})', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé dans la sortie du modèle.")
    return max(matches, key=len)

def extract_json_with_gpt4o(full_text: str, prompt: str) -> str:
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": prompt + "\n\n" + full_text
            }
        ],
        max_tokens=2000,
        temperature=0
    )
    return response.choices[0].message.content

# -------- Prompt GPT --------
prompt = """
Tu es un assistant expert en logistique.

Voici le texte complet d’un bon de livraison PDF, qui peut contenir plusieurs pages.  
Pour chaque ligne, extrait uniquement :
- Référence (参考编号)
- Produit (产品名称)
- Nombre de colis (箱数)
- Nombre de pièces par colis (每箱件数)
- Total de pièces (总件数) = Nombre de colis × Nombre de pièces par colis

Si un même article (même référence et nom exact) apparaît plusieurs fois, additionne les quantités.

À la fin du document, le nombre total officiel de colis est indiqué.  
Calcule la somme totale des colis extraits et compare-la à ce total officiel.  
S’il y a un écart, indique-le uniquement dans une colonne "Alerte (警告)" (exemple : "Écart de 5 colis" ou "Erreur sur la référence XYZ").  
Sinon, laisse la colonne vide.

Formate ta réponse EXCLUSIVEMENT en tableau JSON, comme ceci :
[
  {
    "Référence (参考编号)": "",
    "Produit (产品名称)": "",
    "Nombre de colis (箱数)": 0,
    "Nombre de pièces par colis (每箱件数)": 0,
    "Total de pièces (总件数)": 0,
    "Alerte (警告)": ""
  }
]

Ne mets rien d’autre avant ou après le tableau JSON.
"""

# -------- Interface --------

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

ext = uploaded.name.lower().rsplit('.', 1)[-1]
if ext == 'pdf':
    full_text = extract_text_from_pdf(file_bytes)
    st.markdown('<div class="card"><div class="section-title">2. Texte extrait du PDF</div>', unsafe_allow_html=True)
    st.text_area("Texte extrait :", full_text, height=300)
    st.markdown('</div>', unsafe_allow_html=True)
else:
    st.warning("Ce script ne gère que les PDF pour extraction globale multi-pages.")
    st.stop()

# Extraction JSON globale
st.markdown('<div class="card"><div class="section-title">3. Extraction JSON</div>', unsafe_allow_html=True)
with st.spinner("Analyse GPT-4o en cours... (1 à 3 essais automatiques si besoin)"):
    output, output_clean = None, None
    for attempt in range(1, 4):
        try:
            output = extract_json_with_gpt4o(full_text, prompt)
            output_clean = extract_json_block(output)
            break  # Succès
        except Exception as e:
            output_clean = None
    if not output_clean:
        st.error(f"Échec extraction JSON après 3 essais. Réponse brute :\n{output}")
        st.stop()
    st.code(output, language="json")

# Construction DataFrame et affichage
try:
    lignes = json.loads(output_clean)
    if isinstance(lignes, dict):
        lignes = [lignes]
    if not isinstance(lignes, list):
        st.error("La sortie du modèle n'est ni une liste ni un dictionnaire, résultat : " + repr(lignes))
        st.stop()
    if len(lignes) == 0:
        st.warning("La sortie JSON est vide.")
    df = pd.DataFrame(lignes)
except Exception as e:
    st.error(f"Erreur parsing JSON : {e}\nSortie brute : {output_clean}")
    st.stop()

st.markdown('<div class="card"><div class="section-title">4. Résultats</div>', unsafe_allow_html=True)
st.dataframe(df, use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# Export Excel
st.markdown('<div class="card"><div class="section-title">5. Export Excel</div>', unsafe_allow_html=True)
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
