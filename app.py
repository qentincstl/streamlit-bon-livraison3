import streamlit as st
import pandas as pd
import openai
import fitz
from PIL import Image
import io
import base64
import json
import re
import hashlib

# — Vérification de mot de passe —
def check_password():
    def on_enter():
        st.session_state["ok"] = (st.session_state["pwd"] == "3DTRADEperso")
    if "ok" not in st.session_state:
        st.text_input("🔐 Mot de passe :", type="password", key="pwd", on_change=on_enter)
        st.stop()
    if not st.session_state["ok"]:
        st.text_input("🔐 Mot de passe :", type="password", key="pwd", on_change=on_enter)
        st.error("Mot de passe incorrect.")
        st.stop()

check_password()

# — Configuration de la page —
st.set_page_config(page_title="Extraction colonnes", layout="wide", page_icon="📋")
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)
st.markdown('<h1 class="section-title">Extraction colonnes (multi-prompts via GPT-4o Vision)</h1>', unsafe_allow_html=True)

# — Clé API OpenAI —
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez `OPENAI_API_KEY` dans vos Secrets.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# — Convertir un PDF en images —
def extract_images_from_pdf(pdf_bytes: bytes):
    imgs = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return imgs

# — Appel GPT pour extraire une liste de valeurs via un prompt ciblé —
def extract_values(img: Image.Image, prompt: str) -> list:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}} 
            ]
        }],
        temperature=0,
        max_tokens=500
    )
    out = resp.choices[0].message.content
    m = re.search(r'\{.*?\}', out, re.DOTALL)
    if not m:
        raise ValueError("Aucun JSON trouvé dans la réponse.")
    data = json.loads(m.group(0))
    return data.get("values", [])

# — Prompts par colonne —
COLUMN_PROMPTS = {
    "Référence produit / 产品参考": """
Tu es un assistant logistique expert. Je te fournis une image ou une page de PDF d'un bon de livraison.
Extrait toutes les **références produit** (alphanumériques) et renvoie **uniquement** ce JSON :
{"values": ["REF001", "REF002", ...]}
    """.strip(),
    "Code EAN / 条形码": """
Tu es un assistant logistique expert. Je te fournis une image ou une page de PDF d'un bon de livraison.
Extrait tous les **codes EAN** (13 chiffres) et renvoie **uniquement** ce JSON :
{"values": ["1234567890123", ...]}
    """.strip(),
    "Nombre de cartons / 箱数": """
Tu es un assistant logistique expert. Je te fournis une image ou une page de PDF d'un bon de livraison.
Extrait tous les **nombres de cartons** (entiers) pour chaque ligne de produit
et renvoie **uniquement** ce JSON :
{"values": [1, 2, ...]}
    """.strip(),
    "Nombre de produits / 产品数量": """
Tu es un assistant logistique expert. Je te fournis une image ou une page de PDF d'un bon de livraison.
Extrait tous les **nombres de produits** (entiers) pour chaque ligne de produit
et renvoie **uniquement** ce JSON :
{"values": [108, 50, ...]}
    """.strip()
}

# — Upload du fichier —
uploaded = st.file_uploader("Importez votre PDF ou photo", type=["pdf","png","jpg","jpeg"])
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
checksum = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : **{uploaded.name}** — MD5 : `{checksum}`</div>', unsafe_allow_html=True)

# — Préparer les pages à analyser —
ext = uploaded.name.lower().split(".")[-1]
if ext == "pdf":
    pages = extract_images_from_pdf(file_bytes)
else:
    pages = [Image.open(io.BytesIO(file_bytes))]

# — Aperçu des pages —
st.markdown('<div class="card"><div class="section-title">Aperçu des pages</div></div>', unsafe_allow_html=True)
for i, img in enumerate(pages, start=1):
    st.image(img, caption=f"Page {i}", use_container_width=True)

# — Extraction multi-prompts —
st.markdown('<div class="card"><div class="section-title">Extraction colonnes</div></div>', unsafe_allow_html=True)
all_columns = {col: [] for col in COLUMN_PROMPTS}
for i, img in enumerate(pages, start=1):
    st.markdown(f"##### Page {i}")
    for col, prompt in COLUMN_PROMPTS.items():
        with st.spinner(f"Extraction « {col} »…"):
            try:
                values = extract_values(img, prompt)
                all_columns[col].extend(values)
                st.success(f"{col} : {values}")
            except Exception as e:
                st.error(f"Erreur {col} : {e}")

# — Vérification des longueurs —
lengths = {col: len(vals) for col, vals in all_columns.items()}
if len(set(lengths.values())) != 1:
    st.warning(f"⚠️ Listes de longueurs différentes : {lengths}")

# — Assemblage du tableau —
n = min(lengths.values())
records = [
    {col: all_columns[col][i] for col in all_columns}
    for i in range(n)
]
df = pd.DataFrame(records)

# — Affichage et export —
st.markdown('<div class="card"><div class="section-title">Table finale</div></div>', unsafe_allow_html=True)
st.dataframe(df, use_container_width=True)
csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    "📥 Télécharger CSV",
    data=csv,
    file_name="extraction_colonnes.csv",
    mime="text/csv",
    use_container_width=True
)
