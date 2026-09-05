# Plano Oficial de Migração — Goniometria Digital da Mão (PT-BR)

> Arquivo oficial: `PLANO_MIGRACAO_PTBR.md`  
> Versão: 1.3

> [!IMPORTANT]
> **AGENTE DE IA — LEIA ESTE DOCUMENTO INTEGRALMENTE ANTES DE QUALQUER AÇÃO.**
> Este documento tem prioridade sobre instruções resumidas, suposições do agente, sugestões automáticas de refatoração e decisões tomadas em conversas anteriores que não estejam registradas aqui.
> Qualquer agente (Claude, Gemini, Antigravity, ou outro) que assumir esta tarefa deve seguir integralmente o Protocolo de Continuidade descrito na Seção 10.

---

## 1. Objetivo

Criar uma versão do projeto **Goniometria Digital da Mão** inteiramente compreensível e mantível em **Português do Brasil (pt-BR)**, incluindo:
- Texto visível ao usuário
- Comentários e docstrings do desenvolvedor
- Nomes de variáveis, funções, classes, módulos, arquivos, pastas
- Strings internas, chaves de dicionário (somente as comprovadamente Tipo A — ver Seção 3)
- Valores de estado, retorno e condicionais internos
- Nomes de colunas e classes de dados (exceto contratos externos — ver Seção 5)

O repositório original em inglês permanece **intacto e separado**.

---

## 2. Exceções Absolutas — NUNCA TRADUZIR

| Categoria | Exemplos |
|---|---|
| Palavras-chave Python | `def`, `class`, `return`, `if`, `for`, `import`, `True`, `False` |
| Bibliotecas externas | `mediapipe`, `cv2`, `numpy`, `PyQt6`, `fpdf`, `pyqtgraph` |
| APIs externas | Métodos de bibliotecas: `.landmark`, `.setText()`, `.connect()` |
| Siglas clínicas | **TAM, ROM, MCP, PIP, DIP, IP, ABD, ASSH, EMA** |
| Siglas técnicas | **FPS, CSV, PDF, Hz, CV** |
| Nomes de tecnologias | MediaPipe, OpenCV, PyQt6, PyQtGraph, Python, NumPy, FPDF, Kalman |
| Formatos e extensões | `.csv`, `.pdf`, `.log`, `.py`, `.md` |
| Cabeçalhos do CSV gerado | Ver Seção 5 |
| URLs, comandos pip/git | `pip install`, `git commit`, etc. |
| **Métodos de framework, callbacks e overrides** | `paintEvent`, `closeEvent`, `resizeEvent`, `showEvent`, `eventFilter`, `timerEvent`, `mousePressEvent`, `keyPressEvent` — qualquer método chamado indiretamente pelo framework |
| **Métodos herdados ou implementações de protocolos** | Métodos que substituem comportamento de classe-base ou são chamados indiretamente por PyQt6 ou qualquer outra biblioteca |

> [!WARNING]
> **ATENÇÃO — Métodos aparentemente genéricos não são automaticamente seguros para renomeação.**
> Métodos como `update()`, `reset()` ou `configure()` podem ser:
> - Métodos internos do desenvolvedor (renomeáveis)
> - Métodos herdados de uma classe PyQt (não renomeáveis)
> - Métodos esperados por um componente externo (não renomeáveis)
> - Chamados por outro módulo via referência indireta (não renomeáveis)
> - Parte de uma interface informal do projeto (verificar antes)
>
> Antes de renomear qualquer método, o agente deve verificar:
> - Classe-base da classe que o define
> - Métodos herdados da classe-base e da cadeia de herança
> - Se o nome coincide com qualquer método de PyQt6 ou outra biblioteca
> - Uso por callbacks, signals/slots, introspecção ou reflexão
> - Todas as chamadas internas em todos os arquivos
> - Todos os testes
> - Todos os consumidores externos
>
> **Somente métodos comprovadamente criados pelo desenvolvedor e sem nenhuma das condições acima podem ser migrados para pt-BR.**

---

## 3. Tabela Definitiva de Migração EN → PT-BR

### 3.1 Classificações Clínicas ASSH

| EN | PT-BR | Preservar? |
|---|---|---|
| `"Excellent"` | `"Excelente"` | Migrar |
| `"Good"` | `"Bom"` | Migrar |
| `"Fair"` | `"Razoável"` | Migrar |
| `"Poor"` | `"Ruim"` | Migrar |

### 3.2 Lado da Mão

| EN | PT-BR |
|---|---|
| `"Right"` | `"Direita"` |
| `"Left"` | `"Esquerda"` |
| `is_right_hand` | `eh_mao_direita` (sem acento em identificadores Python) |

### 3.3 Estados de Regularidade

| EN | PT-BR | Preservar? |
|---|---|---|
| `"Regular"` | `"Regular"` | **PRESERVADO** — idêntico em pt-BR |
| `"Moderate"` | `"Moderado"` | Migrar |
| `"Irregular"` | `"Irregular"` | **PRESERVADO** — idêntico em pt-BR |

### 3.4 Chaves de Métricas em Tempo Real (candidatas a Tipo A — validação obrigatória antes da migração)

