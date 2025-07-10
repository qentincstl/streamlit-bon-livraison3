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
  .jsonout { white-space:pre-wrap; font-family:monospace; background:#f8f8f8; padding:1rem; border-radius:0.5rem;}
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="section-title">Fiche de réception (OCR multi-pages & Excel “intelligent”)</h1>', unsafe_allow_html=True)

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

def extract_json_with_gpt4o(images, prompt: str):
    bufs = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        bufs.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                *bufs
            ]
        }],
        max_tokens=2000,
        temperature=0
    )
    return response.choices[0].message.content

def extract_json_block(s: str) -> str:
    json_regex = re.compile(r'(\[.*?\]|\{.*?\})', re.DOTALL)
    matches = json_regex.findall(s)
    if not matches:
        raise ValueError("Aucun JSON trouvé dans la sortie du modèle.")
    return max(matches, key=len)

def excel_bdl_autodetect(df):
    """Extraction intelligente d'un bon de livraison Excel non structuré : trouve infos globales + table produits + fusion doublons + total"""
    bon_livraison, commande, client, date_str = None, None, None, None
    # Recherche infos
    bon_livraison_num = df[df.eq("Bon de livraison N° :").any(1)]
    if not bon_livraison_num.empty:
        idx = bon_livraison_num.index[0]
        bon_livraison = df.iat[idx, bon_livraison_num.columns[0] + 1]

    commande_num = df[df.eq("Commande").any(1)]
    if not commande_num.empty:
        idx = commande_num.index[0]
        commande = df.iat[idx, commande_num.columns[0] + 1]

    client_info = df[df.eq("Client :").any(1)]
    if not client_info.empty:
        idx = client_info.index[0]
        client = df.iat[idx, client_info.columns[0] + 1]

    date_info = df[df.eq("Date :").any(1)]
    if not date_info.empty:
        idx = date_info.index[0]
        date_value = df.iat[idx, date_info.columns[0] + 1]
        date_str = pd.to_datetime(date_value).strftime("%Y-%m-%d") if pd.notna(date_value) else None

    # Repérage table produits
    header_row = df[df.eq("Intitulé").any(1)].index
    articles, table = [], pd.DataFrame()
    if len(header_row) > 0:
        start = header_row[0] + 1
        total_row = df[df.eq("Total").any(1)].index
        end = total_row[0] if len(total_row) > 0 else df.shape[0]
        produit_rows = df.iloc[start:end].reset_index(drop=True)
        produits_list = []
        for _, row in produit_rows.iterrows():
            ref = row[0]
            designation = row[3]
            quantite = row[4]
            if pd.isna(ref) or pd.isna(designation) or pd.isna(quantite):
                continue
            produits_list.append({"ref": ref, "designation": designation, "quantite": float(quantite)})

        # Fusion des doublons de produits par désignation
        fusionnes = {}
        for produit in produits_list:
            nom = str(produit["designation"]).strip()
            qt = float(produit["quantite"])
            if nom in fusionnes:
                fusionnes[nom]["quantite"] += qt
            else:
                fusionnes[nom] = produit.copy()
        articles = list(fusionnes.values())

        # Table formatée pour affichage et export
        table = pd.DataFrame([
            {
                "Référence interne / 内部编号": art["ref"],
                "Référence produit / 产品参考": "",  # À compléter si tu as l'EAN dans une autre colonne
                "Nombre de cartons / 箱数": 1,  # Par défaut 1 ligne = 1 carton (à adapter)
                "Nombre de produits / 产品数量": art["quantite"],
                "Désignation": art["designation"]
            } for art in articles
        ])

        total_calcule = sum(art["quantite"] for art in articles)
        total_lu = None
        if len(total_row) > 0:
            total_lu = produit_rows.iloc[total_row[0] - start, 4]
        total_final = total_calcule if total_lu is None or total_calcule != total_lu else total_lu

        # Ajout du total unique à la fin de la table
        total_row_out = {
            "Référence interne / 内部编号": "Total / 合计",
            "Référence produit / 产品参考": "",
            "Nombre de cartons / 箱数": "",
            "Nombre de produits / 产品数量": total_final,
            "Désignation": ""
        }
        table = pd.concat([table, pd.DataFrame([total_row_out])], ignore_index=True)

        # Complétion du JSON final
        resultat = {
            "bon_de_livraison": bon_livraison,
            "commande": commande,
            "client": client,
            "date": date_str,
            "articles": articles,
            "total": total_final
        }
    else:
        resultat = {}
        table = df
    return resultat, table

