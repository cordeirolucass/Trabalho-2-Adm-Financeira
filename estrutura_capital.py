# -*- coding: utf-8 -*-
"""
===============================================================================
 UFMG - FACE - Departamento de Ciências Administrativas (CAD)
 Disciplina : Administração Financeira (CAD 167) - Turma ICEX/SI
 Professor  : Bruno Pérez Ferreira
 Trabalho 2 : Aplicação prática sobre ESTRUTURA DE CAPITAL
 Dupla      : Lucas Oliveira Frade Ribeiro Cordeiro  /  Olivier Menezes Vasconcelos
 Semestre   : 2º semestre de 2026
===============================================================================

ANALISADOR DE ESTRUTURA DE CAPITAL
----------------------------------
O programa captura dados de uma empresa (pela internet, digitados pelo usuário
ou lidos de um arquivo JSON), calcula o custo de capital atual e simula o que
aconteceria com o custo de capital e com o valor da empresa se ela mudasse a
proporção entre dívida (D) e capital próprio (E).

Base teórica: Berk, DeMarzo & Harford, "Fundamentos de Finanças Empresariais":
  * Cap. 12 - Custo de capital / CMPC (WACC):
        r_wacc = E/(E+D) * r_E  +  D/(E+D) * r_D * (1 - Tc)
        r_E pelo CAPM: r_E = r_f + beta * (prêmio de risco de mercado)
  * Cap. 15 - Estrutura de capital:
      15.2  Mercado de capitais perfeito (Modigliani-Miller, sem impostos)
            - Proposição I : o valor da empresa não depende da estrutura
            - Proposição II: r_E = r_U + D/E * (r_U - r_D)
            - O WACC fica constante e igual a r_U
      15.3  Endividamento e impostos
            - Dedução tributária dos juros = Tc * juros
            - V^L = V^U + PV(dedução tributária)   (= V^U + Tc*D, dívida permanente)
            - r_wacc = r_U - D/(E+D) * Tc * r_D
      15.4/15.5  Custos de dificuldades financeiras e teoria do trade-off
            - V^L = V^U + PV(dedução tributária) - PV(custos de dificuldades financeiras)
            - Alavancagem ótima = nível de dívida que maximiza V^L
      Riscos: risco do negócio x risco financeiro (variação do ROE com a dívida)

Fontes de dados (captura automática, apenas biblioteca padrão do Python):
  * Banco Central do Brasil - SGS, série 432 (Meta Selic, % a.a.) -> taxa livre de risco
  * brapi.dev - cotação, valor de mercado, dívida, caixa, beta e DRE da empresa
    (sem token funcionam PETR4, VALE3, ITUB4 e MGLU3; para outros tickers crie
     um token gratuito em https://brapi.dev e use --token ou a variável
     de ambiente BRAPI_TOKEN)

Relatórios gerados (pasta "relatorios/<empresa>_<data-hora>/"):
  * relatorio.html               -> relatório completo com tabelas e gráficos (SVG)
  * relatorio.txt                -> mesmo conteúdo em texto puro
  * simulacao_alavancagem.csv    -> tabela da simulação (abre no Excel: separador ';')
  * dados_entrada.json           -> dados usados (podem ser recarregados com --arquivo)

Como executar (Python 3.8 ou superior, nenhuma biblioteca externa é necessária):
  python estrutura_capital.py                   # menu interativo
  python estrutura_capital.py --ticker PETR4    # captura online e pergunta ajustes
  python estrutura_capital.py --ticker VALE3 --sem-perguntas --abrir
  python estrutura_capital.py --arquivo exemplo_empresa.json --sem-perguntas
  python estrutura_capital.py --exemplo         # dados de exemplo (sem internet)

Unidades: valores monetários em R$ milhões; taxas guardadas internamente como
fração (0.1375 = 13,75%) e exibidas em %.
===============================================================================
"""

# -----------------------------------------------------------------------------
# 1. IMPORTAÇÕES - somente módulos da biblioteca padrão, para que o programa
#    rode em qualquer computador com Python instalado, sem "pip install".
# -----------------------------------------------------------------------------
import argparse          # leitura dos parâmetros da linha de comando
import csv               # gravação da tabela de simulação em CSV
import datetime as dt    # data/hora para nomear a pasta do relatório
import html              # "escapar" textos inseridos no HTML
import json              # leitura das APIs e dos arquivos de dados
import math              # funções matemáticas (log10, floor, ceil)
import os                # caminhos de arquivos e variáveis de ambiente
import sys               # saída do programa e configuração do terminal
import unicodedata       # remover acentos do nome da pasta de saída
import urllib.error      # tratamento de erros de rede
import urllib.request    # requisições HTTP às APIs (BCB e brapi)
import webbrowser        # abrir o relatório HTML no navegador (opcional)
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple

# No Windows o terminal às vezes não usa UTF-8; isto evita erro com acentos.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # versões antigas do Python não têm reconfigure
    pass


# -----------------------------------------------------------------------------
# 2. CONSTANTES E TABELAS DE REFERÊNCIA
# -----------------------------------------------------------------------------

# Endereço da API do Banco Central (SGS). A série 432 é a Meta Selic definida
# pelo Copom (% ao ano). Ela é usada como taxa livre de risco (r_f) no CAPM.
URL_SELIC = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"

# Endereço da API brapi.dev. Os "modules" pedem dados fundamentalistas:
# balanço, estatísticas (beta), dados financeiros (dívida, caixa) e DRE (EBIT).
URL_BRAPI = ("https://brapi.dev/api/quote/{ticker}"
             "?modules=defaultKeyStatistics,financialData,incomeStatementHistory")

# Tickers que a brapi libera sem token (plano gratuito de teste).
TICKERS_SEM_TOKEN = ["PETR4", "VALE3", "MGLU3", "ITUB4"]

# Tabela de RATING SINTÉTICO (ilustrativa, inspirada nas tabelas públicas de
# A. Damodaran para empresas não financeiras de grande porte).
# Ideia (Cap. 14 e 15): quanto maior a dívida, menor a cobertura de juros
# (EBIT / despesa de juros), pior a classificação de crédito, maior o spread
# cobrado pelos credores e maior a probabilidade de inadimplência.
# Colunas: (cobertura mínima, rating, spread sobre r_f, prob. de default)
TABELA_RATING: List[Tuple[float, str, float, float]] = [
    (8.50, "AAA", 0.0059, 0.0007),
    (6.50, "AA",  0.0070, 0.0051),
    (5.50, "A+",  0.0092, 0.0060),
    (4.25, "A",   0.0107, 0.0066),
    (3.00, "A-",  0.0121, 0.0250),
    (2.50, "BBB", 0.0147, 0.0754),
    (2.25, "BB+", 0.0174, 0.1400),
    (2.00, "BB",  0.0221, 0.1663),
    (1.75, "B+",  0.0275, 0.2500),
    (1.50, "B",   0.0342, 0.3680),
    (1.25, "B-",  0.0515, 0.4500),
    (0.80, "CCC", 0.0820, 0.5901),
    (0.65, "CC",  0.0864, 0.7000),
    (0.20, "C",   0.1134, 0.8500),
    (-1e9, "D",   0.1512, 1.0000),
]

# Pasta onde os relatórios serão gravados (ao lado deste arquivo .py).
PASTA_BASE = os.path.dirname(os.path.abspath(__file__))


