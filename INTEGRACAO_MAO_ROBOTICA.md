# Integração com Mão Robótica

Este documento cobre exclusivamente a integração entre o sistema de goniometria
(este repositório) e a mão robótica de 5 servos controlada por Arduino. Para tudo
que não é específico dessa integração (instalação geral, fluxo clínico, filtros
EMA/Kalman, CSV, PDF), consulte o [README.md](README.md) principal.

**Escopo desta integração**: a goniometria é a única aplicação principal. A câmera,
o MediaPipe e o cálculo de TAM continuam pertencendo exclusivamente a ela. A mão
robótica é apenas um **atuador opcional**, comandado por um único botão liga/desliga.
Não há calibração por usuário, múltiplas mãos, suporte à mão esquerda, ou modos
adicionais (luva, EEG, câmera dupla) nesta versão — esses recursos existem no
projeto histórico `Mão robo/`, mas não fazem parte desta integração.

---

## Sumário

- [Visão geral e fluxo de dados](#visão-geral-e-fluxo-de-dados)
- [Pinagem e valores de servo](#pinagem-e-valores-de-servo)
- [Mapeamento TAM → posição de servo](#mapeamento-tam--posição-de-servo)
- [Comunicação: pyFirmata + StandardFirmata](#comunicação-pyfirmata--standardfirmata)
- [Autodetecção da porta COM](#autodetecção-da-porta-com)
- [O botão liga/desliga](#o-botão-ligadesliga)
- [Avisos de segurança elétrica e mecânica](#avisos-de-segurança-elétrica-e-mecânica)
- [Como testar um servo por vez](#como-testar-um-servo-por-vez)
- [Diagnóstico de erros comuns](#diagnóstico-de-erros-comuns)
- [Limitações conhecidas e achados de investigação](#limitações-conhecidas-e-achados-de-investigação)
- [As três tabelas de classificação de TAM](#as-três-tabelas-de-classificação-de-tam)
- [Relação com o projeto "Mão robo"](#relação-com-o-projeto-mão-robo)
- [Rollback da integração](#rollback-da-integração)

---

## Visão geral e fluxo de dados

```
angles_smooth["INDEX"]["TAM"]   (graus, já processados pelo modo de filtro da sessão)
      │
      ▼
outputs/tam_to_servo.map_all()
      │  traduz a chave da goniometria (INDEX/MIDDLE/RING/PINKY/THUMB) para o
      │  nome do dedo na mão robótica (indicador/medio/anelar/minimo/polegar);
      │  aplica tam_to_servo(): clamp [0, TAM_MAX] -> interpolação linear ->
      │  clamp [SERVO_OPEN, SERVO_CLOSED]. Valor inválido (None/NaN/inf) -> None.
      ▼
RobotHandWorker.update_targets(positions, hand_detected)
      │  chamado pela thread principal (MainWindow._on_result), grava sob lock,
      │  sem nenhuma escrita na porta serial neste ponto.
      ▼
RobotHandWorker._send_cycle()   (thread própria, a cada SEND_INTERVAL_S)
      │  se mão ausente por mais de HAND_LOST_TIMEOUT_S -> força posição aberta;
      │  aplica _step_towards(..., MAX_STEP_PER_UPDATE) — ver constantes abaixo;
      ▼
board.digital[pin].write(posição)   (pyfirmata -> StandardFirmata -> PWM -> servo)
```

A escrita na porta serial **nunca** ocorre na thread da interface Qt — sempre dentro
de `RobotHandWorker.run()`, executado por uma `QThread` dedicada
(`outputs/robot_hand_output.py`).

---

## Pinagem e valores de servo

| Dedo | Pino Arduino | Servo aberto | Servo fechado (valor inicial) | TAM máximo configurado |
|---|---|---|---|---|
| Polegar | 10 | 0 | 150 | 130° |
| Indicador | 9 | 0 | 180 | 270° |
| Médio | 8 | 0 | 160 | 270° |
| Anelar | 7 | 0 | 180 | 270° |
| Mínimo | 6 | 0 | 130 | 270° |

Definidas em `outputs/tam_to_servo.py` (`PIN_MAP`, `SERVO_OPEN`, `SERVO_CLOSED`,
`TAM_MAX`). A pinagem e os valores de "fechado" foram herdados do projeto histórico
`Mão robo/src/outputs/arduino_output.py` (`VALORES_FECHADOS`), para esta mesma mão
física — são um ponto de partida testado com aquele projeto, **não uma calibração
validada dentro desta integração**.

Os valores de `TAM_MAX` (270° para os 4 dedos longos, 130° para o polegar) vêm do
teto biomecânico teórico do próprio pipeline goniométrico (`config.TAM_CEILING`),
**não** de uma medição da amplitude real alcançável por esta mão específica. Uma
investigação de amplitude já realizada mostrou que, na prática, indicador e polegar
raramente chegam perto desse teto, enquanto médio e anelar já o atingiram em sessões
reais registradas — ver [Limitações conhecidas](#limitações-conhecidas-e-achados-de-investigação).

---

## Mapeamento TAM → posição de servo

Regras (`outputs/tam_to_servo.tam_to_servo()`), aplicadas por dedo, de forma
independente:

- `TAM <= 0` → posição aberta (0).
- `TAM >= TAM_MAX` do dedo → posição fechada (`SERVO_CLOSED`).
- Entre os dois extremos → interpolação linear, sempre limitada (clamp) ao
  intervalo `[SERVO_OPEN, SERVO_CLOSED]`.
- `TAM` inválido (`None`, `NaN`, infinito, ou tipo não numérico) → retorna `None`;
  o dedo correspondente **mantém a última posição válida conhecida** (não é
  puxado para 0 nem para o valor anterior de outro dedo).

### Modo de filtro e a mão robótica

O `TAM` que chega aqui vem do modo de filtro escolhido na Tela de Configuração —
`EMA_KALMAN` (padrão), `EMA`, `KALMAN` ou `RAW`. Ver
[README.md → Modo de filtro](README.md#modo-de-filtro).

- **RAW pode acionar a mão robótica normalmente.** Não há bloqueio, aviso ou
  confirmação adicional para esse modo, e nada em `outputs/`, no Arduino, nos pinos,
  nos servos ou no firmware muda em função do modo escolhido.
- As proteções descritas acima **valem para todos os modos**. `RAW` apenas produz
  `None` com mais frequência (por não ter valor anterior para onde recuar quando uma
  medição é inválida), e esse caso já é tratado: o dedo mantém a última posição válida.
- Efeito prático a considerar: sem suavização, os alvos de servo oscilam mais, e o
  movimento da mão robótica fica visivelmente mais trêmulo. Isso é uma consequência
  mecânica esperada do modo, não uma falha — o `_step_towards(..., MAX_STEP_PER_UPDATE)`
  continua limitando a velocidade de cada passo.
- O modo usado em cada sessão fica registrado na coluna `filter_mode` do CSV, o que
  permite reinterpretar depois qualquer comportamento observado na mão robótica.

Não há calibração por usuário, por sessão ou por tamanho de mão nesta versão — os
limites são constantes fixas no código. Qualquer ajuste futuro desses números deve
ser feito com base em dados reais de sessão (ver próxima seção), não por tentativa
isolada.

---

## Comunicação: pyFirmata + StandardFirmata

- O Arduino deve estar gravado com **StandardFirmata** (Arduino IDE → Exemplos →
  Firmata → StandardFirmata) — nenhum firmware customizado é usado ou necessário.
- A comunicação usa a biblioteca `pyfirmata` (fixada em `1.1.0` no
  `requirements.txt`), não um protocolo serial textual próprio.
- Baud rate: 57600 (`BAUD_RATE` em `outputs/robot_hand_output.py`) — é também o
  default da própria biblioteca `pyfirmata`, compatível com o `StandardFirmata` padrão.
- Ao conectar, os 5 pinos são configurados como `SERVO` (`board.digital[pin].mode = SERVO`),
  o que aciona internamente o `SERVO_CONFIG` do pyFirmata com os parâmetros padrão
  do Arduino (`min_pulse=544µs`, `max_pulse=2400µs`) — os mesmos defaults da
  biblioteca `Servo.h` usados pela maioria dos servos de hobby, incluindo SG90.

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
   (`DEFAULT_FALLBACK_PORT`, hoje `None`/desativado) — só seria usado como
   último recurso, nunca com prioridade sobre a autodetecção.

**Risco conhecido**: se mais de um dispositivo conectado corresponder a uma das
palavras-chave (por exemplo, outro adaptador USB-serial que também contenha
"usb serial" na descrição), a ordem de tentativa depende do sistema operacional, não
há garantia de que o Arduino da mão robótica seja testado primeiro. Se isso ocorrer
na prática, desconecte os demais dispositivos seriais durante o uso da mão robótica.

---

## O botão liga/desliga

Único controle na interface: **MÃO ROBÓTICA: DESLIGADA / CONECTANDO... / LIGADA /
ERRO: ARDUINO NÃO CONECTADO**, na barra fixa superior, visível apenas durante uma
avaliação em andamento (estado `RUNNING`).

- **Ligar**: tenta conectar e configurar os 5 pinos em uma thread separada (não
  trava a interface). Só fica verde após sucesso completo; falha volta ao vermelho
  com mensagem de erro, sem travar a aplicação, e permite nova tentativa.
- **Enquanto ligado**: envia posições a `outputs.robot_hand_output.SEND_INTERVAL_S`
  Hz (ver constante no código para o valor atual em vigor). Mão ausente por mais de
  `HAND_LOST_TIMEOUT_S` segundos → posição aberta automática.
- **Desligar** (pelo botão, fim de sessão, ou fechamento da aplicação): envia
  posição aberta fixa aos 5 servos antes de liberar a porta serial.

Detalhe de implementação relevante para manutenção: ao encerrar uma sessão
(`_end_session()`), o desligamento da mão robótica é **assíncrono** (não bloqueia a
interface, que ainda está em uso); ao fechar a aplicação (`closeEvent()`), o mesmo
desligamento é **aguardado com timeout** (até 3s), porque a janela já está fechando
e não há responsividade a preservar. Ver comentários cruzados nos dois métodos em
`ui/main_window.py`.

---

## Avisos de segurança elétrica e mecânica

> **Estas são recomendações preventivas de boas práticas, baseadas em análise
> técnica do código e do hardware descrito. Elas ainda não foram validadas com
> instrumento de medição (multímetro) nesta bancada específica.**

- **Alimentação dos servos**: use sempre uma fonte externa **dedicada** para os 5
  servos. O USB do Arduino não deve alimentar os servos — a porta USB de um
  computador tipicamente não fornece corrente suficiente para 5 servos SG90 (ou
  similares) se movendo/fechando ao mesmo tempo, o que pode causar quedas de
  tensão, resets do Arduino ou comportamento errático dos servos.
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

---

## Como testar um servo por vez

1. Feche qualquer instância de `Mão robo/main.py` — nunca os dois ao mesmo tempo.
2. Conecte o Arduino via USB (já com StandardFirmata gravado).
3. Use a ferramenta de teste já existente em `Mão robo/` (botão "Testar Mão", que
   aciona `run_test_sequence()` em `arduino_output.py`) para mover cada servo
   isoladamente com os mesmos valores de fechamento usados nesta integração
   (150/180/160/180/130) **antes** de testar a integração completa — essa ferramenta
   não depende da goniometria e é a forma mais simples de validar hardware puro.
4. Só depois de confirmar que os 5 servos respondem corretamente de forma isolada,
   inicie uma sessão na goniometria e ligue o botão da mão robótica.

---

## Diagnóstico de erros comuns

| Mensagem/sintoma | Causa provável | O que fazer |
|---|---|---|
| `module 'inspect' has no attribute 'getargspec'` | Ambiente sem o polyfill aplicado, ou `pyfirmata` importado antes de `outputs/__init__.py` rodar | Confirmar que está usando o Python do `.venv` do projeto (3.11.x) e que os arquivos de `outputs/` não foram alterados |
| `Falha ao conectar em todas as portas candidatas` | Nenhuma porta com descrição correspondente às palavras-chave, ou porta ocupada por outro processo | Verificar se `Mão robo/main.py` não está aberto; verificar cabo USB; rodar `Mão robo/detect_ports.py` para listar portas visíveis ao sistema |
| `could not open port 'COMx': PermissionError... Acesso negado` | Outro processo (inclusive uma instância anterior travada desta própria aplicação) já tem a porta aberta | Fechar todos os processos Python pendentes, desconectar/reconectar o cabo USB, tentar novamente |
| Botão fica em "ERRO: ARDUINO NÃO CONECTADO" | Falha de conexão ou de configuração de algum dos 5 pinos | Consultar `logs/app.log` (linhas de `outputs.robot_hand_output`) para a mensagem exata; o botão permite nova tentativa a qualquer momento |
| Mão liga mas não fecha totalmente | Ver seção seguinte — pode ser TAM que não atinge o teto configurado para aquele dedo, ou limitação mecânica/elétrica | Consultar a tabela de amplitude por dedo (achados já documentados internamente); testar fisicamente conforme a seção anterior |
| Mão fecha e reabre sozinha repetidamente durante um fechamento sustentado | Possível perda momentânea de detecção da mão pelo MediaPipe durante oclusão em fechamento total, combinada com `HAND_LOST_TIMEOUT_S` | Ver `HAND_LOST_TIMEOUT_S` em `outputs/robot_hand_output.py`; não é necessariamente um bug de suavização |

---

## Limitações conhecidas e achados de investigação

- **`MAX_STEP_PER_UPDATE` não garante amplitude total**: o valor atual (180) elimina
  qualquer limite artificial de velocidade do servo (o `_step_towards()` vira, na
  prática, uma função identidade — chega ao alvo em um único ciclo). Isso resolveu um
  problema de lentidão percebida, mas **não** garante que a mão feche completamente:
  se o TAM medido pela goniometria para um dedo específico nunca atinge o
  `TAM_MAX` configurado, `tam_to_servo()` nunca calcula a posição de "fechado" para
  aquele dedo — não há nenhum valor de `MAX_STEP_PER_UPDATE` que resolva isso, porque
  a limitação está na entrada (TAM), não na suavização de saída.
- **Amplitude assimétrica entre dedos, comprovada em sessões reais**: dados de CSV de
  sessões já gravadas mostraram que médio e anelar chegaram a atingir o teto de 270°
  configurado, enquanto indicador ficou consistentemente entre ~74–78% do teto e
  polegar entre ~73–87%, em três sessões diferentes. Isso indica que um `TAM_MAX`
  uniforme para os 4 dedos longos provavelmente não reflete a amplitude real
  alcançável por cada dedo individualmente para esta pessoa/câmera — um ajuste
  futuro desses tetos deveria ser baseado em mais dados de sessão reais, não em
  valores arbitrários.
- **Interação entre oclusão do MediaPipe e o timeout de segurança**: o MediaPipe tende
  a perder ou degradar a detecção de landmarks quando a mão está mais fechada
  (dedos se sobrepõem do ponto de vista da câmera). Se isso ocorrer por mais que
  `HAND_LOST_TIMEOUT_S` exatamente no momento em que o usuário consegue fechar a mão
  por completo, a regra de segurança reabre a mão automaticamente — um comportamento
  correto (é a regra de segurança agindo como projetado), mas que pode ser confundido
  com uma falha de suavização.

---

## As três tabelas de classificação de TAM

O sistema tem **três** locais independentes que classificam o TAM em rótulos
("Excelente"/"Bom"/"Razoável"/"Ruim"), cada um para uma finalidade diferente — isso é
**pré-existente e não foi introduzido por esta integração**:

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
explicando o motivo dos números 120/100 em vez de 110/80/50. Também não existe hoje
nenhuma "fonte da verdade" única: os números de dedos longos coincidem nos três
locais, mas não há import compartilhado que garanta que continuem sincronizados no
futuro.

**Decisão registrada**: por ora, essas tabelas permanecem separadas, sem unificação
de código. O PDF é um documento clínico; qualquer alteração nos limiares do polegar
mudaria retroativamente a interpretação de sessões já classificadas, e deve vir de
uma decisão clínica explícita, não de uma harmonização de engenharia. Se essa decisão
for tomada no futuro, a unificação recomendada é centralizar os limiares em um único
local (`goniometry.py`, já que é o mais próximo do cálculo científico) e importar
dali nos outros dois arquivos — mantendo, ainda assim, perfis distintos onde a
finalidade realmente exigir (como a escala de repetições do PDF).

---

## Relação com o projeto "Mão robo"

`Mão robo/` (pasta irmã, fora deste repositório) é o projeto histórico de onde vieram
a pinagem, os valores de fechamento e a lógica de conexão pyFirmata usados aqui. Ele
**não é importado, executado ou modificado** por esta integração — é consultado
apenas como referência de código ao ler `Mão robo/src/outputs/arduino_output.py`.

Continua útil como **ferramenta isolada de teste de hardware** (seu botão "Testar
Mão" e o script `detect_ports.py` para listar portas seriais), mas:
- Nunca deve ser executado ao mesmo tempo que esta integração, se ambos apontarem
  para a mesma porta COM.
- Sua interface (PySide6), seus modos de câmera/luva/EEG e seu `HubController` estão
  fora do escopo desta integração e não têm relação funcional com o botão da mão
  robótica descrito aqui.

---

## Rollback da integração

Nenhuma alteração desta integração toca em código científico (`goniometry.py`,
`smoothing.py`, `workers/*`). Para reverter completamente:
1. Remover a chamada a `outputs.tam_to_servo.map_all()`/`RobotHandWorker.update_targets()`
   dentro de `MainWindow._on_result()`.
2. Remover a criação do botão `btn_robot_hand` e os métodos relacionados em
   `ui/main_window.py`.
3. Remover o pacote `outputs/` inteiro.
4. Remover `pyfirmata`/`pyserial` do `requirements.txt`.

O restante da goniometria volta exatamente ao estado anterior à integração. Os dois
projetos (`Mão robo/` e este) permanecem sempre em repositórios Git separados.
