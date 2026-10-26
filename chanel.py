"""
Application de gestion et d'organisation de chantier (génie civil)
Streamlit + pandas + Plotly + SQLite (bibliothèque standard)

Installation :
    pip install streamlit pandas plotly

Lancement (dans le terminal PyCharm) :
    streamlit run main.py
"""

import sqlite3
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_PATH = "chantier.db"

COLS = ["Tâche", "Début", "Durée (j)", "Avancement (%)", "Budget (€)", "Dépensé (€)", "Responsable"]
METEOS = ["Ensoleillé", "Nuageux", "Pluie légère", "Pluie forte", "Vent fort", "Gel", "Canicule"]

st.set_page_config(page_title="Gestion de chantier", page_icon="🏗️", layout="wide")


# ----------------------------------------------------------------------------
# Base de données (SQLite)
# ----------------------------------------------------------------------------
def run(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(query, params)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        return rows
    finally:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chantiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT UNIQUE NOT NULL,
                adresse TEXT
            );
            CREATE TABLE IF NOT EXISTS taches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chantier_id INTEGER NOT NULL,
                nom TEXT, debut TEXT, duree INTEGER,
                avancement REAL, budget REAL, depense REAL, responsable TEXT
            );
            CREATE TABLE IF NOT EXISTS rapports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chantier_id INTEGER NOT NULL,
                date TEXT, meteo TEXT, effectif INTEGER, observations TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def tache_exemple():
    d = date.today()
    return [
        ("Installation de chantier", d - timedelta(days=20), 5, 100, 15000, 14200, "Chef de chantier"),
        ("Terrassement", d - timedelta(days=15), 12, 80, 60000, 66000, "Équipe VRD"),
        ("Fondations", d - timedelta(days=3), 15, 35, 90000, 38000, "Équipe GO"),
        ("Élévation des murs", d + timedelta(days=12), 20, 0, 120000, 0, "Équipe GO"),
        ("Dalle et plancher", d + timedelta(days=32), 10, 0, 70000, 0, "Équipe GO"),
        ("Finitions", d + timedelta(days=42), 14, 0, 45000, 0, "Second œuvre"),
    ]


def creer_chantier(nom, adresse="", avec_exemple=False):
    run("INSERT INTO chantiers (nom, adresse) VALUES (?, ?)", (nom, adresse))
    cid = run("SELECT id FROM chantiers WHERE nom = ?", (nom,), fetch=True)[0][0]
    if avec_exemple:
        for t in tache_exemple():
            run(
                "INSERT INTO taches (chantier_id, nom, debut, duree, avancement, budget, depense, responsable) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (cid, t[0], t[1].isoformat(), t[2], t[3], t[4], t[5], t[6]),
            )
    return cid


def charger_taches(cid):
    rows = run(
        "SELECT nom, debut, duree, avancement, budget, depense, responsable "
        "FROM taches WHERE chantier_id = ? ORDER BY id",
        (cid,),
        fetch=True,
    )
    df = pd.DataFrame(rows, columns=COLS)
    df["Début"] = pd.to_datetime(df["Début"]).dt.date
    return df


def sauver_taches(cid, df):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM taches WHERE chantier_id = ?", (cid,))
        for _, r in df.iterrows():
            conn.execute(
                "INSERT INTO taches (chantier_id, nom, debut, duree, avancement, budget, depense, responsable) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    cid,
                    r["Tâche"],
                    pd.Timestamp(r["Début"]).date().isoformat(),
                    int(r["Durée (j)"]),
                    float(r["Avancement (%)"]),
                    float(r["Budget (€)"]),
                    float(r["Dépensé (€)"]),
                    r["Responsable"],
                ),
            )
        conn.commit()
    finally:
        conn.close()


def charger_rapports(cid):
    rows = run(
        "SELECT id, date, meteo, effectif, observations FROM rapports "
        "WHERE chantier_id = ? ORDER BY date DESC, id DESC",
        (cid,),
        fetch=True,
    )
    return pd.DataFrame(rows, columns=["id", "Date", "Météo", "Effectif présent", "Observations"])