# -----------------------------------------------------------------------------
# 3. ESTRUTURA DE DADOS DE ENTRADA
#    Um "dataclass" agrupa todos os parâmetros da empresa num único objeto.
# -----------------------------------------------------------------------------
@dataclass
class DadosEmpresa:
    nome: str = "Empresa Exemplo S.A."   # nome exibido no relatório
    ticker: str = ""                     # código na B3 (se capturado online)
    E: float = 10000.0                   # valor de mercado do capital próprio (R$ mi)
    D: float = 2500.0                    # dívida bruta (R$ mi)
    caixa: float = 0.0                   # caixa e aplicações (R$ mi) - informativo
    ebit: float = 2000.0                 # lucro operacional (LAJIR/EBIT) anual (R$ mi)
    beta: float = 1.10                   # beta das ações (alavancado)
    rf: float = 0.1375                   # taxa livre de risco (Selic) - fração
    premio_mercado: float = 0.055        # prêmio de risco de mercado (E[Rm] - rf)
    Tc: float = 0.34                     # alíquota de IR + CSLL (34% no Brasil)
    rD_informado: Optional[float] = None # custo da dívida; None = estimar por rating
    custo_falencia: float = 0.25         # custos de dificuldades financeiras (% de V^U)
    variacao_cenario: float = 0.40       # choque do EBIT nos cenários de risco (+/-40%)
    passo_simulacao: float = 0.05        # passo da grade D/V (5 em 5 pontos)
    fontes: Dict[str, str] = field(default_factory=dict)  # de onde veio cada dado


# -----------------------------------------------------------------------------
# 4. FUNÇÕES AUXILIARES DE FORMATAÇÃO (padrão brasileiro: 1.234,56)
# -----------------------------------------------------------------------------
def fmt_num(x: float, casas: int = 2) -> str:
    """Formata número no padrão brasileiro (ponto no milhar, vírgula decimal)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    if math.isinf(x):
        return "∞"
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(x: float, casas: int = 2) -> str:
    """Recebe uma fração (0.1375) e devolve texto em % ('13,75%')."""
    return "-" if x is None else fmt_num(x * 100, casas) + "%"


def fmt_rs(x: float) -> str:
    """Valor monetário em R$ milhões."""
    return "R$ " + fmt_num(x, 1) + " mi"


def ler_numero(texto: str) -> float:
    """Converte texto digitado ('13,75', '1.234,5' ou '1234.5') em float."""
    t = texto.strip().replace("R$", "").replace("%", "").replace(" ", "")
    if "," in t:                      # formato brasileiro: tira pontos de milhar
        t = t.replace(".", "").replace(",", ".")
    return float(t)


# -----------------------------------------------------------------------------
# 5. CAPTURA DE DADOS
#    5.1 Internet (BCB e brapi)  5.2 Digitação  5.3 Arquivo JSON
# -----------------------------------------------------------------------------
def baixar_json(url: str, timeout: int = 20):
    """Faz um GET HTTP e devolve o JSON já convertido em dict/list do Python."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Trabalho CAD167)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def data_br(texto: Optional[str]) -> str:
    """Converte datas ISO da API ('2025-12-31' ou '2026-11-20T21:30:30Z') para dd/mm/aaaa."""
    if not texto:
        return "?"
    try:
        return dt.datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return texto


def buscar_selic() -> Optional[Tuple[float, str]]:
    """
    Captura a Meta Selic vigente no Banco Central (SGS 432).
    Retorna (taxa em fração, data) ou None se não houver conexão.
    """
    try:
        dados = baixar_json(URL_SELIC)
        ultimo = dados[-1]
        return ler_numero(ultimo["valor"]) / 100.0, ultimo["data"]
    except Exception as erro:
        print(f"  [aviso] Não foi possível obter a Selic no BCB: {erro}")
        return None


def buscar_empresa_brapi(ticker: str, token: Optional[str] = None) -> Optional[dict]:
    """
    Captura na brapi.dev os dados da empresa necessários à análise:
      - valor de mercado (E), dívida total (D), caixa, beta e EBIT anual.
    Os valores da API vêm em R$; aqui são convertidos para R$ milhões.
    """
    url = URL_BRAPI.format(ticker=ticker.upper())
    if token:
        url += "&token=" + token
    try:
        r = baixar_json(url)["results"][0]
    except urllib.error.HTTPError as erro:
        if erro.code in (401, 402, 403):
            print(f"  [aviso] A brapi exige token para {ticker}. "
                  f"Sem token funcionam: {', '.join(TICKERS_SEM_TOKEN)}.")
        else:
            print(f"  [aviso] Erro HTTP {erro.code} ao consultar a brapi.")
        return None
    except Exception as erro:
        print(f"  [aviso] Falha ao consultar a brapi: {erro}")
        return None

    est = r.get("defaultKeyStatistics") or {}
    fin = r.get("financialData") or {}
    # A DRE vem como lista; pegamos a anual (yearly) mais recente.
    dres = [x for x in (r.get("incomeStatementHistory") or []) if x.get("type") == "yearly"]
    dres.sort(key=lambda x: x.get("endDate", ""), reverse=True)
    dre = dres[0] if dres else {}

    milhoes = 1e6
    valor_mercado = r.get("marketCap") or est.get("marketCap")
    divida = fin.get("totalDebt")
    ebit = dre.get("ebit") or dre.get("operatingIncome")

    # Bancos (ex.: ITUB4) não têm "dívida" no sentido usado em estrutura de
    # capital - a análise de MM/trade-off é feita para empresas não financeiras.
    if divida is None:
        print("  [aviso] A API não informou a dívida total. Se for um banco/seguradora,"
              " a análise de estrutura de capital não se aplica da mesma forma.")

    return {
        "nome": r.get("longName") or r.get("shortName") or ticker,
        "ticker": ticker.upper(),
        "E": (valor_mercado or 0) / milhoes,
        "D": (divida or 0) / milhoes,
        "caixa": (fin.get("totalCash") or 0) / milhoes,
        "ebit": (ebit or 0) / milhoes,
        "beta": est.get("beta"),
        "preco": r.get("regularMarketPrice"),
        "data_dre": data_br(dre.get("endDate")),
        "data_cotacao": data_br(r.get("regularMarketTime")),
    }


def perguntar(rotulo: str, padrao, tipo: str = "num"):
    """
    Pergunta um valor ao usuário mostrando o valor padrão entre colchetes.
    ENTER mantém o padrão. tipo: 'num' (número), 'pct' (percentual digitado
    em %, devolvido como fração), 'txt' (texto) ou 'pct_opc' (percentual
    opcional; vazio = None).
    """
    if tipo in ("pct", "pct_opc"):
        mostra = "" if padrao is None else fmt_num(padrao * 100, 2)
        sufixo = " %"
    elif tipo == "num":
        mostra = fmt_num(padrao, 4 if abs(padrao) < 10 else 1)
        sufixo = ""
    else:
        mostra, sufixo = str(padrao), ""
    while True:
        resp = input(f"  {rotulo}{sufixo} [{mostra}]: ").strip()
        if resp == "":
            return padrao
        if tipo == "txt":
            return resp
        if tipo == "pct_opc" and resp.lower() in ("-", "auto", "nenhum"):
            return None
        try:
            valor = ler_numero(resp)
            return valor / 100.0 if tipo in ("pct", "pct_opc") else valor
        except ValueError:
            print("    Valor inválido. Digite um número (ex.: 13,75).")


def revisar_dados(d: DadosEmpresa) -> DadosEmpresa:
    """
    Mostra cada parâmetro e permite ao usuário confirmar (ENTER) ou alterar.
    É a etapa de captura/validação manual dos dados.
    """
    print("\n  Confirme ou altere os dados (ENTER mantém o valor entre colchetes):")
    d.nome = perguntar("Nome da empresa", d.nome, "txt")
    d.E = perguntar("Valor de mercado do capital próprio E (R$ mi)", d.E)
    d.D = perguntar("Dívida bruta D (R$ mi)", d.D)
    d.caixa = perguntar("Caixa e aplicações (R$ mi)", d.caixa)
    d.ebit = perguntar("EBIT / LAJIR anual (R$ mi)", d.ebit)
    d.beta = perguntar("Beta das ações", d.beta)
    d.rf = perguntar("Taxa livre de risco r_f (Selic)", d.rf, "pct")
    d.premio_mercado = perguntar("Prêmio de risco de mercado", d.premio_mercado, "pct")
    d.Tc = perguntar("Alíquota de IR+CSLL (Tc)", d.Tc, "pct")
    d.rD_informado = perguntar("Custo da dívida r_D ('auto' = estimar pelo rating)",
                               d.rD_informado, "pct_opc")
    d.custo_falencia = perguntar("Custo de dificuldades financeiras (% de V^U)",
                                 d.custo_falencia, "pct")
    d.variacao_cenario = perguntar("Choque do EBIT nos cenários (+/-)", d.variacao_cenario, "pct")
    return d


