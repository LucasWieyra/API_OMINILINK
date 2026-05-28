"""
scheduler.py
============
Modo headless: roda o coletor wstt_to_supabase.py em loop contínuo,
sem necessidade de interface gráfica (PyQt5).

Ideal para rodar em servidor/VM Linux sem monitor.

Variáveis de ambiente:
  WSTT_INTERVAL_MIN   → minutos entre execuções (default: 60)
  WSTT_RUN_ON_START   → "1" para rodar imediatamente ao iniciar (default: 1)
  WSTT_SCHED_DIAS     → coleta os últimos N dias até HOJE (janela rolante).
                         Ex: WSTT_SCHED_DIAS=7 coleta os últimos 7 dias.
                         RECOMENDADO para garantir dados sempre atualizados.
  WSTT_SCHED_APENAS   → CSV de etapas (ex: "viagens_telemetria,eventos_tracker_telemetria")
                         Se vazio, executa todas as etapas.

  ── Alternativa ao WSTT_SCHED_DIAS (mês fixo) ──────────────────
  WSTT_SCHED_ANO      → ano alvo (ex: 2026). Requer WSTT_SCHED_MES.
  WSTT_SCHED_MES      → mês alvo (1-12). O fim nunca ultrapassa HOJE,
                         então é seguro manter o mês atual sem travar em
                         datas passadas.

ATENÇÃO: Se WSTT_SCHED_ANO e WSTT_SCHED_MES estiverem definidos com um
mês passado (ex: MES=4 = abril), a coleta vai parar no último dia daquele
mês. Para coletar SEMPRE até hoje, use WSTT_SCHED_DIAS ou deixe sem variáveis
(o padrão coleta mês anterior completo + mês atual até hoje).

Uso:
  python scripts/python/scheduler.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

# Carrega o arquivo .env automaticamente se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def log(msg: str) -> None:
    """Imprime mensagem com timestamp UTC e flush imediato."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def run_once() -> int:
    """
    Executa o coletor wstt_to_supabase.py como subprocesso.

    Constrói o comando com os parâmetros opcionais das variáveis de ambiente
    e aguarda o término. Retorna o código de saída (0 = sucesso, != 0 = erro).

    Prioridade dos parâmetros:
      1. WSTT_SCHED_DIAS  → --dias N  (janela rolante, sempre até hoje)
      2. WSTT_SCHED_ANO + WSTT_SCHED_MES → --ano A --mes M (mês específico)
      3. Nenhum → default do coletor (mês anterior + mês atual até hoje)
    """
    # Localiza o wstt_to_supabase.py no mesmo diretório deste script
    collector_path = os.path.join(os.path.dirname(__file__), "wstt_to_supabase.py")
    cmd = [sys.executable, collector_path]

    # Janela rolante tem prioridade sobre mês fixo
    dias = os.getenv("WSTT_SCHED_DIAS", "").strip()
    if dias.isdigit() and int(dias) > 0:
        cmd += ["--dias", dias]
        log(f"  Modo: últimos {dias} dias até hoje")
    else:
        # Mês fixo (com correção automática: fim nunca ultrapassa hoje)
        ano    = os.getenv("WSTT_SCHED_ANO", "").strip()
        mes    = os.getenv("WSTT_SCHED_MES", "").strip()
        apenas = os.getenv("WSTT_SCHED_APENAS", "").strip()

        if ano and mes:
            cmd += ["--ano", ano, "--mes", mes]
            log(f"  Modo: mês {mes}/{ano} (fim ajustado para hoje se ainda não terminou)")
        else:
            log("  Modo: padrão (mês anterior completo + mês atual até hoje)")

        if apenas:
            cmd += ["--apenas", apenas]

    # Adiciona --apenas se definido (também válido no modo --dias)
    apenas_global = os.getenv("WSTT_SCHED_APENAS", "").strip()
    if apenas_global and "--apenas" not in cmd:
        cmd += ["--apenas", apenas_global]

    log(f"▶ Iniciando coleta: {' '.join(cmd)}")
    try:
        rc = subprocess.call(cmd)
    except Exception as e:
        log(f"❌ Falha ao iniciar o coletor: {e}")
        return 1

    log(f"⏹ Coleta encerrada (código de saída: {rc})")
    return rc


def main() -> int:
    """
    Loop principal do scheduler.

    1. Lê o intervalo entre execuções de WSTT_INTERVAL_MIN (padrão: 60 min)
    2. Opcionalmente roda uma coleta imediata ao iniciar (WSTT_RUN_ON_START=1)
    3. Aguarda o intervalo e repete indefinidamente
    """
    interval_min = int(os.getenv("WSTT_INTERVAL_MIN", "60"))
    run_on_start = os.getenv("WSTT_RUN_ON_START", "1") == "1"

    log(f"🕒 Scheduler iniciado | intervalo={interval_min} min | run_on_start={run_on_start}")

    # Coleta imediata ao iniciar (se configurado)
    if run_on_start:
        run_once()

    # Loop infinito: aguarda o intervalo e executa novamente
    while True:
        log(f"⏳ Próxima execução em {interval_min} minuto(s)...")
        time.sleep(interval_min * 60)
        run_once()


if __name__ == "__main__":
    sys.exit(main())