# ----------------------------------------------------------------------------
# Logique métier (indépendante de l'interface)
# ----------------------------------------------------------------------------
def nettoyer(df):
    """Valide et normalise les saisies. Retourne (df propre, liste d'erreurs)."""
    erreurs = []
    d = df.copy().dropna(how="all")
    d["Tâche"] = d["Tâche"].fillna("").astype(str).str.strip()
    d = d[d["Tâche"] != ""].copy()

    d["Début"] = pd.to_datetime(d["Début"], errors="coerce")
    if d["Début"].isna().any():
        erreurs.append("Certaines dates de début sont manquantes : remplacées par aujourd'hui.")
        d["Début"] = d["Début"].fillna(pd.Timestamp(date.today()))

    for col in ["Durée (j)", "Avancement (%)", "Budget (€)", "Dépensé (€)"]:
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0)

    if (d["Durée (j)"] < 1).any():
        erreurs.append("Les durées doivent être d'au moins 1 jour : corrigées automatiquement.")
        d["Durée (j)"] = d["Durée (j)"].clip(lower=1)
    if ((d["Avancement (%)"] < 0) | (d["Avancement (%)"] > 100)).any():
        erreurs.append("L'avancement doit être compris entre 0 et 100 % : corrigé automatiquement.")
        d["Avancement (%)"] = d["Avancement (%)"].clip(0, 100)
    if ((d["Budget (€)"] < 0) | (d["Dépensé (€)"] < 0)).any():
        erreurs.append("Les montants négatifs ont été ramenés à 0.")
        d["Budget (€)"] = d["Budget (€)"].clip(lower=0)
        d["Dépensé (€)"] = d["Dépensé (€)"].clip(lower=0)

    d["Durée (j)"] = d["Durée (j)"].astype(int)
    d["Responsable"] = d["Responsable"].fillna("").astype(str)
    d["Début"] = d["Début"].dt.date
    return d.reset_index(drop=True), erreurs


def calculer(d):
    """Ajoute les colonnes calculées et retourne (df enrichi, indicateurs)."""
    d = d.copy()
    d["Début_dt"] = pd.to_datetime(d["Début"])
    d["Fin"] = d["Début_dt"] + pd.to_timedelta(d["Durée (j)"], unit="D")  # Fin = Début + Durée
    d["Dépassement"] = d["Dépensé (€)"] > d["Budget (€)"]
    d["Écart (€)"] = d["Budget (€)"] - d["Dépensé (€)"]

    budget_total = float(d["Budget (€)"].sum())
    depense = float(d["Dépensé (€)"].sum())
    if budget_total > 0:
        avancement = float((d["Avancement (%)"] * d["Budget (€)"]).sum() / budget_total)
    else:
        avancement = float(d["Avancement (%)"].mean())

    aujourd_hui = pd.Timestamp(date.today())
    prevu = ((aujourd_hui - d["Début_dt"]) / (d["Fin"] - d["Début_dt"])).clip(0, 1)
    va = float((d["Avancement (%)"] / 100 * d["Budget (€)"]).sum())
    vp = float((prevu * d["Budget (€)"]).sum())
    ipc = va / depense if depense > 0 else None
    ipd = va / vp if vp > 0 else None
    eat = budget_total / ipc if ipc else None

    ind = {
        "budget_total": budget_total,
        "depense": depense,
        "ecart": budget_total - depense,
        "avancement": avancement,
        "fin": d["Fin"].max(),
        "debut": d["Début_dt"].min(),
        "va": va,
        "vp": vp,
        "cr": depense,
        "ipc": ipc,
        "ipd": ipd,
        "eat": eat,
    }
    return d, ind


def euros(x):
    return f"{x:,.0f} €".replace(",", " ")


# ----------------------------------------------------------------------------
# Graphiques
# ----------------------------------------------------------------------------
def figure_gantt(d):
    g = d.copy()
    g["Avancement"] = g["Avancement (%)"]
    fig = px.timeline(
        g,
        x_start="Début_dt",
        x_end="Fin",
        y="Tâche",
        color="Avancement",
        range_color=[0, 100],
        color_continuous_scale=["#d9534f", "#f0ad4e", "#5cb85c"],
        hover_data={"Début_dt": False, "Fin": "|%d/%m/%Y", "Avancement": ":.0f", "Responsable": True},
    )
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title=None)
    today = pd.Timestamp(date.today())
    fig.add_shape(type="line", x0=today, x1=today, y0=0, y1=1, yref="paper",
                  line=dict(color="#333", dash="dash", width=2))
    fig.add_annotation(x=today, y=1, yref="paper", text="Aujourd'hui", showarrow=False,
                       yshift=12, font=dict(size=11))
    fig.update_layout(height=120 + 45 * len(g), margin=dict(l=10, r=10, t=40, b=10),
                      coloraxis_colorbar=dict(title="Avanc. %"))
    return fig