def validar(d: DadosEmpresa) -> List[str]:
    """Verifica consistência dos dados; devolve lista de erros (vazia = ok)."""
    erros = []
    if d.E <= 0:
        erros.append("O valor de mercado do capital próprio (E) deve ser positivo.")
    if d.D < 0:
        erros.append("A dívida (D) não pode ser negativa.")
    if d.ebit <= 0:
        erros.append("O EBIT deve ser positivo para a simulação de rating/cobertura.")
    if not (0 <= d.Tc < 1):
        erros.append("A alíquota Tc deve estar entre 0% e 100%.")
    if d.beta is None or d.beta <= 0:
        erros.append("O beta deve ser positivo.")
    if not (0 < d.passo_simulacao <= 0.25):
        erros.append("O passo da simulação deve estar entre 0% e 25%.")
    return erros


def capturar_online(ticker: str, token: Optional[str]) -> DadosEmpresa:
    """Monta um DadosEmpresa a partir das APIs (BCB + brapi)."""
    d = DadosEmpresa()
    print(f"\n  Consultando Banco Central (Selic)...")
    selic = buscar_selic()
    if selic:
        d.rf = selic[0]
        d.fontes["rf"] = f"BCB/SGS 432 - Meta Selic em {selic[1]}"
        print(f"    Selic = {fmt_pct(d.rf)} ({selic[1]})")
    else:
        d.fontes["rf"] = "valor padrão (sem conexão com o BCB)"

    print(f"  Consultando brapi.dev ({ticker.upper()})...")
    info = buscar_empresa_brapi(ticker, token)
    if info is None:
        print("  Não foi possível capturar a empresa; usando dados de exemplo para revisão.")
        d.fontes["empresa"] = "dados de exemplo (falha na captura online)"
        return d

    d.nome, d.ticker = info["nome"], info["ticker"]
    d.E, d.D, d.caixa, d.ebit = info["E"], info["D"], info["caixa"], info["ebit"]
    if info["beta"]:
        d.beta = float(info["beta"])
    d.fontes["empresa"] = (f"brapi.dev - cotação de {info['data_cotacao']}; "
                           f"DRE anual encerrada em {info['data_dre']}")
    print(f"    {d.nome}: E = {fmt_rs(d.E)} | D = {fmt_rs(d.D)} | "
          f"EBIT = {fmt_rs(d.ebit)} | beta = {fmt_num(d.beta, 2)}")
    return d


def carregar_json(caminho: str) -> DadosEmpresa:
    """Lê um arquivo JSON com os campos do DadosEmpresa (percentuais em fração)."""
    with open(caminho, "r", encoding="utf-8") as f:
        bruto = json.load(f)
    campos = DadosEmpresa.__dataclass_fields__.keys()
    d = DadosEmpresa(**{k: v for k, v in bruto.items() if k in campos})
    d.fontes.setdefault("empresa", f"arquivo {os.path.basename(caminho)}")
    return d


# -----------------------------------------------------------------------------
# 6. MODELOS FINANCEIROS
# -----------------------------------------------------------------------------
def classificar_rating(cobertura: float) -> Tuple[str, float, float]:
    """Dada a cobertura de juros (EBIT/juros), devolve (rating, spread, p_default)."""
    for minimo, rating, spread, prob in TABELA_RATING:
        if cobertura >= minimo:
            return rating, spread, prob
    return TABELA_RATING[-1][1:]


def custo_divida_por_rating(divida: float, ebit: float, rf: float):
    """
    Estima o custo da dívida (r_D) para um montante de dívida.
    Há uma circularidade: o rating depende dos juros, e os juros dependem do
    rating (taxa). Resolve-se por iteração até o rating se estabilizar.
    Retorna (r_D, rating, cobertura, prob_default).
    """
    if divida <= 0:
        _, rating, spread, _ = TABELA_RATING[0]
        return rf + spread, rating, math.inf, 0.0     # sem dívida não há default
    taxa = rf + TABELA_RATING[0][2]                   # começa supondo AAA
    rating, prob, cobertura = "AAA", 0.0, math.inf
    for _ in range(30):
        juros = taxa * divida
        cobertura = ebit / juros
        rating, spread, prob = classificar_rating(cobertura)
        nova_taxa = rf + spread
        if abs(nova_taxa - taxa) < 1e-10:
            break
        taxa = nova_taxa
    return taxa, rating, cobertura, prob


def aliquota_efetiva(ebit: float, juros: float, Tc: float) -> float:
    """
    O benefício fiscal só existe se houver lucro para abater os juros (Cap. 15.3).
    Se os juros superam o EBIT, só a parte coberta pelo EBIT gera economia.
    """
    if juros <= 0:
        return Tc
    if ebit <= 0:
        return 0.0
    return Tc * min(1.0, ebit / juros)