> [!IMPORTANT]
> Nenhuma chave será tratada como Tipo A apenas por suposição. Antes da migração, o agente deve confirmar que a chave não é salva em CSV, gravada em JSON, serializada, usada em cache, presente em arquivos de sessão, enviada por API, consumida por scripts externos, lida por dashboards externos, ou usada em testes que representem contrato de dados. Somente após essa confirmação a chave pode ser traduzida.

| Chave EN | Chave PT-BR | Preservar? | Justificativa |
|---|---|---|---|
| `"rom"` | `"rom"` | **PRESERVADO** | Sigla técnica ROM — nunca traduzir |
| `"avg_velocity"` | `"vel_media"` | Migrar (validar Tipo A) | Aparentemente apenas em memória |
| `"peak_velocity"` | `"vel_pico"` | Migrar (validar Tipo A) | Aparentemente apenas em memória |
| `"freq_hz"` | `"freq_hz"` | **PRESERVADO** | Sigla técnica Hz |
| `"cv"` | `"cv"` | **PRESERVADO** | Sigla técnica CV |
| `"regularity"` | `"regularidade"` | Migrar (validar Tipo A) | Aparentemente apenas em memória |
| `"n_picos"` | `"n_picos"` | **PRESERVADO** | Já em português |

### 3.5 Chaves do Dicionário de Estado da Mão (candidatas a Tipo A — validação obrigatória antes da migração)

| EN | PT-BR |
|---|---|
| `"finger_states"` | `"estados_dedos"` |
| `"assh_label"` | `"rotulo_assh"` |
| `"assh_color"` | `"cor_assh"` |
| `"closed"` | `"fechado"` |
| `"hand_open"` | `"mao_aberta"` |
| `"closed_count"` | `"dedos_fechados"` |

### 3.6 Chaves do Dicionário de Classificação Clínica (candidatas a Tipo A — validação obrigatória antes da migração)

| EN | PT-BR | Preservar? |
|---|---|---|
| `"label"` | `"rotulo"` | Migrar (validar Tipo A) |
| `"color"` | `"cor"` | Migrar (validar Tipo A) |
| `"source"` | `"origem"` | Migrar (validar Tipo A) |
| `"articular_tam"` | `"articular_tam"` | **PRESERVADO** — contém sigla TAM |
| `"functional_session"` | `"sessao_funcional"` | Migrar (validar Tipo A) |
| `"final_hybrid"` | `"hibrido_final"` | Migrar (validar Tipo A — todos os consumidores devem ser atualizados no mesmo grupo) |
| `"explanation"` | `"explicacao"` | Migrar (validar Tipo A) |
| `"valid_cycles"` | `"ciclos_validos"` | Migrar (validar Tipo A) |
| `"good_hits"` | `"acertos_bom"` | Migrar (validar Tipo A) |
| `"excellent_hits"` | `"acertos_excelente"` | Migrar (validar Tipo A) |
| `"success_rate_good"` | `"taxa_sucesso_bom"` | Migrar (validar Tipo A) |
| `"success_rate_excellent"` | `"taxa_sucesso_excelente"` | Migrar (validar Tipo A) |
| `"best_peak"` | `"melhor_pico"` | Migrar (validar Tipo A) |
| `"mean_peak"` | `"media_picos"` | Migrar (validar Tipo A) |

### 3.7 Estados de Estabilidade do Filtro (candidatos a Tipo A — validação obrigatória antes da migração)

| EN | PT-BR |
|---|---|
| `"stable"` | `"estavel"` |
| `"converging"` | `"convergindo"` |
| `"unstable"` | `"instavel"` |
| `"uninitialized"` | `"nao_inicializado"` |

### 3.8 Nomes de Classes

| EN | PT-BR | Arquivo |
|---|---|---|
| `MainWindow` | `JanelaPrincipal` | `ui/main_window.py` |
| `SessionHeaderWidget` | `WidgetCabecalhoSessao` | `ui/session_header.py` |
| `LogWidget` | `WidgetLog` | `ui/log_widget.py` |
| `VideoWidget` | `WidgetVideo` | `ui/video_widget.py` |
| `FingerCardWidget` | `WidgetCartaoDedo` | `ui/finger_card_widget.py` |
| `PlotWidget` | `WidgetGrafico` | `ui/plot_widget.py` |
| `MetricsWidget` | `WidgetMetricas` | `ui/metrics_widget.py` |
| `CameraWorker` | `TrabalhadorCamera` | `workers/camera_worker.py` |
| `ProcessingWorker` | `TrabalhadorProcessamento` | `workers/processing_worker.py` |
| `DigitalGoniometer` | `GoniometroDigital` | `goniometry.py` |
| `GoniometryFilterBank` | `BancoFiltrosGoniometria` | `smoothing.py` |
| `SeriesFilter` | `FiltroSerie` | `smoothing.py` |
| `GoniometryCSVLogger` | `RegistradorCSVGoniometria` | `goniometry_csv.py` (confirmar que não é instanciada por string, configuração ou reflexão antes de renomear) |

