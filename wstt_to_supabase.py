-- ═══════════════════════════════════════════════════════════════
-- supabase_schema.sql
-- Schema das tabelas WSTT no Supabase Postgres
-- ═══════════════════════════════════════════════════════════════
--
-- COMO APLICAR:
--   1. Acesse o Supabase → SQL Editor
--   2. Cole este conteúdo e clique em "Run"
--   3. Todas as tabelas e índices serão criados (sem apagar dados)
--
-- ANTI-DUPLICATAS:
--   Cada tabela tem um índice UNIQUE nas colunas que formam a
--   chave natural do registro. Sem esses índices, o UPSERT do
--   PostgREST NÃO funciona e duplicatas são inseridas normalmente.
--
-- ═══════════════════════════════════════════════════════════════


-- ───────────────────────────────────────────────────────────────
-- TABELA: wstt_execucoes
-- Registra cada execução do coletor (início, fim, status, contadores)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wstt_execucoes (
    id                           BIGSERIAL PRIMARY KEY,
    iniciado_em                  TIMESTAMPTZ DEFAULT NOW(),
    finalizado_em                TIMESTAMPTZ,
    periodo_inicio               DATE,
    periodo_fim                  DATE,
    status                       TEXT DEFAULT 'running',
    erro                         TEXT,
    veiculos                     INT DEFAULT 0,
    dados_historico_telemetria   INT DEFAULT 0,
    viagens_telemetria           INT DEFAULT 0,
    viagens_telemetria_eletrico  INT DEFAULT 0,
    eventos_tracker_telemetria   INT DEFAULT 0,
    eventos_tracker_telemetria2  INT DEFAULT 0
);