def analisar(d: DadosEmpresa) -> dict:
    """
    Núcleo da aplicação. Calcula:
      (a) situação atual: pesos, r_E (CAPM), r_D, WACC, rating;
      (b) simulações para vários níveis de D/V:
          - MM sem impostos (15.2), MM com impostos (15.3), trade-off (15.5);
      (c) estrutura ótima e cenários de risco (ROE).
    Devolve um dicionário com todos os resultados para os relatórios.
    """
    V0 = d.E + d.D                    # valor de mercado da empresa (E + D)
    d0 = d.D / V0                     # alavancagem atual D/(D+E)

    # ---------- (a) SITUAÇÃO ATUAL (Cap. 12) --------------------------------
    rE0 = d.rf + d.beta * d.premio_mercado               # CAPM
    rD_rating, rating0, cob0, prob0 = custo_divida_por_rating(d.D, d.ebit, d.rf)
    rD0 = d.rD_informado if d.rD_informado is not None else rD_rating
    juros0 = rD0 * d.D
    Tc_ef0 = aliquota_efetiva(d.ebit, juros0, d.Tc)
    wacc0 = (d.E / V0) * rE0 + (d.D / V0) * rD0 * (1 - Tc_ef0)
    # Custo de capital desalavancado (WACC antes de impostos, Cap. 12/15):
    # r_U = E/V * r_E + D/V * r_D  -> custo de capital do negócio sem dívida.
    rU = (d.E / V0) * rE0 + (d.D / V0) * rD0
    # Beta desalavancado (Hamada), usado na simulação com dívida arriscada:
    #   beta_L = beta_U * [1 + (1 - Tc) * D/E]
    betaU = d.beta / (1 + (1 - Tc_ef0) * d.D / d.E)

    # ---------- Valor da empresa não alavancada (base do trade-off) ---------
    # Partindo do valor de mercado atual e da identidade do trade-off:
    #   V0 = V^U + Tc*D0 - PV(dificuldades financeiras em d0)
    #   PV(dificuldades) = prob_default * custo_falencia * V^U
    # => V^U = (V0 - Tc*D0) / (1 - prob0 * custo_falencia)
    VU = (V0 - Tc_ef0 * d.D) / (1 - prob0 * d.custo_falencia)

    # ---------- (b) GRADE DE ALAVANCAGEM -----------------------------------
    niveis = [round(i * d.passo_simulacao, 4)
              for i in range(int(0.90 / d.passo_simulacao + 1e-9) + 1)]
    if all(abs(x - d0) > 1e-6 for x in niveis):
        niveis.append(d0)                      # inclui o ponto atual na grade
    niveis.sort()

    linhas = []
    for w in niveis:                           # w = D/V simulado
        D = w * V0                             # dívida medida sobre o valor atual
        E = V0 - D
        DE = D / E if E > 0 else math.inf

        # --- 15.2 MM sem impostos: r_D constante, r_E sobe linearmente com D/E
        rE_mm = rU + DE * (rU - rD0)
        wacc_mm = rU                           # Proposição I: WACC constante

        # --- 15.3 MM com impostos (dívida permanente, r_D constante)
        wacc_imp = rU - w * d.Tc * rD0         # r_wacc = r_U - d*Tc*r_D
        V_imp = VU + d.Tc * D                  # V^L = V^U + Tc*D

        # --- 15.4/15.5 Trade-off: dívida arriscada, r_D sobe com o rating
        rD_t, rating, cob, prob = custo_divida_por_rating(D, d.ebit, d.rf)
        if abs(w - d0) < 1e-9 and d.rD_informado is not None:
            rD_t = d.rD_informado              # mantém o custo informado no ponto atual
        juros = rD_t * D
        Tc_ef = aliquota_efetiva(d.ebit, juros, d.Tc)
        betaL = betaU * (1 + (1 - Tc_ef) * DE) if E > 0 else math.inf
        rE_t = d.rf + betaL * d.premio_mercado
        wacc_t = (E / V0) * rE_t + w * rD_t * (1 - Tc_ef)
        pv_its = Tc_ef * D                     # PV(dedução tributária dos juros)
        pv_dif = prob * d.custo_falencia * VU  # PV(custos de dificuldades financeiras)
        V_t = VU + pv_its - pv_dif             # V^L pela teoria do trade-off

        linhas.append({
            "D/V": w, "D": D, "E": E, "D/E": DE,
            "rE_mm": rE_mm, "wacc_mm": wacc_mm,
            "wacc_imp": wacc_imp, "V_imp": V_imp,
            "rating": rating, "cobertura": cob, "prob_default": prob,
            "rD": rD_t, "Tc_ef": Tc_ef, "beta_L": betaL, "rE": rE_t,
            "wacc": wacc_t, "pv_its": pv_its, "pv_dif": pv_dif, "VL": V_t,
            "atual": abs(w - d0) < 1e-9,
        })

    # ---------- (c) ESTRUTURA ÓTIMA ----------------------------------------
    otima_valor = max(linhas, key=lambda x: x["VL"])     # maximiza V^L (slide 15.5)
    otima_wacc = min(linhas, key=lambda x: x["wacc"])    # minimiza o WACC
    atual = next(x for x in linhas if x["atual"])

    # ---------- Cenários de risco: risco do negócio x risco financeiro -------
    # ROE = lucro líquido / capital próprio investido, para EBIT em 3 cenários.
    cenarios = {"Recessão": 1 - d.variacao_cenario, "Normal": 1.0,
                "Expansão": 1 + d.variacao_cenario}
    estruturas = [("Sem dívida (0%)", 0.0, d.rf + TABELA_RATING[0][2]),
                  (f"Atual ({fmt_pct(d0, 1)})", d0, atual["rD"]),
                  (f"Ótima ({fmt_pct(otima_valor['D/V'], 1)})", otima_valor["D/V"], otima_valor["rD"])]
    tabela_roe = []
    for nome, w, rD in estruturas:
        D, E = w * V0, (1 - w) * V0
        roes = {}
        for cen, fator in cenarios.items():
            lajir = d.ebit * fator
            lair = lajir - rD * D                      # lucro antes do IR
            ll = lair * (1 - d.Tc) if lair > 0 else lair  # IR só sobre lucro positivo
            roes[cen] = ll / E
        amplitude = roes["Expansão"] - roes["Recessão"]   # medida simples de risco
        tabela_roe.append({"estrutura": nome, **roes, "amplitude": amplitude})

    return {
        "V0": V0, "d0": d0, "rE0": rE0, "rD0": rD0, "rD_fonte":
            "informado pelo usuário" if d.rD_informado is not None else f"rating sintético ({rating0})",
        "wacc0": wacc0, "rU": rU, "betaU": betaU, "VU": VU, "rating0": rating0,
        "cobertura0": cob0, "prob0": prob0, "Tc_ef0": Tc_ef0, "juros0": juros0,
        "linhas": linhas, "otima_valor": otima_valor, "otima_wacc": otima_wacc,
        "atual": atual, "tabela_roe": tabela_roe,
    }


def conclusoes(d: DadosEmpresa, r: dict) -> List[str]:
    """Gera, em texto, a interpretação dos resultados para o relatório."""
    ot, at = r["otima_valor"], r["atual"]
    ganho = ot["VL"] - at["VL"]
    dif = ot["D/V"] - r["d0"]
    textos = []
    textos.append(
        f"Estrutura atual: {fmt_pct(r['d0'], 1)} de dívida e {fmt_pct(1 - r['d0'], 1)} de capital próprio "
        f"(D/E = {fmt_num(d.D / d.E, 2)}). Cobertura de juros de {fmt_num(r['cobertura0'], 2)}x, "
        f"rating sintético {r['rating0']} e WACC de {fmt_pct(r['wacc0'])}.")
    textos.append(
        f"Mercado perfeito (MM, 15.2): o WACC permaneceria em r_U = {fmt_pct(r['rU'])} para qualquer "
        f"nível de dívida - o r_E sobe exatamente o suficiente para compensar a dívida mais barata.")
    textos.append(
        f"Com impostos (15.3): cada R$ 1 de dívida permanente gera {fmt_pct(d.Tc, 0)} de economia fiscal; "
        f"o valor subiria linearmente com a dívida, o que levaria à conclusão irreal de 100% de dívida.")
    if abs(dif) <= d.passo_simulacao:
        situacao = "está PRÓXIMA da estrutura ótima estimada"
    elif dif > 0:
        situacao = "está SUB-ALAVANCADA (pode ganhar valor tomando mais dívida)"
    else:
        situacao = "está SOBRE-ALAVANCADA (os custos de dificuldades financeiras superam o benefício fiscal)"
    textos.append(
        f"Trade-off (15.5): o valor máximo V^L = {fmt_rs(ot['VL'])} ocorre com D/V = {fmt_pct(ot['D/V'], 1)} "
        f"(rating {ot['rating']}, r_D = {fmt_pct(ot['rD'])}). O WACC mínimo ({fmt_pct(r['otima_wacc']['wacc'])}) "
        f"ocorre com D/V = {fmt_pct(r['otima_wacc']['D/V'], 1)}. A empresa {situacao}.")
    if abs(dif) > d.passo_simulacao:
        delta_D = (ot["D/V"] - r["d0"]) * r["V0"]
        acao = "captar" if delta_D > 0 else "amortizar"
        textos.append(
            f"Para chegar à estrutura ótima a empresa precisaria {acao} cerca de {fmt_rs(abs(delta_D))} de dívida "
            f"(recomprando ou emitindo ações). O ganho estimado de valor para os acionistas seria de "
            f"{fmt_rs(ganho)} ({fmt_pct(ganho / r['V0'], 1)} do valor atual).")
    roe = r["tabela_roe"]
    textos.append(
        f"Risco financeiro: sem dívida, o ROE varia {fmt_pct(roe[0]['amplitude'], 1)} entre recessão e expansão "
        f"(risco do negócio). Na estrutura ótima essa amplitude passa a {fmt_pct(roe[2]['amplitude'], 1)} - "
        f"a dívida amplia o retorno e também o risco do acionista.")
    textos.append(
        "Limitações: o modelo não captura custos de agência, assimetria de informação (pecking order), "
        "flexibilidade financeira e o padrão do setor (Cap. 15.6). O resultado é uma referência para a "
        "estrutura-alvo de capital, não uma regra automática.")
    return textos