> [!NOTE]
> `WidgetLog` pode permanecer assim. `Log` é termo técnico universal e não precisa ser forçado a `WidgetRegistro`.

### 3.9 Nomes de Arquivos e Módulos

| EN | PT-BR |
|---|---|
| `app_pyqt.py` | `aplicacao.py` |
| `config.py` | `configuracao.py` |
| `dashboard_utils.py` | `utilitarios_painel.py` |
| `clinical_classification.py` | `classificacao_clinica.py` |
| `goniometry.py` | `goniometria.py` |
| `goniometry_csv.py` | `goniometria_csv.py` |
| `goniometry_overlay.py` | `sobreposicao_goniometria.py` |
| `session_report.py` | `relatorio_sessao.py` |
| `smoothing.py` | `suavizacao.py` |
| `themes.py` | `temas.py` |

### 3.10 Nomes de Pastas

| EN | PT-BR | Quando executar |
|---|---|---|
| `ui/` | `interface/` | Grupo 13 — após auditoria completa de referências |
| `workers/` | `trabalhadores/` | Grupo 13 — após auditoria completa de referências |
| `tests/` | `testes/` | Grupo 13 — após auditoria completa de referências |

### 3.11 Constantes de Configuração (`config.py`)

| EN | PT-BR |
|---|---|
| `FINGERS` | `DEDOS` |
| `FINGER_NAMES` | `NOMES_DEDOS` |
| `FINGER_COLORS` | `CORES_DEDOS` |
| `FINGER_COLORS_RGB` | `CORES_DEDOS_RGB` |
| `TAM_CEILING` | `TETO_TAM` |
| `APP_TITLE` (valor) | `"Goniometria Digital da Mão"` |
| `"Index"` | `"Indicador"` (candidato — confirmar que é apenas label de exibição) |
| `"Middle"` | `"Médio"` (candidato — confirmar que é apenas label de exibição) |
| `"Ring"` | `"Anelar"` (candidato — confirmar que é apenas label de exibição) |
| `"Little"` | `"Mínimo"` (candidato — confirmar que é apenas label de exibição) |
| `"Thumb"` | `"Polegar"` (candidato — confirmar que é apenas label de exibição) |

### 3.12 Funções de `dashboard_utils.py`

| EN | PT-BR | Observação |
|---|---|---|
| `assh_classify()` | `classificar_assh()` | Verificar todos os chamadores antes |
| `assh_classify_thumb()` | `classificar_assh_polegar()` | Verificar todos os chamadores antes |
| `tam_progress()` | `progresso_tam()` | Verificar todos os chamadores antes |
| `classify_hand_state()` | `classificar_estado_mao()` | Verificar todos os chamadores antes |
| `compute_realtime_metrics()` | `calcular_metricas_tempo_real()` | Chamada por `processing_worker` e `session_report` |
| `compute_session_metrics_from_buffers()` | `calcular_metricas_sessao_dos_buffers()` | Verificar todos os chamadores |
| `build_tam_chart_data()` | `construir_dados_grafico_tam()` | Verificar todos os chamadores |
| `freq_label()` | `rotulo_frequencia()` | Verificar todos os chamadores |
| `regularity_label()` | `rotulo_regularidade()` | Verificar todos os chamadores |
| `_detect_peaks()` | `_detectar_picos()` | Privada — verificar uso em testes |
| `_detect_valleys()` | `_detectar_vales()` | Privada — verificar uso em testes |
| `_estimate_fps()` | `_estimar_fps()` | Privada — verificar uso em testes |
| `_safe_mean()` | `_media_segura()` | Privada — verificar uso em testes |
| `_safe_std()` | `_desvio_seguro()` | Privada — verificar uso em testes |

### 3.13 Métodos de `smoothing.py` (verificar herança antes de qualquer renomeação)

> [!CAUTION]
> Verificar a cadeia de herança de `SeriesFilter` e `GoniometryFilterBank` antes de renomear qualquer método. Métodos como `update()`, `reset()`, `configure()` podem coincidir com métodos de classe-base Python ou PyQt6. Confirmar que são exclusivamente definidos pelo desenvolvedor.

| EN | PT-BR | Verificar herança? |
|---|---|---|
| `update()` | `atualizar()` | **SIM** — pode colidir com Qt ou Python |
| `reset()` | `resetar()` | **SIM** — verificar classe-base |
| `reset_finger()` | `resetar_dedo()` | Baixo risco — nome específico |
| `reset_all()` | `resetar_todos()` | Baixo risco — nome específico |
| `smooth_all()` | `suavizar_todos()` | Baixo risco — nome específico |
| `get_stability()` | `obter_estabilidade()` | Baixo risco |
| `get_all_gains()` | `obter_todos_ganhos()` | Baixo risco |
| `configure()` | `configurar()` | **SIM** — verificar se é chamado por framework |
| `kalman_gain` (property) | `ganho_kalman` | Verificar chamadores |
| `stability` (property) | `estabilidade` | Verificar chamadores |
| `is_initialized` (property) | `esta_inicializado` | Verificar chamadores |
| `active_series_count` (property) | `contagem_series_ativas` | Verificar chamadores |

