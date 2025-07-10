import streamlit as st
import openai
import fitz
from PIL import Image
import io
import base64
import json
import hashlib
import re

# — Vérif mot de passe —
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
st.set_page_config(page_title="Extraction Quantités", layout="wide", page_icon="📋")
st.markdown("""
<style>
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)
st.markdown('<h1 class="card">Extraction UNIQUEMENT des quantités (OCR via GPT-4o Vision)</h1>', unsafe_allow_html=True)

# — Clé API OpenAI —
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez `OPENAI_API_KEY` dans vos Secrets.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# — Convertit un PDF en liste d’images PIL —
def extract_images_from_pdf(pdf_bytes: bytes):
    imgs = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return imgs

# — Envoie l’image à GPT-4o avec un prompt simplifié —
def extract_quantities_with_gpt4o(img: Image.Image) -> list[int]:
    # prompt ne demande QUE la liste des quantités
    prompt = """
Tu es un assistant logistique. Je te fournis une image ou une page de PDF contenant un bon de livraison.
Extrai **uniquement** toutes les quantités (nombres entiers) présentes sur chaque ligne de produit.
Réponds strictement au format JSON suivant :
{"quantities": [108, 50, 200, ...]}
    """.strip()
    # encoder l’image
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    # appel API
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }],
        max_tokens=500,
        temperature=0
    )
    out = resp.choices[0].message.content
    # extraire le bloc JSON
    m = re.search(r'\{.*\}', out, re.DOTALL)
    if not m:
        raise ValueError("Aucun JSON trouvé dans la réponse.")
    data = json.loads(m.group(0))
    return data.get("quantities", [])

# — Upload du fichier —
uploaded = st.file_uploader("Importez votre PDF ou photo", type=["pdf","png","jpg","jpeg"])
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
checksum = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : **{uploaded.name}** — MD5 : `{checksum}`</div>', unsafe_allow_html=True)

# — Préparation des images à analyser —
ext = uploaded.name.lower().split(".")[-1]
if ext == "pdf":
    pages = extract_images_from_pdf(file_bytes)
else:
    pages = [Image.open(io.BytesIO(file_bytes))]

# — Aperçu —
st.markdown('<div class="card"><strong>Aperçu des pages à analyser :</strong></div>', unsafe_allow_html=True)
for i, img in enumerate(pages, start=1):
    st.image(img, caption=f"Page {i}", use_container_width=True)

# — Extraction des quantités —
all_quantities = []
st.markdown('<div class="card"><strong>Extraction des quantités :</strong></div>', unsafe_allow_html=True)
for i, img in enumerate(pages, start=1):
    st.markdown(f"- Page {i} …")
    with st.spinner(f"Analyse page {i}…"):
        try:
            qs = extract_quantities_with_gpt4o(img)
            all_quantities.extend(qs)
            st.success(f"{len(qs)} quantités trouvées : {qs}")
        except Exception as e:
            st.error(f"❌ Erreur page {i} : {e}")

# — Résumé et total —
if all_quantities:
    total = sum(all_quantities)
    st.markdown('<div class="card"><strong>Résumé :</strong></div>', unsafe_allow_html=True)
    st.write("Quantités extraites :", all_quantities)
    st.write(f"**Total des quantités :** {total}")
else:
    st.warning("Aucune quantité extraite.")

# — (Optionnel) Export simple CSV —
csv_bytes = "quantity\n" + "\n".join(str(q) for q in all_quantities)
st.download_button(
    "📥 Télécharger les quantités (CSV)",
    data=csv_bytes,
    file_name="quantities.csv",
    mime="text/csv",
    use_container_width=True
)