def figure_courbe_s(d, ind):
    debut = d["Début_dt"].min()
    fin = d["Fin"].max()
    jours = pd.date_range(debut, fin, freq="D")
    vp = []
    for j in jours:
        part = ((j - d["Début_dt"]) / (d["Fin"] - d["Début_dt"])).clip(0, 1)
        vp.append(float((part * d["Budget (€)"]).sum()))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=jours, y=vp, mode="lines", name="Valeur planifiée (VP)",
                             line=dict(color="#1f77b4", width=3)))
    today = pd.Timestamp(date.today())
    fig.add_trace(go.Scatter(x=[today], y=[ind["va"]], mode="markers", name="Valeur acquise (VA)",
                             marker=dict(color="#2ca02c", size=14, symbol="diamond")))
    fig.add_trace(go.Scatter(x=[today], y=[ind["cr"]], mode="markers", name="Coût réel (CR)",
                             marker=dict(color="#d62728", size=14, symbol="square")))
    fig.add_shape(type="line", x0=today, x1=today, y0=0, y1=1, yref="paper",
                  line=dict(color="#333", dash="dash", width=1))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="€ cumulés", legend=dict(orientation="h", y=-0.2))
    return fig


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------
init_db()
if not run("SELECT id FROM chantiers", fetch=True):
    creer_chantier("Chantier exemple", "Adresse à renseigner", avec_exemple=True)

# --- Barre latérale : choix du chantier ---
st.sidebar.title("🏗️ Chantiers")
chantiers = run("SELECT id, nom, adresse FROM chantiers ORDER BY nom", fetch=True)
noms = {c[1]: c[0] for c in chantiers}
choix = st.sidebar.selectbox("Chantier actif", list(noms.keys()))
cid = noms[choix]
adresse = next(c[2] for c in chantiers if c[0] == cid)
if adresse:
    st.sidebar.caption(f"📍 {adresse}")

with st.sidebar.expander("➕ Nouveau chantier"):
    n_nom = st.text_input("Nom du chantier", key="n_nom")
    n_adr = st.text_input("Adresse", key="n_adr")
    if st.button("Créer le chantier"):
        if not n_nom.strip():
            st.error("Le nom est obligatoire.")
        elif n_nom.strip() in noms:
            st.error("Ce nom existe déjà.")
        else:
            creer_chantier(n_nom.strip(), n_adr.strip())
            st.rerun()

with st.sidebar.expander("🗑️ Supprimer ce chantier"):
    st.warning("Action définitive : tâches et rapports seront effacés.")
    confirme = st.checkbox("Je confirme la suppression")
    if st.button("Supprimer") and confirme:
        run("DELETE FROM taches WHERE chantier_id = ?", (cid,))
        run("DELETE FROM rapports WHERE chantier_id = ?", (cid,))
        run("DELETE FROM chantiers WHERE id = ?", (cid,))
        st.rerun()

st.title(f"Gestion de chantier — {choix}")

# Version de l'éditeur : permet de le réinitialiser après un enregistrement
ver_key = f"ver_{cid}"
st.session_state.setdefault(ver_key, 0)

tab_taches, tab_gantt, tab_budget, tab_rapports = st.tabs(
    ["📋 Tâches", "📅 Planning (Gantt)", "💰 Budget & indicateurs", "📝 Rapports journaliers"]
)

# --- Onglet Tâches ---
with tab_taches:
    st.subheader("Tableau des tâches")
    st.caption("Ajoutez, modifiez ou supprimez des lignes directement (comme dans un tableur), "
               "puis cliquez sur « Enregistrer ».")
    base = charger_taches(cid)
    edite = st.data_editor(
        base,
        num_rows="dynamic",
        key=f"editor_{cid}_{st.session_state[ver_key]}",
        column_config={
            "Tâche": st.column_config.TextColumn("Tâche", required=True),
            "Début": st.column_config.DateColumn("Début", format="DD/MM/YYYY", required=True,
                                                 default=date.today()),
            "Durée (j)": st.column_config.NumberColumn("Durée (j)", min_value=1, step=1, default=1),
            "Avancement (%)": st.column_config.NumberColumn("Avancement (%)", min_value=0, max_value=100,
                                                            step=1, default=0),
            "Budget (€)": st.column_config.NumberColumn("Budget (€)", min_value=0, step=500, default=0,
                                                        format="%d"),
            "Dépensé (€)": st.column_config.NumberColumn("Dépensé (€)", min_value=0, step=500, default=0,
                                                         format="%d"),
            "Responsable": st.column_config.TextColumn("Responsable"),
        },
    )

    propre, erreurs = nettoyer(edite)
    for e in erreurs:
        st.warning(e)

    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("💾 Enregistrer", type="primary"):
        sauver_taches(cid, propre)
        st.session_state[ver_key] += 1
        st.success("Tâches enregistrées.")
        st.rerun()
    c2.download_button(
        "⬇️ Export CSV",
        propre.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"taches_{choix}.csv",
        mime="text/csv",
    )

# Calculs communs (basés sur la saisie courante)
if propre.empty:
    for t in (tab_gantt, tab_budget):
        with t:
            st.info("Ajoutez au moins une tâche dans l'onglet « Tâches ».")