# -----------------------------------------------------------------------------
# 7. GRÁFICOS EM SVG (sem bibliotecas externas)
#    Cada gráfico é um texto SVG inserido diretamente no relatório HTML.
# -----------------------------------------------------------------------------
CORES = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2"]


def _ticks(vmin: float, vmax: float, n: int = 5) -> List[float]:
    """Calcula marcações 'redondas' para um eixo (ex.: 0, 5, 10, 15...)."""
    if vmax - vmin < 1e-12:
        vmax = vmin + 1
    bruto = (vmax - vmin) / n
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        passo = m * mag
        if (vmax - vmin) / passo <= n:
            break
    inicio = math.floor(vmin / passo) * passo
    ticks, v = [], inicio
    while v <= vmax + passo * 0.5:
        ticks.append(round(v, 10))
        v += passo
    return ticks


def grafico_svg(titulo: str, series: List[dict], rotulo_x: str, formato_y,
                marcadores: List[Tuple[float, str]] = (), largura=760, altura=380) -> str:
    """
    Desenha um gráfico de linhas.
      series     : [{'nome', 'x': [...], 'y': [...], 'tracejado': bool}]
      formato_y  : função que formata os valores do eixo Y
      marcadores : linhas verticais [(x, rótulo)] - ex.: estrutura atual/ótima
    """
    ml, mr, mt, mb = 90, 20, 40, 75                  # margens
    xs = [x for s in series for x in s["x"]]
    ys = [y for s in series for y in s["y"] if y is not None and math.isfinite(y)]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    folga = (ymax - ymin) * 0.08 or abs(ymax) * 0.1 or 1
    ticks_y = _ticks(ymin - folga, ymax + folga)
    ymin, ymax = ticks_y[0], ticks_y[-1]
    pw, ph = largura - ml - mr, altura - mt - mb

    def px(x):  # converte valor X em pixel
        return ml + (x - xmin) / (xmax - xmin) * pw

    def py(y):  # converte valor Y em pixel (Y cresce para baixo no SVG)
        return mt + ph - (y - ymin) / (ymax - ymin) * ph

    p = [f'<svg viewBox="0 0 {largura} {altura}" xmlns="http://www.w3.org/2000/svg" '
         f'role="img" aria-label="{html.escape(titulo)}" class="grafico">']
    p.append(f'<text x="{largura / 2}" y="22" text-anchor="middle" class="g-titulo">{html.escape(titulo)}</text>')
    for t in ticks_y:  # grade horizontal + rótulos do eixo Y
        p.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{py(t):.1f}" y2="{py(t):.1f}" class="g-grade"/>')
        p.append(f'<text x="{ml - 8}" y="{py(t) + 4:.1f}" text-anchor="end" class="g-eixo">{formato_y(t)}</text>')
    for t in _ticks(xmin, xmax, 9):  # rótulos do eixo X
        if xmin - 1e-9 <= t <= xmax + 1e-9:
            p.append(f'<text x="{px(t):.1f}" y="{mt + ph + 18}" text-anchor="middle" class="g-eixo">'
                     f'{fmt_num(t * 100, 0)}%</text>')
    p.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{mt + ph}" y2="{mt + ph}" class="g-base"/>')
    p.append(f'<text x="{ml + pw / 2}" y="{mt + ph + 38}" text-anchor="middle" class="g-eixo">'
             f'{html.escape(rotulo_x)}</text>')
    for i, (x, rot) in enumerate(marcadores):  # linhas verticais de referência
        p.append(f'<line x1="{px(x):.1f}" x2="{px(x):.1f}" y1="{mt}" y2="{mt + ph}" class="g-marca"/>')
        # rótulos em alturas diferentes para não se sobreporem quando próximos
        p.append(f'<text x="{px(x) + 4:.1f}" y="{mt + 12 + 14 * i}" class="g-marca-txt">{html.escape(rot)}</text>')
    for i, s in enumerate(series):  # as linhas de dados
        cor = s.get("cor", CORES[i % len(CORES)])
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(s["x"], s["y"])
                       if y is not None and math.isfinite(y))
        traco = ' stroke-dasharray="6 4"' if s.get("tracejado") else ""
        p.append(f'<polyline points="{pts}" fill="none" stroke="{cor}" stroke-width="2.5"{traco}/>')
    lx = ml  # legenda abaixo do gráfico
    for i, s in enumerate(series):
        cor = s.get("cor", CORES[i % len(CORES)])
        p.append(f'<rect x="{lx}" y="{altura - 18}" width="14" height="4" fill="{cor}"/>')
        p.append(f'<text x="{lx + 20}" y="{altura - 13}" class="g-legenda">{html.escape(s["nome"])}</text>')
        lx += 30 + 7.2 * len(s["nome"])
    p.append("</svg>")
    return "\n".join(p)


# -----------------------------------------------------------------------------
# 8. RELATÓRIOS (HTML, TXT, CSV e JSON)
# -----------------------------------------------------------------------------
def montar_tabela_texto(cabecalho: List[str], linhas: List[List[str]]) -> str:
    """Tabela alinhada em texto puro (para o terminal e o relatorio.txt)."""
    larg = [max(len(str(c)) for c in col) for col in zip(cabecalho, *linhas)]
    sep = "+".join("-" * (w + 2) for w in larg)
    fmt = lambda row: " | ".join(str(c).rjust(w) for c, w in zip(row, larg))
    return "\n".join([fmt(cabecalho), sep] + [fmt(r) for r in linhas])


def linhas_simulacao(r: dict) -> Tuple[List[str], List[List[str]]]:
    """Cabeçalho e linhas formatadas da tabela principal de simulação."""
    cab = ["D/V", "D (R$ mi)", "Rating", "Cobert.", "r_D", "beta_L", "r_E", "WACC",
           "PV benef. fiscal", "PV dific. financ.", "V^L (R$ mi)"]
    out = []
    for x in r["linhas"]:
        marca = " *" if x["atual"] else ""
        marca += " <ótimo" if x is r["otima_valor"] else ""
        out.append([fmt_pct(x["D/V"], 1) + marca, fmt_num(x["D"], 0), x["rating"],
                    fmt_num(x["cobertura"], 2) if math.isfinite(x["cobertura"]) else "∞",
                    fmt_pct(x["rD"]), fmt_num(x["beta_L"], 2), fmt_pct(x["rE"]),
                    fmt_pct(x["wacc"]), fmt_num(x["pv_its"], 0), fmt_num(x["pv_dif"], 0),
                    fmt_num(x["VL"], 0)])
    return cab, out


def resumo_atual(d: DadosEmpresa, r: dict) -> List[Tuple[str, str, str]]:
    """Indicadores da estrutura atual: (indicador, valor, como foi calculado)."""
    return [
        ("Capital próprio (E)", fmt_rs(d.E), d.fontes.get("empresa", "-")),
        ("Dívida bruta (D)", fmt_rs(d.D), "idem"),
        ("Caixa e aplicações", fmt_rs(d.caixa), "idem (informativo)"),
        ("Valor da empresa V = E + D", fmt_rs(r["V0"]), "soma"),
        ("Alavancagem D/V", fmt_pct(r["d0"]), "D / (E + D)"),
        ("D/E", fmt_num(d.D / d.E, 3), "D / E"),
        ("EBIT (LAJIR)", fmt_rs(d.ebit), d.fontes.get("empresa", "-")),
        ("Taxa livre de risco r_f", fmt_pct(d.rf), d.fontes.get("rf", "informado")),
        ("Beta das ações", fmt_num(d.beta, 3), "brapi / informado"),
        ("Prêmio de risco de mercado", fmt_pct(d.premio_mercado), "premissa"),
        ("Custo do capital próprio r_E", fmt_pct(r["rE0"]), "CAPM: r_f + beta x prêmio"),
        ("Cobertura de juros", fmt_num(r["cobertura0"], 2) + "x", "EBIT / juros"),
        ("Rating sintético", r["rating0"], "tabela de cobertura"),
        ("Custo da dívida r_D", fmt_pct(r["rD0"]), r["rD_fonte"]),
        ("Alíquota Tc (efetiva)", fmt_pct(r["Tc_ef0"]), "IR + CSLL"),
        ("WACC atual", fmt_pct(r["wacc0"]), "E/V·r_E + D/V·r_D·(1−Tc)"),
        ("Custo de capital desalavancado r_U", fmt_pct(r["rU"]), "E/V·r_E + D/V·r_D"),
        ("Beta desalavancado", fmt_num(r["betaU"], 3), "beta / [1+(1−Tc)·D/E]"),
        ("Valor não alavancado V^U", fmt_rs(r["VU"]), "V − Tc·D + PV(dificuldades)"),
    ]


