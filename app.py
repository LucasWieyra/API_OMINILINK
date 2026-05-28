# -*- coding: utf-8 -*-
"""
WSTT Dashboard - Streamlit v2.0
Interface web para controle e monitoramento da coleta WSTT (Omnilink) -> Supabase
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- constants ---
ROOT          = Path(__file__).resolve().parent
COLLECTOR     = ROOT / "wstt_to_supabase.py"
LOGO_PATH     = ROOT / "static" / "cargoblue.png"
OMNI_PATH     = ROOT / "static" / "omnilink.png"
ICON_PATH     = ROOT / "static" / "icon.png"

SUPABASE_URL  = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY") or ""
DASH_USER     = (os.getenv("DASHBOARD_USER") or "Admin").strip()
DASH_PASSWORD = os.getenv("DASHBOARD_PASSWORD") or ""
INTERVAL_MIN  = int(os.getenv("WSTT_INTERVAL_MIN", "60"))

# --- Supabase helpers ---
def _req(endpoint: str, timeout: int = 20):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"erro": "SUPABASE_URL / SUPABASE_SERVICE_KEY nao configurados"}
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"erro": str(e)}


def fetch_executions(limit: int = 20) -> list:
    result = _req(f"wstt_execucoes?select=*&order=iniciado_em.desc&limit={limit}", 10)
    if isinstance(result, dict) and "erro" in result:
        return [result]
    return result if isinstance(result, list) else []


def fetch_kpis(days: int = 30) -> dict:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"sem_config": True}
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        veh_r = _req("wstt_veiculos?select=placa", 10)
        total_veic = len(veh_r) if isinstance(veh_r, list) else 0
        vv = _req(
            f"wstt_viagens_telemetria?select=distancia_total_percorrida,consumo_total_litros,placa"
            f"&data_inicio_viagem=gte.{since}", 20
        )
        total_viagens = 0
        total_km      = 0.0
        total_litros  = 0.0
        if isinstance(vv, list):
            total_viagens = len(vv)
            for r in vv:
                total_km     += float(r.get("distancia_total_percorrida") or 0)
                total_litros += float(r.get("consumo_total_litros") or 0)
        ev_url = (
            f"{SUPABASE_URL}/rest/v1/wstt_eventos_tracker_telemetria"
            f"?data_hora=gte.{since}&select=id"
        )
        ev_hdr = {
            "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
            "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0",
        }
        try:
            ev_resp = requests.get(ev_url, headers=ev_hdr, timeout=10)
            cr = ev_resp.headers.get("Content-Range", "")
            ev_count = int(cr.split("/")[-1]) if "/" in cr else 0
        except Exception:
            ev_count = 0
        return {
            "total_veiculos":  total_veic,
            "total_viagens":   total_viagens,
            "total_km":        round(total_km, 1),
            "total_litros":    round(total_litros, 1),
            "eventos_periodo": ev_count,
            "periodo_dias":    days,
        }
    except Exception as e:
        return {"erro": str(e)}


def fetch_km_by_day(days: int = 30) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = _req(
        f"wstt_viagens_telemetria?select=data_inicio_viagem,distancia_total_percorrida,placa"
        f"&data_inicio_viagem=gte.{since}&order=data_inicio_viagem.asc&limit=5000", 30
    )
    if not isinstance(rows, list):
        return []
    bd: dict = {}
    for r in rows:
        raw = r.get("data_inicio_viagem", "")
        if not raw:
            continue
        d = str(raw)[:10]
        if d not in bd:
            bd[d] = {"km": 0.0, "viagens": 0, "veiculos": set()}
        bd[d]["km"]      += float(r.get("distancia_total_percorrida") or 0)
        bd[d]["viagens"] += 1
        if r.get("placa"):
            bd[d]["veiculos"].add(r["placa"])
    return [
        {"data": d, "km": round(v["km"], 1), "viagens": v["viagens"],
         "veiculos": len(v["veiculos"])}
        for d, v in sorted(bd.items())
    ]


def fetch_recent_trips(limit: int = 50) -> list:
    rows = _req(
        f"wstt_viagens_telemetria?select=placa,data_inicio_viagem,data_fim_viagem,"
        f"distancia_total_percorrida,consumo_total_litros,velocidade_media_considerada"
        f"&order=data_inicio_viagem.desc&limit={limit}", 20
    )
    return rows if isinstance(rows, list) else []


def fetch_top_vehicles(days: int = 30, limit: int = 10) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = _req(
        f"wstt_viagens_telemetria?select=placa,distancia_total_percorrida,consumo_total_litros"
        f"&data_inicio_viagem=gte.{since}&limit=5000", 30
    )
    if not isinstance(rows, list):
        return []
    agg: dict = {}
    for r in rows:
        p = r.get("placa") or "?"
        if p not in agg:
            agg[p] = {"placa": p, "km": 0.0, "litros": 0.0, "viagens": 0}
        agg[p]["km"]      += float(r.get("distancia_total_percorrida") or 0)
        agg[p]["litros"]  += float(r.get("consumo_total_litros") or 0)
        agg[p]["viagens"] += 1
    return sorted(agg.values(), key=lambda x: x["km"], reverse=True)[:limit]


def fetch_table_counts() -> dict:
    tables = [
        "wstt_veiculos", "wstt_dados_historico_telemetria",
        "wstt_viagens_telemetria", "wstt_viagens_telemetria_eletrico",
        "wstt_eventos_tracker_telemetria", "wstt_eventos_tracker_telemetria2",
        "wstt_execucoes",
    ]
    counts = {}
    for t in tables:
        try:
            url = f"{SUPABASE_URL}/rest/v1/{t}?select=id"
            hdr = {
                "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0",
            }
            r = requests.get(url, headers=hdr, timeout=8)
            cr = r.headers.get("Content-Range", "")
            counts[t] = int(cr.split("/")[-1]) if "/" in cr else "?"
        except Exception:
            counts[t] = "?"
    return counts


# --- collector subprocess ---
_collector_lock = threading.Lock()
_log_deque: deque = deque(maxlen=500)


def _is_running() -> bool:
    proc = st.session_state.get("collector_proc")
    if proc is None:
        return False
    return proc.poll() is None


def start_collector() -> None:
    with _collector_lock:
        if _is_running():
            return
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"]       = "1"
        try:
            proc = subprocess.Popen(
                [sys.executable, str(COLLECTOR)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                bufsize=1,
            )
            st.session_state["collector_proc"]     = proc
            st.session_state["collector_started"]  = datetime.now(timezone.utc).isoformat(timespec="seconds")
            st.session_state["collector_status"]   = "running"
            _log_deque.clear()
            _log_deque.append(f"[{_ts()}] Coletor iniciado (PID {proc.pid})")

            def _drain():
                for line in proc.stdout:
                    _log_deque.append(f"[{_ts()}] {line.rstrip()}")
                rc = proc.wait()
                st.session_state["collector_status"]   = "ok" if rc == 0 else "erro"
                st.session_state["collector_finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                _log_deque.append(f"[{_ts()}] Coletor encerrado com codigo {rc}")

            threading.Thread(target=_drain, daemon=True).start()
        except Exception as e:
            _log_deque.append(f"[{_ts()}] ERRO ao iniciar coletor: {e}")


def stop_collector() -> None:
    proc = st.session_state.get("collector_proc")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        st.session_state["collector_status"] = "parado"
        _log_deque.append(f"[{_ts()}] Coletor interrompido pelo usuario")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _fmt_ts(ts):
    if not ts:
        return "-"
    try:
        return datetime.fromisoformat(ts).strftime("%d/%m  %H:%M:%S")
    except Exception:
        return str(ts)[:16]


# =================================================================
#  PAGE CONFIG
# =================================================================
st.set_page_config(
    page_title="WSTT Dashboard",
    page_icon="truck",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =================================================================
#  CSS - PROFESSIONAL LIGHT THEME
# =================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ---- Reset & base ---- */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', sans-serif;
}
#MainMenu, header, footer { visibility: hidden; }

/* ---- Page background ---- */
.stApp {
    background: #F0F4F8;
}

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0F2544 0%, #163a6b 100%) !important;
    border-right: none !important;
    box-shadow: 4px 0 16px rgba(0,0,0,0.15);
}
[data-testid="stSidebar"] * {
    color: #E2EAF4 !important;
}
[data-testid="stSidebar"] .stRadio label {
    color: #B8CCEA !important;
    font-size: 14px !important;
    padding: 6px 4px !important;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.12) !important;
}

/* ---- Main content area ---- */
[data-testid="stMainBlockContainer"],
.main .block-container {
    background: transparent;
    padding: 1.5rem 2.5rem 2rem 2.5rem !important;
    max-width: 1400px;
}

/* ---- Page title / section headers ---- */
.page-title {
    font-size: 22px;
    font-weight: 700;
    color: #0F2544;
    margin-bottom: 4px;
    letter-spacing: -0.3px;
}
.page-subtitle {
    font-size: 13px;
    color: #64748B;
    margin-bottom: 24px;
}
.section-label {
    font-size: 11px;
    font-weight: 700;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    margin: 20px 0 10px 0;
    padding-bottom: 6px;
    border-bottom: 2px solid #E2E8F0;
}

/* ---- KPI Cards ---- */
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 20px 22px !important;
    box-shadow: 0 1px 4px rgba(15,37,68,0.07);
    transition: box-shadow 0.2s;
}
[data-testid="stMetric"]:hover {
    box-shadow: 0 4px 16px rgba(15,37,68,0.12);
}
[data-testid="stMetricLabel"] {
    color: #64748B !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
}
[data-testid="stMetricValue"] {
    color: #0F2544 !important;
    font-size: 28px !important;
    font-weight: 700 !important;
    letter-spacing: -0.5px !important;
}

/* ---- Buttons ---- */
.stButton > button {
    background: #1D4ED8 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 8px 20px !important;
    letter-spacing: 0.2px !important;
    transition: all 0.15s !important;
    box-shadow: 0 1px 4px rgba(29,78,216,0.25) !important;
}
.stButton > button:hover {
    background: #1E40AF !important;
    box-shadow: 0 4px 12px rgba(29,78,216,0.35) !important;
    transform: translateY(-1px) !important;
}
.stButton > button:active {
    transform: translateY(0) !important;
}

/* ---- Selectbox / number input ---- */
[data-testid="stSelectbox"] > div > div,
[data-testid="stNumberInput"] > div > div > input {
    background: #FFFFFF !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 8px !important;
    color: #1E293B !important;
    font-size: 13px !important;
}

/* ---- Dataframe ---- */
[data-testid="stDataFrame"] {
    border: 1px solid #E2E8F0 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
    box-shadow: 0 1px 4px rgba(15,37,68,0.05) !important;
}

/* ---- White card wrapper ---- */
.card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
    box-shadow: 0 1px 4px rgba(15,37,68,0.06);
}

/* ---- Status pills ---- */
.pill {
    display: inline-block;
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.3px;
}
.pill-ok    { background: #D1FAE5; color: #065F46; }
.pill-erro  { background: #FEE2E2; color: #991B1B; }
.pill-run   { background: #DBEAFE; color: #1E40AF; }
.pill-parado{ background: #F1F5F9; color: #64748B; }

/* ---- Log box ---- */
.log-box {
    background: #0F172A;
    border: 1px solid #1E3A5F;
    border-radius: 10px;
    padding: 16px 18px;
    font-family: 'Cascadia Code','Fira Code','Consolas',monospace;
    font-size: 12px;
    color: #94A3B8;
    height: 240px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    line-height: 1.7;
}

/* ---- Stat row ---- */
.stat-row {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
}
.stat-box {
    flex: 1;
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 14px 18px;
    box-shadow: 0 1px 3px rgba(15,37,68,0.05);
}
.stat-label {
    font-size: 10px;
    color: #94A3B8;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 4px;
}
.stat-value {
    font-size: 14px;
    color: #0F2544;
    font-weight: 700;
}

/* ---- Divider ---- */
hr { border: none; border-top: 1px solid #E2E8F0; margin: 20px 0; }

/* ---- Info / warning boxes ---- */
.info-box {
    background: #EFF6FF;
    border-left: 4px solid #3B82F6;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    font-size: 13px;
    color: #1E40AF;
    margin-bottom: 12px;
}
.warn-box {
    background: #FFFBEB;
    border-left: 4px solid #F59E0B;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    font-size: 13px;
    color: #92400E;
}

/* ---- Login card ---- */
.login-wrap {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 80vh;
}
.login-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 16px;
    padding: 40px 48px;
    width: 420px;
    box-shadow: 0 8px 32px rgba(15,37,68,0.12);
}
</style>
""", unsafe_allow_html=True)