else:
    calc, ind = calculer(propre)

    # --- Onglet Gantt ---
    with tab_gantt:
        st.subheader("Diagramme de Gantt")
        k1, k2, k3 = st.columns(3)
        k1.metric("Début du chantier", ind["debut"].strftime("%d/%m/%Y"))
        k2.metric("Fin prévue", ind["fin"].strftime("%d/%m/%Y"))
        k3.metric("Durée totale", f"{(ind['fin'] - ind['debut']).days} jours")
        st.plotly_chart(figure_gantt(calc))
        st.caption("Couleur : rouge = peu avancé, vert = terminé. Ligne pointillée = aujourd'hui.")

    # --- Onglet Budget ---
    with tab_budget:
        st.subheader("Synthèse financière")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Budget total", euros(ind["budget_total"]))
        m2.metric("Dépensé", euros(ind["depense"]))
        m3.metric("Écart (budget - dépensé)", euros(ind["ecart"]))
        m4.metric("Avancement global (pondéré)", f"{ind['avancement']:.1f} %")
        st.progress(min(max(ind["avancement"] / 100, 0.0), 1.0))

        depass = calc[calc["Dépassement"]]
        if depass.empty:
            st.success("Aucun dépassement de budget par tâche.")
        else:
            st.error(f"⚠️ {len(depass)} tâche(s) en dépassement de budget :")
            for _, r in depass.iterrows():
                st.write(f"- **{r['Tâche']}** : dépassement de {euros(-r['Écart (€)'])} "
                         f"(budget {euros(r['Budget (€)'])}, dépensé {euros(r['Dépensé (€)'])})")

        st.subheader("Valeur acquise")
        v1, v2, v3, v4 = st.columns(4)
        v1.metric("IPC (coût)", f"{ind['ipc']:.2f}" if ind["ipc"] is not None else "n/a",
                  help="VA / CR. Inférieur à 1 : dépassement de coût.")
        v2.metric("IPD (délai)", f"{ind['ipd']:.2f}" if ind["ipd"] is not None else "n/a",
                  help="VA / VP. Inférieur à 1 : retard.")
        v3.metric("EAT (estimation à terminaison)", euros(ind["eat"]) if ind["eat"] else "n/a",
                  help="Budget total / IPC")
        v4.metric("VA / VP / CR", f"{ind['va']/1000:.0f} / {ind['vp']/1000:.0f} / {ind['cr']/1000:.0f} k€")
        if ind["ipc"] is not None and ind["ipc"] < 1:
            st.warning("IPC < 1 : le coût de réalisation dépasse la valeur produite.")
        if ind["ipd"] is not None and ind["ipd"] < 1:
            st.warning("IPD < 1 : le chantier accuse un retard par rapport au planning.")

        st.subheader("Courbe en S")
        st.plotly_chart(figure_courbe_s(calc, ind))

        st.subheader("Détail par tâche")
        detail = calc[["Tâche", "Budget (€)", "Dépensé (€)", "Écart (€)", "Avancement (%)"]]
        st.dataframe(detail, hide_index=True)

# --- Onglet Rapports journaliers ---
with tab_rapports:
    st.subheader("Nouveau rapport journalier")
    with st.form("form_rapport", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        r_date = f1.date_input("Date", value=date.today(), format="DD/MM/YYYY")
        r_meteo = f2.selectbox("Météo", METEOS)
        r_eff = f3.number_input("Effectif présent", min_value=0, step=1, value=0)
        r_obs = st.text_area("Observations (avancement, incidents, livraisons, sécurité...)")
        if st.form_submit_button("Enregistrer le rapport", type="primary"):
            run(
                "INSERT INTO rapports (chantier_id, date, meteo, effectif, observations) VALUES (?,?,?,?,?)",
                (cid, r_date.isoformat(), r_meteo, int(r_eff), r_obs.strip()),
            )
            st.success("Rapport enregistré.")
            st.rerun()

    st.subheader("Historique")
    rap = charger_rapports(cid)
    if rap.empty:
        st.info("Aucun rapport pour ce chantier.")
    else:
        aff = rap.drop(columns="id").copy()
        aff["Date"] = pd.to_datetime(aff["Date"]).dt.strftime("%d/%m/%Y")
        st.dataframe(aff, hide_index=True)
        d1, d2 = st.columns([1, 3])
        d1.download_button(
            "⬇️ Export CSV",
            aff.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"rapports_{choix}.csv",
            mime="text/csv",
        )
        with st.expander("Supprimer un rapport"):
            options = {
                f"{pd.to_datetime(r['Date']).strftime('%d/%m/%Y')} — {r['Météo']} (n°{r['id']})": r["id"]
                for _, r in rap.iterrows()
            }
            sel = st.selectbox("Rapport à supprimer", list(options.keys()))
            if st.button("Supprimer ce rapport"):
                run("DELETE FROM rapports WHERE id = ?", (int(options[sel]),))
                st.rerun()
