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

# — 1) Password —
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

# — 2) Config page & style —
st.set_page_config(page_title="Extraction + Harmonisation", layout="wide", page_icon="📋")
st.markdown("""
<style>
.section-title { font-size:1.6rem; color:#005b96; margin-bottom:0.5rem; }
.card { background:#fff; padding:1rem; border-radius:0.5rem;
        box-shadow:0 2px 4px rgba(0,0,0,0.07); margin-bottom:1.5rem; }
</style>
""", unsafe_allow_html=True)
st.markdown('<h1 class="section-title">Extraction multi-prompts & harmonisation</h1>', unsafe_allow_html=True)

# — 3) API key —
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("🚩 Ajoutez OPENAI_API_KEY dans vos Secrets.")
    st.stop()
openai.api_key = OPENAI_API_KEY

# — 4) PDF → images —
def extract_images_from_pdf(pdf_bytes: bytes):
    imgs = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for p in doc:
        pix = p.get_pixmap(dpi=300)
        imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return imgs

# — 5) Appel GPT renvoyant un dict JSON —
def call_gpt_json(prompt: str, img: Image.Image=None) -> dict:
    """Si img fourni, on inclut l'image, sinon on envoie juste le prompt."""
    messages = [{"role":"user","content":prompt}]
    if img:
        buf=io.BytesIO(); img.save(buf,format="PNG")
        b64=base64.b64encode(buf.getvalue()).decode()
        messages[0]["content"] = [
            {"type":"text","text":prompt},
            {"type":"image_url","image_url":{"url":f"data:image/png;base64,{b64}"}} 
        ]
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0,
        max_tokens=800
    )
    out = resp.choices[0].message.content
    m = re.search(r'(\{[\s\S]*\})', out)
    if not m:
        raise ValueError("Aucun JSON renvoyé.")
    return json.loads(m.group(1))

# — 6) Prompts —
COLUMN_PROMPTS = {
    "Référence produit / 产品参考": """
Tu es un assistant logistique expert. Je te fournis une image/page PDF d'un bon de livraison.
Extrait toutes les **références produit** (alphanumériques) et renvoie **uniquement** :
{"values": ["REF001","REF002",...]}
""".strip(),
    "Code-barres / 条形码": """
Tu es un assistant logistique expert. Je te fournis une image/page PDF d'un bon de livraison.
Extrait tous les **codes EAN** (13 chiffres) ou codes-barres,
même lorsqu'ils sont sous l'intitulé "Code EAN", "EAN", "Code-barres", etc.
Renvoie **uniquement** :
{"values": ["1234567890123", ...]}
""".strip(),
    "Nombre de cartons / 箱数": """
Tu es un assistant logistique expert. Je te fournis une image/page PDF d'un bon de livraison.
Extrait tous les **nombre de cartons** (entiers) pour chaque ligne
et renvoie **uniquement** :
{"values": [1,2,...]}
""".strip(),
    "Nombre de produits / 产品数量": """
Tu es un assistant logistique expert. Je te fournis une image/page PDF d'un bon de livraison.
Extrait tous les **nombre de produits** (entiers) pour chaque ligne
et renvoie **uniquement** :
{"values": [108,50,...]}
""".strip()
}
TOTAL_PROMPT = """
Tu es un assistant logistique expert. Je te fournis une image/page PDF d'un bon de livraison.
Extrait la **valeur du total** des produits (souvent sous 'Total', 'TOTAL', '合计', etc.)
et renvoie **uniquement** :
{"total": 4296}
""".strip()
HARMONISE_PROMPT_TEMPLATE = """
Tu es un assistant logistique expert. Je t'ai fourni les listes extraites :

- Références : {refs}
- Codes-barres : {eans}
- Cartons : {boxes}
- Produits : {prods}

Associe chaque référence à son code-barres, son nombre de cartons et son nombre de produits.
Si une référence apparaît plusieurs fois, regroupe-les et somme cartons & produits.
Ignore les valeurs qui n'ont pas d'équivalent en référence.
Ajoute une ligne {"Référence produit / 产品参考":"Total / 合计", "Code-barres / 条形码":"", "Nombre de cartons / 箱数":<somme cartons>, "Nombre de produits / 产品数量":<somme produits>, "Vérification / 校验":""}.
Renvoie **uniquement ** le JSON d'une liste d'objets structurés ainsi :
[
  {
    "Référence produit / 产品参考": "...",
    "Code-barres / 条形码": "...",
    "Nombre de cartons / 箱数": X,
    "Nombre de produits / 产品数量": Y,
    "Vérification / 校验": ""
  }, …
]
""".strip()

