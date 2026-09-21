# Integração com Mão Robótica

Este documento cobre exclusivamente a integração entre o sistema de goniometria
(este repositório) e a mão robótica de 5 servos controlada por Arduino. Para tudo
que não é específico dessa integração (instalação geral, fluxo clínico, filtros
EMA/Kalman, CSV, PDF), consulte o [README.md](README.md) principal.

---

## Sumário

- [Objetivo e limites de uso](#objetivo-e-limites-de-uso)
- [Visão geral e fluxo de dados](#visão-geral-e-fluxo-de-dados)
- [Pinagem e valores de servo](#pinagem-e-valores-de-servo)
- [Mapeamento TAM → posição de servo](#mapeamento-tam--posição-de-servo)
- [Perfil Evento](#perfil-evento)
- [Comunicação: pyFirmata + StandardFirmata](#comunicação-pyfirmata--standardfirmata)
- [Autodetecção da porta COM](#autodetecção-da-porta-com)
- [Estados da interface e ciclo de vida](#estados-da-interface-e-ciclo-de-vida)
- [Registros da sessão (CSV, PDF e log)](#registros-da-sessão-csv-pdf-e-log)
- [Avisos de segurança elétrica e mecânica](#avisos-de-segurança-elétrica-e-mecânica)
- [Como testar um servo por vez](#como-testar-um-servo-por-vez)
- [Diagnóstico de erros comuns](#diagnóstico-de-erros-comuns)
- [Limitações conhecidas e amplitude observada](#limitações-conhecidas-e-amplitude-observada)
- [As três tabelas de classificação de TAM](#as-três-tabelas-de-classificação-de-tam)
- [Relação com o projeto "Mão robo"](#relação-com-o-projeto-mão-robo)
- [Remoção da integração](#remoção-da-integração)

---

## Objetivo e limites de uso

A goniometria é a aplicação principal: a câmera, o MediaPipe e o cálculo de TAM
pertencem exclusivamente a ela. A mão robótica é um **atuador opcional**, comandado
por um único botão liga/desliga, que reproduz o movimento dos dedos medido pela
goniometria.

- **A mão robótica não é um instrumento de medição.** Medidas e classificações
  clínicas vêm exclusivamente do pipeline goniométrico e do relatório PDF. A posição
  dos servos é uma resposta demonstrativa e não constitui medida clínica.
- **A integração não realiza calibração.** Usa tabelas fixas de referência e não
  calibra por usuário, sessão, mão, tamanho de mão, tipo de servo ou montagem física.
  Consequências: a amplitude de movimento varia entre pessoas; a geometria da mão
  impressa ou montada varia; os limites mecânicos dos servos variam; e tabelas fixas
  podem abrir ou fechar demais em montagens diferentes.
- **Qualquer alteração física ou de parâmetros exige testes graduais e supervisão**
  (ver [Avisos de segurança](#avisos-de-segurança-elétrica-e-mecânica)).
- **O comportamento do hardware não pode ser garantido por este repositório.** Ele
  depende da montagem real, da fonte de alimentação, do firmware e da porta serial.
- Não fazem parte da integração: mão esquerda, múltiplas mãos e modos adicionais de
  entrada (luva, EEG, câmera dupla).

---

## Visão geral e fluxo de dados

```
angles_smooth["INDEX"]["TAM"]   (graus, já processados pelo modo de filtro da sessão)
      │
      ▼
outputs/tam_to_servo.map_all()
      │  traduz a chave da goniometria (INDEX/MIDDLE/RING/PINKY/THUMB) para o
      │  nome do dedo na mão robótica (indicador/medio/anelar/minimo/polegar);
      │  aplica tam_to_servo(): clamp [0, teto do dedo] -> interpolação linear ->
      │  clamp [SERVO_OPEN, SERVO_CLOSED]. Valor inválido (None/NaN/inf) -> None.
      ▼
RobotHandWorker.update_targets(positions, hand_detected)
      │  chamado pela thread principal (MainWindow._on_result), grava sob lock,
      │  sem nenhuma escrita na porta serial neste ponto.
      ▼
RobotHandWorker._send_cycle()   (thread própria, a cada SEND_INTERVAL_S)
      │  se mão ausente por mais que o timeout de perda de mão da sessão -> força
      │  posição aberta;
      │  aplica _step_towards(..., MAX_STEP_PER_UPDATE) — ver constantes abaixo;
      ▼
board.digital[pin].write(posição)   (pyfirmata -> StandardFirmata -> PWM -> servo)
```

A escrita na porta serial **nunca** ocorre na thread da interface Qt — sempre dentro
de `RobotHandWorker.run()`, executado por uma `QThread` dedicada
(`outputs/robot_hand_output.py`).

**Quando os alvos são enviados.** A interface só chama `update_targets()` quando o
`RobotHandWorker` existe e o estado é **LIGADA** (conectado com sucesso). Em qualquer
outro estado nada é enviado. Ligar ou desligar a mão não interfere no cálculo, no CSV
nem no PDF. O teto de TAM usado no mapeamento e o timeout de perda de mão vêm do
perfil da sessão, definido ao iniciar a avaliação (ver [Perfil Evento](#perfil-evento)).

---

## Pinagem e valores de servo

| Dedo | Pino Arduino | Servo aberto | Servo fechado | TAM máximo configurado |
|---|---|---|---|---|
| Polegar | 10 | 0 | 150 | 130° |
| Indicador | 9 | 0 | 180 | 270° |
| Médio | 8 | 0 | 160 | 270° |
| Anelar | 7 | 0 | 180 | 270° |
| Mínimo | 6 | 0 | 130 | 270° |

Definidas em `outputs/tam_to_servo.py` (`PIN_MAP`, `SERVO_OPEN`, `SERVO_CLOSED`,
`TAM_MAX`). As posições de servo usam a escala 0-180 do Firmata; não são ângulos
medidos da mão. A pinagem e os valores de "fechado" provêm do projeto `Mão robo/`,
para a mesma mão física, conforme registrado nos comentários de
`outputs/tam_to_servo.py`, e **não foram validados dentro desta integração**.

Os valores de `TAM_MAX` (270° para os 4 dedos longos, 130° para o polegar)
correspondem ao teto biomecânico teórico do pipeline goniométrico
(`config.TAM_CEILING`), **não** a uma medição da amplitude alcançável por esta mão.
Ver [Amplitude observada](#amplitude-observada).

---

## Mapeamento TAM → posição de servo

Regras (`outputs/tam_to_servo.tam_to_servo()`), aplicadas por dedo, de forma
independente:

- `TAM <= 0` → posição aberta (0).
- `TAM >= teto` do dedo → posição fechada (`SERVO_CLOSED`).
- Entre os dois extremos → interpolação linear, sempre limitada (clamp) ao intervalo
  `[SERVO_OPEN, SERVO_CLOSED]`.
- `TAM` ausente ou inválido (`None`, `bool`, `NaN`, infinito ou tipo não numérico) e
  dedo desconhecido → retorna `None`; o dedo correspondente **mantém a última posição
  válida conhecida**, sem afetar os demais.
- O teto vem de `TAM_MAX` (perfil clínico) ou de uma tabela passada por chamada
  (`tam_max_table`), como `TAM_MAX_DEMO` no perfil Evento. A tabela deve conter os
  5 dedos: `tam_to_servo()` não valida a tabela e um dedo ausente levanta `KeyError`.
  `SERVO_OPEN` e `SERVO_CLOSED` são os mesmos nos dois perfis.

### Tabelas de teto de TAM

| Dedo | `TAM_MAX` (perfil clínico) | `TAM_MAX_DEMO` (perfil Evento) | `SERVO_CLOSED` |
|---|---|---|---|
| Polegar | 130° | 70° | 150 |
| Indicador | 270° | 150° | 180 |
| Médio | 270° | 150° | 160 |
| Anelar | 270° | 150° | 180 |
| Mínimo | 270° | 150° | 130 |

- `TAM_MAX` é uma **referência técnica** derivada do teto teórico do pipeline, não uma
  calibração.
- `TAM_MAX_DEMO` contém **valores manuais de demonstração, não validados
  clinicamente, não equivalentes a parâmetros clínicos e sujeitos à validação física
  e clínica antes de qualquer uso formal**. Não substituem avaliação individual.

### Modo de filtro e a mão robótica

O `TAM` que chega aqui vem do modo de filtro escolhido na Tela de Configuração —
`EMA_KALMAN` (padrão), `EMA`, `KALMAN` ou `RAW`. Ver
[README.md → Modo de filtro](README.md#modo-de-filtro).

- **RAW pode acionar a mão robótica normalmente.** Não há bloqueio, aviso ou
  confirmação adicional. Nenhum dos quatro modos de filtragem altera `outputs/`, o
  Arduino, os pinos, os servos ou o firmware. O perfil Evento é a exceção controlada:
  usa o filtro `EMA` e passa ao mapeamento e ao worker parâmetros próprios (ver
  [Perfil Evento](#perfil-evento)).
- As proteções descritas acima **valem para todos os modos**. `RAW` apenas produz
  `None` com mais frequência (por não ter valor anterior para onde recuar quando uma
  medição é inválida), e esse caso já é tratado: o dedo mantém a última posição válida.
- Efeito prático a considerar: sem suavização, os alvos de servo oscilam mais, e o
  movimento da mão robótica fica visivelmente mais trêmulo. Isso é uma consequência
  mecânica esperada do modo, não uma falha — o `_step_towards(..., MAX_STEP_PER_UPDATE)`
  continua limitando a velocidade de cada passo.
- O modo usado em cada sessão fica registrado na coluna `filter_mode` do CSV, o que
  permite reinterpretar depois qualquer comportamento observado na mão robótica.

---

## Perfil Evento

Opção do seletor de modo de filtro, escolhida antes de iniciar a sessão, destinada a
demonstrações com a mão robótica em eventos e estandes. Não é um quinto algoritmo de
suavização: usa o filtro `EMA` e altera exclusivamente o comportamento associado à
mão robótica.

| Aspecto | Perfil clínico (padrão) | Perfil Evento |
|---|---|---|
| Filtro aplicado | o modo escolhido (padrão: EMA + Kalman) | `EMA` (`filter_mode=EMA`) |
| Teto de TAM no mapeamento TAM → servo | `TAM_MAX` | `TAM_MAX_DEMO` |
| Timeout de perda de mão | `HAND_LOST_TIMEOUT_S` (1,0 s) | 1,5 s |
| Ângulos, TAM e classificações clínicas | calculados pela goniometria | idênticos: não são alterados |
| Badge na barra superior | não exibido | "EVENTO — DEMONSTRAÇÃO", durante a avaliação |
| CSV | `demo_mode=False` | `demo_mode=True` |
| Relatório PDF | sem aviso | aviso de demonstração no rodapé técnico |

- **O efeito físico só existe com a mão robótica ligada.** Sem ela, o perfil apenas
  registra e sinaliza a sessão (badge, CSV e PDF).
- **O perfil é congelado ao iniciar a sessão.** O teto de TAM e o timeout são lidos
  desse perfil congelado, nunca de uma nova leitura do seletor; o timeout é aplicado
  quando o botão da mão robótica é ligado.

### Natureza dos valores de demonstração

Os valores de `TAM_MAX_DEMO` (70° para o polegar e 150° para os demais dedos) e o
timeout de 1,5 s são:

- **valores manuais de demonstração**, ajustados empiricamente;
- **não validados clinicamente**;
- **não equivalentes a parâmetros clínicos**: não são limites clínicos e não devem ser usados como tal;
- **sujeitos à validação física e clínica antes de qualquer uso formal**.

Servem para que a mão feche por completo com pouco esforço de quem está diante da
câmera. Por isso, a posição dos servos nesse perfil **não é proporcional à amplitude
clínica** e não deve ser usada para inferi-la.

---

## Comunicação: pyFirmata + StandardFirmata

- O Arduino deve estar gravado com **StandardFirmata** (Arduino IDE → Exemplos →
  Firmata → StandardFirmata) — nenhum firmware customizado é usado ou necessário.
- A comunicação usa a biblioteca `pyfirmata` (fixada em `1.1.0` no
  `requirements.txt`), não um protocolo serial textual próprio.
- Baud rate: 57600 (`BAUD_RATE` em `outputs/robot_hand_output.py`), o padrão do
  StandardFirmata. Não alterar sem reconfigurar o firmware do Arduino.
- Ao conectar, os 5 pinos são configurados como `SERVO` (`board.digital[pin].mode = SERVO`)
  e recebem a posição aberta. Os parâmetros de pulso dependem da biblioteca e do servo
  utilizado; este projeto não os define.

**Sobre o polyfill de `inspect.getargspec`**: a versão `1.1.0` do `pyfirmata` chama
internamente `inspect.getargspec()`, uma função removida da biblioteca padrão do
Python a partir da versão **3.11**. Sem correção, `import pyfirmata` falha com
`AttributeError` antes de qualquer tentativa de conexão. Um polyfill
(`inspect.getargspec = inspect.getfullargspec`) é aplicado tanto em
`outputs/__init__.py` quanto em `outputs/robot_hand_output.py` (duplicado de forma
defensiva — ver comentário em cada um dos dois arquivos). **Este polyfill deve ser
removido caso `pyfirmata` seja substituído por uma alternativa mantida e já
compatível com Python 3.11+** (ex.: `pyfirmata2`).

---

## Autodetecção da porta COM

Não há porta fixa em código. A cada tentativa de conexão (`outputs/robot_hand_output._find_candidate_ports()`):

1. Lista as portas seriais disponíveis no sistema operacional.
2. Filtra as que têm, na descrição, uma das palavras-chave: `arduino`, `ch340`,
   `ch341`, `usb serial`, `usb-serial`, `cp210`.
3. Tenta conectar em cada candidata, em ordem, até uma funcionar.
4. Se nenhuma candidata for encontrada, existe um fallback fixo opcional
   (`DEFAULT_FALLBACK_PORT`, cujo valor padrão é `None`, isto é, desativado) — só
   seria usado como último recurso, nunca com prioridade sobre a autodetecção.

**Risco conhecido**: se mais de um dispositivo conectado corresponder a uma das
palavras-chave (por exemplo, outro adaptador USB-serial que também contenha
"usb serial" na descrição), a ordem de tentativa depende do sistema operacional, não
há garantia de que o Arduino da mão robótica seja testado primeiro. Se isso ocorrer
na prática, desconecte os demais dispositivos seriais durante o uso da mão robótica.

---

## Estados da interface e ciclo de vida

Único controle na interface: o botão da mão robótica, na barra fixa superior, visível
apenas durante uma avaliação em andamento (estado `RUNNING`).

| Estado | Texto do botão | Significado | Botão |
|---|---|---|---|
| `off` | MÃO ROBÓTICA: DESLIGADA | Sem worker e sem porta aberta | Liga |
| `connecting` | CONECTANDO... | Tentativa de conexão em thread própria | Desabilitado |
| `on` | MÃO ROBÓTICA: LIGADA | Conectada e configurada; recebe alvos | Desliga |
| `error` | ERRO: ARDUINO NÃO CONECTADO | Falha de conexão, falha ao configurar um pino ou perda de comunicação durante o uso | Nova tentativa |

- **Ligar** tenta conectar e configurar os 5 pinos em uma thread separada, sem travar a
  interface. Só passa a LIGADA após sucesso completo.
- **Não há reconexão automática.** Após um erro, cada nova tentativa exige um clique.
- O texto de erro é o mesmo para falha de conexão e para perda de comunicação em uso; a
  mensagem exata está em `logs/app.log` (logger `outputs.robot_hand_output`).
- **Enquanto ligada**, os servos são atualizados a cada `SEND_INTERVAL_S` (0,05 s, ou
  20 Hz). Se a mão não for detectada por mais que o timeout de perda de mão, os 5 dedos
  vão para a posição aberta e voltam a seguir os alvos quando a mão for detectada. Dentro
  do timeout, os últimos alvos são mantidos.
- **Desligar** (pelo botão, ao encerrar a sessão ou ao fechar a aplicação) move os 5
  servos para a posição aberta e só então libera a porta serial, em até
  `SHUTDOWN_MAX_STEPS` passos de `SEND_INTERVAL_S` (cerca de 1,5 s no pior caso).

Ao encerrar a sessão (`_end_session()`), o desligamento é **assíncrono** (não bloqueia a
interface). Ao fechar a aplicação (`closeEvent()`), é **aguardado com timeout** de até
3 s. Ver os comentários cruzados nos dois métodos em `ui/main_window.py`.

### Comportamento por situação

| Situação | Comportamento | Estado final |
|---|---|---|
| Nenhuma porta com as palavras-chave | Mensagem "Nenhuma porta candidata a Arduino encontrada…" | ERRO |
| Todas as candidatas falham (porta ocupada, acesso negado, firmware incompatível) | Aviso por porta no log e "Falha ao conectar em todas as portas candidatas…" | ERRO |
| Biblioteca `pyfirmata` ausente | "Biblioteca pyfirmata não instalada." | ERRO |
| Mão não detectada além do timeout | Os 5 dedos vão para a posição aberta | LIGADA |
| Mão não detectada dentro do timeout | Os últimos alvos são mantidos | LIGADA |
| TAM inválido em um dedo | Esse dedo mantém a última posição válida | LIGADA |
| Erro de escrita durante o uso (por exemplo, cabo removido) | "Conexão com o Arduino perdida"; **não há tentativa de mover para aberta**; a porta é liberada; os servos podem permanecer na última posição comandada | ERRO |
| Desligar, encerrar sessão ou fechar a aplicação | Posição aberta, depois liberação da porta | DESLIGADA |
| Cabo removido durante o próprio desligamento | O erro é registrado, o movimento é interrompido e a porta é liberada; **os servos podem não chegar à posição aberta** | DESLIGADA |
| Encerramento abrupto do processo (queda de energia do computador, encerramento forçado) | Sem garantia de posição aberta: o desligamento seguro só ocorre em encerramento controlado | indefinido |

A aplicação continua funcionando sem a mão robótica em todos os casos de falha.

---

## Registros da sessão (CSV, PDF e log)

- **CSV** (`logs/session_*.csv`): timestamps, `frame_id`, ângulos suavizados por dedo,
  e as colunas de metadado `filter_mode` (no perfil Evento, `EMA`) e `demo_mode`
  (`True` ou `False`, por extenso). **O CSV não registra** se a mão robótica estava
  ligada, as posições de servo, o timeout aplicado nem a tabela de teto usada; o perfil
  só pode ser inferido de `demo_mode`.
- **Relatório PDF**: no perfil Evento, o rodapé técnico traz o aviso "SESSÃO GERADA NO
  PERFIL EVENTO (DEMONSTRAÇÃO)", que informa que a resposta da mão robótica foi ampliada
  para exibição e que os ângulos e classificações permanecem medições reais. Todo PDF
  informa o modo de filtro e a ressalva de que o relatório é de uso acadêmico e não
  substitui validação clínica formal. O PDF não traz nenhuma outra informação sobre a
  mão robótica.
- **`logs/app.log`**: eventos da mão robótica (conexão na porta, falha por porta, perda
  de conexão) são registrados pelo logger `outputs.robot_hand_output`.

---

## Avisos de segurança elétrica e mecânica

> **Recomendações preventivas de boas práticas, baseadas na análise do código e do
> hardware descrito. Não foram verificadas com instrumento de medição (multímetro) e
> não substituem as instruções do fabricante dos componentes.**

**A segurança física depende da montagem real** (fonte de alimentação, fiação, servos,
firmware, porta serial e estrutura mecânica). Este documento e o código não a garantem.

- **Alimentação dos servos**: use sempre uma fonte externa adequada e **dedicada** para
  os 5 servos. A alimentação pela porta USB do Arduino não é recomendada: a porta USB
  de um computador tipicamente não fornece corrente suficiente para 5 servos de hobby se
  movendo ao mesmo tempo, o que pode causar quedas de tensão, resets do Arduino ou
  comportamento errático dos servos. Este documento não especifica tensão nem corrente:
  consulte a documentação dos servos utilizados.
- **GND comum**: a fonte externa dos servos e o Arduino devem compartilhar o mesmo
  referencial de terra (GND). Sem isso, os sinais PWM enviados aos servos podem ficar
  instáveis ou incorretos.
- **Não execute dois controladores do mesmo Arduino ao mesmo tempo**: nunca rode
  este sistema e `Mão robo/main.py` simultaneamente apontando para a mesma porta
  COM — cada processo tentaria abrir a porta serial de forma exclusiva, e o segundo
  a tentar falhará (ou pior, ambos podem enviar comandos conflitantes se a porta for
  liberada e reaberta no meio do uso).
- **Teste um servo por vez antes dos cinco simultâneos**: antes de qualquer sessão
  nova ou após alterar `SERVO_CLOSED`/`SERVO_OPEN`/`MAX_STEP_PER_UPDATE`, valide cada
  servo isoladamente (ver próxima seção) antes de operar os 5 juntos — reduz o risco
  de identificar um problema mecânico ou elétrico só quando todos já estão em uso.
- **Sinais de fonte insuficiente a observar**: zumbido nos servos sem movimento
  correspondente, queda perceptível de força quando múltiplos servos se movem juntos,
  reinicialização do Arduino (LED interno piscando/reset) durante o fechamento
  simultâneo dos 5 dedos. Qualquer um desses sinais indica que a fonte, a fiação ou o
  GND comum precisam ser revisados antes de continuar o uso.

### Checklist antes de energizar

- [ ] A fonte externa dos servos está ligada ao circuito **e** compartilha o GND com o Arduino.
- [ ] A pinagem física confere com a tabela de [Pinagem e valores de servo](#pinagem-e-valores-de-servo).
- [ ] Nenhum outro programa (inclusive `Mão robo/main.py`) está usando a porta serial.
- [ ] O Arduino tem o StandardFirmata gravado.
- [ ] Cada servo foi testado isoladamente antes dos cinco juntos.
- [ ] Após qualquer alteração de `SERVO_CLOSED`, `SERVO_OPEN` ou `MAX_STEP_PER_UPDATE`, o teste
      isolado foi repetido. Com `MAX_STEP_PER_UPDATE = 180` o limitador de velocidade não
      restringe o movimento; para testes iniciais, um valor menor limita o deslocamento por ciclo.
- [ ] O botão da mão robótica (LIGADA) está acessível para desligar a qualquer momento;
      fechar a aplicação também desliga.
- [ ] Nenhum outro adaptador USB-serial com descrição semelhante está conectado
      (ver [Autodetecção da porta COM](#autodetecção-da-porta-com)).
- [ ] **Orientação preventiva de segurança (não é um requisito comprovado pelo código):**
      testar inicialmente a mão sem carga mecânica e sem forçar o curso dos servos.

---

## Como testar um servo por vez

Use um procedimento controlado que acione um servo por vez, com a mão sem carga e
supervisão, antes de testar os cinco servos juntos.

1. Feche qualquer outro programa que use o mesmo Arduino (inclusive `Mão robo/main.py`)
   — nunca dois controladores ao mesmo tempo.
2. Conecte o Arduino via USB, com o StandardFirmata já gravado e a fonte externa dos
   servos ligada, conforme o [checklist](#checklist-antes-de-energizar).
3. Acione cada servo isoladamente com os mesmos valores de fechamento usados nesta
   integração (150/180/160/180/130 para polegar, indicador, médio, anelar e mínimo),
   aumentando o deslocamento gradualmente, com a mão sem carga e sem forçar o curso.
4. Só depois de confirmar que os 5 servos respondem corretamente de forma isolada,
   inicie uma sessão na goniometria e ligue o botão da mão robótica.

---

## Diagnóstico de erros comuns

| Mensagem/sintoma | Causa provável | O que fazer |
|---|---|---|
| `module 'inspect' has no attribute 'getargspec'` | Ambiente sem o polyfill aplicado, ou `pyfirmata` importado antes de `outputs/__init__.py` rodar | Confirmar que está usando o Python 3.11 do `.venv` do projeto e que os arquivos de `outputs/` não foram alterados |
| `Falha ao conectar em todas as portas candidatas` | Nenhuma porta com descrição correspondente às palavras-chave, ou porta ocupada por outro processo | Verificar se outro programa (inclusive `Mão robo/main.py`) não está usando a porta; verificar o cabo USB; listar as portas seriais visíveis ao sistema operacional (por exemplo, pelo gerenciador de dispositivos) |
| `could not open port 'COMx': PermissionError... Acesso negado` | Outro processo (inclusive uma instância anterior travada desta própria aplicação) já tem a porta aberta | Fechar todos os processos Python pendentes, desconectar/reconectar o cabo USB, tentar novamente |
| Botão fica em "ERRO: ARDUINO NÃO CONECTADO" | Falha de conexão ou de configuração de algum dos 5 pinos | Consultar `logs/app.log` (linhas de `outputs.robot_hand_output`) para a mensagem exata; o botão permite nova tentativa a qualquer momento |
| Botão passa a "ERRO: ARDUINO NÃO CONECTADO" depois de funcionar; log com "Conexão com o Arduino perdida" | Cabo, alimentação ou reset do Arduino durante o uso | Verificar cabo e fonte (ver sinais de fonte insuficiente); ligar novamente pelo botão |
| Mão liga mas não fecha totalmente | TAM que não atinge o teto configurado para aquele dedo, ou limitação mecânica/elétrica | Consultar a [amplitude observada](#amplitude-observada); testar fisicamente conforme [Como testar um servo por vez](#como-testar-um-servo-por-vez) |
| No perfil Evento a mão fecha com pouca amplitude da mão do visitante | Comportamento esperado: a tabela de demonstração tem tetos menores | Usar o perfil clínico se a resposta proporcional for necessária |
| A mão abre sozinha com a mão parada diante da câmera | Mão não detectada além do timeout | Verificar iluminação e enquadramento; ver o timeout de perda de mão |
| Mão fecha e reabre sozinha repetidamente durante um fechamento sustentado | Possível perda momentânea de detecção da mão pelo MediaPipe durante oclusão em fechamento total, combinada com o timeout de perda de mão | Ver `HAND_LOST_TIMEOUT_S` em `outputs/robot_hand_output.py`; não é necessariamente um bug de suavização |

---

## Limitações conhecidas e amplitude observada

- **`MAX_STEP_PER_UPDATE` não garante amplitude total**: com o valor 180, o passo
  máximo cobre o curso inteiro num único ciclo e `_step_towards()` equivale à identidade:
  o limitador não restringe a velocidade. Isso não garante que a mão feche
  completamente: se o TAM medido pela goniometria para um dedo específico nunca atinge
  o teto configurado, `tam_to_servo()` nunca calcula a posição de "fechado" para aquele
  dedo. A limitação está na entrada (TAM), não na suavização de saída.
- **Interação entre oclusão do MediaPipe e o timeout de segurança**: o MediaPipe tende
  a perder ou degradar a detecção de landmarks quando a mão está mais fechada
  (dedos se sobrepõem do ponto de vista da câmera). Se isso ocorrer por mais que o
  timeout de perda de mão em vigor (1,0 s no perfil clínico; 1,5 s no Evento, valor
  manual de demonstração) exatamente no momento em que o usuário consegue fechar a mão
  por completo, a regra de segurança reabre a mão automaticamente — um comportamento
  correto (é a regra de segurança agindo como projetado), mas que pode ser confundido
  com uma falha de suavização.
- **Ajuste de limites**: não há calibração; os limites são constantes fixas no código.
  Qualquer ajuste desses números deve se basear em dados reais de sessão e ser validado
  com testes físicos graduais, não por tentativa isolada.

### Amplitude observada

Distribuição do TAM registrado nos CSVs locais do projeto (`logs/`, não versionados):
**32 sessões com pelo menos 100 quadros, 14.056 quadros no total**, incluindo sessões do
perfil Evento (o TAM medido não depende do perfil).

| Dedo | p50 | p90 | p99 | máximo | p90 / `TAM_MAX` |
|---|---|---|---|---|---|
| Polegar | 31° | 85° | 117° | 130° | 65 % |
| Indicador | 85° | 202° | 253° | 270° | 75 % |
| Médio | 112° | 253° | 270° | 270° | 94 % |
| Anelar | 144° | 253° | 270° | 270° | 94 % |
| Mínimo | 137° | 236° | 270° | 270° | 88 % |

**Como ler estes dados:**

- São dados **locais e indicativos, não representativos**: sessões de uso e teste, sem
  controle de pessoa, câmera ou iluminação. **Não devem ser usados isoladamente para
  definir limites clínicos.**
- Médio e anelar atingem o teto (p99 igual ao máximo), enquanto indicador e polegar
  ficam bem abaixo. Um teto único para os dedos longos, portanto, não reflete a
  amplitude alcançável por dedo.
- Valores de aproximadamente **100/200/230/230/230** (polegar, indicador, médio, anelar
  e mínimo) ficam na mesma ordem de grandeza do percentil 90 (indicador 200 contra 202
  e mínimo 230 contra 236), embora difiram para o polegar (100 contra 85) e para médio e
  anelar (230 contra 253). Servem **apenas como referência próxima ao percentil 90,
  nunca como calibração validada**: qualquer teto por dedo depende de mais sessões e de
  validação física e clínica.

---

## As três tabelas de classificação de TAM

O sistema tem **três** locais independentes que classificam o TAM em rótulos
("Excelente"/"Bom"/"Razoável"/"Ruim"), cada um para uma finalidade diferente, e
independentes entre si:

| Local | Finalidade | Limiares (dedos longos) | Limiares (polegar) |
|---|---|---|---|
| `goniometry.py` (`DigitalGoniometer.classify_tam`) | Overlay desenhado sobre o vídeo em tempo real | ≥260 Excelente / ≥195 Bom / ≥130 Razoável / <130 Ruim | ≥110 Excelente / ≥80 Bom / ≥50 Razoável / <50 Ruim |
| `dashboard_utils.py` (`assh_classify`/`assh_classify_thumb`) | Painel/cards ao vivo na interface | Idêntico ao anterior (mesmos números, cor em formato diferente para Qt) | Idêntico ao anterior |
| `clinical_classification.py` (`classify_articular_tam`, Camada 1 de 4) | Relatório PDF pós-sessão | Idêntico aos dois anteriores | **>120 Excelente / 100–120 Bom / <100 Ruim (sem faixa "Razoável")** |

Os limiares para **dedos longos** são idênticos nos três locais. A única divergência
real está no **polegar**, especificamente na Camada 1 do PDF (`clinical_classification.py`),
que usa uma escala de 3 faixas (120/100) em vez das 4 faixas (110/80/50) usadas no
overlay e no painel ao vivo. Além disso, as Camadas 2 e 4 do PDF (contagem de
repetições válidas) usam ainda uma quarta escala interna (`target_good`/`target_excellent`
= 180/220 para dedos longos, 100/120 para o polegar), propositalmente diferente das
demais porque mede algo distinto (um único pico dentro de um exercício repetido, não
o melhor TAM da sessão inteira).

**Não há evidência no código de que a divergência específica do polegar entre a
Camada 1 do PDF e as demais fontes seja intencional** — não existe comentário
explicando o motivo dos números 120/100 em vez de 110/80/50. Não existe uma "fonte da
verdade" única: os números de dedos longos coincidem nos três locais, mas não há import
compartilhado que garanta que continuem sincronizados.

**Decisão de projeto**: essas tabelas permanecem separadas, sem unificação de código.
O PDF é um documento clínico; qualquer alteração nos limiares do polegar mudaria
retroativamente a interpretação de sessões já classificadas, e deve vir de uma decisão
clínica explícita, não de uma harmonização de engenharia. Caso essa decisão clínica seja
tomada, a unificação recomendada é centralizar os limiares em um único local
(`goniometry.py`, já que é o mais próximo do cálculo científico) e importar dali nos
outros dois arquivos — mantendo, ainda assim, perfis distintos onde a finalidade
realmente exigir (como a escala de repetições do PDF).

---

## Relação com o projeto "Mão robo"

`Mão robo/` (pasta irmã, fora deste repositório) é o projeto de origem da pinagem, dos
valores de fechamento e da lógica de conexão pyFirmata usados aqui, conforme registrado
nos comentários de `outputs/tam_to_servo.py` e `outputs/robot_hand_output.py`. Ele
**não é importado, executado ou modificado** por esta integração.

- Nunca deve ser executado ao mesmo tempo que esta integração, se ambos apontarem para
  a mesma porta COM.
- Suas demais partes (interface PySide6, `HubController` e outros modos de operação)
  estão fora do escopo desta integração e não têm relação funcional com o botão da mão
  robótica descrito aqui.

---

## Remoção da integração

A integração é isolada: não altera `goniometry.py`, `smoothing.py` nem o cálculo de TAM.
O único ponto de `workers/processing_worker.py` relacionado ao perfil Evento é o
registro do metadado `demo_mode`, que não altera nenhum ângulo. Para remover a mão
robótica:

1. Remover a chamada a `outputs.tam_to_servo.map_all()`/`RobotHandWorker.update_targets()`
   dentro de `MainWindow._on_result()`.
2. Remover a criação do botão `btn_robot_hand` e os métodos relacionados em
   `ui/main_window.py`.
3. Remover o pacote `outputs/` inteiro (e, com ele, o uso de `TAM_MAX_DEMO` e do timeout
   de perfil em `MainWindow`).
4. Remover `pyfirmata`/`pyserial` do `requirements.txt`.

O badge, o registro de `demo_mode` no CSV e o aviso no PDF não dependem da mão robótica
e podem permanecer. O restante da goniometria opera normalmente sem a mão robótica. Os
dois projetos (`Mão robo/` e este) permanecem sempre em repositórios Git separados.