def gerar_txt(d: DadosEmpresa, r: dict, quando: str) -> str:
    """Relatório completo em texto puro."""
    L = []
    L.append("=" * 100)
    L.append(f" RELATÓRIO DE ESTRUTURA DE CAPITAL - {d.nome} {('(' + d.ticker + ')') if d.ticker else ''}")
    L.append(f" Gerado em {quando}  |  valores em R$ milhões")
    L.append("=" * 100)
    L.append("\n1. SITUAÇÃO ATUAL (Cap. 12 - custo de capital)\n")
    L.append(montar_tabela_texto(["Indicador", "Valor", "Fonte / cálculo"],
                                 [list(x) for x in resumo_atual(d, r)]))
    L.append("\n2. SIMULAÇÃO DA ALAVANCAGEM - TEORIA DO TRADE-OFF (Cap. 15.4/15.5)")
    L.append("   (* = estrutura atual; <ótimo = maior valor V^L)\n")
    cab, lin = linhas_simulacao(r)
    L.append(montar_tabela_texto(cab, lin))
    L.append("\n3. MODIGLIANI-MILLER (Cap. 15.2 e 15.3)\n")
    mm = [[fmt_pct(x["D/V"], 1), fmt_num(x["D/E"], 2) if math.isfinite(x["D/E"]) else "∞",
           fmt_pct(x["rE_mm"]), fmt_pct(x["wacc_mm"]), fmt_pct(x["wacc_imp"]), fmt_num(x["V_imp"], 0)]
          for x in r["linhas"]]
    L.append(montar_tabela_texto(["D/V", "D/E", "r_E (MM)", "WACC sem IR", "WACC com IR",
                                  "V^L=V^U+Tc·D"], mm))
    L.append("\n4. RISCO DO NEGÓCIO x RISCO FINANCEIRO - ROE por cenário de EBIT\n")
    roe = [[x["estrutura"], fmt_pct(x["Recessão"]), fmt_pct(x["Normal"]), fmt_pct(x["Expansão"]),
            fmt_pct(x["amplitude"])] for x in r["tabela_roe"]]
    L.append(montar_tabela_texto(["Estrutura", f"Recessão (EBIT −{fmt_pct(d.variacao_cenario, 0)})",
                                  "Normal", f"Expansão (EBIT +{fmt_pct(d.variacao_cenario, 0)})",
                                  "Amplitude"], roe))
    L.append("\n5. CONCLUSÕES\n")
    for i, t in enumerate(conclusoes(d, r), 1):
        L.append(f"  {i}. {t}")
    L.append("")
    return "\n".join(L)