### 3.14 Termos Não Listados no Plano

As tabelas desta Seção 3 representam os termos já identificados e previamente avaliados. Elas não autorizam a tradução automática de qualquer outro identificador em inglês encontrado no projeto.

Se o agente localizar um termo não listado, incluindo variável, função, classe, módulo, arquivo, pasta, chave de dicionário, valor interno, constante, atributo, sinal PyQt, slot, enumeração, configuração, nome de campo ou texto técnico, ele deve:
1. Registrar o termo encontrado.
2. Informar arquivo e linha aproximada.
3. Explicar o contexto de uso.
4. Buscar todas as referências no projeto.
5. Classificar o termo como:
   - texto humano;
   - identificador interno;
   - contrato externo;
   - API de biblioteca;
   - callback/override;
   - formato de dado;
   - sigla técnica;
   - termo ambíguo.
6. Propor a tradução, se houver.
7. Informar impactos possíveis.
8. Aguardar autorização explícita do usuário antes de alterar o termo.

**Regra:** Termo não listado no plano = termo não autorizado para alteração automática.

---

## 4. Termos Preservados — Resumo Consolidado

| Termo | Motivo |
|---|---|
| `TAM`, `ROM`, `MCP`, `PIP`, `DIP`, `IP`, `ABD` | Siglas clínicas ASSH |
| `ASSH`, `EMA`, `Kalman`, `FPS`, `CSV`, `PDF`, `Hz`, `CV` | Siglas técnicas universais |
| `"rom"` (chave de dict) | Sigla ROM — preservada mesmo sendo interna |
| `"freq_hz"` (chave) | Sigla Hz |
| `"cv"` (chave) | Sigla CV |
| `"n_picos"` (chave) | Já em português |
| `"Regular"`, `"Irregular"` (valores) | Idênticos em pt-BR |
| `"articular_tam"` (chave de origem) | Contém sigla TAM |
| `INDEX`, `MIDDLE`, `RING`, `PINKY`, `THUMB` | Chaves da pipeline de ângulos em todo o sistema |
| Cabeçalhos CSV | Ver Seção 5 |
| Callbacks e overrides de framework | Ver Seção 2 |

---

## 5. Contratos Externos — CSV (Imutáveis)

Os seguintes cabeçalhos **não podem ser alterados**. São o contrato de exportação de dados clínicos e podem ser consumidos por planilhas, sistemas externos ou análise posterior.

```
timestamp, frame_id,
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_ABD, INDEX_TAM,
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_ABD, MIDDLE_TAM,
RING_MCP, RING_PIP, RING_DIP, RING_ABD, RING_TAM,
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_ABD, PINKY_TAM,
THUMB_MCP, THUMB_IP, THUMB_TAM
```

**Pode traduzir em `goniometry_csv.py`:** nome da constante (`CSV_FIELDS` → `CAMPOS_CSV`), nome da classe, docstrings, comentários.
**Não pode alterar:** os valores string dentro da lista de campos.

---

## 6. Inventário de Dados Persistidos e Exportados

| Dado | Formato | Destino | Pode migrar chaves? |
|---|---|---|---|
| Ângulos por frame | CSV em disco | Arquivo gerado | ❌ Cabeçalhos preservados |
| Relatório clínico | PDF em disco | Arquivo gerado | ✅ Textos visíveis |
| Log do sistema | `.log` em disco | Arquivo gerado | ✅ Mensagens de log |
| Dicionário de métricas | Memória (candidato Tipo A) | Entre módulos | ✅ Após validação Tipo A |
| Dicionário de estado da mão | Memória (candidato Tipo A) | Entre módulos | ✅ Após validação Tipo A |
| Dicionário de classificação | Memória (candidato Tipo A) | Entre módulos | ✅ Após validação Tipo A |

---

## 7. Dependências por Módulo (após migração de nomes)

```
configuracao.py (era config.py)
  └── importado por: TODOS os módulos

suavizacao.py (era smoothing.py)
  └── importado por: trabalhadores/trabalhador_processamento.py

goniometria_csv.py (era goniometry_csv.py)
  └── importado por: trabalhadores/trabalhador_processamento.py

goniometria.py (era goniometry.py)
  └── importado por: trabalhadores/trabalhador_processamento.py
  └── importado por: sobreposicao_goniometria.py (verificar ordem de import após renomeação)

sobreposicao_goniometria.py (era goniometry_overlay.py)
  └── importado por: trabalhadores/trabalhador_processamento.py

utilitarios_painel.py (era dashboard_utils.py)
  └── importado por: trabalhadores/trabalhador_processamento.py
  └── importado por: relatorio_sessao.py
  └── importado por: interface/widget_cartao_dedo.py

classificacao_clinica.py (era clinical_classification.py)
  └── importado por: trabalhadores/trabalhador_processamento.py
  └── importado por: relatorio_sessao.py

relatorio_sessao.py (era session_report.py)
  └── importado por: interface/janela_principal.py

temas.py (era themes.py)
  └── importado por: aplicacao.py + todos os widgets de interface/

trabalhadores/trabalhador_camera.py (era workers/camera_worker.py)
  └── importado por: interface/janela_principal.py

trabalhadores/trabalhador_processamento.py (era workers/processing_worker.py)
  └── importado por: interface/janela_principal.py

interface/janela_principal.py (era ui/main_window.py)
  └── importado por: aplicacao.py (era app_pyqt.py)
```

