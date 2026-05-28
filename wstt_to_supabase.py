"""
wstt_to_supabase.py
===================
Coletor de dados WSTT (Omnilink) → Supabase Postgres.

Cobre os endpoints das páginas 545-557 do Manual de Integração WSTT v1.191:
  31.12  ListarDadosHistoricoTelemetria          → wstt_dados_historico_telemetria
  31.13  ListarHistoricoViagemTelemetria         → wstt_viagens_telemetria
  31.14  ListarHistoricoViagemTelemetriaEletrico → wstt_viagens_telemetria_eletrico
  31.15  ListarEventosTrackerTelemetria          → wstt_eventos_tracker_telemetria
  31.16  ListarEventosTrackerTelemetria2         → wstt_eventos_tracker_telemetria2

Frota:
  ListarVeiculoTodos → wstt_veiculos  (lista de placas usada em 31.13 e 31.14)

─────────────────────────────────────────────────────────────────
REGRAS IMPORTANTES DO WSTT (ver manual pág. 545-557)
─────────────────────────────────────────────────────────────────
• 31.12, 31.15 e 31.16 NÃO aceitam janelas de tempo maiores que 1 hora.
  O coletor fatia automaticamente qualquer período em janelas de 1h.
• 31.13 e 31.14 são consultados por PLACA e aceitam períodos maiores.
  Formato de data: YYYY-MM-DD HH:MM:SS.
• 31.12, 31.15 e 31.16 usam o formato dd/MM/yyyy hh:mm:ss.
• 31.13/31.14 retornam campos com JSON aninhado dentro do XML
  (ex: <velocidade>{"maior_120":0,...}</velocidade>).
  Esses campos são gravados como JSONB no Supabase.

─────────────────────────────────────────────────────────────────
ANTI-DUPLICATAS (UPSERT)
─────────────────────────────────────────────────────────────────
Cada tabela tem uma chave natural única definida em STEP_TABLE.
O UPSERT usa o header "Prefer: resolution=merge-duplicates" do PostgREST,
que sobrescreve a linha existente pela mais nova sempre que houver conflito.

ATENÇÃO: Para o UPSERT funcionar o Supabase PRECISA ter constraints UNIQUE
nas colunas de conflito. Execute o supabase_schema.sql no editor SQL do
Supabase para garantir que essas constraints existam.

─────────────────────────────────────────────────────────────────
USO
─────────────────────────────────────────────────────────────────
  python scripts/python/wstt_to_supabase.py                # mês anterior + atual
  python scripts/python/wstt_to_supabase.py --ano 2026 --mes 4
  python scripts/python/wstt_to_supabase.py --apenas viagens_telemetria
  python scripts/python/wstt_to_supabase.py --skip-eventos-tracker

Variáveis de ambiente obrigatórias:
  WSTT_USUARIO, WSTT_SENHA, SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import json
import os
import re
import signal
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterator

# Garante que o stdout use UTF-8 mesmo em terminais Windows (que usam cp1252 por padrão)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests

# Carrega o arquivo .env automaticamente se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES GERAIS
# ═══════════════════════════════════════════════════════════════

# Credenciais WSTT (lidas do .env)
WSTT_USUARIO = os.getenv("WSTT_USUARIO", "")
WSTT_SENHA   = os.getenv("WSTT_SENHA", "")
WSTT_URL     = "https://wstt.omnilink.com.br/iasws/iasws.asmx"

# A API WSTT exige a senha em MD5 (não texto puro)
WSTT_SENHA_MD5 = hashlib.md5(WSTT_SENHA.encode()).hexdigest() if WSTT_SENHA else ""

# Credenciais Supabase (lidas do .env)
SUPABASE_URL  = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1" if SUPABASE_URL else ""

# Controle de taxa de chamadas: espera mínima de 1.2s entre requests WSTT
LAST_CALL    = 0.0
RATE_LIMIT_S = 1.2

# Tamanho máximo de cada lote enviado ao Supabase por request
BATCH_SIZE = 500


def log(msg: str) -> None:
    """Imprime uma mensagem no console com flush imediato (visível em tempo real)."""
    print(msg, flush=True)


# ═══════════════════════════════════════════════════════════════
# CAMADA SOAP (comunicação com a API WSTT)
# ═══════════════════════════════════════════════════════════════

def soap_call(action: str, body_inner: str, timeout: int = 60) -> str:
    """
    Faz uma chamada SOAP para o webservice WSTT.

    Parâmetros:
      action      – nome do método SOAP (ex: "ListarVeiculoTodos")
      body_inner  – XML com os parâmetros internos do método
      timeout     – segundos até timeout do request (padrão: 60s)

    Retorna a resposta SOAP como string XML.
    Respeita o rate limit de RATE_LIMIT_S segundos entre chamadas.
    """
    global LAST_CALL
    # Espera o tempo necessário para não ultrapassar o rate limit da API
    delta = time.time() - LAST_CALL
    if delta < RATE_LIMIT_S:
        time.sleep(RATE_LIMIT_S - delta)
    LAST_CALL = time.time()

    ns = "http://microsoft.com/webservices/"
    # Monta o envelope SOAP completo com autenticação no header
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
        ' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"'
        f' xmlns:tns="{ns}">'
        '<soap:Header>'
        f'<tns:Auth><tns:Usuario>{WSTT_USUARIO}</tns:Usuario>'
        f'<tns:Senha>{WSTT_SENHA_MD5}</tns:Senha></tns:Auth>'
        '</soap:Header>'
        f'<soap:Body><tns:{action}>{body_inner}</tns:{action}></soap:Body>'
        '</soap:Envelope>'
    )
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{ns}{action}"',
    }
    resp = requests.post(WSTT_URL, data=envelope.encode("utf-8"),
                         headers=headers, timeout=timeout)
    return resp.text


def auth_xml() -> str:
    """Retorna o bloco XML de autenticação (usado dentro do body de cada endpoint)."""
    return f"<Usuario>{WSTT_USUARIO}</Usuario><Senha>{WSTT_SENHA_MD5}</Senha>"


def parse_return_xml(soap_resp: str) -> ET.Element | None:
    """
    Extrai o elemento <return> de uma resposta SOAP e faz o parse do XML interno.

    O WSTT retorna um XML escapado (HTML entities) dentro do elemento <return>.
    Essa função desescapa e faz o parse, retornando o elemento raiz ou None.
    """
    try:
        root = ET.fromstring(soap_resp)
    except ET.ParseError:
        return None

    for elem in root.iter():
        if elem.tag.endswith("return"):
            raw = elem.text or ""
            if not raw.strip():
                return None
            # Tenta parsear o XML interno; o WSTT às vezes não escapa corretamente
            try:
                return ET.fromstring(html.unescape(raw))
            except ET.ParseError:
                try:
                    return ET.fromstring(raw)
                except ET.ParseError:
                    return None
    return None


def soap_fault(soap_resp: str) -> str | None:
    """
    Verifica se a resposta SOAP contém um erro (SOAP Fault).
    Retorna o texto do erro ou None se não houver fault.
    """
    if "Fault" not in soap_resp:
        return None
    try:
        root = ET.fromstring(soap_resp)
    except ET.ParseError:
        return None
    for elem in root.iter():
        if elem.tag.endswith("faultstring"):
            return (elem.text or "").strip() or None
    return None


def _local_tag(elem: ET.Element) -> str:
    """Remove o namespace de uma tag XML e retorna só o nome local.
    Ex: '{http://...}Veiculo' → 'Veiculo'
    """
    return elem.tag.split("}", 1)[-1]


def _flat_text(elem: ET.Element) -> dict[str, str]:
    """
    Achata um elemento XML em um dicionário {tag: texto}.
    Mantém apenas a PRIMEIRA ocorrência de cada tag.
    Usado para registros simples que não têm JSON aninhado.
    """
    out: dict[str, str] = {}
    for c in elem.iter():
        if c is elem:
            continue
        tag = _local_tag(c)
        if tag in out:
            continue  # mantém a primeira ocorrência
        text = (c.text or "").strip()
        if text:
            out[tag] = text
    return out


def _pick(d: dict[str, Any], *names: str) -> Any:
    """
    Retorna o PRIMEIRO valor não vazio entre as variantes de nome fornecidas.
    A busca é case-insensitive como fallback.

    Útil porque o WSTT retorna alguns campos ora com PascalCase ora camelCase.
    Ex: _pick(d, "Placa", "placa", "PLACA")
    """
    lower = {k.lower(): v for k, v in d.items()}
    for n in names:
        v = d.get(n)
        if v not in (None, ""):
            return v
        v = lower.get(n.lower())
        if v not in (None, ""):
            return v
    return ""


# ═══════════════════════════════════════════════════════════════
# PARSE DE JSON ANINHADO DENTRO DE XML (endpoints 31.13 e 31.14)
# ═══════════════════════════════════════════════════════════════

def parse_nested_json(s: Any) -> Any:
    """
    Faz o parse de campos que o WSTT retorna como JSON dentro de XML.

    Exemplo de campo na resposta XML:
      <velocidade>{"maior_120": 0, "entre_0_e_20": 12, ...}</velocidade>

    Retorna o objeto Python decodificado, ou None se não for JSON válido.
    Tenta algumas correções comuns (aspas simples, vírgulas pendentes).
    """
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s  # já está decodificado
    raw = str(s).strip()
    if not raw or raw in ("{}", "[]", "null"):
        return None

    # Tentativa 1: parse direto
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Tentativa 2: corrige aspas simples → duplas
    try:
        return json.loads(raw.replace("'", '"'))
    except json.JSONDecodeError:
        pass

    # Tentativa 3: corrige "chave": , (valor ausente) → "chave": null,
    cleaned = re.sub(r'("[^"]+"\s*:)\s*([,}\]])', r'\1 null\2', raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None  # desiste, grava None no banco


# ═══════════════════════════════════════════════════════════════
# COERÇÃO DE TIPOS (string XML → tipos Python/Postgres corretos)
# ═══════════════════════════════════════════════════════════════

# Formatos de data/hora aceitos (o WSTT usa formatos inconsistentes)
_TS_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
)


def to_ts(s: Any) -> str | None:
    """Converte string de data/hora para formato ISO 8601 (YYYY-MM-DD HH:MM:SS)."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Remove fuso horário e microssegundos para normalizar
    base = s.replace("T", " ").split(".", 1)[0].split("+", 1)[0].split("Z", 1)[0]
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(base, fmt).isoformat(sep=" ")
        except ValueError:
            continue
    return None  # formato não reconhecido