# --- session state defaults ---
for key, default in [
    ("authenticated", False),
    ("collector_proc", None),
    ("collector_status", "parado"),
    ("collector_started", None),
    ("collector_finished", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# =================================================================
#  LOGIN
# =================================================================
def login_page():
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)

        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=200)
        else:
            st.markdown("### WSTT Dashboard")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<p style="font-size:18px;font-weight:700;color:#0F2544;margin-bottom:4px;">Bem-vindo de volta</p>', unsafe_allow_html=True)
        st.markdown('<p style="font-size:13px;color:#64748B;margin-bottom:20px;">Entre com suas credenciais para acessar o painel</p>', unsafe_allow_html=True)

        with st.form("login_form"):
            user = st.text_input("Usuario", placeholder="Admin")
            pwd  = st.text_input("Senha",   placeholder="Senha", type="password")
            submitted = st.form_submit_button("Entrar", use_container_width=True)

        if submitted:
            if user.strip() == DASH_USER and pwd == DASH_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Usuario ou senha incorretos.")

        st.markdown("<br>", unsafe_allow_html=True)
        if OMNI_PATH.exists():
            c1, c2 = st.columns([1, 2])
            with c1:
                st.image(str(OMNI_PATH), width=90)


# =================================================================
#  SIDEBAR
# =================================================================
def sidebar() -> str:
    with st.sidebar:
        st.markdown("<br>", unsafe_allow_html=True)
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=155)
        else:
            st.markdown("### WSTT Dashboard")

        st.markdown("---")

        nav = st.radio(
            "Menu",
            ["Painel", "Analytics", "Configuracoes", "Exportar SQL"],
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Collector status
        status  = st.session_state.get("collector_status", "parado")
        running = _is_running()
        st.markdown('<p style="font-size:10px;font-weight:700;color:#7A9CC4;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">Status do Coletor</p>', unsafe_allow_html=True)
        if running:
            st.markdown('<span class="pill pill-run">Em execucao</span>', unsafe_allow_html=True)
        elif status == "ok":
            st.markdown('<span class="pill pill-ok">Concluido com sucesso</span>', unsafe_allow_html=True)
        elif status == "erro":
            st.markdown('<span class="pill pill-erro">Encerrado com erro</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="pill pill-parado">Aguardando</span>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if OMNI_PATH.exists():
            st.image(str(OMNI_PATH), width=90)

        st.markdown("---")
        st.markdown(f'<p style="font-size:11px;color:#7A9CC4;">Logado como <strong style="color:#B8CCEA;">{DASH_USER}</strong></p>', unsafe_allow_html=True)
        st.markdown('<p style="font-size:11px;color:#7A9CC4;">WSTT Dashboard v2.0</p>', unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Sair", use_container_width=True):
            st.session_state["authenticated"] = False
            st.rerun()

    return nav


# =================================================================
#  PAINEL
# =================================================================
def page_painel():
    st.markdown('<p class="page-title">Painel de Controle</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Gerencie a coleta de dados WSTT e acompanhe o historico de execucoes.</p>', unsafe_allow_html=True)

    # --- Collector control card ---
    with st.container():
        running = _is_running()
        c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
        with c1:
            if st.button("Iniciar Coletor", disabled=running, use_container_width=True):
                start_collector(); st.rerun()
        with c2:
            if st.button("Parar", disabled=not running, use_container_width=True):
                stop_collector(); st.rerun()
        with c3:
            if st.button("Rodar Agora", use_container_width=True):
                start_collector(); st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # --- Stats row ---
    status = st.session_state.get("collector_status", "parado")
    started  = _fmt_ts(st.session_state.get("collector_started"))
    finished = _fmt_ts(st.session_state.get("collector_finished"))
    status_label = {"ok": "Concluido com sucesso", "erro": "Encerrado com erro",
                    "running": "Em execucao...", "parado": "Aguardando"}.get(status, status)
    status_color = {"ok": "#065F46", "erro": "#991B1B",
                    "running": "#1E40AF", "parado": "#64748B"}.get(status, "#64748B")

    st.markdown(f"""
    <div class="stat-row">
      <div class="stat-box">
        <div class="stat-label">Ultima Execucao</div>
        <div class="stat-value">{started}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Concluida em</div>
        <div class="stat-value">{finished}</div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Status</div>
        <div class="stat-value" style="color:{status_color};">{status_label}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # --- Logs ---
    st.markdown('<p class="section-label">Logs ao Vivo</p>', unsafe_allow_html=True)
    logs = list(_log_deque)
    log_text = "\n".join(logs[-80:]) if logs else "Nenhum log ainda. Inicie o coletor para ver os registros aqui."
    st.markdown(f'<div class="log-box">{log_text}</div>', unsafe_allow_html=True)
    if running:
        st.caption("Coletor em execucao — recarregue a pagina para atualizar os logs")

    # --- History ---
    st.markdown('<p class="section-label">Historico de Execucoes</p>', unsafe_allow_html=True)
    col_ref, _ = st.columns([1, 6])
    with col_ref:
        if st.button("Atualizar"):
            st.rerun()

    rows = fetch_executions(20)
    if rows and "erro" in rows[0]:
        st.markdown(f'<div class="warn-box">Erro ao carregar historico: {rows[0]["erro"]}</div>', unsafe_allow_html=True)
    elif rows:
        table_data = []
        for r in rows:
            c = r.get("contagens") or {}
            table_data.append({
                "Inicio":    _fmt_ts(r.get("iniciado_em")),
                "Fim":       _fmt_ts(r.get("finalizado_em")),
                "Status":    r.get("status", "-"),
                "Veiculos":  c.get("wstt_veiculos", "-"),
                "Historico": c.get("wstt_dados_historico_telemetria", "-"),
                "Viagens":   c.get("wstt_viagens_telemetria", "-"),
                "Eletrico":  c.get("wstt_viagens_telemetria_eletrico", "-"),
                "Eventos":   c.get("wstt_eventos_tracker_telemetria", "-"),
            })
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="info-box">Nenhuma execucao registrada ainda. Inicie o coletor para comecar.</div>', unsafe_allow_html=True)


# =================================================================
#  ANALYTICS
# =================================================================
def page_analytics():
    st.markdown('<p class="page-title">Analytics</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">KPIs e metricas da frota em tempo real a partir dos dados coletados.</p>', unsafe_allow_html=True)

    col_days, _ = st.columns([1, 5])
    with col_days:
        days = st.selectbox("Periodo de analise", [7, 15, 30, 60, 90], index=2,
                            format_func=lambda d: f"Ultimos {d} dias")

    with st.spinner("Carregando dados..."):
        kpis = fetch_kpis(days)

    if "sem_config" in kpis:
        st.markdown('<div class="warn-box">Configure SUPABASE_URL e SUPABASE_SERVICE_KEY nas variaveis de ambiente ou no arquivo .env</div>', unsafe_allow_html=True)
        return
    if "erro" in kpis:
        st.error(f"Erro ao carregar KPIs: {kpis['erro']}")
        return

    # KPI row
    st.markdown('<p class="section-label">Resumo do Periodo</p>', unsafe_allow_html=True)
    k1, k2, k3, k4, k5 = st.columns(5)
    kpi_data = [
        (k1, "Veiculos na Frota",  f"{kpis.get('total_veiculos', 0):,}",  "#3B82F6"),
        (k2, "Viagens Realizadas", f"{kpis.get('total_viagens', 0):,}",   "#10B981"),
        (k3, "KM Percorridos",     f"{kpis.get('total_km', 0):,.0f} km",  "#6366F1"),
        (k4, "Consumo Total",      f"{kpis.get('total_litros', 0):,.0f} L","#F59E0B"),
        (k5, "Eventos de Risco",   f"{kpis.get('eventos_periodo', 0):,}", "#EF4444"),
    ]
    for col, label, value, color in kpi_data:
        with col:
            st.markdown(f"""
            <div style="background:#fff;border:1px solid #E2E8F0;border-top:3px solid {color};
                        border-radius:10px;padding:18px 20px;
                        box-shadow:0 1px 4px rgba(15,37,68,0.06);">
              <p style="font-size:10px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                        letter-spacing:0.8px;margin:0 0 8px 0;">{label}</p>
              <p style="font-size:26px;font-weight:700;color:#0F2544;
                        letter-spacing:-0.5px;margin:0;">{value}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # KM chart
    st.markdown('<p class="section-label">KM Percorrido por Dia</p>', unsafe_allow_html=True)
    with st.spinner("Carregando grafico..."):
        km_data = fetch_km_by_day(days)

    if km_data:
        df_km = pd.DataFrame(km_data)
        df_km["data"] = pd.to_datetime(df_km["data"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_km["data"], y=df_km["km"],
            mode="lines+markers",
            line=dict(color="#1D4ED8", width=2.5),
            marker=dict(size=5, color="#1D4ED8", line=dict(width=1.5, color="white")),
            fill="tozeroy",
            fillcolor="rgba(29,78,216,0.08)",
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>KM: %{y:,.1f}<extra></extra>",
        ))
        fig.update_layout(
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FAFBFD",
            font=dict(family="Inter, sans-serif", color="#334155", size=12),
            xaxis=dict(
                gridcolor="#E2E8F0", showgrid=True, tickformat="%d/%m",
                tickfont=dict(color="#94A3B8", size=11),
                linecolor="#E2E8F0", zeroline=False,
            ),
            yaxis=dict(
                gridcolor="#E2E8F0", showgrid=True, title="KM",
                tickfont=dict(color="#94A3B8", size=11),
                linecolor="#E2E8F0", zeroline=False,
            ),
            margin=dict(l=10, r=10, t=16, b=10),
            height=280,
            showlegend=False,
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        total_km_p = df_km["km"].sum()
        total_v_p  = df_km["viagens"].sum()
        st.caption(f"Total acumulado: {total_km_p:,.0f} km  |  {len(df_km)} dias  |  {total_v_p:,} viagens")
    else:
        st.markdown('<div class="info-box">Sem dados de viagens para o periodo selecionado.</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown('<p class="section-label">Viagens por Dia</p>', unsafe_allow_html=True)
        if km_data:
            df_v = pd.DataFrame(km_data)
            df_v["data"] = pd.to_datetime(df_v["data"])
            fig2 = go.Figure(go.Bar(
                x=df_v["data"], y=df_v["viagens"],
                marker_color="#6366F1",
                marker_line_color="rgba(0,0,0,0)",
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Viagens: %{y}<extra></extra>",
            ))
            fig2.update_layout(
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FAFBFD",
                font=dict(family="Inter, sans-serif", color="#334155", size=12),
                xaxis=dict(gridcolor="#E2E8F0", tickformat="%d/%m",
                           tickfont=dict(color="#94A3B8", size=11), linecolor="#E2E8F0"),
                yaxis=dict(gridcolor="#E2E8F0", title="Viagens",
                           tickfont=dict(color="#94A3B8", size=11), linecolor="#E2E8F0"),
                margin=dict(l=10, r=10, t=16, b=10),
                height=260, showlegend=False,
                bargap=0.25,
            )
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div class="info-box">Sem dados.</div>', unsafe_allow_html=True)

    with col_right:
        st.markdown('<p class="section-label">Top 10 Veiculos (KM)</p>', unsafe_allow_html=True)
        with st.spinner("Carregando..."):
            top_v = fetch_top_vehicles(days)
        if top_v:
            df_top = pd.DataFrame(top_v)
            df_top.columns = ["Placa", "KM", "Litros", "Viagens"]
            df_top["KM"]     = df_top["KM"].apply(lambda x: f"{x:,.1f}")
            df_top["Litros"] = df_top["Litros"].apply(lambda x: f"{x:,.1f}")
            st.dataframe(df_top, use_container_width=True, hide_index=True, height=260)
        else:
            st.markdown('<div class="info-box">Sem dados.</div>', unsafe_allow_html=True)

    # Trips table
    st.markdown('<p class="section-label">Viagens Recentes</p>', unsafe_allow_html=True)
    with st.spinner("Carregando viagens..."):
        trips = fetch_recent_trips(50)

    if trips:
        df_t = pd.DataFrame(trips).rename(columns={
            "placa":                        "Placa",
            "data_inicio_viagem":           "Inicio",
            "data_fim_viagem":              "Fim",
            "distancia_total_percorrida":   "KM",
            "consumo_total_litros":         "Litros",
            "velocidade_media_considerada": "Vel. Media",
        })
        for col in ["Inicio", "Fim"]:
            if col in df_t.columns:
                df_t[col] = pd.to_datetime(df_t[col], errors="coerce").dt.strftime("%d/%m  %H:%M")
        for col in ["KM", "Litros", "Vel. Media"]:
            if col in df_t.columns:
                df_t[col] = pd.to_numeric(df_t[col], errors="coerce").round(1)
        st.dataframe(df_t, use_container_width=True, hide_index=True, height=380)
    else:
        st.markdown('<div class="info-box">Sem viagens registradas para o periodo selecionado.</div>', unsafe_allow_html=True)


# =================================================================
#  CONFIGURACOES
# =================================================================
def page_config():
    st.markdown('<p class="page-title">Configuracoes</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Informacoes de conexao e ferramentas de manutencao.</p>', unsafe_allow_html=True)

    st.markdown('<p class="section-label">Conexao atual</p>', unsafe_allow_html=True)
    url_display = SUPABASE_URL if SUPABASE_URL else "Nao configurado"
    key_display = ("*" * 10 + SUPABASE_KEY[-6:]) if len(SUPABASE_KEY) > 6 else "Nao configurado"

    st.markdown(f"""
    <div class="card">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr>
          <td style="color:#94A3B8;font-weight:600;padding:6px 0;width:180px;">Supabase URL</td>
          <td style="color:#0F2544;font-weight:500;font-family:monospace;">{url_display}</td>
        </tr>
        <tr>
          <td style="color:#94A3B8;font-weight:600;padding:6px 0;">Service Key</td>
          <td style="color:#0F2544;font-weight:500;font-family:monospace;">{key_display}</td>
        </tr>
        <tr>
          <td style="color:#94A3B8;font-weight:600;padding:6px 0;">Usuario Dashboard</td>
          <td style="color:#0F2544;font-weight:500;">{DASH_USER}</td>
        </tr>
        <tr>
          <td style="color:#94A3B8;font-weight:600;padding:6px 0;">Intervalo Padrao</td>
          <td style="color:#0F2544;font-weight:500;">{INTERVAL_MIN} minutos</td>
        </tr>
      </table>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<p class="section-label">Contagem de Registros</p>', unsafe_allow_html=True)
    if st.button("Consultar Supabase"):
        with st.spinner("Consultando..."):
            counts = fetch_table_counts()
        rows = [{"Tabela": k, "Registros": v} for k, v in counts.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown('<p class="section-label">Execucao via Linha de Comando</p>', unsafe_allow_html=True)
    st.markdown("""
    <div class="card" style="background:#F8FAFC;">
    """, unsafe_allow_html=True)
    st.code("""# Coleta manual (uma vez)
python wstt_to_supabase.py

# Modo agendado sem GUI (servidor/VM)
python scheduler.py

# Periodo especifico
python wstt_to_supabase.py --ano 2026 --mes 5
python wstt_to_supabase.py --dias 7
""", language="bash")
    st.markdown("</div>", unsafe_allow_html=True)


# =================================================================
#  EXPORTAR SQL
# =================================================================
def page_export():
    st.markdown('<p class="page-title">Exportar SQL</p>', unsafe_allow_html=True)
    st.markdown('<p class="page-subtitle">Baixe o schema das tabelas ou exporte dados para CSV / SQL.</p>', unsafe_allow_html=True)

    schema_path = ROOT / "supabase_schema.sql"
    if not schema_path.exists():
        st.error("Arquivo supabase_schema.sql nao encontrado.")
        return

    schema_sql = schema_path.read_text(encoding="utf-8")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<p class="section-label">Schema das Tabelas</p>', unsafe_allow_html=True)
        st.markdown("""
        <div class="card">
          <p style="font-size:13px;color:#475569;margin-bottom:16px;">
            DDL completo de todas as tabelas WSTT com constraints UNIQUE necessarias
            para o UPSERT funcionar corretamente no Supabase.
          </p>
        </div>
        """, unsafe_allow_html=True)
        st.download_button(
            "Baixar Schema SQL",
            data=schema_sql,
            file_name=f"wstt_schema_{datetime.now().strftime('%Y%m%d')}.sql",
            mime="text/plain",
            use_container_width=True,
        )

    with col2:
        st.markdown('<p class="section-label">Exportar Dados como CSV</p>', unsafe_allow_html=True)
        tables = [
            "wstt_veiculos", "wstt_viagens_telemetria",
            "wstt_eventos_tracker_telemetria", "wstt_execucoes",
        ]
        sel_table    = st.selectbox("Tabela", tables, label_visibility="collapsed")
        export_limit = st.number_input("Max. registros", min_value=100, max_value=50000,
                                       value=1000, step=100)
        if st.button("Gerar CSV", use_container_width=True):
            with st.spinner("Baixando dados do Supabase..."):
                data = _req(f"{sel_table}?select=*&limit={export_limit}&order=id.desc")
            if isinstance(data, list) and data:
                csv = pd.DataFrame(data).to_csv(index=False)
                st.download_button(
                    f"Baixar {sel_table}.csv",
                    data=csv,
                    file_name=f"{sel_table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                st.success(f"{len(data):,} registros exportados.")
            elif isinstance(data, dict) and "erro" in data:
                st.error(f"Erro: {data['erro']}")
            else:
                st.warning("Nenhum dado encontrado.")

    st.markdown('<p class="section-label">Visualizar Schema</p>', unsafe_allow_html=True)
    with st.expander("Expandir schema SQL completo"):
        st.code(schema_sql, language="sql")


# =================================================================
#  MAIN
# =================================================================
def main():
    if not st.session_state["authenticated"]:
        login_page()
        return
    nav = sidebar()
    if nav == "Painel":
        page_painel()
    elif nav == "Analytics":
        page_analytics()
    elif nav == "Configuracoes":
        page_config()
    elif nav == "Exportar SQL":
        page_export()


if __name__ == "__main__":
    main()