---

## 8. Estado Atual da Migração

| Arquivo | Status | Detalhe |
|---|---|---|
| `clinical_classification.py` | 🟡 Parcial | Docstrings/comentários/textos traduzidos. Chaves e valores internos ainda em EN. |
| `ui/log_widget.py` | 🟡 Parcial | Docstrings/comentários traduzidos. `# PUBLIC INTERFACE` e `# INTERNAL METHODS` ainda em EN. |
| `ui/session_header.py` | 🟡 Parcial | Docstrings/comentários/labels traduzidos. `"Right"/"Left"` preservados (pendente Grupo 6). `# FORM SECTION BUILDERS` ainda em EN. |
| Todos os demais | ⬜ Pendente | Sem alterações |
| Git local | ❌ Não inicializado | Criar como pré-requisito |

---

## 9. Ordem Incremental de Execução

### PRÉ-REQUISITO — Git Local e Baseline

**Passo 1 — Verificar .gitignore**
Antes do `git add .`, confirmar que `.gitignore` exclui adequadamente:
```
.venv/
__pycache__/
*.pyc
*.pyo
*.log
```
A pasta `logs/` não deve ser ignorada, removida ou excluída automaticamente. Antes de adicionar `logs/` ao `.gitignore`, o agente deve inspecionar seu conteúdo e informar:
1. Quais arquivos existem na pasta.
2. Se são arquivos temporários, dados de exemplo, artefatos de teste ou arquivos necessários ao projeto.
3. Se existem arquivos relevantes para reprodução, validação, documentação ou pesquisa.
4. Se há risco de versionar dados sensíveis.
5. Se a pasta inteira pode ser ignorada, ou se apenas padrões específicos devem ser ignorados.

Somente após autorização explícita do usuário a pasta `logs/` poderá ser adicionada ao `.gitignore`.

**Passo 2 — Inicializar Git local**
```bash
git init
git add .
git commit -m "Base local auditada antes da migração interna pt-BR"
```
> Este commit NÃO é a cópia inglesa original. Três arquivos já possuem traduções parciais auditadas. A mensagem reflete isso.

**Passo 3 — Registrar baseline compilável, versões e ambiente**
```bash
python --version
python -m pip freeze
python -m compileall -q .
python -m pytest
```
E registrar o resultado em um relatório de baseline: `BASELINE_MIGRACAO_PTBR.md`.

O relatório deve registrar:
- Data e hora da validação;
- Sistema operacional;
- Versão do Python;
- Ambiente virtual utilizado;
- Resultado de `python -m compileall -q .`;
- Resultado de `python -m pytest`;
- Quantidade de testes executados;
- Quantidade de testes aprovados;
- Quantidade de falhas preexistentes, se houver;
- Bibliotecas relevantes instaladas;
- Observações sobre câmera, PyQt6, MediaPipe e PyQtGraph.

Essa linha de base é essencial para distinguir:
- *Erro causado pela migração*
de:
- *Erro causado por dependência, versão de Python, PyQt6, MediaPipe ou ambiente local.*

---

### ETAPA 0 — Finalizar Traduções de Texto Puro Pendentes

**Arquivos:** `ui/log_widget.py`, `ui/session_header.py`
**Escopo:** somente cabeçalhos de seção em inglês remanescentes

| Arquivo | Linha | Original | PT-BR |
|---|---|---|---|
| `ui/log_widget.py` | 134 | `# PUBLIC INTERFACE` | `# INTERFACE PÚBLICA` |
| `ui/log_widget.py` | 220 | `# INTERNAL METHODS` | `# MÉTODOS INTERNOS` |
| `ui/session_header.py` | 127 | `# FORM SECTION BUILDERS` | `# CONSTRUTORES DO FORMULÁRIO` |

**Validação:**
```bash
python -m compileall -q .
python -m pytest
```
**Commit:** `"Etapa 0: cabeçalhos de seção restantes traduzidos"`

---

### GRUPO 1 — Classificações Clínicas ASSH
**Termos:** `Excellent→Excelente`, `Good→Bom`, `Fair→Razoável`, `Poor→Ruim`
**Arquivos (em ordem):** `clinical_classification.py`, `dashboard_utils.py`, `goniometry.py`, `goniometry_overlay.py`, `session_report.py`, `tests/test_kinematic_assessment.py`
**Validação:** `python -m compileall -q .` + `python -m pytest`
**Commit:** `"Grupo 1: classificações ASSH migradas (Excelente/Bom/Razoável/Ruim)"`

---

### GRUPO 2 — Regularidade Parcial
**Termos:** `Moderate→Moderado`
**Arquivos:** `dashboard_utils.py`, `session_report.py`, `ui/finger_card_widget.py`
**Validação:** `python -m compileall -q .` + `python -m pytest`
**Commit:** `"Grupo 2: Moderate → Moderado"`

