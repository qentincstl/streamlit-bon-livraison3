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



# — 2) Configuration de la page & style —
st.set_page_config(page_title="Extraction complète de la table", layout="wide", page_icon="📋")
st.markdown("""
<style>
  .section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
  .card { background:#fff; padding:1rem; border-radius:0.5rem;
          box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)
st.markdown('<h1 class="section-title">Extraction complète de la table (OCR→JSON)</h1>', unsafe_allow_html=True)

# — 3) Clé API OpenAI —
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez 'OPENAI_API_KEY' dans vos Secrets Streamlit.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# — 4) Fonction de conversion PDF → images —
def extract_images_from_pdf(pdf_bytes: bytes) -> list[Image.Image]:
    pages = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        pages.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return pages

# — 5) Prompt unifié pour extraire la table et le total —
UNIFIED_PROMPT = """
Tu es un assistant logistique expert. Je te fournis une seule page d’un bon de livraison au format image ou PDF.
Extrait **toutes** les lignes de produits, avec ces champs exacts :
- Référence produit / 产品参考
- Code-barres / 条形码
- Nombre de cartons / 箱数
- Nombre de produits / 产品数量
Renvoie **uniquement** ce JSON, incluant en dernier la ligne Total / 合计 :
[
  {
    "Référence produit / 产品参考": "CODE123",
    "Code-barres / 条形码": "3401348573060",
    "Nombre de cartons / 箱数": 1,
    "Nombre de produits / 产品数量": 837,
    "Vérification / 校验": ""
  },
  …,
  {
    "Référence produit / 产品参考": "Total / 合计",
    "Code-barres / 条形码": "",
    "Nombre de cartons / 箱数": 13,
    "Nombre de produits / 产品数量": 10730,
    "Vérification / 校验": ""
  }
]
"""

# — 6) Extraction d'une page —
def extract_table_with_gpt4o(img: Image.Image) -> list[dict]:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": UNIFIED_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }],
        temperature=0,
        max_tokens=2000
    )
    content = response.choices[0].message.content
    blocks = re.findall(r'(\[.*?\])', content, re.DOTALL)
    if not blocks:
        raise ValueError("Aucun JSON détecté dans la réponse GPT.")
    return json.loads(max(blocks, key=len))

# — 7) Upload du fichier —
uploaded = st.file_uploader("Importez votre PDF ou photo", type=["pdf", "png", "jpg", "jpeg"])
if not uploaded:
    st.stop()
file_bytes = uploaded.getvalue()
checksum = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : **{uploaded.name}** — MD5 : `{checksum}`</div>', unsafe_allow_html=True)

# — 8) Préparer les pages —
ext = uploaded.name.lower().rsplit('.', 1)[-1]
if ext == "pdf":
    pages = extract_images_from_pdf(file_bytes)
else:
    pages = [Image.open(io.BytesIO(file_bytes))]

# — 9) Aperçu des pages —
st.markdown('<div class="card"><div class="section-title">Aperçu des pages</div></div>', unsafe_allow_html=True)
for i, page in enumerate(pages, start=1):
    st.image(page, caption=f"Page {i}", use_container_width=True)

# — 10) Extraction & agrégation —
st.markdown('<div class="card"><div class="section-title">Extraction des tables</div></div>', unsafe_allow_html=True)
all_rows = []
for i, page in enumerate(pages, start=1):
    with st.spinner(f"Analyse page {i}…"):
        try:
            rows = extract_table_with_gpt4o(page)
            all_rows.extend(rows)
            st.success(f"{len(rows)} lignes extraites (dont total)")
        except Exception as e:
            st.error(f"Échec page {i} : {e}")

# — 11) Affichage, vérification, export —
if all_rows:
    df = pd.DataFrame(all_rows)
    # Convertir en numérique
    df["Nombre de cartons / 箱数"] = pd.to_numeric(df["Nombre de cartons / 箱数"], errors="coerce")
    df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")
    # Total document & total calculé
    total_doc = int(df.iloc[-1]["Nombre de produits / 产品数量"])
    total_calc = int(df.iloc[:-1]["Nombre de produits / 产品数量"].sum())
    verif = "OK ✅" if total_calc == total_doc else f"❌ Écart : {total_calc - total_doc}"

    st.markdown('<div class="card"><div class="section-title">Résultats</div></div>', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)
    st.markdown(f"- **Total extrait** : {total_doc}")
    st.markdown(f"- **Total calculé** : {total_calc}")
    st.markdown(f"- **Vérification** : {verif}")

    # Export Excel
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
    out.seek(0)
    st.download_button(
        "📥 Télécharger (Excel)",
        data=out,
        file_name="bon_de_livraison_extrait.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    st.error("Aucune ligne extraite.")
