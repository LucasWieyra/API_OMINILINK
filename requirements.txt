"""Geração dos PDFs de documentação (usuário e técnica)."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

LOGO_PATH = Path(__file__).resolve().parent / "static" / "cargoblue.png"

BLUE = colors.HexColor("#1F6FEB")
DARK = colors.HexColor("#0B1A2B")
GREY = colors.HexColor("#5A6B85")
LIGHT = colors.HexColor("#EEF3FB")


def _styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"],
                             fontName="Helvetica-Bold", fontSize=22,
                             textColor=DARK, spaceAfter=10, leading=26),
        "h2": ParagraphStyle("h2", parent=base["Heading2"],
                             fontName="Helvetica-Bold", fontSize=14,
                             textColor=BLUE, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base["Heading3"],
                             fontName="Helvetica-Bold", fontSize=11.5,
                             textColor=DARK, spaceBefore=8, spaceAfter=2),
        "p":  ParagraphStyle("p", parent=base["BodyText"],
                             fontName="Helvetica", fontSize=10.5,
                             textColor=DARK, leading=15, spaceAfter=6,
                             alignment=TA_LEFT),
        "small": ParagraphStyle("small", parent=base["BodyText"],
                                fontName="Helvetica", fontSize=9,
                                textColor=GREY, leading=12),
        "code": ParagraphStyle("code", parent=base["BodyText"],
                               fontName="Courier", fontSize=9,
                               textColor=DARK, backColor=LIGHT, leading=12,
                               leftIndent=8, rightIndent=8,
                               spaceBefore=4, spaceAfter=8,
                               borderPadding=6),
        "li": ParagraphStyle("li", parent=base["BodyText"],
                             fontName="Helvetica", fontSize=10.5,
                             textColor=DARK, leading=15,
                             leftIndent=14, bulletIndent=2, spaceAfter=3),
    }


def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(BLUE)
    canvas.rect(0, h - 1.0 * cm, w, 1.0 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(2 * cm, h - 0.65 * cm, "CARGOBLUE  ·  WSTT Dashboard")
    canvas.setFont("Helvetica", 8.5)
    canvas.drawRightString(w - 2 * cm, h - 0.65 * cm,
                           datetime.now().strftime("%d/%m/%Y"))
    # rodapé
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(2 * cm, 1.2 * cm, "dev: Lucas Vieira Ramos")
    canvas.drawRightString(w - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.setStrokeColor(LIGHT)
    canvas.line(2 * cm, 1.6 * cm, w - 2 * cm, 1.6 * cm)
    canvas.restoreState()


def _cover(title: str, subtitle: str, sty) -> list:
    flow = []
    if LOGO_PATH.exists():
        try:
            img = Image(str(LOGO_PATH), width=8 * cm, height=2.2 * cm)
            img.hAlign = "LEFT"
            flow.append(Spacer(1, 3 * cm))
            flow.append(img)
        except Exception:
            pass
    flow.append(Spacer(1, 1.4 * cm))
    flow.append(Paragraph(title, sty["h1"]))
    flow.append(Paragraph(subtitle, sty["small"]))
    flow.append(Spacer(1, 0.6 * cm))
    flow.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", sty["small"]))
    flow.append(PageBreak())
    return flow


def _li(text: str, sty) -> Paragraph:
    return Paragraph(f"• {text}", sty["li"])


def _table(rows: list[list[str]]) -> Table:
    t = Table(rows, hAlign="LEFT", colWidths=[5.0 * cm, 11.0 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.4, GREY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _build(content_builder, filename_hint: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=2 * cm,
                            title=filename_hint, author="Lucas Vieira Ramos")
    sty = _styles()
    doc.build(content_builder(sty),
              onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


# ───────────────────────── Documentação do Usuário ─────────────────────────

def build_user_pdf() -> bytes:
    def content(sty):
        f = _cover(
            "Manual do Usuário",
            "Painel WSTT Dashboard — guia rápido para operação do dia a dia.",
            sty,
        )

        f += [Paragraph("1. O que é o painel", sty["h2"])]
        f += [Paragraph(
            "O <b>WSTT Dashboard</b> é a tela onde você liga, desliga e acompanha "
            "a coleta automática de dados da frota WSTT (Omnilink) que abastece "
            "o banco de dados usado pelo Power BI. Tudo roda em segundo plano "
            "no servidor da Replit — você só usa o painel para controlar e ver "
            "o que está acontecendo.", sty["p"])]

        f += [Paragraph("2. Acesso", sty["h2"])]
        f += [Paragraph(
            "Ao abrir o painel, o navegador pede um <b>usuário</b> e uma "
            "<b>senha</b>. São as credenciais cadastradas pela equipe técnica. "
            "Se errar, basta atualizar a página e digitar de novo.", sty["p"])]

        f += [Paragraph("3. Aba Painel", sty["h2"])]
        f += [Paragraph("Tem três áreas principais:", sty["p"])]
        f += [
            _li("<b>Controle</b> — onde você define o intervalo (em minutos) "
                "e os botões <b>Iniciar</b>, <b>Parar</b> e <b>Rodar agora</b>.", sty),
            _li("<b>Logs ao vivo</b> — terminal preto que mostra cada passo da "
                "coleta em tempo real.", sty),
            _li("<b>Histórico</b> — tabela com as últimas execuções, mostrando "
                "quantos registros foram gravados em cada tabela.", sty),
        ]

        f += [Paragraph("4. Como funciona o agendamento", sty["h2"])]
        f += [Paragraph(
            "Quando você clica em <b>Iniciar</b>, o painel dispara uma coleta "
            "imediatamente e depois repete a cada N minutos (padrão: 60). Você "
            "pode parar a qualquer momento clicando em <b>Parar</b>. Se quiser "
            "uma coleta avulsa fora do agendamento, clique em <b>Rodar agora</b>.",
            sty["p"])]

        f += [Paragraph("5. Indicadores de estado", sty["h2"])]
        f += [_table([
            ["Estado", "O que significa"],
            ["Verde pulsando", "Agendador ligado, aguardando próxima execução."],
            ["Azul pulsando", "Coleta em andamento agora."],
            ["Cinza", "Agendador parado — nenhuma coleta vai rodar."],
            ["Status OK", "A última coleta foi gravada sem erros."],
            ["Status Erro", "A última coleta falhou — veja o terminal de logs."],
        ])]
        f += [Spacer(1, 0.4 * cm)]

        f += [Paragraph("6. O que cada coluna do histórico significa", sty["h2"])]
        f += [_table([
            ["Coluna", "Conteúdo"],
            ["Início / Fim", "Hora em que a coleta começou e terminou."],
            ["Status", "OK = tudo certo, Erro = falhou."],
            ["Coords", "Pontos de localização dos veículos."],
            ["Pos", "Última posição conhecida de cada veículo."],
            ["Eventos", "Total de eventos da frota no período."],
            ["Viagens", "Viagens fechadas no período."],
            ["Cercas", "Cercas eletrônicas cadastradas."],
            ["Mensagens", "Mensagens enviadas para os veículos."],
            ["Iscas", "Quantidade de iscas e seus eventos."],
            ["Ocorr.", "Ocorrências abertas/fechadas."],
        ])]

        f += [PageBreak()]

        f += [Paragraph("7. Aba Configurações", sty["h2"])]
        f += [Paragraph(
            "Aqui é onde a equipe técnica escolhe o destino dos dados (hoje "
            "<b>Supabase</b>; futuramente <b>AWS RDS Postgres</b>) e define os "
            "dados de conexão. Para o uso comum, você não precisa mexer nada.",
            sty["p"])]

        f += [Paragraph("8. Aba Exportar SQL", sty["h2"])]
        f += [Paragraph(
            "Gera um arquivo <b>.sql</b> com tudo o que está no banco hoje — "
            "estrutura das tabelas e dados. Útil para backup, para enviar para "
            "outro servidor ou para abrir em ferramentas externas.", sty["p"])]
        f += [_li("<b>Baixar arquivo .sql</b>: estrutura + dados.", sty)]
        f += [_li("<b>Só estrutura</b>: somente os comandos CREATE TABLE.", sty)]
        f += [Paragraph(
            "O download começa na hora; em bancos grandes pode demorar alguns "
            "segundos para terminar.", sty["small"])]

        f += [Paragraph("9. Dúvidas comuns", sty["h2"])]
        f += [Paragraph("<b>O painel pode ficar fechado?</b>", sty["h3"])]
        f += [Paragraph(
            "Sim. O painel é só uma janela de visualização — a coleta continua "
            "rodando no servidor mesmo com o navegador fechado.", sty["p"])]
        f += [Paragraph("<b>E se eu fechar o computador?</b>", sty["h3"])]
        f += [Paragraph(
            "Como tudo roda no servidor da Replit, fechar o computador não "
            "interfere. Para garantir 24×7, mesmo se o ambiente de "
            "desenvolvimento dormir, o sistema deve ser publicado em produção "
            "(Reserved VM).", sty["p"])]
        f += [Paragraph("<b>Onde aparece o resultado da coleta?</b>", sty["h3"])]
        f += [Paragraph(
            "Direto no banco de dados, e de lá no Power BI. O painel só serve "
            "para controlar e monitorar.", sty["p"])]
        f += [Paragraph("<b>O que faço se der erro?</b>", sty["h3"])]
        f += [Paragraph(
            "Olhe o terminal de logs — a mensagem de erro fica destacada em "
            "vermelho. Encaminhe a mensagem para a equipe técnica.", sty["p"])]

        f += [Spacer(1, 1 * cm)]
        f += [Paragraph(
            "Em caso de dúvidas: dev — Lucas Vieira Ramos.", sty["small"])]
        return f

    return _build(content, "Manual do Usuário — WSTT Dashboard")


# ───────────────────────── Documentação Técnica ─────────────────────────

def build_tech_pdf() -> bytes:
    def content(sty):
        f = _cover(
            "Documentação Técnica",
            "Arquitetura, instalação, operação e migração do WSTT Dashboard.",
            sty,
        )

        f += [Paragraph("1. Visão geral", sty["h2"])]
        f += [Paragraph(
            "Sistema em Python que coleta dados do <b>WSTT (Omnilink)</b> via "
            "SOAP, normaliza/tipa os campos e grava no <b>Supabase Postgres</b>. "
            "Inclui um painel web (Flask) com Start/Stop, logs em streaming "
            "(SSE), histórico, gerenciamento de configuração e exportação SQL.",
            sty["p"])]

        f += [Paragraph("2. Stack", sty["h2"])]
        f += [_table([
            ["Componente", "Tecnologia"],
            ["Linguagem", "Python 3.11"],
            ["Web", "Flask + Server-Sent Events"],
            ["Coleta", "requests + xml.etree (SOAP cru)"],
            ["Banco atual", "Supabase Postgres (REST PostgREST)"],
            ["Banco futuro", "AWS RDS / Aurora Postgres"],
            ["PDF", "ReportLab"],
            ["Auth do painel", "HTTP Basic"],
            ["Hospedagem", "Replit (dev) / Reserved VM (prod)"],
        ])]

        f += [Paragraph("3. Arquivos do projeto", sty["h2"])]
        f += [_table([
            ["Arquivo", "Função"],
            ["scripts/python/dashboard.py", "Servidor Flask + agendador (Start/Stop)"],
            ["scripts/python/wstt_to_supabase.py", "Coletor SOAP → Postgres (idempotente)"],
            ["scripts/python/scheduler.py", "Modo headless (sem painel)"],
            ["scripts/python/supabase_schema.sql", "DDL tipado (TIMESTAMP, NUMERIC, BOOL...)"],
            ["scripts/python/docs_pdf.py", "Geração dos PDFs de documentação"],
            ["scripts/python/templates/index.html", "Template do painel"],
            ["scripts/python/static/app.css | app.js", "Front-end"],
            ["scripts/python/.config.json", "Configuração persistida (backend escolhido)"],
        ])]

        f += [Paragraph("4. Variáveis de ambiente / Secrets", sty["h2"])]
        f += [_table([
            ["Chave", "Uso"],
            ["WSTT_USUARIO", "Login da API SOAP do WSTT"],
            ["WSTT_SENHA", "Senha da API SOAP do WSTT"],
            ["SUPABASE_URL", "URL do projeto Supabase"],
            ["SUPABASE_SERVICE_KEY", "JWT do service_role (escrita)"],
            ["DASHBOARD_USER", "Usuário do painel (HTTP Basic)"],
            ["DASHBOARD_PASSWORD", "Senha do painel"],
            ["WSTT_INTERVAL_MIN", "Intervalo padrão do scheduler (default 60)"],
            ["AWS_DB_PASSWORD", "Senha do Postgres no AWS (futuro)"],
            ["PORT", "Porta do servidor Flask (default 5000)"],
        ])]

        f += [PageBreak()]

        f += [Paragraph("5. Fluxo de coleta", sty["h2"])]
        f += [_li("<b>Login SOAP</b> em <i>EfetuarLogon</i> retorna chave de sessão.", sty)]
        f += [_li("<b>ListarVeiculos</b> traz a frota ativa (paginado).", sty)]
        f += [_li(
            "Para cada placa, o coletor chama os métodos relevantes "
            "(coordenadas, viagens, ocioso, posições, eventos, cercas, "
            "pontos de referência, motoristas, alvos, rotas, sensores, "
            "histórico de transmissão, mensagens, iscas, eventos de iscas "
            "e ocorrências).", sty)]
        f += [_li(
            "Os XMLs são reduzidos a <i>dicts</i> e passados por mapeadores "
            "que normalizam nomes (case-insensitive, múltiplas variantes).", sty)]
        f += [_li(
            "Antes de enviar ao Postgres, cada linha passa pelo "
            "<i>coerce_row(table, row)</i>, que aplica os tipos definidos em "
            "<b>COLUMN_TYPES</b> (timestamp BR → ISO, vírgula decimal, bool "
            "&quot;Ligada/Desligada&quot;, etc.).", sty)]
        f += [_li(
            "É calculado um <b>row_hash</b> (SHA-1 dos campos significativos). "
            "O UPSERT usa <i>on_conflict=row_hash</i>, garantindo "
            "idempotência: rodar duas vezes não duplica.", sty)]
        f += [_li(
            "Cada execução grava um resumo em <b>wstt_execucoes</b> com "
            "início, fim, status e contagens por tabela.", sty)]

        f += [Paragraph("6. Schema (resumo)", sty["h2"])]
        f += [Paragraph(
            "22 tabelas planas (sem JSON aninhado), prontas para Power BI. "
            "Tipos principais:", sty["p"])]
        f += [_table([
            ["Tipo Postgres", "Para que serve"],
            ["TIMESTAMP", "Datas vindas do WSTT (horário local Brasil)"],
            ["TIMESTAMPTZ", "Carimbos do servidor (importado_em / capturado_em)"],
            ["DATE", "Datas sem hora (validade CNH, períodos)"],
            ["NUMERIC", "Números (km, litros, lat/lng, horas, RPM, etc.)"],
            ["INTEGER", "Contagens inteiras (quantidades, intervalo de tx)"],
            ["BOOLEAN", "Flags (ignição, ativo)"],
            ["TEXT", "Identificadores e textos livres"],
            ["row_hash UNIQUE", "Garante UPSERT idempotente"],
        ])]

        f += [Paragraph("7. Endpoints HTTP", sty["h2"])]
        f += [_table([
            ["Rota", "Função"],
            ["GET /", "Renderiza o painel (HTML)"],
            ["GET /api/status", "Estado do scheduler"],
            ["POST /api/start", "Liga o scheduler (body: {interval_min})"],
            ["POST /api/stop", "Para o scheduler"],
            ["POST /api/run-now", "Dispara coleta avulsa"],
            ["GET /api/logs", "Buffer atual de logs (JSON)"],
            ["GET /api/logs/stream", "Stream SSE de logs em tempo real"],
            ["GET /api/executions", "Últimas execuções (lê wstt_execucoes)"],
            ["GET /api/config", "Lê .config.json"],
            ["POST /api/config", "Atualiza backend e dados de conexão"],
            ["GET /api/export.sql", "Stream de SQL (schema + dados)"],
            ["GET /api/docs/user.pdf", "Manual do Usuário em PDF"],
            ["GET /api/docs/tech.pdf", "Documentação Técnica em PDF"],
        ])]

        f += [PageBreak()]

        f += [Paragraph("8. Operação", sty["h2"])]
        f += [Paragraph("<b>Subir o painel</b>", sty["h3"])]
        f += [Paragraph("Workflow Replit <b>WSTT Dashboard</b>:", sty["p"])]
        f += [Paragraph("python scripts/python/dashboard.py", sty["code"])]
        f += [Paragraph("<b>Modo headless (sem painel)</b>", sty["h3"])]
        f += [Paragraph("python scripts/python/scheduler.py", sty["code"])]
        f += [Paragraph("<b>Coleta única manual</b>", sty["h3"])]
        f += [Paragraph(
            "python scripts/python/wstt_to_supabase.py --apenas posicoes,rastreadores",
            sty["code"])]

        f += [Paragraph("9. Migração para AWS RDS Postgres", sty["h2"])]
        f += [_li("Provisionar instância RDS Postgres (libera porta 5432 para o IP do servidor de coleta).", sty)]
        f += [_li("Criar database e usuário com permissões CRUD em <i>public</i>.", sty)]
        f += [_li("Na aba <b>Exportar SQL</b>, baixar o arquivo (schema + dados).", sty)]
        f += [_li("Aplicar no AWS: <i>psql -h ... -U ... -d ... -f wstt_export_*.sql</i>.", sty)]
        f += [_li("Adicionar o secret <b>AWS_DB_PASSWORD</b> no Replit.", sty)]
        f += [_li("Aba <b>Configurações</b>: trocar para <b>AWS RDS Postgres</b>, preencher os campos, salvar.", sty)]
        f += [_li("Próximo ciclo do scheduler já grava no AWS (após o switch ser ativado no coletor — psycopg2).", sty)]

        f += [Paragraph("10. Segurança", sty["h2"])]
        f += [_li("Painel atrás de HTTP Basic (hmac.compare_digest, anti-timing).", sty)]
        f += [_li("Service key do Supabase nunca aparece no front-end — só no servidor.", sty)]
        f += [_li("Senha do AWS deve ficar em secret, nunca no .config.json.", sty)]
        f += [_li("Em produção, publicar como Reserved VM e configurar HTTPS automático do Replit Deployments.", sty)]

        f += [Paragraph("11. Manutenção", sty["h2"])]
        f += [_li("Adicionar nova etapa de coleta: criar mapeador em wstt_to_supabase.py, registrar em ALL_STEPS, adicionar tabela no SQL e tipos em COLUMN_TYPES.", sty)]
        f += [_li("Mudar intervalo padrão: variável de ambiente WSTT_INTERVAL_MIN.", sty)]
        f += [_li("Trocar credenciais do painel: editar secrets DASHBOARD_USER / DASHBOARD_PASSWORD e reiniciar o workflow.", sty)]
        f += [_li("Logs ficam em buffer em memória (1500 linhas) e são reenviados via SSE para clientes recém-conectados.", sty)]

        f += [Spacer(1, 0.6 * cm)]
        f += [Paragraph(
            "Documento mantido por Lucas Vieira Ramos.", sty["small"])]
        return f

    return _build(content, "Documentação Técnica — WSTT Dashboard")