def to_date(s: Any) -> str | None:
    """Converte string de data para formato ISO (YYYY-MM-DD)."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    base = s.replace("T", " ").split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(base, fmt).date().isoformat()
        except ValueError:
            continue
    # Fallback: extrai a parte de data de um timestamp completo
    ts = to_ts(s)
    return ts.split(" ", 1)[0] if ts else None


def to_num(s: Any) -> float | None:
    """
    Converte string numérica para float.
    Lida com formatos brasileiros (vírgula decimal, ponto milhar):
      "1.234,56" → 1234.56
      "1234,56"  → 1234.56
      "1234.56"  → 1234.56
    """
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(" ", "")
    if not s:
        return None
    # Detecta formato brasileiro: ponto como milhar, vírgula como decimal
    if s.count(",") == 1 and s.count(".") >= 1 and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def to_int(s: Any) -> int | None:
    """Converte string numérica para inteiro."""
    n = to_num(s)
    if n is None:
        return None
    try:
        return int(n)
    except (ValueError, OverflowError):
        return None


# Valores aceitos como True/False para campos booleanos do WSTT
_BOOL_TRUE  = {"1", "true", "t", "sim", "s", "y", "yes", "ligada", "ligado", "on", "ativa", "ativo"}
_BOOL_FALSE = {"0", "false", "f", "nao", "não", "n", "no", "desligada", "desligado", "off", "inativa", "inativo"}


def to_bool(s: Any) -> bool | None:
    """Converte string para booleano, entendendo variantes em português."""
    if s is None:
        return None
    if isinstance(s, bool):
        return s
    v = str(s).strip().lower()
    if not v:
        return None
    if v in _BOOL_TRUE:
        return True
    if v in _BOOL_FALSE:
        return False
    return None


# Constantes para identificar o tipo de cada coluna na coerção
TS = "ts"    # timestamp
DT = "date"  # só data
NU = "num"   # número real (float)
IN = "int"   # inteiro
BO = "bool"  # booleano
JS = "json"  # JSONB (objeto/array)

# ───────────────────────────────────────────────────────────────
# Mapeamento de colunas por tabela → tipo esperado no Postgres.
# Colunas não listadas são gravadas como texto (string limpa).
# ───────────────────────────────────────────────────────────────
COLUMN_TYPES: dict[str, dict[str, str]] = {
    "wstt_dados_historico_telemetria": {
        "data_hora": TS, "data_sys": TS,
        "altitude": NU, "autonomia": NU, "azimute": NU,
        "ciclo_carga": NU, "consumo_combustivel": NU,
        "corrente_bateria_propulsao": NU, "distancia_total": NU,
        "ignicao": BO, "latitude": NU, "longitude": NU,
        "media_consumo_combustivel": NU, "nivel_adblue": NU,
        "nivel_combustivel_litros": NU, "nivel_combustivel_percentual": NU,
        "pedal_acelerador_maxima": NU, "pedal_acelerador_media": NU,
        "qnt_horas_ativo": NU, "qnt_horas_motor": NU,
        "qnt_horas_ocioso": NU, "qnt_horas_total": NU,
        "qnt_kickdown": IN,
        "rpm": NU, "rpm_max": NU, "rpm_media": NU,
        "temperatura_bateria": NU, "temperatura_liquido_arrefecimento": NU,
        "tensao_bateria_propulsao": NU,
        "velocidade_can": NU, "velocidade_gps": NU,
        "velocidade_maxima": NU, "velocidade_media": NU,
    },
    "wstt_viagens_telemetria": {
        "data_inicio_viagem": TS, "data_fim_viagem": TS,
        "distancia_total_percorrida": NU,
        "horimetro_inicial": NU, "horimetro_final": NU,
        "odometro_inicial": NU, "odometro_final": NU,
        "latitude_inicial": NU, "longitude_inicial": NU,
        "latitude_final": NU, "longitude_final": NU,
        "media_consumo_viagem": NU,
        "nivel_adblue_final": NU,
        "nivel_combustivel_inicial": NU, "nivel_combustivel_final": NU,
        "quantidade_aceleracao_brusca": IN, "quantidade_freada_brusca": IN,
        "quantidade_evento_embreagem": IN, "quantidade_evento_freio_estacionario": IN,
        "quantidade_evento_freio_motor": IN, "quantidade_evento_pedal_freio": IN,
        "quantidade_evento_piloto_automatico": IN, "quantidade_evento_pto": IN,
        "quantidade_excesso_velocidade": IN, "quantidade_excesso_velocidade_chuva": IN,
        "quantidade_horas_ativo": NU, "quantidade_horas_ocioso": NU,
        "quantidade_horas_total": NU, "quantidade_kickdowns": IN,
        "tempo_evento_embreagem": NU, "tempo_evento_freio_estacionario": NU,
        "tempo_evento_freio_motor": NU, "tempo_evento_pedal_freio": NU,
        "tempo_evento_piloto_automatico": NU, "tempo_evento_pto": NU,
        "tempo_excesso_velocidade": NU, "tempo_excesso_velocidade_chuva": NU,
        "tempo_kickdowns": NU,
        "total_litros_ativo": NU, "total_litros_consumidos_inicial": NU,
        "total_litros_consumidos_final": NU, "total_litros_ocioso": NU,
        "acelerador": JS, "acelerador_velocidade": JS,
        "tempo_rpm_pedal_acelerador": JS, "velocidade": JS,
    },
    "wstt_viagens_telemetria_eletrico": {
        "data_inicio_viagem": TS, "data_fim_viagem": TS,
        "distancia_total_percorrida": NU, "distancia_percorrida_modo_eco": NU,
        "distancia_percorrida_modo_normal": NU,
        "horimetro_inicial": NU, "horimetro_final": NU,
        "odometro_inicial": NU, "odometro_final": NU,
        "latitude_inicial": NU, "longitude_inicial": NU,
        "latitude_final": NU, "longitude_final": NU,
        "autonomia": NU, "energia_recuperada": NU, "media_consumo_viagem": NU,
        "corrente_bateria_propulsao": NU, "tensao_bateria_propulsao": NU,
        "temperatura_bateria": NU,
        "nivel_adblue_inicial": NU, "nivel_adblue_final": NU,
        "nivel_energia_inicial": NU, "nivel_energia_final": NU,
        "nota_evento_aceleracao": NU, "nota_evento_exc_vel": NU,
        "nota_evento_exc_vel_chuva": NU, "nota_evento_freada_brusca": NU,
        "nota_final_do_motorista": NU, "nota_indice_economia": NU,
        "nota_indice_seguranca": NU,
        "quantidade_aceleracao_brusca": IN, "quantidade_freada_brusca": IN,
        "quantidade_ciclos_carga": IN,
        "quantidade_evento_embreagem": IN, "quantidade_evento_freio_estacionario": IN,
        "quantidade_evento_freio_motor": IN, "quantidade_evento_pedal_freio": IN,
        "quantidade_evento_piloto_automatico": IN, "quantidade_evento_pto": IN,
        "quantidade_excesso_velocidade": IN, "quantidade_excesso_velocidade_chuva": IN,
        "quantidade_horas_ativo": NU, "quantidade_horas_ocioso": NU,
        "quantidade_horas_total": NU, "quantidade_kickdowns": IN,
        "tempo_evento_embreagem": NU, "tempo_evento_freio_estacionario": NU,
        "tempo_evento_freio_motor": NU, "tempo_evento_pedal_freio": NU,
        "tempo_evento_piloto_automatico": NU, "tempo_evento_pto": NU,
        "tempo_excesso_velocidade": NU, "tempo_excesso_velocidade_chuva": NU,
        "tempo_kickdowns": NU,
        "total_kwh_ativo": NU, "total_kwh_consumidos_inicial": NU,
        "total_kwh_consumidos_final": NU, "total_kwh_ocioso": NU,
        "velocidade": JS,
        "evento_excesso_velocidade": JS,
        "evento_excesso_velocidade_chuva": JS,
        "evento_excesso_rpm": JS,
        "evento_ignicao_desligada_veiculo_movimento": JS,
        "evento_superaquecimento_liquido_arrefecimento": JS,
        "evento_excesso_rotacao_veiculo_parado": JS,
    },
    "wstt_eventos_tracker_telemetria": {
        "data_evento": TS, "data_cadastro": TS,
        "latitude_inicial": NU, "longitude_inicial": NU,
        "latitude_final": NU, "longitude_final": NU,
        "duracao_evento": NU, "distancia_percorrida": NU,
        "aceleracao_configurada": NU, "aceleracao_maxima": NU,
        "aceleracao_lateral_configurada": NU, "aceleracao_lateral_maxima": NU,
        "desaceleracao_configurada": NU, "desaceleracao_maxima": NU,
        "nivel_combustivel_anterior": NU, "nivel_combustivel_posterior": NU,
        "percentual_queda_combustivel": NU, "percentual_subida_combustivel": NU,
        "rpm_limite_configurado": NU, "rpm_maximo": NU,
        "tempo_configurado": NU,
        "velocidade_limite_configurado": NU, "velocidade_maxima": NU,
        "velocidade": NU,
        "temperatura_limite_configurado": NU, "valor_maximo_temperatura": NU,
        "porcentagem_pedal_acelerador": NU,
    },
}

# O endpoint 31.16 tem os mesmos campos do 31.15 + campo descricao_evento
COLUMN_TYPES["wstt_eventos_tracker_telemetria2"] = COLUMN_TYPES["wstt_eventos_tracker_telemetria"]

# Mapeia as constantes de tipo para as funções de conversão correspondentes
_COERCERS: dict[str, Callable[[Any], Any]] = {
    TS: to_ts,
    DT: to_date,
    NU: to_num,
    IN: to_int,
    BO: to_bool,
    JS: parse_nested_json,
}


def coerce_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """
    Aplica a coerção de tipos em todas as colunas de uma linha.
    Colunas sem tipo definido → limpa espaços e converte vazio para None.
    """
    types = COLUMN_TYPES.get(table, {})
    out: dict[str, Any] = {}
    for k, v in row.items():
        t = types.get(k)
        if t is not None:
            out[k] = _COERCERS[t](v)
        elif isinstance(v, str):
            # Colunas de texto: remove espaços e converte string vazia para None
            v2 = v.strip()
            out[k] = v2 if v2 else None
        else:
            out[k] = v
    return out


# ═══════════════════════════════════════════════════════════════
# CAMADA SUPABASE (REST / PostgREST)
# ═══════════════════════════════════════════════════════════════

def supabase_headers(prefer: str = "resolution=merge-duplicates,return=minimal") -> dict[str, str]:
    """
    Monta os headers padrão para chamadas ao Supabase REST (PostgREST).

    O header 'Prefer: resolution=merge-duplicates' instrui o PostgREST
    a sobrescrever linhas existentes em conflito (UPSERT real).

    ATENÇÃO: Para funcionar, a tabela precisa ter uma constraint UNIQUE
    nas colunas passadas como on_conflict. Sem ela, o PostgREST insere
    duplicatas em vez de fazer merge.
    """
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        prefer,
    }


def supabase_upsert(table: str, rows: list[dict[str, Any]], on_conflict: str) -> int:
    """
    Envia linhas para o Supabase via UPSERT em lotes de BATCH_SIZE.

    Comportamento em conflito: sobrescreve a linha antiga pela nova
    (definido pelo header 'resolution=merge-duplicates').

    Parâmetros:
      table       – nome da tabela no Supabase
      rows        – lista de dicionários (uma linha = um dict)
      on_conflict – coluna(s) que formam a chave natural única,
                    separadas por vírgula (ex: "placa,data_hora")

    Retorna o total de linhas enviadas com sucesso.

    NOTA ANTI-DUPLICATA EXTRA:
      Antes de enviar, remove duplicatas LOCAIS (mesmo lote) pela chave
      natural, mantendo apenas a última ocorrência de cada chave.
      Isso evita erro do PostgREST que rejeita lotes com ON CONFLICT
      quando a mesma chave aparece mais de uma vez no mesmo batch.
    """
    if not rows:
        return 0
    if not SUPABASE_REST or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY não configurados no .env")

    # Aplica coerção de tipos em todas as linhas
    rows = [coerce_row(table, r) for r in rows]

    # ── Deduplica localmente pelo on_conflict ────────────────────
    # Linhas com a mesma chave no mesmo lote quebram o UPSERT do PostgREST.
    # Mantemos apenas a última linha para cada combinação de chave.
    keys = [k.strip() for k in on_conflict.split(",") if k.strip()]
    seen: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        sig = tuple(r.get(k) for k in keys)
        seen[sig] = r  # sobrescreve → a última linha vence
    rows = list(seen.values())
    # ────────────────────────────────────────────────────────────

    # URL do PostgREST com o parâmetro on_conflict indicando as colunas de conflito
    url = f"{SUPABASE_REST}/{table}?on_conflict={on_conflict}"
    headers = supabase_headers()
    enviados = 0

    # Envia em lotes para não ultrapassar o limite de payload do Supabase
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i: i + BATCH_SIZE]
        resp = requests.post(url, headers=headers,
                             data=json.dumps(batch, default=str), timeout=120)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Supabase UPSERT em '{table}' falhou "
                f"(HTTP {resp.status_code}): {resp.text[:500]}"
            )
        enviados += len(batch)
        log(f"      ↑ {table}: {enviados}/{len(rows)} linhas")
    return enviados


def supabase_insert_returning(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """
    Insere UMA linha e retorna a linha completa gravada (com o id gerado).
    Usado exclusivamente para registrar o início de uma execução em wstt_execucoes.
    """
    url = f"{SUPABASE_REST}/{table}"
    resp = requests.post(
        url,
        headers=supabase_headers(prefer="return=representation"),
        data=json.dumps([row]),
        timeout=60,
    )
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Supabase INSERT em '{table}' falhou "
            f"(HTTP {resp.status_code}): {resp.text[:500]}"
        )
    data = resp.json()
    return data[0] if isinstance(data, list) and data else {}


# Cache de colunas por tabela (evita chamar o PostgREST várias vezes)
_TABLE_COLUMNS_CACHE: dict[str, set[str]] = {}
_SCHEMA_WARNED: set[str] = set()


def _table_columns(table: str) -> set[str]:
    """
    Descobre as colunas de uma tabela consultando o schema OpenAPI do PostgREST.
    O resultado é cacheado para não fazer múltiplas chamadas.
    Retorna set() vazio se não conseguir (o caller faz fallback e envia tudo).
    """
    if table in _TABLE_COLUMNS_CACHE:
        return _TABLE_COLUMNS_CACHE[table]
    cols: set[str] = set()
    try:
        resp = requests.get(f"{SUPABASE_REST}/", headers=supabase_headers(), timeout=15)
        if resp.status_code < 300:
            spec = resp.json()
            # PostgREST 9/10 usa Swagger 2.0 ("definitions")
            defs = (spec.get("definitions") or {}).get(table) or {}
            # PostgREST 11+ usa OpenAPI 3.0 ("components.schemas")
            if not defs:
                defs = (((spec.get("components") or {}).get("schemas")) or {}).get(table) or {}
            props = defs.get("properties") or {}
            cols = set(props.keys())
    except Exception:
        pass  # sem introspecção de schema → tenta enviar tudo
    _TABLE_COLUMNS_CACHE[table] = cols
    return cols


def _filter_to_table(table: str, values: dict[str, Any]) -> dict[str, Any]:
    """
    Remove campos que não existem na tabela (schema desatualizado).
    Avisa UMA vez por tabela quando encontra colunas ausentes no banco.
    Isso evita erros HTTP 400 do PostgREST por colunas inexistentes.
    """
    cols = _table_columns(table)
    if not cols:
        return values  # sem introspecção → tenta enviar tudo

    filtered = {k: v for k, v in values.items() if k in cols}
    missing = sorted(k for k in values if k not in cols)
    if missing and table not in _SCHEMA_WARNED:
        _SCHEMA_WARNED.add(table)
        log(
            f"  ℹ️  Colunas ausentes em '{table}': {missing}.\n"
            f"     Execute o supabase_schema.sql no editor SQL do Supabase "
            f"para que esses campos sejam gravados corretamente."
        )
    return filtered


def supabase_patch(table: str, match: dict[str, Any], values: dict[str, Any]) -> None:
    """
    Atualiza campos de uma linha existente via PATCH (UPDATE parcial).
    Usado para atualizar o status de uma execução em wstt_execucoes.

    Parâmetros:
      table  – nome da tabela
      match  – dict com filtros (ex: {"id": 42}) → vira WHERE id = 42
      values – campos a atualizar
    """
    if not match:
        return
    # Remove colunas que não existem na tabela para evitar erro 400
    values = _filter_to_table(table, values)
    if not values:
        return

    # Monta a query string com os filtros (ex: ?id=eq.42)
    qs = "&".join(f"{k}=eq.{v}" for k, v in match.items())
    url = f"{SUPABASE_REST}/{table}?{qs}"
    resp = requests.patch(
        url,
        headers=supabase_headers(prefer="return=minimal"),
        data=json.dumps(values),
        timeout=60,
    )
    if resp.status_code >= 300:
        if resp.status_code == 400 and "PGRST204" in resp.text:
            raise RuntimeError(
                f"Schema desatualizado em '{table}'. "
                f"Execute o supabase_schema.sql no editor SQL do Supabase."
            )
        raise RuntimeError(
            f"Supabase PATCH em '{table}' falhou "
            f"(HTTP {resp.status_code}): {resp.text[:500]}"
        )


# ═══════════════════════════════════════════════════════════════
# JANELAS DE 1 HORA (exigência dos endpoints 31.12, 31.15, 31.16)
# ═══════════════════════════════════════════════════════════════

def hourly_windows(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    """
    Gera janelas [ini, fim] de exatamente 1 hora cobrindo o período [start, end].

    O WSTT rejeita chamadas com janelas maiores que 1 hora nos endpoints
    31.12, 31.15 e 31.16. Essa função fatia o período automaticamente.

    Cada janela tem:
      - início: hora cheia (minuto e segundo = 0)
      - fim: início + 59min59s (ou o fim do período, o que vier primeiro)

    Exemplo: 14/05 08:30 → 14/05 11:00 gera:
      [08:00-08:59], [09:00-09:59], [10:00-10:59], [11:00-11:00]
    """
    # Nunca consultar além do momento atual (dados futuros não existem)
    now = datetime.now(timezone.utc) if start.tzinfo else datetime.now()
    if end > now:
        end = now

    # Começa na hora cheia do início para não perder dados da hora parcial
    cur = start.replace(minute=0, second=0, microsecond=0)
    while cur < end:
        nxt = cur + timedelta(hours=1)
        win_fim = min(nxt - timedelta(seconds=1), end)
        yield cur, win_fim
        cur = nxt


def fmt_br(d: datetime) -> str:
    """Formata datetime no padrão brasileiro usado pelo WSTT: dd/MM/yyyy HH:mm:ss"""
    return d.strftime("%d/%m/%Y %H:%M:%S")


def fmt_iso(d: datetime) -> str:
    """Formata datetime no padrão ISO usado pelos endpoints 31.13/31.14: YYYY-MM-DD HH:MM:SS"""
    return d.strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════════
# FROTA: ListarVeiculoTodos
# ═══════════════════════════════════════════════════════════════

def buscar_placas() -> list[dict[str, str]]:
    """
    Busca todas as placas da frota via ListarVeiculoTodos.

    Retorna lista de dicts com {"placa": "...", "frota": "..."}.
    As placas são necessárias para os endpoints 31.13 e 31.14.
    Duplicatas de placa são removidas (mantém a última ocorrência).
    """
    log("🔍 Buscando frota (placas)...")
    raw = soap_call("ListarVeiculoTodos", auth_xml())

    # Verifica se houve erro SOAP antes de processar
    fault = soap_fault(raw)
    if fault:
        raise RuntimeError(f"WSTT ListarVeiculoTodos erro: {fault}")

    inner = parse_return_xml(raw)
    if inner is None:
        log("  ⚠️  Sem retorno na listagem de veículos")
        return []

    veiculos = []
    for v in inner.iter():
        # Procura elementos cujo tag começa com "veiculo" (case-insensitive)
        if not _local_tag(v).lower().startswith("veiculo"):
            continue
        d = _flat_text(v)
        placa = _pick(d, "Placa", "PLACA")
        frota = _pick(d, "Terminal", "IdTerminal", "Frota")
        if placa:
            veiculos.append({"placa": placa, "frota": frota})

    # Remove placas duplicadas (mantém última ocorrência)
    uniq: dict[str, dict[str, str]] = {}
    for v in veiculos:
        uniq[v["placa"]] = v
    veiculos = list(uniq.values())

    log(f"  ✅ {len(veiculos)} veículos encontrados")
    return veiculos


# ═══════════════════════════════════════════════════════════════
# 31.12 — ListarDadosHistoricoTelemetria
# Telemetria em tempo real por janelas de 1h (sem filtro de placa)
# ═══════════════════════════════════════════════════════════════

def _map_dados_historico(d: dict[str, str]) -> dict[str, Any]:
    """
    Converte um dicionário flat (resultado de _flat_text) em uma linha
    para a tabela wstt_dados_historico_telemetria.

    O _pick() trata as variações de PascalCase/camelCase que o WSTT usa.
    """
    return {
        "placa":                              _pick(d, "placa", "Placa"),
        "serial":                             _pick(d, "serial", "Serial"),
        "data_hora":                          _pick(d, "dataHora", "DataHora"),
        "data_sys":                           _pick(d, "dataSys", "DataSys"),
        "id_cliente":                         _pick(d, "idCliente", "IdCliente"),
        "id_contrato":                        _pick(d, "idContrato", "IdContrato"),
        "chassis":                            _pick(d, "chassis", "Chassis"),
        "chaveiro_serial":                    _pick(d, "chaveiroSerial", "ChaveiroSerial"),
        "flags_status":                       _pick(d, "FlagsStatus", "flagsStatus"),
        "veiculo_eletrico":                   _pick(d, "veiculoEletrico", "VeiculoEletrico"),
        "versao_firmware":                    _pick(d, "versaoFirmware", "VersaoFirmware"),
        "release_firmware":                   _pick(d, "releaseFirmware", "ReleaseFirmware"),
        "revisao_firmware":                   _pick(d, "revisaoFirmware", "RevisaoFirmware"),
        "letra_firmware":                     _pick(d, "letraFirmware", "LetraFirmware"),
        "altitude":                           _pick(d, "altitude", "Altitude"),
        "autonomia":                          _pick(d, "autonomia", "Autonomia"),
        "azimute":                            _pick(d, "azimute", "Azimute"),
        "carregador":                         _pick(d, "carregador", "Carregador"),
        "ciclo_carga":                        _pick(d, "cicloCarga", "CicloCarga"),
        "consumo_combustivel":                _pick(d, "consumoCombustivel", "ConsumoCombustivel"),
        "corrente_bateria_propulsao":         _pick(d, "correnteBateriaPropulsao"),
        "distancia_total":                    _pick(d, "distanciaTotal", "DistanciaTotal"),
        "ignicao":                            _pick(d, "ignicao", "Ignicao"),
        "latitude":                           _pick(d, "latitude", "Latitude"),
        "longitude":                          _pick(d, "longitude", "Longitude"),
        "media_consumo_combustivel":          _pick(d, "mediaConsumoCombustivel"),
        "nivel_adblue":                       _pick(d, "nivelAdBlue", "nivelAdblue"),
        "nivel_combustivel_litros":           _pick(d, "nivelCombustivelLitros"),
        "nivel_combustivel_percentual":       _pick(d, "nivelCombustivelPercentual"),
        "pedal_acelerador_maxima":            _pick(d, "pedalAceleradorMaxima"),
        "pedal_acelerador_media":             _pick(d, "pedalAceleradorMedia"),
        "qnt_horas_ativo":                    _pick(d, "qntHorasAtivo"),
        "qnt_horas_motor":                    _pick(d, "qntHorasMotor"),
        "qnt_horas_ocioso":                   _pick(d, "qntHorasOcioso"),
        "qnt_horas_total":                    _pick(d, "qntHorastotal", "qntHorasTotal"),
        "qnt_kickdown":                       _pick(d, "qntKickdown"),
        "rpm":                                _pick(d, "rpm", "RPM"),
        "rpm_max":                            _pick(d, "rpmMax", "RpmMax"),
        "rpm_media":                          _pick(d, "rpmMedia", "RpmMedia"),
        "temperatura_bateria":                _pick(d, "temperaturaBateria"),
        "temperatura_liquido_arrefecimento":  _pick(d, "temperaturaLiquidoArrefecimento"),
        "tensao_bateria_propulsao":           _pick(d, "tensaoBateriaPropulsao"),
        "velocidade_can":                     _pick(d, "velocidadeCan", "VelocidadeCan"),
        "velocidade_gps":                     _pick(d, "velocidadeGps", "VelocidadeGps"),
        "velocidade_maxima":                  _pick(d, "velocidadeMaxima", "VelocidadeMaxima"),
        "velocidade_media":                   _pick(d, "velocidadeMedia", "VelocidadeMedia"),
    }


def coletar_dados_historico_telemetria(ini: datetime, fim: datetime) -> list[dict]:
    """
    Coleta dados do endpoint 31.12 — ListarDadosHistoricoTelemetria.

    Quebra o período em janelas de 1 hora (limite da API).
    Chave única: (placa, data_hora, serial) → garante sem duplicata no banco.
    """
    rows: list[dict] = []
    janelas = list(hourly_windows(ini, fim))
    log(f"  📅 Janelas de 1h: {len(janelas)}")

    for n, (h_ini, h_fim) in enumerate(janelas, 1):
        body = (
            f"{auth_xml()}"
            f"<dataInicio>{fmt_br(h_ini)}</dataInicio>"
            f"<dataFim>{fmt_br(h_fim)}</dataFim>"
        )
        try:
            raw = soap_call("ListarDadosHistoricoTelemetria", body, timeout=120)
            fault = soap_fault(raw)
            if fault:
                log(f"    ⚠ {h_ini:%d/%m %H:%M}: {fault}")
                continue

            inner = parse_return_xml(raw)
            if inner is None:
                continue  # janela sem dados é normal (veículos parados)

            cnt = 0
            for rec in inner.iter():
                # Procura especificamente o elemento <HistoricoTelemetria>
                if _local_tag(rec) != "HistoricoTelemetria":
                    continue
                d = _flat_text(rec)
                if not d:
                    continue
                rows.append(_map_dados_historico(d))
                cnt += 1

            if cnt:
                log(f"    [{n}/{len(janelas)}] {h_ini:%d/%m %H:%M}: +{cnt} registros")

        except Exception as e:
            log(f"    ❌ Erro na janela {h_ini:%d/%m %H:%M}: {e}")

    log(f"  ✅ Dados histórico telemetria: {len(rows)} total")
    return rows


# ═══════════════════════════════════════════════════════════════
# 31.13 — ListarHistoricoViagemTelemetria (veículos a combustão)
# Consulta por placa; aceita períodos maiores que 1h
# ═══════════════════════════════════════════════════════════════

# Campos simples (texto/número) da resposta de viagem
_VT_FIELDS = (
    "id", "id_cliente", "id_contrato", "driver_id", "placa", "serial",
    "sequencia_jornada",
    "data_inicio_viagem", "data_fim_viagem",
    "duracao_da_viagem", "distancia_total_percorrida",
    "horimetro_inicial", "horimetro_final",
    "odometro_inicial", "odometro_final",
    "latitude_inicial", "longitude_inicial",
    "latitude_final", "longitude_final",
    "media_consumo_viagem",
    "nivel_adblue_final",
    "nivel_combustivel_inicial", "nivel_combustivel_final",
    "quantidade_aceleracao_brusca", "quantidade_freada_brusca",
    "quantidade_evento_embreagem", "quantidade_evento_freio_estacionario",
    "quantidade_evento_freio_motor", "quantidade_evento_pedal_freio",
    "quantidade_evento_piloto_automatico", "quantidade_evento_pto",
    "quantidade_excesso_velocidade", "quantidade_excesso_velocidade_chuva",
    "quantidade_horas_ativo", "quantidade_horas_ocioso",
    "quantidade_horas_total", "quantidade_kickdowns",
    "tempo_evento_embreagem", "tempo_evento_freio_estacionario",
    "tempo_evento_freio_motor", "tempo_evento_pedal_freio",
    "tempo_evento_piloto_automatico", "tempo_evento_pto",
    "tempo_excesso_velocidade", "tempo_excesso_velocidade_chuva",
    "tempo_kickdowns",
    "total_litros_ativo", "total_litros_consumidos_inicial",
    "total_litros_consumidos_final", "total_litros_ocioso",
)

# Campos que contêm JSON aninhado dentro do XML (gravados como JSONB)
_VT_JSON_FIELDS = ("acelerador", "acelerador_velocidade",
                   "tempo_RPM_pedal_acelerador", "velocidade")


def _map_viagem_telemetria(elem: ET.Element, placa_default: str) -> dict[str, Any]:
    """
    Extrai uma viagem do XML separando campos simples de campos JSON.

    Não usa _flat_text() porque alguns campos são objetos JSON —
    precisamos separar antes de fazer qualquer parse.
    """
    flat: dict[str, str] = {}    # campos de texto/número
    nested: dict[str, str] = {}  # campos com JSON aninhado

    for c in elem:
        tag = _local_tag(c)
        text = (c.text or "").strip()
        if tag in _VT_JSON_FIELDS:
            nested[tag] = text
        else:
            if tag not in flat and text:
                flat[tag] = text

    # Monta a linha com os campos simples
    row: dict[str, Any] = {f: _pick(flat, f) for f in _VT_FIELDS}

    # Renomeia "id" para "viagem_id" para clareza no banco
    row["viagem_id"] = row.pop("id", "") or ""

    # Usa a placa do XML; se não vier, usa a placa do request como fallback
    row["placa"] = row.get("placa") or placa_default

    # Adiciona os campos JSONB
    row["acelerador"]                 = nested.get("acelerador", "")
    row["acelerador_velocidade"]      = nested.get("acelerador_velocidade", "")
    row["tempo_rpm_pedal_acelerador"] = nested.get("tempo_RPM_pedal_acelerador", "")
    row["velocidade"]                 = nested.get("velocidade", "")

    return row


def coletar_viagens_telemetria(veiculos: list[dict[str, str]],
                                ini: datetime, fim: datetime) -> list[dict]:
    """
    Coleta dados do endpoint 31.13 — ListarHistoricoViagemTelemetria.

    Itera sobre cada placa da frota e coleta as viagens no período.
    Chave única: (placa, data_inicio_viagem) → previne duplicatas.
    """
    rows: list[dict] = []
    total = len(veiculos)
    di = fmt_iso(ini)
    df = fmt_iso(fim)

    for idx, v in enumerate(veiculos, 1):
        placa = v["placa"]
        log(f"  [{idx}/{total}] Viagens telemetria: {placa}")
        body = (
            f"{auth_xml()}"
            f"<Placa>{placa}</Placa>"
            f"<dataInicio>{di}</dataInicio>"
            f"<dataFim>{df}</dataFim>"
        )
        try:
            raw = soap_call("ListarHistoricoViagemTelemetria", body, timeout=180)
            fault = soap_fault(raw)
            if fault:
                log(f"    ⚠ {placa}: {fault}")
                continue

            inner = parse_return_xml(raw)
            if inner is None:
                continue  # sem viagens para essa placa no período

            cnt = 0
            for viagem in inner.iter():
                if _local_tag(viagem) != "historicoViagemTelemetria":
                    continue
                row = _map_viagem_telemetria(viagem, placa)
                # Descarta registros sem data de início (dados incompletos)
                if not row.get("data_inicio_viagem"):
                    continue
                rows.append(row)
                cnt += 1

            if cnt:
                log(f"    +{cnt} viagens")

        except Exception as e:
            log(f"    ❌ Erro em {placa}: {e}")

    log(f"  ✅ Viagens telemetria: {len(rows)} total")
    return rows


# ═══════════════════════════════════════════════════════════════
# 31.14 — ListarHistoricoViagemTelemetriaEletrico (veículos elétricos)
# Mesmo padrão do 31.13, mas com campos adicionais de energia
# ═══════════════════════════════════════════════════════════════

# Campos simples da resposta de viagem elétrica
_VTE_FIELDS = (
    "id", "id_cliente", "id_contrato", "driver_id", "placa", "serial",
    "sequencia_jornada", "flag_veiculo_eletrico", "status_carregador",
    "data_inicio_viagem", "data_fim_viagem",
    "duracao_da_viagem", "distancia_total_percorrida",
    "distancia_percorrida_modo_eco", "distancia_percorrida_modo_normal",
    "horimetro_inicial", "horimetro_final",
    "odometro_inicial", "odometro_final",
    "latitude_inicial", "longitude_inicial",
    "latitude_final", "longitude_final",
    "autonomia", "energia_recuperada", "media_consumo_viagem",
    "corrente_bateria_propulsao", "tensao_bateria_propulsao",
    "temperatura_bateria",
    "nivel_adblue_inicial", "nivel_adblue_final",
    "nivel_energia_inicial", "nivel_energia_final",
    "nota_evento_aceleracao", "nota_evento_exc_vel",
    "nota_evento_exc_vel_chuva", "nota_evento_freada_brusca",
    "nota_final_do_motorista", "nota_indice_economia", "nota_indice_seguranca",
    "quantidade_aceleracao_brusca", "quantidade_freada_brusca",
    "quantidade_ciclos_carga",
    "quantidade_evento_embreagem", "quantidade_evento_freio_estacionario",
    "quantidade_evento_freio_motor", "quantidade_evento_pedal_freio",
    "quantidade_evento_piloto_automatico", "quantidade_evento_pto",
    "quantidade_excesso_velocidade", "quantidade_excesso_velocidade_chuva",
    "quantidade_horas_ativo", "quantidade_horas_ocioso",
    "quantidade_horas_total", "quantidade_kickdowns",
    "tempo_evento_embreagem", "tempo_evento_freio_estacionario",
    "tempo_evento_freio_motor", "tempo_evento_pedal_freio",
    "tempo_evento_piloto_automatico", "tempo_evento_pto",
    "tempo_excesso_velocidade", "tempo_excesso_velocidade_chuva",
    "tempo_kickdowns",
    "total_kwh_ativo", "total_kwh_consumidos_inicial",
    "total_kwh_consumidos_final", "total_kwh_ocioso",
)

# Campos JSON da resposta elétrica (evento_* são histogramas de velocidade etc.)
_VTE_JSON_FIELDS = (
    "velocidade",
    "evento_excesso_velocidade",
    "evento_excesso_velocidade_chuva",
    "evento_excesso_rpm",
    "evento_ignicao_desligada_veiculo_movimento",
    "evento_superaquecimento_liquido_arrefecimento",
    "evento_excesso_rotacao_veiculo_parado",
)


def _map_viagem_telemetria_eletrico(elem: ET.Element, placa_default: str) -> dict[str, Any]:
    """
    Extrai uma viagem elétrica do XML (mesmo padrão do 31.13, com mais campos).
    """
    flat: dict[str, str] = {}
    nested: dict[str, str] = {}

    for c in elem:
        tag = _local_tag(c)
        text = (c.text or "").strip()
        if tag in _VTE_JSON_FIELDS:
            nested[tag] = text
        else:
            if tag not in flat and text:
                flat[tag] = text

    row: dict[str, Any] = {f: _pick(flat, f) for f in _VTE_FIELDS}
    row["viagem_id"] = row.pop("id", "") or ""
    row["placa"] = row.get("placa") or placa_default

    # Adiciona todos os campos JSON
    for jf in _VTE_JSON_FIELDS:
        row[jf] = nested.get(jf, "")

    return row


def coletar_viagens_telemetria_eletrico(veiculos: list[dict[str, str]],
                                         ini: datetime, fim: datetime) -> list[dict]:
    """
    Coleta dados do endpoint 31.14 — ListarHistoricoViagemTelemetriaEletrico.

    Nota: o WSTT retorna SOAP Fault para placas que não são elétricas.
    Por isso, faults são silenciados (continue) nesta função.
    """
    rows: list[dict] = []
    total = len(veiculos)
    di = fmt_iso(ini)
    df = fmt_iso(fim)

    for idx, v in enumerate(veiculos, 1):
        placa = v["placa"]
        log(f"  [{idx}/{total}] Viagens elétrico: {placa}")
        body = (
            f"{auth_xml()}"
            f"<Placa>{placa}</Placa>"
            f"<dataInicio>{di}</dataInicio>"
            f"<dataFim>{df}</dataFim>"
        )
        try:
            raw = soap_call("ListarHistoricoViagemTelemetriaEletrico", body, timeout=180)
            fault = soap_fault(raw)
            if fault:
                # Fault esperado: placa não é elétrica → ignora silenciosamente
                continue

            inner = parse_return_xml(raw)
            if inner is None:
                continue

            cnt = 0
            for viagem in inner.iter():
                if _local_tag(viagem) != "historicoViagemTelemetriaEletrico":
                    continue
                row = _map_viagem_telemetria_eletrico(viagem, placa)
                if not row.get("data_inicio_viagem"):
                    continue
                rows.append(row)
                cnt += 1

            if cnt:
                log(f"    +{cnt} viagens elétrico")

        except Exception as e:
            log(f"    ❌ Erro em {placa}: {e}")

    log(f"  ✅ Viagens telemetria elétrico: {len(rows)} total")
    return rows


# ═══════════════════════════════════════════════════════════════
# 31.15/31.16 — ListarEventosTrackerTelemetria(2)
# Eventos por janelas de 1h; 31.16 tem campo descricao_evento a mais
# ═══════════════════════════════════════════════════════════════

def _map_evento_tracker(d: dict[str, str], with_descricao: bool = False) -> dict[str, Any]:
    """
    Converte um dicionário flat em uma linha para wstt_eventos_tracker_telemetria.
    O campo with_descricao=True adiciona descricao_evento (exclusivo do 31.16).
    """
    row: dict[str, Any] = {
        "evento_id":                     _pick(d, "Id"),
        "cod_evento":                    _pick(d, "CodEvento"),
        "placa":                         _pick(d, "Placa"),
        "serial":                        _pick(d, "Serial"),
        "chaveiro_serial":               _pick(d, "ChaveiroSerial"),
        "data_evento":                   _pick(d, "DataEvento"),
        "data_cadastro":                 _pick(d, "DataCadastro"),
        "endereco":                      _pick(d, "Endereco"),
        "endereco_final":                _pick(d, "EnderecoFinal"),
        "latitude_inicial":              _pick(d, "LatitudeInicial"),
        "longitude_inicial":             _pick(d, "LongitudeInicial"),
        "latitude_final":                _pick(d, "LatitudeFinal"),
        "longitude_final":               _pick(d, "LongitudeFinal"),
        "id_cliente":                    _pick(d, "IdCliente"),
        "id_viagem":                     _pick(d, "IdViagem"),
        "duracao_evento":                _pick(d, "DuracaoEvento"),
        "distancia_percorrida":          _pick(d, "DistanciaPercorrida"),
        "aceleracao_configurada":        _pick(d, "AceleracaoConfigurada"),
        "aceleracao_maxima":             _pick(d, "AceleracaoMaxima"),
        "aceleracao_lateral_configurada":_pick(d, "AceleracaoLateralConfigurada"),
        "aceleracao_lateral_maxima":     _pick(d, "AceleracaoLateralMaxima"),
        "desaceleracao_configurada":     _pick(d, "DesaceleracaoConfigurada"),
        "desaceleracao_maxima":          _pick(d, "DesaceleracaoMaxima"),
        "nivel_combustivel_anterior":    _pick(d, "NivelCombustivelAnterior"),
        "nivel_combustivel_posterior":   _pick(d, "NivelCombustivelPosterior"),
        "percentual_queda_combustivel":  _pick(d, "PercentualQuedaCombustivel"),
        "percentual_subida_combustivel": _pick(d, "PercentualSubidaCombustivel"),
        "rpm_limite_configurado":        _pick(d, "RpmLimiteConfigurado"),
        "rpm_maximo":                    _pick(d, "RpmMaximo"),
        "tempo_configurado":             _pick(d, "TempoConfigurado"),
        "velocidade_limite_configurado": _pick(d, "VelocidadeLimiteConfigurado"),
        "velocidade_maxima":             _pick(d, "VelocidadeMaxima"),
        "velocidade":                    _pick(d, "Velocidade"),
        "referencia":                    _pick(d, "Referencia"),
        "status":                        _pick(d, "Status"),
        "temperatura_limite_configurado":_pick(d, "TemperaturaLimiteConfigurado"),
        "valor_maximo_temperatura":      _pick(d, "ValorMaximoTemperatura"),
        "flag_tipo_veiculo":             _pick(d, "FlagTipoVeiculo"),
        "curva_forca_g":                 _pick(d, "CurvaForcaG"),
        "id_cerca":                      _pick(d, "IdCerca"),
        "porcentagem_pedal_acelerador":  _pick(d, "PorcentagemPedalAcelerador"),
    }
    if with_descricao:
        row["descricao_evento"] = _pick(d, "DescricaoEvento")
    return row


def _coletar_eventos_tracker(action: str, ini: datetime, fim: datetime,
                              with_descricao: bool) -> list[dict]:
    """
    Coleta eventos do tracker em janelas de 1h (31.15 ou 31.16).

    Descarta eventos sem evento_id E sem data_evento, pois sem ao menos
    um desses campos não há como deduplicar no banco.
    """
    rows: list[dict] = []
    janelas = list(hourly_windows(ini, fim))
    log(f"  📅 {action} – {len(janelas)} janela(s) de 1h")

    for n, (h_ini, h_fim) in enumerate(janelas, 1):
        body = (
            f"{auth_xml()}"
            f"<DataHoraInicial>{fmt_br(h_ini)}</DataHoraInicial>"
            f"<DataHoraFinal>{fmt_br(h_fim)}</DataHoraFinal>"
        )
        try:
            raw = soap_call(action, body, timeout=120)
            fault = soap_fault(raw)
            if fault:
                log(f"    ⚠ {h_ini:%d/%m %H:%M}: {fault}")
                continue

            inner = parse_return_xml(raw)
            if inner is None:
                continue

            cnt = 0
            for ev in inner.iter():
                if _local_tag(ev) != "EventoTelemetria":
                    continue
                d = _flat_text(ev)
                if not d:
                    continue
                row = _map_evento_tracker(d, with_descricao=with_descricao)

                # Sem evento_id e sem data_evento o registro não tem chave natural
                # e não pode ser deduplicado → descarta
                if not row.get("evento_id") and not row.get("data_evento"):
                    continue

                rows.append(row)
                cnt += 1

            if cnt:
                log(f"    [{n}/{len(janelas)}] {h_ini:%d/%m %H:%M}: +{cnt} eventos")

        except Exception as e:
            log(f"    ❌ Erro na janela {h_ini:%d/%m %H:%M}: {e}")

    log(f"  ✅ {action}: {len(rows)} total")
    return rows


def coletar_eventos_tracker_telemetria(ini: datetime, fim: datetime) -> list[dict]:
    """Wrapper para 31.15 — sem campo descricao_evento."""
    return _coletar_eventos_tracker(
        "ListarEventosTrackerTelemetria", ini, fim, with_descricao=False
    )


def coletar_eventos_tracker_telemetria2(ini: datetime, fim: datetime) -> list[dict]:
    """Wrapper para 31.16 — com campo descricao_evento."""
    return _coletar_eventos_tracker(
        "ListarEventosTrackerTelemetria2", ini, fim, with_descricao=True
    )


# ═══════════════════════════════════════════════════════════════
# PONTO DE ENTRADA PRINCIPAL (main)
# ═══════════════════════════════════════════════════════════════

# Lista de todas as etapas disponíveis (usada para --apenas e --skip)
ALL_STEPS = [
    "dados_historico_telemetria",
    "viagens_telemetria",
    "viagens_telemetria_eletrico",
    "eventos_tracker_telemetria",
    "eventos_tracker_telemetria2",
]

# Mapeamento: nome da etapa → (tabela no Supabase, colunas do ON CONFLICT)
# As colunas de ON CONFLICT DEVEM ter UNIQUE constraint no Supabase!
STEP_TABLE = {
    "dados_historico_telemetria":  ("wstt_dados_historico_telemetria",  "placa,data_hora,serial"),
    "viagens_telemetria":          ("wstt_viagens_telemetria",          "placa,data_inicio_viagem"),
    "viagens_telemetria_eletrico": ("wstt_viagens_telemetria_eletrico", "placa,data_inicio_viagem"),
    "eventos_tracker_telemetria":  ("wstt_eventos_tracker_telemetria",  "evento_id,data_evento"),
    "eventos_tracker_telemetria2": ("wstt_eventos_tracker_telemetria2", "evento_id,data_evento"),
}


def parse_args() -> argparse.Namespace:
    """Define e parseia os argumentos de linha de comando."""
    p = argparse.ArgumentParser(
        description="WSTT → Supabase (endpoints 31.12 a 31.16, pág. 545-557)"
    )
    p.add_argument("--ano", type=int, default=None,
                   help="Ano do mês alvo (ex: 2026). Requer --mes.")
    p.add_argument("--mes", type=int, default=None,
                   help="Mês alvo (1-12). Requer --ano.")
    p.add_argument("--dias", type=int, default=None,
                   help="Coleta os últimos N dias a partir de hoje (ex: --dias 30). "
                        "Tem prioridade sobre --ano/--mes.")
    p.add_argument("--sem-mes-anterior", action="store_true",
                   help="Coleta só o mês atual (ignora o mês anterior no default).")
    p.add_argument("--apenas", type=str, default="",
                   help=f"CSV de etapas a executar. Disponíveis: {','.join(ALL_STEPS)}")
    # Gera --skip-<etapa> para cada etapa disponível
    for s in ALL_STEPS:
        p.add_argument(f"--skip-{s.replace('_', '-')}", action="store_true",
                       help=f"Pula a etapa '{s}'.")
    return p.parse_args()


def _is_enabled(step: str, args: argparse.Namespace) -> bool:
    """Verifica se uma etapa deve ser executada, considerando --apenas e --skip."""
    apenas = [s.strip() for s in (args.apenas or "").split(",") if s.strip()]
    if apenas:
        return step in apenas  # --apenas define lista explícita
    return not getattr(args, f"skip_{step}", False)  # respeita --skip-<etapa>


def _periodos_default(args: argparse.Namespace) -> list[tuple[date, date]]:
    """
    Decide o(s) período(s) a coletar.

    Prioridade dos modos:
      1. --dias N            → últimos N dias até HOJE (janela rolante)
      2. --ano A --mes M     → do dia 1 ao min(último dia do mês, HOJE)
                               Garante que nunca ultrapassa a data atual.
      3. (padrão)            → mês anterior completo + mês atual até HOJE

    O fim do período nunca ultrapassa date.today() — dados futuros não existem.
    """
    today = date.today()

    # ── Modo 1: janela rolante de N dias ────────────────────────
    if args.dias and args.dias > 0:
        ini = today - timedelta(days=args.dias - 1)
        return [(ini, today)]

    # ── Modo 2: mês explícito ────────────────────────────────────
    if args.ano and args.mes:
        ini = date(args.ano, args.mes, 1)
        ultimo_dia_mes = date(args.ano, args.mes,
                              calendar.monthrange(args.ano, args.mes)[1])
        # *** CORREÇÃO: nunca ultrapassa hoje ***
        # Se o mês especificado ainda não terminou (é o mês atual ou futuro),
        # usa hoje como fim para capturar dados até agora.
        fim = min(ultimo_dia_mes, today)
        if fim < ini:
            # Mês completamente no futuro — nada a coletar
            log(f"⚠ Período {ini:%d/%m/%Y}→{fim:%d/%m/%Y} está no futuro. Nada a coletar.")
            return [(today, today)]  # período vazio (hourly_windows não gerará janelas)
        return [(ini, fim)]

    # ── Modo 3: padrão — mês anterior + mês atual até hoje ──────
    cur_ini = today.replace(day=1)   # 1º dia do mês atual
    cur_fim = today                   # hoje (mês atual em andamento)
    periodos: list[tuple[date, date]] = []

    if not args.sem_mes_anterior:
        prev_last_day = cur_ini - timedelta(days=1)   # último dia do mês anterior
        prev_ini      = prev_last_day.replace(day=1)  # 1º dia do mês anterior
        periodos.append((prev_ini, prev_last_day))

    periodos.append((cur_ini, cur_fim))
    return periodos


def main() -> int:
    """
    Função principal: valida configurações, registra execução e roda todas as etapas.

    Fluxo:
      1. Valida variáveis de ambiente obrigatórias
      2. Registra o início da execução em wstt_execucoes
      3. Busca a frota (placas)
      4. Para cada período, executa as etapas habilitadas
      5. Atualiza o status da execução ao final (ok / error / interrupted)

    Retorna 0 em sucesso, 1 em falha.
    """
    args = parse_args()

    # ── Validação de configuração ────────────────────────────────
    if not WSTT_USUARIO or not WSTT_SENHA_MD5:
        log("❌ WSTT_USUARIO e/ou WSTT_SENHA não configurados no arquivo .env")
        return 1
    if not SUPABASE_URL or not SUPABASE_KEY:
        log("❌ SUPABASE_URL e/ou SUPABASE_SERVICE_KEY não configurados no arquivo .env")
        return 1

    # ── Calcula os períodos ──────────────────────────────────────
    periodos = _periodos_default(args)
    periodo_ini = min(p[0] for p in periodos)
    periodo_fim = max(p[1] for p in periodos)

    log("=" * 60)
    label = " + ".join(f"{a:%d/%m/%Y}→{b:%d/%m/%Y}" for a, b in periodos)
    log(f"WSTT → Supabase | {label}")
    log("=" * 60)

    # ── Registra o início da execução no banco ───────────────────
    execucao = supabase_insert_returning("wstt_execucoes", {
        "periodo_inicio": periodo_ini.isoformat(),
        "periodo_fim":    periodo_fim.isoformat(),
        "status":         "running",
    })
    exec_id = execucao.get("id")  # None se o INSERT falhar (não quebra a coleta)

    # Contadores por etapa (atualizados progressivamente no banco)
    counts: dict[str, int] = {s: 0 for s in ALL_STEPS}
    n_veic = 0

    def _patch_progress() -> None:
        """Atualiza o progresso parcial em wstt_execucoes (tolerante a falhas)."""
        if exec_id is None:
            return
        try:
            supabase_patch("wstt_execucoes", {"id": exec_id}, {
                "veiculos": n_veic,
                **counts,
            })
        except Exception as e:
            log(f"  ⚠ Não foi possível salvar progresso parcial: {e}")

    def _on_signal(signum, frame):
        """Captura SIGTERM/SIGINT e marca a execução como interrompida antes de sair."""
        log(f"\n⚠ Sinal {signum} recebido — marcando execução como interrompida…")
        if exec_id is not None:
            try:
                supabase_patch("wstt_execucoes", {"id": exec_id}, {
                    "finalizado_em": datetime.now(timezone.utc).isoformat(),
                    "status":        "interrupted",
                    "erro":          f"interrompido por sinal {signum}",
                    "veiculos":      n_veic,
                    **counts,
                })
            except Exception:
                pass
        sys.exit(143 if signum == signal.SIGTERM else 130)

    # Registra handlers de sinal para garantir status correto em caso de kill
    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
    except Exception:
        pass  # Windows não suporta todos os sinais

    try:
        # ── Busca a frota ────────────────────────────────────────
        veiculos = buscar_placas()
        if not veiculos:
            raise RuntimeError("Nenhum veículo retornado pela WSTT — verifique credenciais")
        n_veic = len(veiculos)

        # Atualiza (upsert) a lista de veículos no banco
        ts = datetime.now(timezone.utc).isoformat()
        veic_rows = [
            {"placa": v["placa"], "frota": v["frota"], "atualizado_em": ts}
            for v in veiculos
        ]
        supabase_upsert("wstt_veiculos", veic_rows, on_conflict="placa")
        _patch_progress()

        # ── Itera sobre os períodos e executa as etapas ──────────
        for p_ini, p_fim in periodos:
            log(f"\n══ Período {p_ini:%d/%m/%Y} → {p_fim:%d/%m/%Y} ══")
            # Converte date → datetime (início do dia e fim do dia)
            dt_ini = datetime.combine(p_ini, datetime.min.time())
            dt_fim = datetime.combine(p_fim, datetime.max.time().replace(microsecond=0))

            # ── 31.12 Dados Histórico Telemetria ─────────────────
            if _is_enabled("dados_historico_telemetria", args):
                log("\n── 31.12 DADOS HISTÓRICO TELEMETRIA ──")
                rows = coletar_dados_historico_telemetria(dt_ini, dt_fim)
                table, conflict = STEP_TABLE["dados_historico_telemetria"]
                counts["dados_historico_telemetria"] += supabase_upsert(
                    table, rows, on_conflict=conflict
                )
                _patch_progress()

            # ── 31.13 Viagens Telemetria (combustão) ─────────────
            if _is_enabled("viagens_telemetria", args):
                log("\n── 31.13 VIAGENS TELEMETRIA ──")
                rows = coletar_viagens_telemetria(veiculos, dt_ini, dt_fim)
                table, conflict = STEP_TABLE["viagens_telemetria"]
                counts["viagens_telemetria"] += supabase_upsert(
                    table, rows, on_conflict=conflict
                )
                _patch_progress()

            # ── 31.14 Viagens Telemetria (elétrico) ─────────────
            if _is_enabled("viagens_telemetria_eletrico", args):
                log("\n── 31.14 VIAGENS TELEMETRIA ELÉTRICO ──")
                rows = coletar_viagens_telemetria_eletrico(veiculos, dt_ini, dt_fim)
                table, conflict = STEP_TABLE["viagens_telemetria_eletrico"]
                counts["viagens_telemetria_eletrico"] += supabase_upsert(
                    table, rows, on_conflict=conflict
                )
                _patch_progress()

            # ── 31.15 Eventos Tracker Telemetria ─────────────────
            if _is_enabled("eventos_tracker_telemetria", args):
                log("\n── 31.15 EVENTOS TRACKER TELEMETRIA ──")
                rows = coletar_eventos_tracker_telemetria(dt_ini, dt_fim)
                table, conflict = STEP_TABLE["eventos_tracker_telemetria"]
                counts["eventos_tracker_telemetria"] += supabase_upsert(
                    table, rows, on_conflict=conflict
                )
                _patch_progress()

            # ── 31.16 Eventos Tracker Telemetria 2 ───────────────
            if _is_enabled("eventos_tracker_telemetria2", args):
                log("\n── 31.16 EVENTOS TRACKER TELEMETRIA 2 ──")
                rows = coletar_eventos_tracker_telemetria2(dt_ini, dt_fim)
                table, conflict = STEP_TABLE["eventos_tracker_telemetria2"]
                counts["eventos_tracker_telemetria2"] += supabase_upsert(
                    table, rows, on_conflict=conflict
                )
                _patch_progress()

        # ── Marca execução como concluída com sucesso ────────────
        if exec_id is not None:
            supabase_patch("wstt_execucoes", {"id": exec_id}, {
                "finalizado_em": datetime.now(timezone.utc).isoformat(),
                "veiculos":      n_veic,
                "status":        "ok",
                **counts,
            })

        log("\n" + "=" * 60)
        log(f"✅ Concluído com sucesso. Veículos={n_veic}")
        for k, v in counts.items():
            if v:
                log(f"  • {k}: {v} linhas")
        log("=" * 60)
        return 0

    except Exception as e:
        log(f"\n❌ Falha geral: {e}")
        # Marca execução como erro no banco (best-effort)
        if exec_id is not None:
            try:
                supabase_patch("wstt_execucoes", {"id": exec_id}, {
                    "finalizado_em": datetime.now(timezone.utc).isoformat(),
                    "status":        "error",
                    "erro":          str(e)[:500],
                    "veiculos":      n_veic,
                    **counts,
                })
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