# — 7) Upload —
uploaded = st.file_uploader("Importez PDF ou image", type=["pdf","png","jpg","jpeg"])
if not uploaded: st.stop()
file_bytes = uploaded.getvalue()
checksum = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : **{uploaded.name}** — MD5 : `{checksum}`</div>', unsafe_allow_html=True)

# — 8) Pages à analyser —
ext = uploaded.name.lower().split(".")[-1]
pages = (extract_images_from_pdf(file_bytes) if ext=="pdf"
         else [Image.open(io.BytesIO(file_bytes))])

# — 9) Aperçu —
st.markdown('<div class="card"><div class="section-title">Aperçu</div></div>', unsafe_allow_html=True)
for i,img in enumerate(pages,1):
    st.image(img, caption=f"Page {i}", use_container_width=True)

# — 10) Extract multi-prompts —
st.markdown('<div class="card"><div class="section-title">Extraction brute</div></div>', unsafe_allow_html=True)
all_cols = {col: [] for col in COLUMN_PROMPTS}
for i,img in enumerate(pages,1):
    st.markdown(f"##### Page {i}")
    for col,p in COLUMN_PROMPTS.items():
        with st.spinner(f"→ {col}"):
            try:
                vals = call_gpt_json(p, img)["values"]
                all_cols[col].extend(vals)
                st.success(f"{col} : {vals}")
            except Exception as e:
                st.error(f"Erreur {col} : {e}")

# — 11) Total —
st.markdown('<div class="card"><div class="section-title">Extraction du total</div></div>', unsafe_allow_html=True)
try:
    total = int(call_gpt_json(TOTAL_PROMPT, pages[0])["total"])
    st.success(f"Total extrait : {total}")
except Exception as e:
    total = None
    st.error(f"Erreur total : {e}")

# — 12) Harmonisation finale via GPT —
st.markdown('<div class="card"><div class="section-title">Harmonisation & finalisation</div></div>', unsafe_allow_html=True)
harmo_prompt = HARMONISE_PROMPT_TEMPLATE.format(
    refs=json.dumps(all_cols["Référence produit / 产品参考"], ensure_ascii=False),
    eans=json.dumps(all_cols["Code-barres / 条形码"], ensure_ascii=False),
    boxes=json.dumps(all_cols["Nombre de cartons / 箱数"], ensure_ascii=False),
    prods=json.dumps(all_cols["Nombre de produits / 产品数量"], ensure_ascii=False)
)
try:
    final_list = call_gpt_json(harmo_prompt)[""]  # on extrait tout le JSON
    # Si l'API renvoie directement la liste, on la récupère ainsi :
    final_list = json.loads(re.search(r'(\[.*\])', json.dumps(call_gpt_json(harmo_prompt)), re.DOTALL).group(1))
except Exception as e:
    st.error(f"Échec harmonisation : {e}")
    final_list = []

# — 13) Affichage + vérif programmatique —
if final_list:
    df = pd.DataFrame(final_list)
    # Conversion & vérification
    df["Nombre de produits / 产品数量"] = pd.to_numeric(df["Nombre de produits / 产品数量"], errors="coerce")
    somme_calc = int(df["Nombre de produits / 产品数量"].sum())
    verif = "✅ OK" if total is not None and somme_calc == total else f"❌ Écart : {somme_calc - (total or 0)}"
    st.dataframe(df, use_container_width=True)
    st.markdown(f"**Somme calculée :** {somme_calc} — **Vérif vs total :** {verif}")
    # Export
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Télécharger CSV final", data=csv,
                       file_name="resultat_harmonise.csv", mime="text/csv",
                       use_container_width=True)
else:
    st.error("Aucun résultat final à afficher.")
