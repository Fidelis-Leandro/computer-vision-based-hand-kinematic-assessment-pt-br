# Relatório de Baseline Pré-Migração (PT-BR)

> **Documento Oficial de Baseline**  
> **Data e Hora:** 2026-09-05 17:42:00 (Horário de Brasília / UTC-3)  
> **Projeto:** Goniometria Digital da Mão (Cópia PT-BR)  
> **Commit-Base Associado:** `1480451` ("Base local auditada antes da migração interna pt-BR")

---

## 1. Identificação do Ambiente e Sistema

- **Sistema Operacional:** Windows (Microsoft Windows 11 / Windows 10, PowerShell)
- **Localização do Repositório PT-BR:** `C:\Users\leand\OneDrive\Documentos\GitHub\computer-vision-based-hand-kinematic-assessment PT-BR`
- **Ambientes Python Detectados:**
  1. **Python Global do Usuário:** `C:\Users\leand\AppData\Local\Programs\Python\Python311\python.exe`
  2. **Ambiente Virtual do Projeto Original:** `C:\Users\leand\OneDrive\Documentos\GitHub\computer-vision-based-hand-kinematic-assessment\.venv\Scripts\python.exe`
  3. **Comando `python` no PATH do Shell:** Aponta para o alias de execução do Windows (`C:\Users\leand\AppData\Local\Microsoft\WindowsApps\python.exe`), que emite aviso de instalação via Microsoft Store caso o alias esteja ativo sem o Python no PATH de sistema.
- **Versão do Python:** `Python 3.11.9`

---

## 2. Pacotes e Dependências Instaladas (`pip freeze`)

### 2.1 Ambiente Virtual do Projeto Original (`.venv` Python 3.11.9)
```text
absl-py==2.5.0
attrs==26.1.0
cffi==2.1.1
colorama==0.4.6
contourpy==1.3.3
cycler==0.12.1
defusedxml==0.7.1
flatbuffers==25.12.19
fonttools==4.63.0
fpdf2==2.8.8
jax==0.7.1
jaxlib==0.7.1
kiwisolver==1.5.0
matplotlib==3.11.1
mediapipe==0.10.14
ml_dtypes==0.5.4
numpy==1.26.4
opencv-contrib-python==4.11.0.86
opencv-python==4.11.0.86
opt_einsum==3.4.0
packaging==26.3
pillow==12.3.0
protobuf==4.25.9
psutil==7.2.2
pycparser==3.0
pyparsing==3.3.2
PyQt6==6.11.0
PyQt6-Qt6==6.11.1
PyQt6_sip==13.12.0
pyqtgraph==0.14.0
python-dateutil==2.9.0.post0
scipy==1.17.1
six==1.17.0
sounddevice==0.5.6
```

### 2.2 Python Global do Usuário (`Python311`)
```text
absl-py==2.5.0
attrs==26.1.0
cffi==2.1.1
contourpy==1.3.3
cycler==0.12.1
flatbuffers==25.12.19
fonttools==4.63.0
jax==0.10.2
jaxlib==0.10.2
kiwisolver==1.5.0
matplotlib==3.11.1
mediapipe==0.10.14
ml_dtypes==0.6.0
numpy==2.4.6
opencv-contrib-python==5.0.0.93
opencv-python==5.0.0.93
opt_einsum==3.4.0
packaging==26.3
pandas==3.0.5
pillow==12.3.0
protobuf==4.25.9
pycparser==3.0
pyparsing==3.3.2
python-dateutil==2.9.0.post0
scipy==1.17.1
six==1.17.0
sounddevice==0.5.6
tzdata==2026.3
```

---

## 3. Resultado da Compilação (`compileall`)

- **Comando:** `python -m compileall -q .` (executado com Python 3.11.9)
- **Código de Retorno:** `0` (Sucesso absoluto)
- **Erros de Sintaxe:** 0
- **Resultado:** 100% dos arquivos Python do repositório (`app_pyqt.py`, `config.py`, `clinical_classification.py`, `dashboard_utils.py`, `goniometry.py`, `goniometry_csv.py`, `goniometry_overlay.py`, `session_report.py`, `smoothing.py`, `themes.py`, todos os módulos de `ui/`, todos os de `workers/` e de `tests/`) compilam perfeitamente sem falhas sintáticas.

---

## 4. Resultado da Execução de Testes (`pytest`)

- **Comando Executado:** `python -m pytest`
- **Código de Retorno:** `1` (Módulo não encontrado)
- **Mensagem do Sistema:** `No module named pytest`
- **Diagnóstico:** O pacote `pytest` não está atualmente instalado nos ambientes Python do sistema (nem no global nem no `.venv` original).
- **Quantidade de Testes Coletados:** 0 (execução bloqueada pela ausência da ferramenta pytest).
- **Quantidade de Testes Aprovados:** N/A.
- **Quantidade de Falhas ou Erros:** N/A (ausência do pacote pytest no ambiente de execução).
- **Observação Crucial:** O arquivo `tests/test_kinematic_assessment.py` existe e possui testes definidos, importando `pytest`, `numpy`, `DigitalGoniometer`, `assh_classify`, etc. Caso o usuário deseje executar a suíte, bastará instalar `pytest` no ambiente (`pip install pytest`). Esta condição preexistente de ambiente fica formalmente registrada para não ser confundida com qualquer efeito de migração.

---

## 5. Observações sobre Bibliotecas Relevantes

- **MediaPipe:** Instalado na versão `0.10.14` (totalmente compatível com Python 3.11).
- **OpenCV:** Instalado nas versões `4.11.0.86` / `5.0.0.93`.
- **PyQt6 & PyQt6-Qt6:** Instalados no `.venv` original nas versões `6.11.0` / `6.11.1`.
- **PyQtGraph:** Instalado no `.venv` original na versão `0.14.0`.
- **NumPy:** Instalado no `.venv` original na versão `1.26.4` e no Python global na versão `2.4.6`.
- **FPDF2:** Instalado no `.venv` original na versão `2.8.8`.

---

## 6. Auditoria de Arquivos Temporários Criados

- **Arquivos criados durante a validação:**
  - `__pycache__/`
  - `ui/__pycache__/`
  - `workers/__pycache__/`
  - `tests/__pycache__/`
- **Status no Git:** Todos os diretórios `__pycache__/` foram confirmados como **100% ignorados** pelo `.gitignore` e não constam no stage.
- **Arquivos CSV, PDF ou Logs gerados:** Nenhum.

---

## 7. Declaração de Integridade

- **Nenhum cálculo matemático foi alterado.**
- **Nenhum threshold foi modificado.**
- **Nenhum algoritmo cinemático foi alterado.**
- **Nenhuma regra clínica ASSH foi alterada.**
- **Os 25 cabeçalhos CSV imutáveis permanecem rigorosamente preservados.**
- **Nenhum código Python foi modificado.**