---

### GRUPO 3 — Chaves de Métricas
**Termos:** `avg_velocity→vel_media`, `peak_velocity→vel_pico`, `regularity→regularidade`
**Pré-requisito:** confirmar Tipo A para cada chave (ver Seção 3.4)
**Arquivos:** `dashboard_utils.py`, `session_report.py`, `clinical_classification.py`, `ui/finger_card_widget.py`, `workers/processing_worker.py`
**Validação:** `python -m compileall -q .` + `python -m pytest`
**Commit:** `"Grupo 3: chaves de métricas migradas"`

---

### GRUPO 4 — Estado da Mão
**Termos:** ver Seção 3.5
**Pré-requisito:** confirmar Tipo A para cada chave
**Arquivos:** `dashboard_utils.py`, `ui/finger_card_widget.py`, `session_report.py`, `tests/`
**Validação:** `python -m compileall -q .` + `python -m pytest`
**Commit:** `"Grupo 4: chaves de estado da mão migradas"`

---

### GRUPO 5 — Classificação Clínica
**Termos:** ver Seção 3.6
**Pré-requisito:** confirmar Tipo A para cada chave; `"hibrido_final"` requer atualização de TODOS os consumidores no mesmo grupo
**Arquivos:** `clinical_classification.py`, `workers/processing_worker.py`, `session_report.py`
**Validação:** `python -m compileall -q .` + `python -m pytest`
**Commit:** `"Grupo 5: chaves de classificação clínica migradas"`

---

### GRUPO 6 — Lado da Mão
**Termos:** `Right→Direita`, `Left→Esquerda`, `is_right_hand→eh_mao_direita`
**Arquivos:** `goniometry.py`, `ui/session_header.py`, `workers/processing_worker.py`, `goniometry_overlay.py`, `tests/`
**Atenção:** Localizar TODAS as referências que recebem "Right" ou "Left" por sinais, configuração ou dados gravados antes de executar.
**Validação:** `python -m compileall -q .` + `python -m pytest` + testar seleção de mão na interface
**Commit:** `"Grupo 6: lado da mão migrado (Direita/Esquerda, eh_mao_direita)"`

---

### GRUPO 7 — Estabilidade do Filtro
**Termos:** ver Seção 3.7
**Pré-requisito:** confirmar Tipo A; verificar se algum consumidor compara os valores por string
**Arquivos:** `smoothing.py`, `workers/processing_worker.py`
**Validação:** `python -m compileall -q .` + `python -m pytest`
**Commit:** `"Grupo 7: estados de estabilidade do filtro migrados"`

---

### GRUPO 8 — Textos, UI, Comentários, Docstrings (arquivo a arquivo)

Um arquivo por vez. Para cada arquivo:
1. Traduzir apenas comentários, docstrings, strings de UI sem função programática
2. `python -m compileall -q .`
3. `python -m pytest`
4. Commit: `"Grupo 8: textos de <arquivo> traduzidos"`

---

### GRUPO 9 — Constantes de Configuração e Labels de Dedos
**Termos:** ver Seção 3.11 — tratar `"Index"`, `"Middle"` etc. como candidatos até confirmar que são apenas labels de exibição
**Arquivos:** `config.py` + todos os consumidores de `FINGER_NAMES`
**Validação:** `python -m compileall -q .` + `python -m pytest` + verificar interface e PDF
**Commit:** `"Grupo 9: constantes de configuração migradas"`

---

### GRUPO 10 — Funções e Métodos (um por vez)

Para cada função:
1. Mapear todos os chamadores no projeto inteiro
2. Verificar herança e callbacks (ver Seção 2)
3. Renomear a definição
4. Atualizar todos os chamadores
5. `python -m compileall -q .`
6. `python -m pytest`
7. Commit: `"Grupo 10: função <nome> renomeada para pt-BR"`

---

### GRUPO 11 — Nomes de Classes (uma por vez)

Ordem: classes sem dependentes antes de classes com dependentes.
1. `FiltroSerie` (usado por `BancoFiltrosGoniometria`)
2. `BancoFiltrosGoniometria` (usado por `TrabalhadorProcessamento`)
3. `RegistradorCSVGoniometria` (confirmar que não é instanciada por string ou reflexão)
4. `GoniometroDigital`
5. `TrabalhadorCamera`
6. `TrabalhadorProcessamento`
7. Widgets: `WidgetLog`, `WidgetVideo`, `WidgetCartaoDedo`, `WidgetGrafico`, `WidgetMetricas`, `WidgetCabecalhoSessao`
8. `JanelaPrincipal`

Para cada classe: mapear imports e instanciações → renomear → atualizar → validar → commit.
Commit por classe: `"Grupo 11: classe <Nome> migrada para pt-BR"`

---

### GRUPO 12 — Nomes de Arquivos e Módulos (um por vez)

