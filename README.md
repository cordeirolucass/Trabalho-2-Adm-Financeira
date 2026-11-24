# Trabalho 2 – Analisador de Estrutura de Capital

**Disciplina:** Administração Financeira (CAD 167) – UFMG/FACE – Turma ICEX/SI – 2º/2026
**Professor:** Bruno Pérez Ferreira
**Dupla:** Lucas Oliveira Frade Ribeiro Cordeiro / Olivier Menezes Vasconcelos
**Tema escolhido:** Estrutura de Capital (Berk, DeMarzo & Harford – caps. 12 e 15)

## O que a aplicação faz

1. **Captura os dados**
   - pela internet: Selic do Banco Central (SGS 432) e, na brapi.dev, valor de mercado, dívida, caixa, beta e EBIT da empresa;
   - digitados pelo usuário, com o valor capturado já preenchido (ENTER confirma);
   - de um arquivo JSON (`exemplo_empresa.json` ou o `dados_entrada.json` de uma execução anterior).
2. **Calcula a situação atual (cap. 12):** pesos D/V e E/V, r_E pelo CAPM, r_D por rating sintético (cobertura de juros), WACC, r_U e beta desalavancado.
3. **Simula a alavancagem de 0% a 90% de D/V** em três modelos:
   - **MM sem impostos (15.2):** r_E = r_U + D/E·(r_U − r_D); o WACC fica constante;
   - **MM com impostos (15.3):** V^L = V^U + Tc·D; r_WACC = r_U − D/V·Tc·r_D;
   - **Trade-off (15.4/15.5):** V^L = V^U + PV(dedução tributária) − PV(custos de dificuldades financeiras), com r_D e a probabilidade de default subindo conforme o rating piora.
4. **Encontra a estrutura ótima** (maior V^L e menor WACC) e diz se a empresa está sub ou sobre-alavancada.
5. **Mostra o risco financeiro:** o ROE em recessão, cenário normal e expansão, sem dívida, com a dívida atual e com a dívida ótima.
6. **Gera os relatórios** em `relatorios/<EMPRESA>_<data_hora>/`:
   - `relatorio.html`: relatório completo com 4 gráficos (abre em qualquer navegador);
   - `relatorio.txt`: o mesmo conteúdo em texto;
   - `simulacao_alavancagem.csv`: tabela da simulação (Excel, separador `;`);
   - `dados_entrada.json`: os dados usados, para reproduzir a análise.

## Como executar

Requisito: **Python 3.8 ou superior**. Só usa a biblioteca padrão, então não é preciso instalar nada.

```bash
python estrutura_capital.py
```
Abre o menu interativo (1: online, 2: manual, 3: arquivo JSON, 4: exemplo).

```bash
python estrutura_capital.py --ticker PETR4 --abrir
```
Captura PETR4 online, deixa revisar os dados e abre o HTML no final.

```bash
python estrutura_capital.py --ticker VALE3 --sem-perguntas
```
Captura e analisa direto, sem perguntas.

```bash
python estrutura_capital.py --arquivo exemplo_empresa.json --sem-perguntas
```
Roda sem internet, com a empresa hipotética.

Sem token, a brapi.dev libera **PETR4, VALE3, MGLU3 e ITUB4**. Para outros tickers, crie um token gratuito em https://brapi.dev e use `--token SEU_TOKEN` ou a variável de ambiente `BRAPI_TOKEN`.
Bancos (ITUB4) não são o caso típico de estrutura de capital, porque a "dívida" de um banco é a sua matéria-prima.

## Premissas (todas podem ser alteradas na execução)

| Parâmetro | Padrão |
|---|---|
| Taxa livre de risco | Selic atual (BCB) |
| Prêmio de risco de mercado | 5,5% |
| Alíquota IR + CSLL | 34% |
| Custo de falência | 25% de V^U |
| Choque do EBIT nos cenários | ±40% |
| Tabela rating → spread → prob. de default | ilustrativa, inspirada em Damodaran (`TABELA_RATING` no código) |