-- ───────────────────────────────────────────────────────────────
-- TABELA: wstt_veiculos
-- Lista de veículos da frota (atualizada a cada execução)
-- Chave única: placa
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wstt_veiculos (
    id            BIGSERIAL PRIMARY KEY,
    placa         TEXT NOT NULL,
    frota         TEXT,
    atualizado_em TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS wstt_veiculos_placa_idx
    ON wstt_veiculos (placa);


-- ───────────────────────────────────────────────────────────────
-- TABELA: wstt_dados_historico_telemetria  (endpoint 31.12)
-- Telemetria ponto-a-ponto de cada veículo
-- Chave única: (placa, data_hora, serial)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wstt_dados_historico_telemetria (
    id                                  BIGSERIAL PRIMARY KEY,
    placa                               TEXT,
    serial                              TEXT,
    data_hora                           TIMESTAMP,
    data_sys                            TIMESTAMP,
    id_cliente                          TEXT,
    id_contrato                         TEXT,
    chassis                             TEXT,
    chaveiro_serial                     TEXT,
    flags_status                        TEXT,
    veiculo_eletrico                    TEXT,
    versao_firmware                     TEXT,
    release_firmware                    TEXT,
    revisao_firmware                    TEXT,
    letra_firmware                      TEXT,
    altitude                            NUMERIC,
    autonomia                           NUMERIC,
    azimute                             NUMERIC,
    carregador                          TEXT,
    ciclo_carga                         NUMERIC,
    consumo_combustivel                 NUMERIC,
    corrente_bateria_propulsao          NUMERIC,
    distancia_total                     NUMERIC,
    ignicao                             BOOLEAN,
    latitude                            NUMERIC,
    longitude                           NUMERIC,
    media_consumo_combustivel           NUMERIC,
    nivel_adblue                        NUMERIC,
    nivel_combustivel_litros            NUMERIC,
    nivel_combustivel_percentual        NUMERIC,
    pedal_acelerador_maxima             NUMERIC,
    pedal_acelerador_media              NUMERIC,
    qnt_horas_ativo                     NUMERIC,
    qnt_horas_motor                     NUMERIC,
    qnt_horas_ocioso                    NUMERIC,
    qnt_horas_total                     NUMERIC,
    qnt_kickdown                        INT,
    rpm                                 NUMERIC,
    rpm_max                             NUMERIC,
    rpm_media                           NUMERIC,
    temperatura_bateria                 NUMERIC,
    temperatura_liquido_arrefecimento   NUMERIC,
    tensao_bateria_propulsao            NUMERIC,
    velocidade_can                      NUMERIC,
    velocidade_gps                      NUMERIC,
    velocidade_maxima                   NUMERIC,
    velocidade_media                    NUMERIC
);

-- Índice UNIQUE para o UPSERT (on_conflict=placa,data_hora,serial)
CREATE UNIQUE INDEX IF NOT EXISTS wstt_dados_historico_telemetria_uq
    ON wstt_dados_historico_telemetria (placa, data_hora, serial);

-- Índice de leitura para consultas por placa/data (Power BI)
CREATE INDEX IF NOT EXISTS wstt_dados_historico_telemetria_placa_idx
    ON wstt_dados_historico_telemetria (placa, data_hora DESC);


-- ───────────────────────────────────────────────────────────────
-- TABELA: wstt_viagens_telemetria  (endpoint 31.13)
-- Viagens completas de veículos a combustão
-- Chave única: (placa, data_inicio_viagem)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wstt_viagens_telemetria (
    id                                      BIGSERIAL PRIMARY KEY,
    viagem_id                               TEXT,
    placa                                   TEXT,
    serial                                  TEXT,
    id_cliente                              TEXT,
    id_contrato                             TEXT,
    driver_id                               TEXT,
    sequencia_jornada                       TEXT,
    data_inicio_viagem                      TIMESTAMP,
    data_fim_viagem                         TIMESTAMP,
    duracao_da_viagem                       TEXT,
    distancia_total_percorrida              NUMERIC,
    horimetro_inicial                       NUMERIC,
    horimetro_final                         NUMERIC,
    odometro_inicial                        NUMERIC,
    odometro_final                          NUMERIC,
    latitude_inicial                        NUMERIC,
    longitude_inicial                       NUMERIC,
    latitude_final                          NUMERIC,
    longitude_final                         NUMERIC,
    media_consumo_viagem                    NUMERIC,
    nivel_adblue_final                      NUMERIC,
    nivel_combustivel_inicial               NUMERIC,
    nivel_combustivel_final                 NUMERIC,
    quantidade_aceleracao_brusca            INT,
    quantidade_freada_brusca                INT,
    quantidade_evento_embreagem             INT,
    quantidade_evento_freio_estacionario    INT,
    quantidade_evento_freio_motor           INT,
    quantidade_evento_pedal_freio           INT,
    quantidade_evento_piloto_automatico     INT,
    quantidade_evento_pto                   INT,
    quantidade_excesso_velocidade           INT,
    quantidade_excesso_velocidade_chuva     INT,
    quantidade_horas_ativo                  NUMERIC,
    quantidade_horas_ocioso                 NUMERIC,
    quantidade_horas_total                  NUMERIC,
    quantidade_kickdowns                    INT,
    tempo_evento_embreagem                  NUMERIC,
    tempo_evento_freio_estacionario         NUMERIC,
    tempo_evento_freio_motor                NUMERIC,
    tempo_evento_pedal_freio                NUMERIC,
    tempo_evento_piloto_automatico          NUMERIC,
    tempo_evento_pto                        NUMERIC,
    tempo_excesso_velocidade                NUMERIC,
    tempo_excesso_velocidade_chuva          NUMERIC,
    tempo_kickdowns                         NUMERIC,
    total_litros_ativo                      NUMERIC,
    total_litros_consumidos_inicial         NUMERIC,
    total_litros_consumidos_final           NUMERIC,
    total_litros_ocioso                     NUMERIC,
    acelerador                              JSONB,
    acelerador_velocidade                   JSONB,
    tempo_rpm_pedal_acelerador              JSONB,
    velocidade                              JSONB
);

-- Índice UNIQUE para o UPSERT (on_conflict=placa,data_inicio_viagem)
CREATE UNIQUE INDEX IF NOT EXISTS wstt_viagens_telemetria_uq
    ON wstt_viagens_telemetria (placa, data_inicio_viagem);

CREATE INDEX IF NOT EXISTS wstt_viagens_telemetria_placa_idx
    ON wstt_viagens_telemetria (placa, data_inicio_viagem DESC);


-- ───────────────────────────────────────────────────────────────
-- TABELA: wstt_viagens_telemetria_eletrico  (endpoint 31.14)
-- Viagens completas de veículos elétricos
-- Chave única: (placa, data_inicio_viagem)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wstt_viagens_telemetria_eletrico (
    id                                          BIGSERIAL PRIMARY KEY,
    viagem_id                                   TEXT,
    placa                                       TEXT,
    serial                                      TEXT,
    id_cliente                                  TEXT,
    id_contrato                                 TEXT,
    driver_id                                   TEXT,
    sequencia_jornada                           TEXT,
    flag_veiculo_eletrico                       TEXT,
    status_carregador                           TEXT,
    data_inicio_viagem                          TIMESTAMP,
    data_fim_viagem                             TIMESTAMP,
    duracao_da_viagem                           TEXT,
    distancia_total_percorrida                  NUMERIC,
    distancia_percorrida_modo_eco               NUMERIC,
    distancia_percorrida_modo_normal            NUMERIC,
    horimetro_inicial                           NUMERIC,
    horimetro_final                             NUMERIC,
    odometro_inicial                            NUMERIC,
    odometro_final                              NUMERIC,
    latitude_inicial                            NUMERIC,
    longitude_inicial                           NUMERIC,
    latitude_final                              NUMERIC,
    longitude_final                             NUMERIC,
    autonomia                                   NUMERIC,
    energia_recuperada                          NUMERIC,
    media_consumo_viagem                        NUMERIC,
    corrente_bateria_propulsao                  NUMERIC,
    tensao_bateria_propulsao                    NUMERIC,
    temperatura_bateria                         NUMERIC,
    nivel_adblue_inicial                        NUMERIC,
    nivel_adblue_final                          NUMERIC,
    nivel_energia_inicial                       NUMERIC,
    nivel_energia_final                         NUMERIC,
    nota_evento_aceleracao                      NUMERIC,
    nota_evento_exc_vel                         NUMERIC,
    nota_evento_exc_vel_chuva                   NUMERIC,
    nota_evento_freada_brusca                   NUMERIC,
    nota_final_do_motorista                     NUMERIC,
    nota_indice_economia                        NUMERIC,
    nota_indice_seguranca                       NUMERIC,
    quantidade_aceleracao_brusca                INT,
    quantidade_freada_brusca                    INT,
    quantidade_ciclos_carga                     INT,
    quantidade_evento_embreagem                 INT,
    quantidade_evento_freio_estacionario        INT,
    quantidade_evento_freio_motor               INT,
    quantidade_evento_pedal_freio               INT,
    quantidade_evento_piloto_automatico         INT,
    quantidade_evento_pto                       INT,
    quantidade_excesso_velocidade               INT,
    quantidade_excesso_velocidade_chuva         INT,
    quantidade_horas_ativo                      NUMERIC,
    quantidade_horas_ocioso                     NUMERIC,
    quantidade_horas_total                      NUMERIC,
    quantidade_kickdowns                        INT,
    tempo_evento_embreagem                      NUMERIC,
    tempo_evento_freio_estacionario             NUMERIC,
    tempo_evento_freio_motor                    NUMERIC,
    tempo_evento_pedal_freio                    NUMERIC,
    tempo_evento_piloto_automatico              NUMERIC,
    tempo_evento_pto                            NUMERIC,
    tempo_excesso_velocidade                    NUMERIC,
    tempo_excesso_velocidade_chuva              NUMERIC,
    tempo_kickdowns                             NUMERIC,
    total_kwh_ativo                             NUMERIC,
    total_kwh_consumidos_inicial                NUMERIC,
    total_kwh_consumidos_final                  NUMERIC,
    total_kwh_ocioso                            NUMERIC,
    velocidade                                  JSONB,
    evento_excesso_velocidade                   JSONB,
    evento_excesso_velocidade_chuva             JSONB,
    evento_excesso_rpm                          JSONB,
    evento_ignicao_desligada_veiculo_movimento  JSONB,
    evento_superaquecimento_liquido_arrefecimento JSONB,
    evento_excesso_rotacao_veiculo_parado       JSONB
);

-- Índice UNIQUE para o UPSERT (on_conflict=placa,data_inicio_viagem)
CREATE UNIQUE INDEX IF NOT EXISTS wstt_viagens_telemetria_eletrico_uq
    ON wstt_viagens_telemetria_eletrico (placa, data_inicio_viagem);

CREATE INDEX IF NOT EXISTS wstt_viagens_telemetria_eletrico_placa_idx
    ON wstt_viagens_telemetria_eletrico (placa, data_inicio_viagem DESC);


-- ───────────────────────────────────────────────────────────────
-- TABELA: wstt_eventos_tracker_telemetria  (endpoint 31.15)
-- Eventos de condução (aceleração, freada, excesso de vel., etc.)
-- Chave única: (evento_id, data_evento)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wstt_eventos_tracker_telemetria (
    id                              BIGSERIAL PRIMARY KEY,
    evento_id                       TEXT,
    cod_evento                      TEXT,
    placa                           TEXT,
    serial                          TEXT,
    chaveiro_serial                 TEXT,
    data_evento                     TIMESTAMP,
    data_cadastro                   TIMESTAMP,
    endereco                        TEXT,
    endereco_final                  TEXT,
    latitude_inicial                NUMERIC,
    longitude_inicial               NUMERIC,
    latitude_final                  NUMERIC,
    longitude_final                 NUMERIC,
    id_cliente                      TEXT,
    id_viagem                       TEXT,
    duracao_evento                  NUMERIC,
    distancia_percorrida            NUMERIC,
    aceleracao_configurada          NUMERIC,
    aceleracao_maxima               NUMERIC,
    aceleracao_lateral_configurada  NUMERIC,
    aceleracao_lateral_maxima       NUMERIC,
    desaceleracao_configurada       NUMERIC,
    desaceleracao_maxima            NUMERIC,
    nivel_combustivel_anterior      NUMERIC,
    nivel_combustivel_posterior     NUMERIC,
    percentual_queda_combustivel    NUMERIC,
    percentual_subida_combustivel   NUMERIC,
    rpm_limite_configurado          NUMERIC,
    rpm_maximo                      NUMERIC,
    tempo_configurado               NUMERIC,
    velocidade_limite_configurado   NUMERIC,
    velocidade_maxima               NUMERIC,
    velocidade                      NUMERIC,
    referencia                      TEXT,
    status                          TEXT,
    temperatura_limite_configurado  NUMERIC,
    valor_maximo_temperatura        NUMERIC,
    flag_tipo_veiculo               TEXT,
    curva_forca_g                   TEXT,
    id_cerca                        TEXT,
    porcentagem_pedal_acelerador    NUMERIC
);

-- Índice UNIQUE para o UPSERT (on_conflict=evento_id,data_evento)
CREATE UNIQUE INDEX IF NOT EXISTS wstt_eventos_tracker_telemetria_uq
    ON wstt_eventos_tracker_telemetria (evento_id, data_evento);

CREATE INDEX IF NOT EXISTS wstt_eventos_tracker_telemetria_placa_idx
    ON wstt_eventos_tracker_telemetria (placa, data_evento DESC);


-- ───────────────────────────────────────────────────────────────
-- TABELA: wstt_eventos_tracker_telemetria2  (endpoint 31.16)
-- Mesmo conteúdo do 31.15 + campo descricao_evento
-- Chave única: (evento_id, data_evento)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wstt_eventos_tracker_telemetria2 (
    id                              BIGSERIAL PRIMARY KEY,
    evento_id                       TEXT,
    cod_evento                      TEXT,
    placa                           TEXT,
    serial                          TEXT,
    chaveiro_serial                 TEXT,
    data_evento                     TIMESTAMP,
    data_cadastro                   TIMESTAMP,
    endereco                        TEXT,
    endereco_final                  TEXT,
    latitude_inicial                NUMERIC,
    longitude_inicial               NUMERIC,
    latitude_final                  NUMERIC,
    longitude_final                 NUMERIC,
    id_cliente                      TEXT,
    id_viagem                       TEXT,
    duracao_evento                  NUMERIC,
    distancia_percorrida            NUMERIC,
    aceleracao_configurada          NUMERIC,
    aceleracao_maxima               NUMERIC,
    aceleracao_lateral_configurada  NUMERIC,
    aceleracao_lateral_maxima       NUMERIC,
    desaceleracao_configurada       NUMERIC,
    desaceleracao_maxima            NUMERIC,
    nivel_combustivel_anterior      NUMERIC,
    nivel_combustivel_posterior     NUMERIC,
    percentual_queda_combustivel    NUMERIC,
    percentual_subida_combustivel   NUMERIC,
    rpm_limite_configurado          NUMERIC,
    rpm_maximo                      NUMERIC,
    tempo_configurado               NUMERIC,
    velocidade_limite_configurado   NUMERIC,
    velocidade_maxima               NUMERIC,
    velocidade                      NUMERIC,
    referencia                      TEXT,
    status                          TEXT,
    temperatura_limite_configurado  NUMERIC,
    valor_maximo_temperatura        NUMERIC,
    flag_tipo_veiculo               TEXT,
    curva_forca_g                   TEXT,
    id_cerca                        TEXT,
    porcentagem_pedal_acelerador    NUMERIC,
    descricao_evento                TEXT   -- exclusivo do endpoint 31.16
);

-- Índice UNIQUE para o UPSERT (on_conflict=evento_id,data_evento)
CREATE UNIQUE INDEX IF NOT EXISTS wstt_eventos_tracker_telemetria2_uq
    ON wstt_eventos_tracker_telemetria2 (evento_id, data_evento);

CREATE INDEX IF NOT EXISTS wstt_eventos_tracker_telemetria2_placa_idx
    ON wstt_eventos_tracker_telemetria2 (placa, data_evento DESC);


-- ═══════════════════════════════════════════════════════════════
-- LIMPEZA DE DUPLICATAS JÁ EXISTENTES (execute separadamente se precisar)
-- ═══════════════════════════════════════════════════════════════

-- DELETE FROM wstt_dados_historico_telemetria a
-- USING wstt_dados_historico_telemetria b
-- WHERE a.id > b.id
--   AND a.placa IS NOT DISTINCT FROM b.placa
--   AND a.data_hora IS NOT DISTINCT FROM b.data_hora
--   AND a.serial IS NOT DISTINCT FROM b.serial;

-- DELETE FROM wstt_viagens_telemetria a
-- USING wstt_viagens_telemetria b
-- WHERE a.id > b.id
--   AND a.placa IS NOT DISTINCT FROM b.placa
--   AND a.data_inicio_viagem IS NOT DISTINCT FROM b.data_inicio_viagem;

-- DELETE FROM wstt_viagens_telemetria_eletrico a
-- USING wstt_viagens_telemetria_eletrico b
-- WHERE a.id > b.id
--   AND a.placa IS NOT DISTINCT FROM b.placa
--   AND a.data_inicio_viagem IS NOT DISTINCT FROM b.data_inicio_viagem;

-- DELETE FROM wstt_eventos_tracker_telemetria a
-- USING wstt_eventos_tracker_telemetria b
-- WHERE a.id > b.id
--   AND a.evento_id IS NOT DISTINCT FROM b.evento_id
--   AND a.data_evento IS NOT DISTINCT FROM b.data_evento;

-- DELETE FROM wstt_eventos_tracker_telemetria2 a
-- USING wstt_eventos_tracker_telemetria2 b
-- WHERE a.id > b.id
--   AND a.evento_id IS NOT DISTINCT FROM b.evento_id
--   AND a.data_evento IS NOT DISTINCT FROM b.data_evento;