def gerar_html(d: DadosEmpresa, r: dict, quando: str) -> str:
    """Relatório completo em HTML, com tabelas e quatro gráficos SVG."""
    e = html.escape
    xs = [x["D/V"] for x in r["linhas"]]
    marc = [(r["d0"], "atual"), (r["otima_valor"]["D/V"], "ótimo")]
    pct_fmt = lambda v: fmt_num(v * 100, 1) + "%"
    mi_fmt = lambda v: fmt_num(v, 0)

    # Gráfico 1 - MM sem impostos (15.2)
    g1 = grafico_svg("MM sem impostos: custos de capital x alavancagem", [
        {"nome": "r_E (Prop. II)", "x": xs, "y": [x["rE_mm"] for x in r["linhas"]]},
        {"nome": "r_D", "x": xs, "y": [r["rD0"]] * len(xs)},
        {"nome": "WACC = r_U", "x": xs, "y": [x["wacc_mm"] for x in r["linhas"]], "tracejado": True},
    ], "Dívida / Valor da empresa (D/V)", pct_fmt, [(r["d0"], "atual")])
    # Gráfico 2 - Valor: MM com impostos x trade-off (como no slide do Cap. 15)
    g2 = grafico_svg("Valor da empresa: V^U, V^U + Tc·D e V^L (trade-off)", [
        {"nome": "V^U (sem dívida)", "x": xs, "y": [r["VU"]] * len(xs), "tracejado": True},
        {"nome": "V^U + PV(benefício fiscal)", "x": xs, "y": [r["VU"] + x["pv_its"] for x in r["linhas"]]},
        {"nome": "V^L = V^U + PV(benef.) − PV(dificuldades)", "x": xs, "y": [x["VL"] for x in r["linhas"]]},
    ], "Dívida / Valor da empresa (D/V)", mi_fmt, marc)
    # Gráfico 3 - Custos de capital no trade-off
    g3 = grafico_svg("Trade-off: custos de capital com dívida arriscada", [
        {"nome": "r_E", "x": xs, "y": [x["rE"] for x in r["linhas"]]},
        {"nome": "r_D (antes do IR)", "x": xs, "y": [x["rD"] for x in r["linhas"]]},
        {"nome": "WACC", "x": xs, "y": [x["wacc"] for x in r["linhas"]]},
    ], "Dívida / Valor da empresa (D/V)", pct_fmt,
        [(r["d0"], "atual"), (r["otima_wacc"]["D/V"], "WACC mín.")])
    # Gráfico 4 - Benefício fiscal x custo de dificuldades
    g4 = grafico_svg("Benefício fiscal x custos de dificuldades financeiras (R$ mi)", [
        {"nome": "PV benefício fiscal", "x": xs, "y": [x["pv_its"] for x in r["linhas"]], "cor": "#16a34a"},
        {"nome": "PV custos de dificuldades", "x": xs, "y": [x["pv_dif"] for x in r["linhas"]], "cor": "#dc2626"},
        {"nome": "Ganho líquido", "x": xs, "y": [x["pv_its"] - x["pv_dif"] for x in r["linhas"]], "cor": "#2563eb"},
    ], "Dívida / Valor da empresa (D/V)", mi_fmt, marc)

    def tabela(cab, linhas, destaque=None):
        h = ["<table><thead><tr>" + "".join(f"<th>{e(c)}</th>" for c in cab) + "</tr></thead><tbody>"]
        for i, l in enumerate(linhas):
            cls = f' class="{destaque[i]}"' if destaque and destaque[i] else ""
            h.append(f"<tr{cls}>" + "".join(f"<td>{e(str(c))}</td>" for c in l) + "</tr>")
        return "".join(h) + "</tbody></table>"

    cab, lin = linhas_simulacao(r)
    dest = ["otimo" if x is r["otima_valor"] else ("atual" if x["atual"] else "") for x in r["linhas"]]
    mm = [[fmt_pct(x["D/V"], 1), fmt_num(x["D/E"], 2) if math.isfinite(x["D/E"]) else "∞",
           fmt_pct(x["rE_mm"]), fmt_pct(x["wacc_mm"]), fmt_pct(x["wacc_imp"]), fmt_num(x["V_imp"], 0)]
          for x in r["linhas"]]
    roe = [[x["estrutura"], fmt_pct(x["Recessão"]), fmt_pct(x["Normal"]), fmt_pct(x["Expansão"]),
            fmt_pct(x["amplitude"])] for x in r["tabela_roe"]]
    ot = r["otima_valor"]
    cards = [("D/V atual", fmt_pct(r["d0"], 1)), ("WACC atual", fmt_pct(r["wacc0"])),
             ("D/V ótimo (máx. V^L)", fmt_pct(ot["D/V"], 1)),
             ("Ganho de valor potencial", fmt_rs(ot["VL"] - r["atual"]["VL"]))]

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estrutura de Capital - {e(d.nome)}</title>
<style>
 :root {{ --tinta:#1f2937; --suave:#6b7280; --linha:#e5e7eb; --fundo:#ffffff; --realce:#eff6ff; --ok:#ecfdf5; }}
 body {{ font-family: Segoe UI, Arial, sans-serif; color:var(--tinta); background:var(--fundo);
        max-width:1100px; margin:0 auto; padding:24px 16px 60px; line-height:1.5; }}
 h1 {{ margin-bottom:4px; }} h2 {{ margin-top:40px; border-bottom:2px solid var(--linha); padding-bottom:6px; }}
 .sub {{ color:var(--suave); }}
 .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin:20px 0; }}
 .card {{ border:1px solid var(--linha); border-radius:10px; padding:14px; }}
 .card b {{ display:block; font-size:1.5em; }} .card span {{ color:var(--suave); font-size:.9em; }}
 .tabela {{ overflow-x:auto; }}
 table {{ border-collapse:collapse; width:100%; font-size:.88em; margin:10px 0; }}
 th, td {{ border-bottom:1px solid var(--linha); padding:6px 8px; text-align:right; white-space:nowrap; }}
 th {{ background:#f9fafb; }} td:first-child, th:first-child {{ text-align:left; }}
 tr.atual {{ background:var(--realce); font-weight:600; }} tr.otimo {{ background:var(--ok); font-weight:600; }}
 .formula {{ font-family:Consolas, monospace; background:#f9fafb; padding:8px 12px; border-radius:6px; display:inline-block; }}
 svg.grafico {{ width:100%; height:auto; margin:14px 0; border:1px solid var(--linha); border-radius:8px; }}
 .g-titulo {{ font-size:15px; font-weight:600; fill:#1f2937; }} .g-eixo {{ font-size:11px; fill:#6b7280; }}
 .g-legenda {{ font-size:12px; fill:#1f2937; }} .g-grade {{ stroke:#eef0f3; }} .g-base {{ stroke:#9ca3af; }}
 .g-marca {{ stroke:#9ca3af; stroke-dasharray:3 3; }} .g-marca-txt {{ font-size:11px; fill:#374151; }}
 ol li {{ margin-bottom:8px; }} footer {{ margin-top:40px; color:var(--suave); font-size:.85em; }}
</style></head><body>
<h1>Estrutura de Capital — {e(d.nome)}{(' (' + e(d.ticker) + ')') if d.ticker else ''}</h1>
<div class="sub">Relatório gerado em {e(quando)} · valores em R$ milhões · Administração Financeira (CAD 167) — Trabalho 2</div>
<div class="cards">{''.join(f'<div class="card"><span>{e(a)}</span><b>{e(b)}</b></div>' for a, b in cards)}</div>

<h2>1. Situação atual (Cap. 12 — custo de capital)</h2>
<p><span class="formula">r<sub>WACC</sub> = E/(E+D)·r<sub>E</sub> + D/(E+D)·r<sub>D</sub>·(1 − T<sub>c</sub>)</span>
 &nbsp; com &nbsp; <span class="formula">r<sub>E</sub> = r<sub>f</sub> + β·(prêmio de mercado)</span></p>
<div class="tabela">{tabela(["Indicador", "Valor", "Fonte / cálculo"], [list(x) for x in resumo_atual(d, r)])}</div>

<h2>2. Mercado de capitais perfeito — Modigliani-Miller (Cap. 15.2)</h2>
<p>Sem impostos e sem custos de falência, o valor da empresa não depende da estrutura de capital (Proposição I).
O custo do capital próprio cresce com a alavancagem (Proposição II) e compensa exatamente a dívida mais barata,
de modo que o WACC fica constante e igual a r<sub>U</sub>.</p>
<p><span class="formula">r<sub>E</sub> = r<sub>U</sub> + D/E·(r<sub>U</sub> − r<sub>D</sub>)</span></p>
{g1}

<h2>3. Endividamento e impostos (Cap. 15.3)</h2>
<p>Os juros são dedutíveis do IR/CSLL. A dedução tributária anual é T<sub>c</sub> × juros e, para dívida permanente,
seu valor presente é T<sub>c</sub>·D.</p>
<p><span class="formula">V<sup>L</sup> = V<sup>U</sup> + T<sub>c</sub>·D</span> &nbsp;
<span class="formula">r<sub>WACC</sub> = r<sub>U</sub> − D/(E+D)·T<sub>c</sub>·r<sub>D</sub></span></p>
<div class="tabela">{tabela(["D/V", "D/E", "r_E (MM)", "WACC sem IR", "WACC com IR", "V^L = V^U + Tc·D"], mm)}</div>

<h2>4. Estrutura ótima — teoria do trade-off (Cap. 15.4 e 15.5)</h2>
<p>Com mais dívida a cobertura de juros cai, o rating piora, o custo da dívida e a probabilidade de
inadimplência sobem. O valor da empresa passa a ser:</p>
<p><span class="formula">V<sup>L</sup> = V<sup>U</sup> + PV(dedução tributária) − PV(custos de dificuldades financeiras)</span></p>
<p>PV(custos de dificuldades) = probabilidade de default (pelo rating) × custo de falência
({fmt_pct(d.custo_falencia, 0)} de V<sup>U</sup>). O beta é realavancado por
β<sub>L</sub> = β<sub>U</sub>·[1 + (1 − T<sub>c</sub>)·D/E]. A <b>alavancagem ótima</b> é a que maximiza V<sup>L</sup>.</p>
{g2}
{g4}
{g3}
<p class="sub">Nos gráficos, as linhas verticais tracejadas marcam a estrutura atual e a ótima. Na tabela,
a linha azul é a estrutura atual e a verde é a ótima (maior V<sup>L</sup>).</p>
<div class="tabela">{tabela(cab, lin, dest)}</div>

<h2>5. Risco do negócio x risco financeiro</h2>
<p>ROE (lucro líquido ÷ capital próprio) com o EBIT {fmt_pct(d.variacao_cenario, 0)} menor (recessão) e
{fmt_pct(d.variacao_cenario, 0)} maior (expansão). Sem dívida a variação reflete só o risco do negócio;
a dívida acrescenta o risco financeiro.</p>
<div class="tabela">{tabela(["Estrutura", "Recessão", "Normal", "Expansão", "Amplitude"], roe)}</div>

<h2>6. Conclusões</h2>
<ol>{''.join(f'<li>{e(t)}</li>' for t in conclusoes(d, r))}</ol>

<h2>7. Premissas e fontes</h2>
<ul>
 <li>Taxa livre de risco: {e(d.fontes.get('rf', 'informada pelo usuário'))}.</li>
 <li>Dados da empresa: {e(d.fontes.get('empresa', 'informados pelo usuário'))}.</li>
 <li>Prêmio de risco de mercado: {fmt_pct(d.premio_mercado)}; alíquota IR+CSLL: {fmt_pct(d.Tc)}.</li>
 <li>Spreads e probabilidades de default por rating: tabela ilustrativa inspirada em A. Damodaran (editável no código).</li>
 <li>A dívida simulada é medida sobre o valor atual da empresa (D = D/V × V<sub>0</sub>), como numa recapitalização.</li>
</ul>
<footer>Referência: Berk, DeMarzo &amp; Harford — Fundamentos de Finanças Empresariais, caps. 12 e 15.</footer>
</body></html>"""


def salvar_relatorios(d: DadosEmpresa, r: dict, pasta_saida: Optional[str]) -> str:
    """Grava os quatro arquivos de saída e devolve o caminho da pasta."""
    agora = dt.datetime.now()
    quando = agora.strftime("%d/%m/%Y %H:%M")
    rotulo = (d.ticker or d.nome.split()[0] or "empresa").upper()
    # remove acentos e símbolos para o nome da pasta (ex.: "INDÚSTRIA" -> "INDUSTRIA")
    rotulo = unicodedata.normalize("NFKD", rotulo).encode("ascii", "ignore").decode()
    rotulo = "".join(c for c in rotulo if c.isalnum() or c in "-_") or "EMPRESA"
    pasta = pasta_saida or os.path.join(PASTA_BASE, "relatorios",
                                        f"{rotulo}_{agora.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(pasta, exist_ok=True)

    with open(os.path.join(pasta, "relatorio.html"), "w", encoding="utf-8") as f:
        f.write(gerar_html(d, r, quando))
    with open(os.path.join(pasta, "relatorio.txt"), "w", encoding="utf-8") as f:
        f.write(gerar_txt(d, r, quando))
    # CSV com ';' e vírgula decimal para abrir direto no Excel em português.
    with open(os.path.join(pasta, "simulacao_alavancagem.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["D/V", "D", "E", "D/E", "rating", "cobertura", "prob_default", "r_D", "Tc_efetiva",
                    "beta_L", "r_E", "WACC", "PV_beneficio_fiscal", "PV_dificuldades", "V_L",
                    "r_E_MM_sem_IR", "WACC_MM_sem_IR", "WACC_MM_com_IR", "V_L_MM_com_IR", "atual"])
        for x in r["linhas"]:
            n = lambda v, c=6: fmt_num(v, c).replace(".", "") if math.isfinite(v) else ""
            w.writerow([n(x["D/V"], 4), n(x["D"], 2), n(x["E"], 2), n(x["D/E"], 4), x["rating"],
                        n(x["cobertura"], 4), n(x["prob_default"], 4), n(x["rD"]), n(x["Tc_ef"]),
                        n(x["beta_L"], 4), n(x["rE"]), n(x["wacc"]), n(x["pv_its"], 2), n(x["pv_dif"], 2),
                        n(x["VL"], 2), n(x["rE_mm"]), n(x["wacc_mm"]), n(x["wacc_imp"]), n(x["V_imp"], 2),
                        "sim" if x["atual"] else ""])
    with open(os.path.join(pasta, "dados_entrada.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(d), f, ensure_ascii=False, indent=2)
    return pasta


# -----------------------------------------------------------------------------
# 9. INTERFACE COM O USUÁRIO (menu e linha de comando)
# -----------------------------------------------------------------------------
def imprimir_resumo(d: DadosEmpresa, r: dict):
    """Mostra no terminal os principais resultados da análise."""
    print("\n" + "=" * 78)
    print(f" RESULTADO - {d.nome}")
    print("=" * 78)
    print(f"  Estrutura atual : D/V = {fmt_pct(r['d0'], 1)} | rating {r['rating0']} | "
          f"r_E = {fmt_pct(r['rE0'])} | r_D = {fmt_pct(r['rD0'])} | WACC = {fmt_pct(r['wacc0'])}")
    ot, mw = r["otima_valor"], r["otima_wacc"]
    print(f"  Ótimo (máx. V^L): D/V = {fmt_pct(ot['D/V'], 1)} | rating {ot['rating']} | "
          f"V^L = {fmt_rs(ot['VL'])} | WACC = {fmt_pct(ot['wacc'])}")
    print(f"  WACC mínimo     : D/V = {fmt_pct(mw['D/V'], 1)} | WACC = {fmt_pct(mw['wacc'])}")
    print("\n  Conclusões:")
    for i, t in enumerate(conclusoes(d, r), 1):
        print(f"   {i}. {t}")


def executar(d: DadosEmpresa, pasta_saida: Optional[str], abrir: bool):
    """Valida, analisa, imprime o resumo e grava os relatórios."""
    erros = validar(d)
    if erros:
        print("\n  Dados inválidos:")
        for e in erros:
            print("   -", e)
        return None
    r = analisar(d)
    imprimir_resumo(d, r)
    pasta = salvar_relatorios(d, r, pasta_saida)
    print(f"\n  Relatórios gravados em: {pasta}")
    for arq in ("relatorio.html", "relatorio.txt", "simulacao_alavancagem.csv", "dados_entrada.json"):
        print(f"    - {arq}")
    if abrir:
        webbrowser.open("file://" + os.path.join(os.path.abspath(pasta), "relatorio.html"))
    return pasta


def menu(args):
    """Menu interativo, usado quando o programa é chamado sem parâmetros."""
    while True:
        print("\n" + "=" * 60)
        print("   ANALISADOR DE ESTRUTURA DE CAPITAL  (Berk, caps. 12 e 15)")
        print("=" * 60)
        print("  1 - Capturar dados online por ticker (BCB + brapi.dev)")
        print("  2 - Digitar os dados manualmente")
        print("  3 - Carregar dados de um arquivo JSON")
        print("  4 - Usar empresa de exemplo (funciona sem internet)")
        print("  0 - Sair")
        op = input("  Opção: ").strip()
        if op == "0":
            print("  Até logo!")
            return
        if op == "1":
            tk = input(f"  Ticker (sem token: {', '.join(TICKERS_SEM_TOKEN)}) [PETR4]: ").strip() or "PETR4"
            d = revisar_dados(capturar_online(tk, args.token))
        elif op == "2":
            d = DadosEmpresa()
            selic = buscar_selic()          # mesmo no modo manual tenta a Selic atual
            if selic:
                d.rf = selic[0]
                d.fontes["rf"] = f"BCB/SGS 432 - Meta Selic em {selic[1]}"
            d.fontes["empresa"] = "digitado pelo usuário"
            d = revisar_dados(d)
        elif op == "3":
            caminho = input("  Caminho do arquivo [exemplo_empresa.json]: ").strip() or \
                os.path.join(PASTA_BASE, "exemplo_empresa.json")
            try:
                d = revisar_dados(carregar_json(caminho))
            except (OSError, ValueError, TypeError) as erro:
                print(f"  Não foi possível ler o arquivo: {erro}")
                continue
        elif op == "4":
            d = DadosEmpresa()
            d.fontes = {"rf": "premissa do exemplo", "empresa": "empresa hipotética de exemplo"}
        else:
            print("  Opção inválida.")
            continue
        executar(d, args.saida, args.abrir)
        input("\n  Pressione ENTER para voltar ao menu...")


def main():
    """Ponto de entrada: interpreta a linha de comando e escolhe o modo de execução."""
    p = argparse.ArgumentParser(description="Analisador de Estrutura de Capital (MM, impostos e trade-off).")
    p.add_argument("--ticker", help="código da ação na B3 para captura online (ex.: PETR4)")
    p.add_argument("--arquivo", help="arquivo JSON com os dados da empresa")
    p.add_argument("--exemplo", action="store_true", help="usa a empresa de exemplo (sem internet)")
    p.add_argument("--token", default=os.environ.get("BRAPI_TOKEN"), help="token da brapi.dev (opcional)")
    p.add_argument("--sem-perguntas", action="store_true", help="não pede confirmação dos dados capturados")
    p.add_argument("--saida", help="pasta onde gravar os relatórios")
    p.add_argument("--abrir", action="store_true", help="abre o relatório HTML no navegador ao final")
    args = p.parse_args()

    if not (args.ticker or args.arquivo or args.exemplo):
        menu(args)                                   # modo interativo
        return
    if args.ticker:
        d = capturar_online(args.ticker, args.token)
    elif args.arquivo:
        d = carregar_json(args.arquivo)
    else:
        d = DadosEmpresa()
        d.fontes = {"rf": "premissa do exemplo", "empresa": "empresa hipotética de exemplo"}
    if not args.sem_perguntas:
        d = revisar_dados(d)
    if executar(d, args.saida, args.abrir) is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
