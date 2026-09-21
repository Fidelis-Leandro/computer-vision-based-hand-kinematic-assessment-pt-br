# Avaliação Cinemática da Mão Baseada em Visão Computacional

<div align="center">
  <img src="assets/screenshots/tela-avaliacao.jpg" alt="Interface de Avaliação Cinemática da Mão Baseada em Visão Computacional" width="800"/>
</div>

> **Avaliação cinemática de dedos sem marcadores em tempo real com emissão automatizada de relatórios clínicos — webcam RGB comum, sem necessidade de hardware especializado.**
> 
[![Python](https://img.shields.io/badge/Python-3.11.9%20validado-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.6%2B-41CD52?style=flat-square&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-0.10%2B-0097A7?style=flat-square&logo=google&logoColor=white)](https://mediapipe.dev/)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.9%2B-5C3EE8?style=flat-square&logo=opencv&logoColor=white)](https://opencv.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

---

## Sumário

- [Sobre o Projeto](#sobre-o-projeto)
- [Funcionalidades](#funcionalidades)
- [Fluxo Clínico e Telas](#fluxo-clínico-e-telas)
- [Arquitetura do Sistema](#arquitetura-do-sistema)
- [Tecnologias Utilizadas](#tecnologias-utilizadas)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
- [Como Executar](#como-executar)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Configuração](#configuração)
- [Integração com Mão Robótica](#integração-com-mão-robótica)
- [Geração de Relatórios e Exportação](#geração-de-relatórios-e-exportação)
- [Logs e Dados da Sessão](#logs-e-dados-da-sessão)
- [Contribuição](#contribuição)
- [Licença](#licença)

---

## Sobre o Projeto

O **Computer Vision-Based Hand Kinematic Assessment** é uma aplicação desktop clínica desenvolvida para profissionais da saúde — fisioterapeutas, terapeutas ocupacionais e médicos — que necessitam medir com precisão os ângulos de flexão/extensão das articulações dos dedos da mão em tempo real.

O sistema utiliza a câmera do computador, sem a necessidade de nenhum equipamento físico adicional (como o goniômetro manual tradicional), e detecta automaticamente os marcos anatômicos da mão para calcular os ângulos articulares de **MCP**, **PIP**, **DIP** e, para o polegar, **IP** e **ABD**. Além disso, calcula automaticamente o Movimento Ativo Total (**TAM**) com classificação funcional baseada no protocolo **ASSH**.

### Contexto Clínico

A goniometria é o método padrão-ouro para avaliação da amplitude de movimento articular (ROM). No contexto de reabilitação, medições frequentes e objetivas são essenciais para acompanhar a evolução do paciente. Este sistema digitaliza e acelera esse processo, eliminando o erro operador-dependente do goniômetro físico.

---

## Funcionalidades

- **Captura de vídeo em tempo real** via webcam com resolução HD (1280x720)
- **Detecção automática de marcos anatômicos** das 21 articulações da mão via MediaPipe
- **Cálculo goniométrico em tempo real** para os 5 dedos (Indicador, Médio, Anelar, Mínimo e Polegar)
- **Cálculo de TAM** e amplitude articular com classificação funcional no padrão ASSH
- **Gráficos dinâmicos** com histórico de ângulos por articulação (PyQtGraph)
- **Painel de métricas clínicas** com amplitude mínima, máxima e média da sessão
- **Pipeline duplo de suavização** — Média Móvel Exponencial (EMA) + Filtro de Kalman — para eliminar oscilações (jitter) sem introduzir latência
- **Modo de filtro selecionável na interface** — EMA + Kalman (padrão), EMA, Kalman ou dados brutos (RAW), escolhido antes de iniciar a sessão e registrado no CSV e no relatório PDF
- **Perfil Evento para demonstração** — opção do seletor de modo de filtro voltada a demonstrações com a mão robótica; usa o filtro EMA, exibe um badge de demonstração e é registrada no CSV e no relatório PDF (ver [Perfil Evento](#perfil-evento))
- **Gravação contínua em CSV** no diretório `logs/` com registro temporal (timestamp) e valores por articulação
- **Geração de relatório em PDF sob demanda** com resumo clínico da sessão gerado em thread secundária
- **Visualização do relatório PDF dentro da aplicação**, sem depender do leitor de PDF do sistema operacional
- **Remoção opcional dos arquivos da sessão** — "Não Salvar Esta Sessão" apaga o CSV e o PDF da sessão atual, após confirmação
- **Fluxo clínico em 3 telas desacopladas** (Configuração → Avaliação → Resultado) via `QStackedWidget`
- **Barra fixa superior de avaliação** fora da área de rolagem, garantindo encerramento seguro e imediato
- **Painel de logs recolhível** integrado à interface para inspeção diagnóstica sem poluir a visão clínica
- **Interface em Modo Escuro (Dark Mode)** profissional e responsiva
- **Configuração centralizada** — todos os parâmetros em um único arquivo `config.py`

---

## Fluxo Clínico e Telas

A interface do sistema é organizada em torno de um fluxo clínico intuitivo e seguro composto por três telas gerenciadas por um `QStackedWidget`:

```text
Tela 1 — Configuração
       │
       ▼ [Iniciar Avaliação]
Tela 2 — Avaliação em Andamento (Gravação contínua em CSV)
       │
       ▼ [Encerrar Sessão com confirmação modal]
Tela 3 — Resultado da Sessão
       │
       ├─► [Gerar Relatório PDF] (sob demanda via thread dedicada)
       ├─► [Exportar CSV] (diálogo nativo para salvar em qualquer pasta)
       ├─► [Visualizar Relatório] (abre o PDF numa janela da própria aplicação)
       ├─► [Abrir Pasta de Sessões] (abre a pasta logs/)
       ├─► [Não Salvar Esta Sessão] (remove o CSV e o PDF da sessão, com confirmação)
       └─► [Nova Avaliação] (reset completo com confirmação → Tela 1 em IDLE)
```

1. **Tela de Configuração da Sessão (Página 1)**:

   ![Tela de Configuração da Sessão](assets/screenshots/tela-configuracao.jpg)
   - Formulário inicial limpo para inserção de:
     - Nome do paciente;
     - Mão avaliada (Direita ou Esquerda);
     - Número da sessão (sequencial);
     - **Modo de filtro** aplicado à sessão (ver [Modo de filtro](#modo-de-filtro));
   - Ação: botão **"Iniciar Avaliação"** (ou tecla Enter) valida os dados, inicializa as threads de captura e IA e transiciona para a tela de avaliação.

2. **Tela de Avaliação em Andamento (Página 0)**:

   ![Tela de Avaliação em Andamento](assets/screenshots/tela-avaliacao.jpg)
   - **Barra fixa externa superior**: permanece fixa no topo da janela (fora da área rolável), exibindo o status da avaliação e o botão **"Encerrar Sessão"** sempre visível e acessível. Ao lado dele ficam o botão da mão robótica e, no perfil Evento, o badge de demonstração.
   - **Área de rolagem clínica (`QScrollArea`)**:
     - *SessionHeaderWidget*: dados da sessão, mão avaliada e cronômetro em tempo real;
     - *VideoWidget*: transmissão da câmera HD com renderização de esqueleto anatômico e vetores goniométricos;
     - *MetricsWidget*: visualização em modo clínico com ângulos atuais, TAM, ROM e classificação ASSH;
     - *GoniometryPlotWidget*: gráficos temporais de flexão/extensão por articulação;
     - *FingerCardsPanel*: cartões de amplitude detalhada por dedo;
     - *LogWidget recolhível*: painel de eventos do sistema com botão para expandir ou recolher logs técnicos.
   - **Gravação automática**: todos os quadros processados são gravados continuamente no arquivo CSV da sessão (`logs/`).
   - **Encerramento seguro**: o clique em "Encerrar Sessão" aciona um diálogo modal de confirmação defensiva antes de parar as threads e fechar o arquivo CSV. Durante a avaliação, botões de exportação, nova avaliação e relatório PDF permanecem ocultos.

3. **Tela de Resultado da Sessão (Página 2)**:

   ![Tela de Resultado da Sessão](assets/screenshots/tela-resultado.jpg)
   - Apresentada automaticamente após a parada completa dos workers (`STOPPED`) e o fechamento do arquivo CSV.
   - Apresenta o resumo clínico e operacional da avaliação:
     - Nome do paciente;
     - Mão avaliada;
     - Número da sessão;
     - Horário de início;
     - Duração total da coleta;
     - Caminho completo do arquivo CSV gerado.
   - **Ações disponíveis** (na ordem em que aparecem na tela; **Gerar Relatório PDF** e **Exportar CSV** ocupam a mesma linha):
     - **Gerar Relatório PDF**: gera sob demanda o relatório clínico com métricas consolidadas via `_PdfGeneratorWorker` em background, sem travar a interface gráfica. O arquivo recebe o nome do CSV da sessão com o sufixo `_report.pdf`; gerar novamente substitui o PDF anterior da mesma sessão.
     - **Exportar CSV**: abre diálogo nativo do sistema operacional permitindo salvar uma cópia do CSV da sessão em qualquer pasta.
     - **Visualizar Relatório**: abre o PDF da sessão numa janela da própria aplicação, sem depender do leitor de PDF do sistema operacional. Usa `QPdfDocument` e `QPdfView`, incluídos no PyQt6. A janela não é modal: a Tela de Resultado continua utilizável enquanto o relatório está aberto. Existe uma só janela por vez, e um novo clique traz a existente para frente. O botão só fica habilitado quando o PDF existe em disco e é bloqueado enquanto o PDF está sendo gerado. O documento é fechado antes de gerar o PDF novamente, iniciar outra sessão, executar **Nova Avaliação** ou remover os arquivos da sessão, o que libera o arquivo no Windows. Se o PDF não puder ser lido, a aplicação avisa e não abre a janela.
     - **Abrir Pasta de Sessões**: abre o explorador de arquivos diretamente no diretório `logs/`.
     - **Não Salvar Esta Sessão**: remove definitivamente do disco o CSV da sessão e o relatório PDF correspondente, se já tiver sido gerado — para quando o atendimento não deve ficar arquivado (sessão de teste, erro de operação, pedido do paciente). Pede confirmação, lista os nomes reais dos arquivos antes de remover e tem *Cancelar* como botão padrão. Fecha o visualizador de PDF antes de remover. Se um arquivo não puder ser removido (por exemplo, CSV aberto no Excel), o outro ainda é removido, a aplicação continua funcionando, o operador é avisado e o arquivo permanece. **Não remove** cópias já exportadas para outras pastas e **não altera `logs/app.log`**, que pode conservar registros técnicos anteriores, inclusive caminhos de arquivo que contêm o nome do paciente (ver [Logs e Dados da Sessão](#logs-e-dados-da-sessão)). O botão fica bloqueado enquanto o PDF está sendo gerado, com tooltip explicando o motivo.
     - **Nova Avaliação**: único caminho de reset do sistema. Com confirmação defensiva (botão padrão *Cancelar*), fecha o visualizador de PDF, para e recria os workers, limpa gráficos, métricas, widgets e log em tela, apaga a identificação do paciente (nome em branco, mão Direita, sessão 1), devolve o modo de filtro ao padrão (EMA + Kalman) e retorna à Tela 1 no estado `IDLE`. **Não remove arquivos**: o CSV e o PDF já gravados permanecem em `logs/`.

   > **Nova Avaliação** limpa o estado da aplicação; **Não Salvar Esta Sessão** remove os arquivos da sessão atual. As duas ações são independentes, e nenhuma delas afeta cópias criadas por **Exportar CSV**.

---

## Arquitetura do Sistema

O sistema foi construído no padrão **Produtor-Consumidor com Workers Qt**, garantindo que captura de vídeo, processamento de IA e atualizações de UI sejam completamente desacoplados e não bloqueiem a interface gráfica através de uma API interna de sinais thread-safe.

```
+-------------------------------------------------------------------------------+
|                                  app_pyqt.py                                  |
|                         (Ponto de Entrada + Logging)                          |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                              ui/main_window.py                                |
|                        (Orquestrador Principal da UI)                         |
|                                                                               |
|   +-----------------------------------------------------------------------+   |
|   | Barra Fixa de Avaliação (Status + Mão Robótica + Encerrar Sessão)     |   |
|   +-----------------------------------------------------------------------+   |
|                                                                               |
|   +-----------------------------------------------------------------------+   |
|   | QStackedWidget (Gerenciador de Telas)                                 |   |
|   |                                                                       |   |
|   | [Tela 1: Config.]    [Tela 2: Avaliação]       [Tela 3: Resultado]    |   |
|   | - Nome do paciente   - SessionHeaderWidget     - Resumo da sessão     |   |
|   | - Mão avaliada       - VideoWidget (Câmera)    - Gerar PDF            |   |
|   | - Número da sessão   - MetricsWidget (Clínico) - Exportar CSV         |   |
|   | - Modo de filtro     - GoniometryPlotWidget    - Visualizar Relatório |   |
|   | - Iniciar Avaliação  - FingerCardsPanel        - Abrir Pasta          |   |
|   |                      - LogWidget (Recolhível)  - Não Salvar Sessão    |   |
|   |                                                - Nova Avaliação       |   |
|   +-----------------------------------------------------------------------+   |
+---------------------------------------+---------------------------------------+
                                        | Sinais Qt (thread-safe)
                         +--------------+--------------+
                         v                             v
            +--------------------+         +----------------------+
            |   workers/         |  Queue  |   workers/           |
            |   CameraWorker     +-------->|   ProcessingWorker   |
            | (Thread da Câmera) |  (=1)   | (Thread de IA/Cálc.) |
            +--------------------+         +----------+-----------+
                                                      |
                                          +-----+-----+------+
                                          v     v            v
                                     goniometry  smoothing  clinical_
                                        .py        .py      classification.py
                                          |
                                          v
                                    goniometry_csv.py (gravação contínua em logs/)
                                    session_report.py (PDF sob demanda em logs/)

  ui/main_window.py --> ui/pdf_viewer_dialog.py  (visualização do PDF da sessão)
  ui/main_window.py --> outputs/                 (mão robótica opcional: TAM -> servo -> Arduino)
```

**Princípios de design:**
- **Thread Safety**: Toda a comunicação entre threads utiliza a API de sinais/slots do Qt — nunca acesso direto à interface a partir de threads secundárias.
- **Tamanho da Fila = 1 (Queue Size = 1)**: A fila entre CameraWorker e ProcessingWorker possui tamanho máximo 1, garantindo que o processador sempre receba o quadro mais recente (sem acúmulo de latência).
- **Configuração centralizada**: Sem "números mágicos" espalhados pelo código — tudo centralizado em `config.py`.

---

## Tecnologias Utilizadas

| Categoria | Tecnologia | Versão |
|-----------|-----------|--------|
| **Linguagem** | Python | 3.11.9 (validado) |
| **Interface Gráfica** | PyQt6 | 6.6+ |
| **Gráficos em Tempo Real** | PyQtGraph | 0.13+ |
| **Visão Computacional** | MediaPipe | 0.10.11-0.10.17 |
| **Captura de Vídeo** | OpenCV (cv2) | 4.9+ |
| **Cálculos Matemáticos** | NumPy | 1.24-1.x |
| **Relatórios em PDF** | FPDF2 | 2.7+ |
| **Visualização de Dados** | Matplotlib | 3.7+ |
| **Texto com Acentos no Vídeo** | Pillow | 9.3+ |
| **Monitoramento / Logs** | Logging (stdlib) | native |
| **Monitoramento de Recursos** | psutil | 5.9+ |

### Resumo Técnico

* **Linguagem**: Python 3.11.9 (ambiente validado)
* **Interface**: PyQt6
* **Visão Computacional**: MediaPipe & OpenCV
* **Cálculos Matemáticos**: NumPy
* **Relatórios**: FPDF2
* **Logs do Sistema**: Módulo nativo `logging`

---

## Pré-requisitos

- **Sistema Operacional**: Windows 11 — ambiente validado. Outros sistemas operacionais não foram verificados neste ambiente.
- **Python**: 3.11.9 — ambiente validado. Outras versões do Python não foram verificadas.
- **Câmera**: Webcam integrada ou USB com resolução mínima de 720p
- **Memória RAM**: Mínimo de 4 GB (8 GB recomendado)
- **GPU**: Não necessária — o processamento é realizado na CPU

### Ambiente validado

O projeto foi executado e testado com as versões abaixo. Versões diferentes podem funcionar, mas não foram verificadas.

| Componente | Versão |
|------------|--------|
| Python | 3.11.9 |
| MediaPipe | 0.10.14 |
| NumPy | 1.26.4 |
| OpenCV (`opencv-python`) | 4.11.0.86 |
| PyQt6 | 6.11.0 |
| PyQtGraph | 0.14.0 |
| FPDF2 | 2.8.8 |
| Matplotlib | 3.11.1 |
| Pillow | 12.3.0 |
| psutil | 7.2.2 |
| PyFirmata | 1.1.0 |
| PySerial | 3.5 |

---

## Instalação

### 1. Clonar o repositório

```bash
git clone https://github.com/Fidelis-Leandro/computer-vision-based-hand-kinematic-assessment-pt-br.git
cd computer-vision-based-hand-kinematic-assessment-pt-br
```

### 2. Criar e ativar um ambiente virtual

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux/macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar as dependências

```bash
pip install -r requirements.txt
```

---

## Como Executar

### Interface Desktop (PyQt6) — Recomendada

```bash
python app_pyqt.py
```

---

## Estrutura do Projeto

```
computer-vision-based-hand-kinematic-assessment/
|
+-- app_pyqt.py                  # Ponto de entrada principal (PyQt6)
+-- config.py                    # Configuração centralizada (parâmetros globais)
+-- goniometry.py                # Motor de cálculo goniométrico (ângulos articulares)
+-- goniometry_overlay.py        # Renderização de sobreposição na imagem da câmera
+-- goniometry_csv.py            # Gravação dos dados da sessão em CSV
+-- session_report.py            # Geração de relatório clínico em PDF
+-- smoothing.py                 # Pipeline de suavização (EMA + Filtro de Kalman)
+-- clinical_classification.py   # Classificação clínica dos ângulos medidos
+-- dashboard_utils.py           # Utilitários de painel e cálculo
+-- themes.py                    # Tema visual Dark Mode (estilos Qt)
+-- requirements.txt             # Dependências do projeto
+-- INTEGRACAO_MAO_ROBOTICA.md   # Documentação técnica da integração com a mão robótica
|
+-- ui/                          # Interface gráfica (widgets PyQt6)
|   +-- main_window.py           #   Janela principal (orquestrador)
|   +-- video_widget.py          #   Widget de visualização da câmera
|   +-- plot_widget.py           #   Widget de gráficos em tempo real
|   +-- finger_card_widget.py    #   Cartões individuais por dedo
|   +-- metrics_widget.py        #   Painel de métricas clínicas
|   +-- session_header.py        #   Cabeçalho da sessão
|   +-- log_widget.py            #   Painel de logs integrado
|   +-- pdf_viewer_dialog.py     #   Visualizador embutido do relatório PDF (janela não modal)
|
+-- workers/                     # Threads de processamento (Produtor-Consumidor)
|   +-- camera_worker.py         #   Thread de captura de vídeo (workers/camera_worker.py)
|   +-- processing_worker.py     #   Thread de processamento de IA + cálculos (workers/processing_worker.py)
|
+-- outputs/                     # Integração com a mão robótica (Arduino/pyFirmata)
|   +-- tam_to_servo.py          #   Mapeamento puro TAM (graus) -> posição de servo
|   +-- robot_hand_output.py     #   RobotHandWorker (QThread): conexão e envio ao Arduino
|
+-- logs/                        # app.log, CSVs e PDFs das sessões
+-- tests/                       # Testes automatizados
|   +-- test_ui_flow.py                   #   Fluxo multitelas da interface (PyQt6)
|   +-- test_session_report.py            #   CSV, relatório PDF, unidades e sanitização
|   +-- test_smoothing.py                 #   Filtros e modos de filtro
|   +-- test_kinematic_assessment.py      #   Cálculo goniométrico e gravação do CSV
|   +-- test_processing_worker.py         #   Integração ProcessingWorker <-> filtros e CSV
|   +-- test_goniometry_overlay.py        #   Overlay de vídeo
|   +-- test_tam_to_servo.py              #   Mapeamento TAM -> servo (sem hardware)
|   +-- test_robot_hand_worker_config.py  #   Configuração do RobotHandWorker (sem hardware)
```

> Nota: os recursos estáticos do projeto ficam em `assets/screenshots/`
> (capturas de tela das três telas do fluxo clínico, referenciadas ao longo
> deste README) e nos modelos usados internamente pelo MediaPipe.

---

## Configuração

Todos os parâmetros do sistema estão centralizados em [`config.py`](config.py). Não é necessário alterar nenhum outro arquivo para ajustar o comportamento do sistema.

> O **modo de filtro** é a exceção: ele é escolhido diretamente na interface, a cada sessão. `config.py` define apenas qual modo vem pré-selecionado. Ver [Modo de filtro](#modo-de-filtro).

### Principais parâmetros

| Parâmetro | Valor Padrão | Descrição |
|-----------|-------------|-----------|
| `CAMERA_INDEX` | `0` | Índice da câmera (0 = padrão) |
| `CAMERA_WIDTH` | `1280` | Largura de captura em pixels |
| `CAMERA_HEIGHT` | `720` | Altura de captura em pixels |
| `TARGET_FPS` | `30` | Taxa de quadros pretendida (FPS) |
| `EMA_ALPHA` | `0.30` | Fator de suavização EMA (0-1) |
| `KALMAN_Q` | `0.01` | Ruído de processo (Filtro de Kalman) |
| `KALMAN_R` | `0.10` | Ruído de medição (Filtro de Kalman) |
| `MP_DETECT_CONF` | `0.70` | Confiança mínima de detecção (MediaPipe) |
| `MP_TRACK_CONF` | `0.50` | Confiança mínima de rastreamento (MediaPipe) |
| `BUFFER_SIZE` | `500` | Pontos no histórico dos gráficos (~16s a 30 FPS) |
| `CSV_LOG_INTERVAL` | `3` | Frequência de gravação no CSV (a cada N quadros) |

### Alterar câmera

Caso o computador possua múltiplas câmeras, altere em `config.py`:

```python
CAMERA_INDEX: int = 1  # 0 = padrão, 1 = câmera externa, etc.
```

### Modo de filtro

O modo de suavização aplicado aos ângulos é escolhido **na própria interface**, no
seletor **Modo de Filtro** da Tela de Configuração — não é necessário editar
`config.py` para trocá-lo.

| Opção no seletor | Valor gravado no CSV | Quando usar |
|------------------|----------------------|-------------|
| EMA + Kalman — recomendado | `EMA_KALMAN` | **Padrão.** Pipeline clínico validado. Use em avaliações reais. |
| EMA — suavização exponencial | `EMA` | Suavização simples, levemente mais responsiva, com mais oscilação residual. |
| Kalman — filtro preditivo | `KALMAN` | Filtro preditivo. Bom para movimento contínuo. |
| Dados brutos (RAW) — sem suavização | `RAW` | Demonstração, comparação ou diagnóstico técnico. Os valores oscilam visivelmente. |
| Evento — resposta rápida da mão robótica | `EMA` | Demonstração com a mão robótica. Ver [Perfil Evento](#perfil-evento). |

Regras de uso:

- **EMA + Kalman é o padrão**, definido por `FILTER_MODE_DEFAULT` em `config.py`. Quem
  nunca tocar no seletor obtém o pipeline clínico validado (EMA + Kalman).
- A escolha é feita **antes de iniciar a sessão**. Durante a avaliação (`RUNNING`) o
  seletor fica desabilitado, e o modo não muda no meio da coleta.
- O modo escolhido **vale para toda a sessão** e é aplicado a um banco de filtros novo,
  sem nenhum resíduo do modo anterior.
- O modo fica **registrado na coluna `filter_mode`** de cada linha do CSV da sessão e
  **aparece no rodapé técnico do relatório PDF**, para que qualquer medição possa ser
  interpretada sabendo como foi processada.
- **RAW pode ser usado com a mão robótica**, sem bloqueio nem confirmação adicional. As
  proteções contra valores inválidos (`None`, `NaN`, infinito) continuam ativas em todos
  os modos — ver [INTEGRACAO_MAO_ROBOTICA.md](INTEGRACAO_MAO_ROBOTICA.md).
- Sessões gravadas em modos diferentes não são diretamente comparáveis entre si; o
  registro no CSV e no PDF existe justamente para tornar essa diferença visível.

### Perfil Evento

**Evento** é uma opção do seletor de modo de filtro voltada à demonstração da mão robótica em eventos e estandes. Não é um algoritmo de suavização a mais: o filtro aplicado é o `EMA`, e o perfil altera apenas a resposta da mão robótica.

- **Resposta da mão robótica mais permissiva**: o mapeamento TAM → servo usa uma tabela própria de demonstração, de modo que a mão feche por completo com menos amplitude de movimento.
- **Maior tolerância à perda de detecção**: a mão robótica aguarda um intervalo maior sem detectar a mão antes de executar o comportamento de segurança (retornar à posição aberta).
- **Só com a mão robótica ligada**: essas duas mudanças só têm efeito quando o botão da mão robótica está ligado. Sem ela, o perfil apenas registra e sinaliza a sessão, como descrito a seguir.
- **Badge de demonstração**: a barra superior exibe o badge "EVENTO — DEMONSTRAÇÃO" durante a avaliação.
- **Ângulos e classificações inalterados**: o TAM, os ângulos e as classificações clínicas exibidos continuam sendo calculados pela goniometria, sem interferência do perfil.
- **Registro no CSV**: a coluna `demo_mode` recebe `True` em todas as linhas da sessão (e `False` nas demais sessões), e `filter_mode` registra `EMA`.
- **Aviso no relatório PDF**: o relatório da sessão é gerado normalmente e inclui um aviso de que ela foi realizada no perfil Evento.

Como os demais modos, o perfil é escolhido antes de iniciar a sessão e não muda durante a avaliação; **Nova Avaliação** devolve o seletor ao modo padrão. Os ajustes da resposta da mão robótica são manuais e voltados à demonstração: não constituem parâmetros clínicos validados. Sessões desse perfil ficam identificadas no CSV e no PDF. Sobre a integração com a mão robótica, ver [INTEGRACAO_MAO_ROBOTICA.md](INTEGRACAO_MAO_ROBOTICA.md).

---

## Integração com Mão Robótica

A goniometria pode, opcionalmente, comandar uma mão robótica de 5 servos conectada
via Arduino (StandardFirmata + pyFirmata). A câmera e o cálculo de TAM continuam
pertencendo exclusivamente a este sistema — a mão robótica é apenas um atuador
externo, ligado/desligado por um único botão na barra fixa superior durante uma
avaliação em andamento (**MÃO ROBÓTICA: DESLIGADA / LIGADA**).

Resumo rápido:
- Fluxo: `angles_smooth[<dedo>]["TAM"]` → `outputs/tam_to_servo.py` (mapeamento
  linear fixo, sem calibração por usuário) → `outputs/robot_hand_output.py`
  (`RobotHandWorker`, thread dedicada) → pyFirmata → Arduino → servos.
- A porta COM é autodetectada por descrição (não é fixa em código).
- Requer StandardFirmata já gravado no Arduino e fonte externa dedicada para os servos.
- **Nunca execute este sistema e `Mão robo/main.py` ao mesmo tempo apontando para
  a mesma porta COM** — os dois disputariam o mesmo Arduino.
- O perfil **Evento** do seletor de modo de filtro altera a resposta da mão robótica; ver [Perfil Evento](#perfil-evento).

Para pinagem, valores de calibração inicial, diagnóstico de erros comuns
("Arduino não conectado"), avisos de segurança elétrica/mecânica e o roteiro de
teste físico dos servos, consulte **[INTEGRACAO_MAO_ROBOTICA.md](INTEGRACAO_MAO_ROBOTICA.md)**.

---

## Geração de Relatórios e Exportação

Durante e após a avaliação clínica, o sistema gerencia os dados coletados de forma segura e estruturada no diretório `logs/`:

1. **Gravação Contínua em CSV** — Durante a avaliação (na Tela 2), os ângulos articulares de cada dedo, o TAM e os timestamps são gravados continuamente em arquivo CSV com frequência definida em `CSV_LOG_INTERVAL` (padrão a cada 3 quadros, ~10 amostras/s). As duas últimas colunas, `filter_mode` e `demo_mode`, registram o modo de filtro e o perfil da sessão.
   - Localização: `logs/session_<paciente>_<timestamp>_s<num>.csv`
   - O arquivo é fechado com segurança antes de qualquer navegação pós-sessão.

2. **Geração de Relatório em PDF sob Demanda** — Ao encerrar a sessão e transicionar para a Tela 3 (Resultado), o profissional pode emitir o relatório clínico completo clicando no botão **"Gerar Relatório PDF"**.
   - Gerado via [`session_report.py`](session_report.py) com a biblioteca FPDF2 em thread secundária assíncrona (`_PdfGeneratorWorker`), impedindo qualquer congelamento da interface visual.
   - Contém metadados da sessão, faixas de normalidade ASSH, amplitudes mínimas, máximas e médias por articulação e visualizações gráficas das curvas de flexão/extensão.
   - As medidas angulares são apresentadas em graus (`54°`) e as velocidades angulares em graus por segundo (`75°/s`).
   - Sessões do perfil Evento são geradas normalmente e recebem um aviso de demonstração no rodapé técnico do relatório.
   - Localização: `logs/session_<paciente>_<timestamp>_s<num>_report.pdf`. Gerar novamente substitui o PDF da mesma sessão; se o visualizador estiver aberto, ele é fechado antes.

3. **Visualização, Exportação e Gestão de Arquivos**:
   - **Visualizar Relatório**: botão **"Visualizar Relatório"** abre o PDF da sessão numa janela da própria aplicação (ver [Tela de Resultado](#fluxo-clínico-e-telas)).
   - **Exportar CSV**: botão **"Exportar CSV"** na Tela de Resultado abre uma caixa de diálogo nativa do sistema operacional para copiar o arquivo CSV para diretórios externos (como pendrives, prontuários eletrônicos ou pastas compartilhadas de rede).
   - **Abrir Pasta de Sessões**: botão **"Abrir Pasta de Sessões"** abre o gerenciador de arquivos nativo diretamente na pasta `logs/`.
   - **Não Salvar Esta Sessão**: botão **"Não Salvar Esta Sessão"** remove o CSV e o PDF da sessão atual, após confirmação. Cópias exportadas não são afetadas.

---

## Logs e Dados da Sessão

O sistema centraliza todos os arquivos gerados no diretório `logs/`:

| Tipo | Localização | Conteúdo | Momento da Criação |
|------|------------|----------|--------------------|
| **Log da Aplicação** | `logs/app.log` | Registro técnico: eventos do sistema, diagnósticos e erros de execução | Inicialização e tempo de execução |
| **Dados da Sessão (CSV)** | `logs/session_*.csv` | Ângulos articulares e timestamps quadro a quadro; as últimas colunas, `filter_mode` e `demo_mode`, registram o modo de filtro e o perfil da sessão | Gravação contínua durante a avaliação |
| **Relatório Clínico (PDF)** | `logs/session_*_report.pdf` | Resumo estatístico, faixas ASSH e gráficos consolidados | Sob demanda na Tela de Resultado |

### Log da aplicação

O log utiliza o módulo nativo `logging` do Python, configurado em [`app_pyqt.py`](app_pyqt.py) no nível `INFO`, e registra simultaneamente no **console** (terminal) e no arquivo `logs/app.log` (UTF-8). O painel de logs da Tela de Avaliação é um recurso à parte: exibe eventos na tela e não grava nesse arquivo.

Formato das mensagens:

```text
AAAA-MM-DD HH:MM:SS,mmm | NÍVEL | logger | mensagem
```

O campo `logger` identifica o módulo de origem, por exemplo `ui.main_window`, `outputs.robot_hand_output` ou `app_pyqt`. Exemplos ilustrativos, com dados fictícios:

```text
2026-09-21 10:15:42,318 | INFO | ui.main_window | Sessão encerrada. CSV: logs\session_<paciente>_<timestamp>_s<sessão>.csv
2026-09-21 10:16:01,244 | INFO | ui.main_window | closeEvent: encerrando workers antes de fechar.
```

> **Privacidade:** `logs/app.log` é um registro técnico. A aplicação apenas acrescenta linhas a ele: nenhuma ação da interface o edita ou apaga, inclusive **Não Salvar Esta Sessão** e **Nova Avaliação**. Ele pode conter o caminho dos arquivos da sessão, que inclui o nome do paciente informado no formulário, e mensagens de erro do sistema operacional que citam esses caminhos. Trate esse arquivo com o mesmo cuidado dado aos CSV e PDF das sessões.

---

## Contribuição

Contribuições são bem-vindas. Para contribuir:

1. Faça um fork do projeto
2. Crie uma branch para sua feature: `git checkout -b feature/my-feature`
3. Faça o commit das suas alterações: `git commit -m "feat: add my feature"`
4. Envie o push para a branch: `git push origin feature/my-feature`
5. Abra um Pull Request

### Padrões de código

- Siga as convenções de nomenclatura existentes (`snake_case` para funções/variáveis, `UPPER_CASE` para constantes)
- Qualquer novo parâmetro numérico deve ser adicionado ao `config.py`, nunca inline no código
- Docstrings são obrigatórias para novas funções e classes
- Mantenha os testes em `/tests` atualizados

---

## Licença

Este projeto está licenciado sob a Licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

---

Desenvolvido para aplicação clínica em fisioterapia e terapia ocupacional.