prompt = """
Tu es un assistant logistique expert. Tu vas recevoir un bon de livraison (PDF, image ou Excel).

OBJECTIF :
1. Extrait le total des quantités indiqué en bas du document (ex. TOTAL, TOTAL UNITÉ, ou équivalent).
2. Reconstitue un tableau clair (français + chinois), AVEC CES COLONNES :
   - Référence interne / 内部编号
   - Référence produit / 产品参考
   - Nombre de cartons / 箱数
   - Nombre de produits / 产品数量
   - Vérification / 校验

3. Regroupe les lignes ayant la même référence produit.
4. Additionne les quantités pour chaque produit.
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

st.markdown('<div class="card"><div class="section-title">1. Import du document</div></div>', unsafe_allow_html=True)
uploaded = st.file_uploader("Importez votre PDF, image ou Excel", type=["pdf", "png", "jpg", "jpeg", "xlsx"], key="file_uploader")
if not uploaded:
    st.stop()

file_bytes = uploaded.getvalue()
hash_md5 = hashlib.md5(file_bytes).hexdigest()
st.markdown(f'<div class="card">Fichier : {uploaded.name} — Hash MD5 : {hash_md5}</div>', unsafe_allow_html=True)

ext = uploaded.name.lower().rsplit('.', 1)[-1]

if ext == "xlsx":
    try:
        # Lecture brute (header=None pour laisser la détection auto)
        df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None)
        # Extraction “auto-détection” : infos principales + table produits + JSON
        json_bdl, table = excel_bdl_autodetect(df_raw)

        st.markdown('<div class="card"><div class="section-title">2. Résumé et JSON</div>', unsafe_allow_html=True)
        st.markdown("#### Informations globales")
        infos = {k: v for k, v in json_bdl.items() if k in ["bon_de_livraison", "commande", "client", "date"]}
        st.write(infos)
        st.markdown("#### Sortie JSON (articles + total)")
        st.markdown(f"<div class='jsonout'>{json.dumps(json_bdl, ensure_ascii=False, indent=2)}</div>", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="card"><div class="section-title">3. Tableau consolidé</div>', unsafe_allow_html=True)
        st.dataframe(table, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Export Excel
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            table.to_excel(writer, index=False, sheet_name="BON_DE_LIVRAISON")
        out.seek(0)
        st.download_button(
            "📅 Télécharger le tableau au format Excel",
            data=out,
            file_name="bon_de_livraison_corrige.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        st.stop()
    except Exception as e:
        st.error(f"Erreur lors de la lecture ou transformation Excel : {e}")
        st.stop()
else:
    # PDF/image : toutes pages envoyées d'un coup à GPT-4o pour 1 SEUL total final
    images = extract_images_from_pdf(file_bytes) if ext == 'pdf' else [Image.open(io.BytesIO(file_bytes))]
    st.markdown('<div class="card"><div class="section-title">2. Aperçu du document</div>', unsafe_allow_html=True)
    for i, img in enumerate(images):
        st.image(img, caption=f"Page {i+1}", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="section-title">3. Extraction JSON</div>', unsafe_allow_html=True)
    with st.spinner("Analyse en cours..."):
        try:
            output = extract_json_with_gpt4o(images, prompt)
            output_clean = extract_json_block(output)
            lignes = json.loads(output_clean)
            # Supprime les totaux non finaux s'il y en avait plusieurs
            if len(lignes) > 2:
                last_idx = max(i for i, x in enumerate(lignes) if (
                    "Total" in x.get("Référence interne / 内部编号", "") or "合计" in x.get("Référence interne / 内部编号", ""))
                )
                lignes = lignes[:last_idx] + [lignes[last_idx]]
            df = pd.DataFrame(lignes)
        except Exception as e:
            st.error(f"❌ Erreur d'extraction ou de format JSON : {e}")
            st.stop()

    st.markdown('<div class="card"><div class="section-title">4. Résultats</div>', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

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
