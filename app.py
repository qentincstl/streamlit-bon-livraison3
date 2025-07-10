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

# — Vérification mot de passe —
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

# — Page config & style —
st.set_page_config(page_title="Extraction colonnes & vérif", layout="wide", page_icon="📋")
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)
st.markdown('<h1 class="section-title">Extraction Colonnes et Vérification</h1>', unsafe_allow_html=True)

# — Clé API OpenAI —
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez `OPENAI_API_KEY` dans vos Secrets.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# — Convertir PDF → images —
def extract_images_from_pdf(pdf_bytes: bytes):
    imgs = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return imgs

# — Appel générique renvoyant le JSON complet —
def call_gpt_for_json(img: Image.Image, prompt: str) -> dict:
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
        max_tokens=600
    )
    out = resp.choices[0].message.content
    m = re.search(r'(\{.*?\})', out, re.DOTALL)
    if not m:
        raise ValueError("Aucun JSON trouvé dans la réponse.")
    return json.loads(m.group(0))

# — Prompts pour chaque extraction —
COLUMN_PROMPTS = {
    "Référence produit / 产品参考": """
Tu es un assistant logistique expert. Je te fournis une image ou une page de PDF d'un bon de livraison.
Extrait toutes les **références produit** (alphanumériques) et renvoie **uniquement** ce JSON :
{"values": ["REF001", "REF002", ...]}
    """.strip(),
    "Code EAN / 条形码": """
Tu es un assistant logistique expert. Je te fournis une image ou une page de PDF d'un bon de livraison.
Extrait tous les **codes EAN** (13 chiffres) ou numéros de code-barres,
parfois indiqués sous "Code EAN", "EAN", "Code-barres", etc.
Renvoie **uniquement** ce JSON :
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

# — Prompt pour extraire le total à vérifier —
TOTAL_PROMPT = """
Tu es un assistant logistique expert. Je te fournis une image ou une page de PDF d'un bon de livraison.
Extrait la **valeur du total des produits** indiquée dans le document,
souvent sous "Total", "TOTAL", "合计", etc.
Renvoie **uniquement** ce JSON :
{"total": 4296}
""".strip()

# — Upload —
uploaded = st.file_uploader("Importez votre PDF ou photo", type=["pdf","png","jpg","jpeg"])
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
checksum = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : **{uploaded.name}** — MD5 : `{checksum}`</div>', unsafe_allow_html=True)

# — Préparation des pages —
ext = uploaded.name.lower().split(".")[-1]
if ext == "pdf":
    pages = extract_images_from_pdf(file_bytes)
else:
    pages = [Image.open(io.BytesIO(file_bytes))]

# — Aperçu —
st.markdown('<div class="card"><div class="section-title">Aperçu des pages</div></div>', unsafe_allow_html=True)
for i, img in enumerate(pages, start=1):
    st.image(img, caption=f"Page {i}", use_container_width=True)

# — Extraction des colonnes multiprompts —
st.markdown('<div class="card"><div class="section-title">Extraction des colonnes</div></div>', unsafe_allow_html=True)
all_columns = {col: [] for col in COLUMN_PROMPTS}
for i, img in enumerate(pages, start=1):
    st.markdown(f"##### Page {i}")
    for col, prompt in COLUMN_PROMPTS.items():
        with st.spinner(f"Extraction « {col} »…"):
            try:
                data = call_gpt_for_json(img, prompt)
                vals = data.get("values", [])
                all_columns[col].extend(vals)
                st.success(f"{col} : {vals}")
            except Exception as e:
                st.error(f"Erreur sur {col} : {e}")

# — Extraction du total (seulement sur la 1ʳᵉ page) —
st.markdown('<div class="card"><div class="section-title">Extraction du total</div></div>', unsafe_allow_html=True)
try:
    total_data = call_gpt_for_json(pages[0], TOTAL_PROMPT)
    total_extrait = int(total_data.get("total", 0))
    st.success(f"Total extrait : {total_extrait}")
except Exception as e:
    total_extrait = None
    st.error(f"Erreur extraction total : {e}")

# — Assemblage —
# Vérification que toutes les listes ont la même longueur
lengths = {col: len(vals) for col, vals in all_columns.items()}
if len(set(lengths.values())) != 1:
    st.warning(f"⚠️ Listes de longueurs différentes : {lengths}")
n = min(lengths.values())
records = [
    {col: all_columns[col][i] for col in COLUMN_PROMPTS}
    for i in range(n)
]
df = pd.DataFrame(records)

# — Comparaison somme vs total —
df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")
somme = int(df["Nombre de produits / 产品数量"].sum())
verif = "OK ✅" if total_extrait is not None and somme == total_extrait else f"❌ {abs(somme - (total_extrait or 0))} de différence"
st.markdown('<div class="card"><div class="section-title">Vérification finale</div></div>', unsafe_allow_html=True)
st.write(f"- Somme des produits calculée : **{somme}**")
if total_extrait is not None:
    st.write(f"- Total extrait du document : **{total_extrait}**")
st.write(f"- **Résultat** : {verif}")

# — Affichage et export —
st.markdown('<div class="card"><div class="section-title">Table finale</div></div>', unsafe_allow_html=True)
st.dataframe(df, use_container_width=True)
csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    "📥 Télécharger CSV",
    data=csv,
    file_name="extraction_finale.csv",
    mime="text/csv",
    use_container_width=True
)