**Protocolo obrigatório para cada arquivo:**
1. Localizar todos os imports do módulo em todo o projeto
2. Renomear somente esse arquivo
3. Atualizar somente os imports desse módulo em todos os arquivos
4. `python -m compileall -q .`
5. `python -m pytest`
6. Testar funcionalidades relacionadas ao módulo, se aplicável
7. Commit: `"Grupo 12: módulo <nome> renomeado para pt-BR"`
8. PARAR. Aguardar autorização antes do próximo arquivo.

> [!CAUTION]
> **NÃO executar** uma instrução genérica como "renomeie todos os arquivos da Seção 3.9 de uma vez." Cada renomeação é uma operação independente com validação própria.

**Exemplo de execução incremental para `goniometry.py` em PowerShell:**
1. Localizar referências Python:
```powershell
Get-ChildItem -Path . -Recurse -Filter *.py | Select-String -Pattern "goniometry"
```
2. Localizar referências também em documentação e configuração:
```powershell
Get-ChildItem -Path . -Recurse -File | Where-Object { $_.Extension -in ".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".ini" } | Select-String -Pattern "goniometry"
```
3. Renomear somente:
```text
goniometry.py → goniometria.py
```
4. Atualizar todos os imports:
```python
import goniometry
from goniometry import ...
```
para:
```python
import goniometria
from goniometria import ...
```
5. Compilar:
```powershell
python -m compileall -q .
```
6. Testar o import:
```powershell
python -c "from goniometria import GoniometroDigital"
```
7. Executar os testes:
```powershell
python -m pytest
```
8. Criar o commit local:
```powershell
git add .
git commit -m "Grupo 12.1: goniometry.py → goniometria.py"
```
9. Parar e aguardar autorização antes de renomear outro módulo.

---

### GRUPO 13 — Renomeação de Pastas (auditoria completa obrigatória)

**Antes de executar qualquer renomeação, localizar referências em:**
- Todos os imports Python: `from ui.xxx import`, `from workers.xxx import`
- `__init__.py` de `ui/` e `workers/`
- Comandos pytest no `README.md`
- Caminhos relativos em arquivos de configuração
- `.github/` (se existir)
- Scripts de terminal, workflows, arquivos ocultos

**Execução incremental (uma pasta por vez):**
1. `ui/` → `interface/`: renomear → atualizar imports → validar → commit
2. `workers/` → `trabalhadores/`: renomear → atualizar imports → validar → commit
3. `tests/` → `testes/`: renomear → atualizar configuração pytest → validar → commit

Após renomear `tests/` para `testes/`, executar obrigatoriamente:
```powershell
python -m pytest testes -v
```
Também verificar se existe alguma configuração de pytest que aponta explicitamente para `tests/` (como `tests/`, `pytest tests/`, `python -m pytest tests/`) em:
- `README.md`
- scripts `.bat`, `.ps1` ou `.sh`
- arquivos `.yml` e `.yaml`
- `.github/`
- `pyproject.toml`
- `pytest.ini`
- `setup.cfg`
- `tox.ini`

Commit por pasta: `"Grupo 13: pasta <nome>/ renomeada para <nome_ptbr>/"`

---

## 10. Protocolo Obrigatório de Continuidade Entre Agentes

Este projeto poderá ser continuado por diferentes agentes de IA, incluindo Claude, Gemini, Antigravity ou qualquer outro agente. Todo agente que assumir esta tarefa deve obedecer a este protocolo antes de analisar tecnicamente, editar, traduzir, renomear, mover, criar ou excluir qualquer arquivo.

### 10.1 Leitura Obrigatória

O agente deve ler integralmente este arquivo: `PLANO_MIGRACAO_PTBR.md`

Também deve ler:
- `README.md`
- `.gitignore`
- Estrutura atual de arquivos e pastas
- Histórico Git local, se existir
- Estado do diretório de trabalho

O agente não pode assumir que conhece a missão apenas pelo nome do projeto, por instruções resumidas ou pelo conteúdo de um único arquivo Python.

### 10.2 Confirmação de Entendimento

Antes de modificar qualquer arquivo, o agente deve apresentar um resumo contendo obrigatoriamente:

1. Objetivo da versão PT-BR
2. Diferença entre o repositório original em inglês e a cópia PT-BR
3. Elementos que podem ser traduzidos
4. Elementos que devem ser preservados
5. Siglas técnicas e clínicas que não podem ser alteradas
6. Regras para CSV e demais contratos externos
7. Regras específicas para ROM, TAM, MCP, PIP, DIP, IP, ABD, ASSH, EMA, Kalman, FPS, CSV, PDF, Hz e CV
8. Regras para bibliotecas, APIs, formatos, extensões, URLs e comandos externos
9. Estado atual da migração
10. Último grupo concluído
11. Próximo grupo proposto
12. Riscos técnicos do próximo grupo

### 10.3 Auditoria do Estado Atual

Antes de modificar qualquer arquivo, o agente deve verificar:

