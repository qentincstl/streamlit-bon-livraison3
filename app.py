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

st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="section-title">Fiche de réception (OCR multi-pages & Excel via GPT-4o)</h1>', unsafe_allow_html=True)

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez `OPENAI_API_KEY` dans les Secrets de Streamlit Cloud.")
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

# PROMPT FINAL
prompt = """
Tu es un assistant logistique expert. Tu vas recevoir un bon de livraison (PDF ou image).

---

OBJECTIF :
1. Extrait le **total des quantités** indiqué en bas du document (ex. `TOTAL`, `TOTAL UNITÉ`, ou équivalent).
2. Reconstitue un tableau clair (français + chinois), AVEC CES COLONNES :
   - Référence interne / 内部编号
   - Référence produit / 产品参考
   - Nombre de cartons / 箱数
   - Nombre de produits / 产品数量
   - Vérification / 校验

3. **Regroupe** les lignes ayant la même référence produit.
4. **Additionne** les quantités pour chaque produit.
5. À la fin du tableau (UNE SEULE FOIS), ajoute une ligne “Total / 合计” avec la somme des colonnes Nombre de cartons et Nombre de produits.

CONTRAINTES :
- Tu NE DOIS PAS afficher de sous-total ou total au milieu du tableau, seulement en toute dernière ligne.
- Tu DOIS vérifier que la somme calculée = total inscrit sur le document.
    - Si ce n’est pas le cas, signale une erreur dans la colonne Vérification (“Écart avec le total du document”).
- N’ajoute aucun texte, ni commentaire, ni total ailleurs que la dernière ligne.

FORMAT DE SORTIE OBLIGATOIRE (JSON) :
[
  {
    "Référence interne / 内部编号": "1V1073DM",
    "Référence produit / 产品参考": "3401560192347",
    "Nombre de cartons / 箱数": 3,
    "Nombre de produits / 产品数量": 324,
    "Vérification / 校验": ""
  },
  ...,
  {
    "Référence interne / 内部编号": "Total / 合计",
    "Référence produit / 产品参考": "",
    "Nombre de cartons / 箱数": XX,
    "Nombre de produits / 产品数量": 4296,
    "Vérification / 校验": ""
  }
]
"""


---

🛑 Ne fournis **aucun texte ou commentaire autour** du JSON. La réponse doit être **strictement** le tableau JSON demandé.
"""

# ---- UI ----

st.markdown('<div class="card"><div class="section-title">1. Import du document</div></div>', unsafe_allow_html=True)
uploaded = st.file_uploader("Importez votre PDF, photo ou Excel", type=["pdf", "png", "jpg", "jpeg", "xlsx"], key="file_uploader")
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : {uploaded.name} — Hash MD5 : {hash_md5}</div>', unsafe_allow_html=True)

ext = uploaded.name.lower().rsplit('.', 1)[-1]

# Gestion EXCEL
if ext in ["xlsx"]:
    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
        st.markdown('<div class="card"><div class="section-title">Aperçu Excel</div>', unsafe_allow_html=True)
        st.dataframe(df, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        # Optionnel : ajouter contrôle sur colonnes attendues ou transformer le DataFrame
        st.success("✅ Excel importé et affiché.")
    except Exception as e:
        st.error(f"Erreur lors de la lecture Excel : {e}")
        st.stop()
else:
    # PDF ou image : OCR + GPT
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
    st.dataframe(df, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- Export Excel ---
st.markdown('<div class="card"><div class="section-title">5. Export Excel</div>', unsafe_allow_html=True)
out = io.BytesIO()
with pd.ExcelWriter(out, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
out.seek(0)
st.download_button(
    "📅 Télécharger au format Excel",
    data=out,
    file_name="bon_de_livraison_corrige.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
st.markdown('</div>', unsafe_allow_html=True)
