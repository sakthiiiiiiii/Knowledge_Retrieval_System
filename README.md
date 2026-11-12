# SwiftPay Knowledge Desk — Enterprise HR RAG

A document-based question-answering application for HR policies and IT operations. It searches the supplied Word, PDF and Excel files, returns relevant evidence, and shows the source location behind each answer. The interface uses a beige background, red accents and black text.

**Start here:** follow [Run locally on Windows](#run-locally-on-windows). For generated answers, then follow [Run the Groq language model](#run-the-groq-language-model). The [detailed run guide](docs/RUN_GUIDE.md) covers restart, optional semantic retrieval and troubleshooting. The [project walkthrough](docs/README.md) explains the code and data flow.

## What problem does this project solve?

Employees need answers to questions such as “How many sick leave days are allowed?” or “What is the database recovery objective?” The relevant information is spread across documents and tables. This project brings those sources into one searchable interface and keeps the answer connected to its evidence.

The project supports:

- Questions about leave, travel, expenses, service ownership, incident response and backups.
- Source citations with headings and paragraph, sheet, row or page locations.
- Table-aware parsing so values stay associated with their column names.
- Access checks that keep restricted records away from unauthorized users.
- Clear messages when the documents do not contain an answer.
- Optional Groq generation, with labelled source excerpts if the provider fails.

This is a local RAG application. **You do not train or fine-tune a new model.** RAG means *retrieval-augmented generation*: retrieve relevant document passages first, then optionally ask a language model to write an answer using them.

## Which mode should I run?

| Mode | How documents are searched | How the answer is produced | Requirements |
|---|---|---|---|
| Default local mode | BM25 keyword ranking in SQLite | Direct, cited source excerpts | Base Python dependencies; no API key or Docker |
| Groq answers | Same local search by default | Configured Groq model writes an answer from retrieved evidence | Base dependencies, internet, valid Groq key and cloud opt-in |
| Optional dense retrieval | Local Sentence Transformers embeddings and Qdrant similarity search | Either excerpts or Groq, depending on generation settings | Dense dependencies, model download and Qdrant |

**Retrieval and generation are separate choices.** You can use Groq with the default local search; Qdrant is not required for that. The configured generation model is `llama-3.3-70b-versatile`. The optional embedding model is `BAAI/bge-small-en-v1.5`. These names come from this project's configuration; model availability and account access must be checked in your own environment.

## Run locally on Windows

### 1. Extract the project and open its folder

Install Python **3.11 or 3.12** if needed. Extract the ZIP into a new folder. Open PowerShell inside `Enterprise_HR_RAG_Full_Project`, where `start.py`, `app.py` and `requirements.txt` are located. Stop any older copy of the API or Streamlit before starting this one.

If the terminal is elsewhere, use your actual extracted path:

```powershell
cd "C:\Users\YOUR_USERNAME\Downloads\Enterprise_HR_RAG_Full_Project"
```

Confirm Python is available:

```powershell
py -3.12 --version
```

If only Python 3.11 is installed, substitute `py -3.11` in the environment-creation command below.

### 2. Create one virtual environment and install dependencies

Run these commands once for the extracted project:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The `.venv` folder holds this project's Python libraries. You do not need a second environment, and you do not need to activate it because the commands directly use its Python executable. Internet access is needed for the first dependency installation.

### 3. Start the API and interface together

```powershell
.\.venv\Scripts\python.exe start.py
```

The launcher creates `.env` if it is missing, generates a private local session token, starts FastAPI, prepares the approved source documents and starts Streamlit. It preserves an existing configuration.

Open [http://localhost:8501](http://localhost:8501). Keep the terminal running. The sidebar should show **Local source excerpts** and the documents available in the selected knowledge area.

Choose **People & policies** and ask:

> How many leaves is the employee entitled to?

The answer should contain policy excerpts and a **View evidence** section. Choose **IT & operations** for backup and incident questions. **Research** has no bundled sources after the unrelated HTML files were removed.

### 4. Stop and run again

Press **Ctrl+C** in the launcher terminal to stop both services. For later runs, open the project folder and run only:

```powershell
.\.venv\Scripts\python.exe start.py
```

Do not recreate the environment or reinstall packages every time.

## Run the Groq language model

Use this mode when you want a written answer synthesized from the retrieved passages.

1. Complete the local setup above and stop the app with **Ctrl+C**.
2. Open the project's `.env` file. Edit `.env`, not `.env.example` and not the Python source.
3. Set these values using your own Groq API key:

```dotenv
RETRIEVAL_MODE=lexical
GENERATION_MODE=auto
ENABLE_EXTERNAL_LLM=true
GROQ_API_KEY=YOUR_ACTUAL_GROQ_API_KEY
GROQ_MODEL=llama-3.3-70b-versatile
ALLOW_EXTERNAL_CONFIDENTIAL=false
```

4. Save the file and restart:

```powershell
.\.venv\Scripts\python.exe start.py
```

5. Open [http://localhost:8501](http://localhost:8501) and ask an HR policy question. A successful generated answer is labelled **DOCUMENT ANSWER · Generated with Groq**.

The language model runs through **Groq's API**, not on your laptop. The default document search still runs locally. Only authorized evidence permitted by the cloud-disclosure settings is sent. The **Session token** field is for API authentication; do not paste your Groq API key there. The launcher supplies the local session token automatically.

“Groq configured” in the sidebar means the settings are present. The key and model are actually verified when a question is sent. If the key is rejected, a limit is reached, the request times out, or returned citations fail validation, the app explains the problem and shows relevant **SOURCE EXCERPTS** when possible. Such a response is a fallback, not proof of a successful model call.

To return to local excerpts, set `ENABLE_EXTERNAL_LLM=false` and `GENERATION_MODE=extractive`, then restart. No real Groq credential is included in this archive.

## Run on macOS or Linux

From the extracted project folder, using Python 3.11 or 3.12:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python start.py
```

Open [http://localhost:8501](http://localhost:8501). The same `.env` settings enable Groq. Use `.venv/bin/python` in place of the Windows Python path for the other commands in these guides.

## How the project works

1. **Load approved sources.** The application reads the originals from `data/source/` and checks each filename against `config/dataset_policies.json`.
2. **Parse the files.** Word paragraphs, PDF text and table rows become structured blocks. Headings and source locations are retained for citations.
3. **Apply permissions.** Document, section and row rules are assigned before chunking so sensitive material cannot inherit broader permissions.
4. **Create chunks and build an index.** Related prose is split into manageable pieces; rows remain separate from neighbouring rows. The default backend stores searchable chunks in local SQLite. The optional dense backend embeds them and stores vectors in Qdrant.
5. **Retrieve relevant evidence.** The API verifies the session and searches only active content that the identity can access in the chosen knowledge area.
6. **Produce and check the answer.** Local mode quotes matching passages. Groq mode requests an answer using the retrieved evidence. Citation IDs are checked before display; this check does not prove every factual claim is correct.
7. **Display the evidence.** The UI shows the answer and the original passages with their locations. Optional Redis caching can reuse eligible answers within the same access and corpus context.

The included `data/parsed/*.jsonl` files are readable parser exports. **Startup indexes the originals in `data/source/`; it does not use the JSONL exports as a separate source dataset.** Existing unchanged sources reuse their indexed version on restart.

## Included dataset

| Original source | Purpose | Local demo access |
|---|---|---|
| `POL-HR-010_Leave_Travel_and_Expense_Policy.docx` | Leave, travel and expense rules | Available |
| `SOP-OPS-001_Incident_Management_and_Escalation.pdf` | Incident handling and escalation | Available |
| `SOP-OPS-005_Database_Backup_and_Restore.pdf` | Backup and restore procedures | Available |
| `SwiftPay_Service_Catalogue_and_Ownership.xlsx` | Service ownership and recovery objectives | Available |
| `RPT-OPS-2026-09_Monthly_IT_Operations_Report_September_2026.docx` | Monthly operations report with restricted sections | Restricted |
| `SwiftPay_Employee_Training_Records.xls` | Employee and training records | Restricted |

The six originals are preserved with six parsed JSONL exports: **442 blocks, including 187 table rows**. The unrelated Kimi K3 report and TimesFM HTML guide were removed, along with their parsed outputs and configuration entries. Generated duplicate datasets were also removed.

The sidebar lists documents permitted for the current session, not every file on disk. The local demo can access four documents across the two populated areas. Adding an unknown file does not automatically grant permission to index it; it needs an approved policy. See the [project walkthrough](docs/README.md#dataset-and-access-rules).

To regenerate the parser exports on Windows:

```powershell
.\.venv\Scripts\python.exe scripts/parse_dataset.py
```

This writes `data/parsed/*.jsonl` and `reports/dataset_parsing.json`. It does not start the interface or replace the active search index by itself.

## Example questions and expected results

| Question | Knowledge area | Expected result from the supplied documents |
|---|---|---|
| How many leaves is the employee entitled to? | People & policies | Annual: 20 working days; sick: 10; casual: 6; other leave types and eligibility/crediting conditions, with evidence |
| How many sick leave days are permanent employees entitled to? | People & policies | 10 working days, with the policy qualifications |
| What is the Bangalore hotel limit and above-limit approval? | People & policies | Bengaluru: INR 4,000 per night; prior written department-head approval above the limit |
| How many days can employees work from home? | People & policies | 2 days per week with manager approval |
| What is the Payments database RPO in the backup SOP? | IT & operations | 15 minutes, from its PDF table row |
| What is the Tier 0 RPO in the service catalogue? | IT & operations | 5 minutes, from its own catalogue source |
| Where is Bangalore? | People & policies | No evidence: the corpus describes travel limits, not geography |
| What is my remaining live leave balance? | People & policies | No evidence: the app is not connected to a live employee balance system |

A clear no-evidence response is expected when the documents cannot answer the question. It should not appear as a generic API error.

## Files to understand first

| Path | Responsibility |
|---|---|
| `start.py` | Prepare the local session and run both services |
| `app.py`, `ui/styles.css` | Streamlit interface and beige/red/black theme |
| `hr_rag/api.py` | Authentication dependencies, request validation and API routes |
| `hr_rag/config.py`, `.env.example` | Configuration and defaults |
| `hr_rag/bootstrap.py` | Select components and import approved sources |
| `hr_rag/parse.py`, `policy.py`, `chunking.py`, `ingestion.py` | Parse, classify, split and publish document versions |
| `hr_rag/lexical.py` | Default local BM25 search |
| `hr_rag/embeddings.py`, `vectors.py` | Optional neural embeddings and Qdrant search |
| `hr_rag/engine.py`, `generation.py` | Retrieve evidence, generate or quote answers, validate citations |
| `hr_rag/security.py`, `cache.py`, `registry.py` | Access decisions, scoped caching and source metadata |
| `data/source/`, `data/parsed/` | Originals and parser exports |
| `config/`, `scripts/`, `tests/`, `reports/` | Policies, utility commands, tests and validation records |

The Python files have consistent spacing and `#` comments explaining why major steps are needed. `engine.py` includes a numbered retrieval-to-answer flow. For more detail, read [docs/README.md](docs/README.md).

## Optional semantic retrieval

Dense retrieval uses a pretrained embedding model to represent passages and questions as vectors, then searches them in Qdrant. It is optional and requires additional setup. Follow the complete commands in [the dense retrieval run guide](docs/RUN_GUIDE.md#optional-dense-retrieval-with-qdrant). Keep the default lexical mode for the simplest first run.

## Troubleshooting

| Symptom | Action |
|---|---|
| `py` is not recognized | Install Python 3.11/3.12 with the Windows launcher, reopen PowerShell and check the version. If `python` already points to a compatible version, use it to create `.venv`. |
| `requirements.txt` or `start.py` cannot be found | Open the terminal in the extracted project root, not its parent folder. |
| `ModuleNotFoundError` | Install requirements with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`, then start with that same interpreter. |
| Port 8000 or 8501 is occupied | Stop the older launcher with Ctrl+C, or use `start.py --api-port 8001 --ui-port 8502` with the virtual environment's Python. Open port 8502 in this case. |
| API is not reachable | Keep the launcher terminal open and inspect its error. Start with `start.py`, not only `app.py`. |
| Session token is invalid | Clear any manually entered Session token and use `start.py` for the local demo. The Groq key is a different credential. |
| Only source excerpts appear | This is the default. For Groq, set a real key, `ENABLE_EXTERNAL_LLM=true` and `GENERATION_MODE=auto`, then restart. Read any fallback warning. |
| Groq rejects the key/model or reaches a limit | Check your key, model access and account limits; update `.env` and restart. Provider failures do not require changing the Python code. |
| No documents appear | Select People & policies or IT & operations, check that `data/source/` contains the six originals and `AUTO_IMPORT_DATASET=true`, then use Check connection. Restricted sources are not available to the demo identity. |
| Dense mode fails to start | Check Qdrant and the model download, or return to `RETRIEVAL_MODE=lexical` and restart. |

More instructions are in [docs/RUN_GUIDE.md](docs/RUN_GUIDE.md#troubleshooting-in-order).

## Tests and verification

Run these from the project folder on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app.py start.py hr_rag scripts tests
```

The optional Qdrant test can be skipped when its optional package is not installed. The test suite uses simulated provider responses for Groq; it does not validate a real API key. See [reports/VALIDATION_SUMMARY.md](reports/VALIDATION_SUMMARY.md) for the recorded runtime and browser checks and their limits. The latest code-readability pass verified formatting, compilation and unchanged syntax-tree logic for all 33 Python files. This documentation update changes no application code or datasets.

The previous repair corrected dictionary handling in the Groq request, added actionable API errors and local excerpt fallback, separated liveness from readiness, restored source files, retained PDF table provenance and refreshed the interface. Live Groq access, external dense services and a real enterprise identity provider still need verification in the target environment.

## Scope and limitations

The application answers from its approved documents. It does not provide general web search, live HR balances, model training or guaranteed factual correctness. Default BM25 retrieval is keyword-based; local excerpts are not LLM-generated answers. Read citations and policy qualifications before relying on an answer.

This is a local single-writer project. Multi-user use requires a verified identity provider and appropriate deployment controls. Keep `.env`, runtime indexes and private source data out of public commits; the supplied `.gitignore` excludes them.