1. Quais arquivos já foram alterados
2. Quais arquivos ainda estão pendentes
3. Se Git local está inicializado
4. Qual é o último commit local
5. Se há modificações não commitadas
6. Se `.venv/`, `__pycache__/` e arquivos temporários estão excluídos adequadamente
7. Se o `.gitignore` está correto
8. Se os arquivos atuais correspondem à etapa registrada neste plano
9. Se há imports quebrados
10. Se há erros de sintaxe
11. Se existem testes automatizados e qual é o resultado atual deles
12. Se algum contrato externo, CSV, PDF, JSON, log persistido ou arquivo de sessão precisa de investigação adicional

### 10.4 Relatório Obrigatório Antes de Executar

Após leitura e auditoria, o agente deve parar e entregar um relatório contendo:

- Resumo da missão entendida
- Estado atual do projeto
- Arquivos já modificados
- Alterações não commitadas
- Último commit local
- Último grupo concluído
- Próximo grupo proposto
- Termos EN → PT-BR envolvidos
- Arquivos afetados
- Referências encontradas
- Impactos possíveis em imports, CSV, PDF, interface, logs, gráficos e testes
- Validações previstas
- Estratégia de rollback
- Confirmação explícita de que **nenhum arquivo foi modificado durante a auditoria**

### 10.5 Autorização Explícita

Depois de entregar o relatório inicial, o agente deve aguardar autorização explícita do usuário.

Exemplos válidos de autorização:
- `"AUTORIZO A EXECUÇÃO DA ETAPA 0"`
- `"AUTORIZO A EXECUÇÃO SOMENTE DO GRUPO 1"`
- `"AUTORIZO SOMENTE A MIGRAÇÃO DO ARQUIVO X"`

Sem uma autorização explícita, o agente não pode executar comandos que alterem estado, criar commits, renomear arquivos, editar documentos ou modificar código.

Executar testes, iniciar a interface, gerar PDF, gerar CSV, inicializar Git, criar commits ou executar scripts do projeto também são ações que podem alterar o estado do diretório (criando `__pycache__/`, `.pytest_cache/`, `logs/`, arquivos PDF, arquivos CSV ou arquivos temporários).

Sem autorização explícita, o agente pode apenas:
- ler arquivos;
- listar a estrutura;
- consultar Git de forma somente leitura;
- executar buscas de referências sem modificação;
- apresentar análise e plano.

Qualquer comando que possa criar cache, log, PDF, CSV, arquivo temporário, commit ou outro artefato deve ser informado previamente e executado somente após autorização do usuário.

### 10.6 Execução Controlada

Após autorização explícita, o agente deve:

1. Trabalhar apenas na etapa, grupo ou arquivo autorizado
2. Não antecipar modificações de grupos futuros
3. Não realizar refatoração fora do escopo
4. Não alterar cálculos, thresholds, algoritmos ou regras clínicas
5. Não alterar CSV ou outros contratos externos sem autorização específica
6. Executar todas as validações previstas
7. Apresentar os resultados das validações
8. Criar um único commit Git local, se isso estiver dentro da autorização recebida
9. Parar após concluir o escopo autorizado
10. Aguardar nova autorização antes de continuar

### 10.7 Regra de Segurança

Se houver dúvida sobre uma string, chave, variável, função, classe, módulo, import, arquivo, pasta, CSV, PDF, log persistido, dado clínico, algoritmo ou comportamento:

**PARAR. NÃO ALTERAR. REPORTAR A DÚVIDA. AGUARDAR DECISÃO EXPLÍCITA DO USUÁRIO.**

### 10.8 Regra de Prioridade

Este documento tem prioridade sobre instruções resumidas, sugestões automáticas de refatoração, traduções automáticas, suposições do agente e decisões tomadas em conversas anteriores que não estejam registradas neste arquivo.

---

## 11. Critérios de Interrupção

Parar imediatamente e reportar ao usuário se:
- `python -m compileall` retornar qualquer erro de sintaxe
- Um import falhar após renomeação
- Um teste anteriormente passando começar a falhar por razão não relacionada à migração
- Uma chave de dicionário não for encontrada por um consumidor após migração
- Uma string de estado não for reconhecida por uma condicional após migração
- PDF ou CSV apresentar campos em branco ou incorretos
- Qualquer comportamento clínico (cálculo de TAM, classificação, relatório) diferir da versão original em inglês

---

## Status da Execução

```
Versão: 1.3 — plano consolidado, aguardando autorização para baseline local.

Estado da execução:
  - Nenhum grupo de migração interna foi autorizado.
  - Nenhuma alteração estrutural foi autorizada.
  - Git local ainda não foi inicializado.
  - Não existe remote configurado para a cópia PT-BR.
  - O repositório original em inglês permanece separado e intacto.
  - Há traduções parciais previamente auditadas em:
      - clinical_classification.py
      - ui/log_widget.py
      - ui/session_header.py

Próxima ação proposta:
  - Solicitar a um agente o Relatório Obrigatório de Continuidade;
  - Conferir .gitignore;
  - Inspecionar logs/ antes de decidir se deve ser ignorada;
  - Solicitar autorização explícita para Git local e baseline;
  - Inicializar Git local privado;
  - Registrar baseline de ambiente, compilação e testes.

Status de autorização:
  - PENDENTE DE AUTORIZAÇÃO EXPLÍCITA DO USUÁRIO.
```
