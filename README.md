# Nyaya Mitra — legal information and citizen guidance prototype

Nyaya Mitra is a local Streamlit application for searching and asking questions about **Indian legal documents that you actually index**. It is a final-year B.Tech demonstration prototype. It is **not** an official government service, **not** a substitute for a lawyer, and it does **not** claim complete legal or multilingual accuracy.

Answers are limited to retrieved passages. If the indexed documents are insufficient, the application says so.

## What is implemented

- Home library updates, Act name/Act number search, indexed PDF browsing, chat assistant, quiz, and admin upload
- English, Hindi, and Telugu **interface** labels (legal quotations stay in the source language)
- PDF ingestion with SHA-256 duplicate detection, page numbers, chapter/section detection (including bare numbered headings), and FAISS retrieval when embeddings load
- Offline retrieval across all indexed Acts and cited source excerpts when no LLM API key is configured
- Optional multilingual query expansion before retrieval, followed by source-grounded answer generation and Hindi/Telugu translation when an OpenAI-compatible API key is configured
- Optional OpenAI-compatible RAG with timeout and extractive fallback
- SQLite persistence for documents, chunks, chats, quiz attempts, and PBKDF2 password hashes
- One configured administrator login, with admin-uploaded PDFs stored in the shared law library
- Admin-managed quiz questions with validation, editing, and removal
- Act-specific quiz rounds generated from uploaded PDF section openings: 10 questions per set, fresh sections in the next set, completion tracking for the active app session, and retakes
- Administrator sign-in (PBKDF2 password hashing). Admin pages are hidden and server-checked; signed-in accounts can manage their own PDFs

## What is not claimed

- Official verification of uploaded PDFs
- OCR for scanned PDFs (not implemented)
- 100% legal accuracy, up-to-date amendments, or production hardening
- Full multilingual coverage of Indian law (UI translation is not the same as translated statutes)

## Documents currently added to this local project

The local database currently contains uploaded copies of the following Acts, alongside the educational starter records:

- The Protection of Children from Sexual Offences Act, 2012
- The Protection of Women from Domestic Violence Act, 2005
- The Bharatiya Nyaya Sanhita, 2023 (the supplied PDF says “As on 6 October 2025”)
- The Consumer Protection Act, 2019
- The Information Technology Act, 2000

These PDFs were supplied as uploads and are marked `unverified_upload`. Their presence in the app does not establish official source, completeness, or current legal status. The app opens on the chat assistant; Home and other modules remain available in the sidebar. Home highlights documents in the local library and is not a live legal-news feed. Browse Laws supports searching by Act name or Act number and lists uploaded PDFs by enactment year. Quizzes use section-opening lines extracted from each PDF and cite the original page; extraction quality varies with the supplied file.

Starter records in `data/legal_knowledge.json` are **educational samples or short public excerpts**. Replace them with text you have checked against India Code or another official source before a graded demonstration of “grounded law”.

## Supported Python

Use **Python 3.10, 3.11, or 3.12**. The Render deployment is pinned to Python 3.12.11 in `.python-version`.

## Windows setup

Open Command Prompt or PowerShell in this folder:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` **privately**:

- Set `ADMIN_PASSWORD` to a password you will not screenshot or commit.
- Set `OPENAI_API_KEY` to an OpenAI-compatible API key for the detailed legal explanations, supported next steps, and Hindi/Telugu answer translation. Without it the app can retrieve and show citations, but it cannot generate the requested explanation or translate arbitrary PDF passages.

Launch:

```bat
streamlit run app.py
```

Or double-click `run_windows.bat`. The batch file creates `.venv` if needed, installs dependencies, copies `.env.example` to `.env` when `.env` is missing, and starts Streamlit. If a step fails it prints the error and waits.

The app uses offline keyword retrieval by default so startup does not wait for a model download. Semantic retrieval packages are intentionally excluded from the default deployment requirements. To enable multilingual semantic retrieval without an AI API, install `requirements-embeddings.txt`, then set `NYAYA_USE_EMBEDDINGS=1` in `.env`; the first launch then loads/downloads `intfloat/multilingual-e5-small` (internet required if it is not cached). This optional setup may download large machine-learning dependencies. If model loading fails, the app falls back to keyword search. A configured `OPENAI_API_KEY` also enables general Telugu/Hindi-to-English query expansion before searching English PDFs. Without either capability, cross-language matching is limited; the app still shows exact retrieved source passages and must not claim universal multilingual coverage. The interface uses system fonts and does not need Google Fonts to load.

## Administrator access

For local use, configure `ADMIN_USERNAME` and `ADMIN_PASSWORD` in the ignored `.env` file. The Admin Portal presents one centered login form; account registration is disabled. The configured administrator can upload and manage PDFs, and the password is stored as a PBKDF2 hash in SQLite.

For a public deployment, configure `ADMIN_USERNAME` and a unique `ADMIN_PASSWORD` in the hosting provider's environment or secrets before launch. Do not commit credentials. Only the configured administrator can access the upload and management pages.

Limitations: this is a small Streamlit demonstration, not production identity management. Use a persistent disk for hosted deployments, protect the administrator secret, and do not treat the app as a secure legal case-management system.

## Indian Acts directory

The Laws page includes the 891-entry Central Acts title list published by the Legislative Department in June 2025. It is an index of titles, years, and Act numbers, not a bundle of the full Act texts; those entries may include historical or repealed Acts. Use the India Code links on the page to open official Act text and browse Central and State Acts, and check official sources for amendments and current status. The app does not claim to contain every current Indian law or every State law locally.

## PDF upload

1. Sign in to **Admin Portal** with the configured administrator credentials.
2. Open **Upload Documents** or **Admin Dashboard**.
3. Choose a **text-based** PDF (not a scan).
4. Enter Act/document name and an official source URL if you have one (for example an India Code link). Uploading does **not** mark the file as officially verified.
5. Processing rejects duplicates (SHA-256), files that are not PDFs, oversized files, encrypted PDFs, corrupt PDFs, and files with too little extractable text.

If extraction finds almost no text, the app reports that OCR would be needed. OCR is **not** implemented.

## Tests

```bat
.venv\Scripts\activate
python -m pytest
```

Tests use synthetic PDFs and mocked LLM clients. They do not need a paid API key.

## Persistence model

The administrator hash is in `data/nyay_mitra.db`. Bundled Acts and PDFs uploaded through the Admin Portal are stored in the shared `data/law_library/` database and `data/law_library/uploads/` folder. Admin uploads are visible on Home and Browse Laws and available to every visitor's assistant. Chat history remains under the signed-in profile when history is enabled. These runtime files are ignored by git.

## Free public demo deployment (Streamlit Community Cloud)

The app can run on Streamlit Community Cloud without a paid server plan. Connect the GitHub repository `poppoppulanaresh-max/NyayaMitra`, choose the `main` branch and `app.py` as the entrypoint, then add the values from `streamlit-secrets.example.toml` under **App settings → Secrets**. At minimum, set `NYAYA_PUBLIC_MODE = "1"`. Choose a unique `ADMIN_PASSWORD`; do not paste a real password into this repository. The `.streamlit/secrets.toml` file is ignored by Git if you create it locally.

Set `ADMIN_USERNAME = "NyayaMitra"` and set `ADMIN_PASSWORD` in the private Secrets panel to the password you intend to use. The repository example contains placeholders only. Add a valid `OPENAI_API_KEY` there as well; this is required for the detailed answer format and regional-language translation. If sign-in rejects the values, check for old admin environment variables: environment variables take precedence over Streamlit Secrets. Save changes and reboot the app so it reloads configuration. The assistant detects Hindi or Telugu script and answers in that language. It translates retrieved English passages as an unofficial explanation, cites the Act and provision, and gives next steps or escalation only when the evidence supports them. Questions and retrieved legal excerpts are sent to the configured provider, so tell visitors not to enter private or sensitive case details.

Streamlit Community Cloud uses an ephemeral local filesystem. PDFs committed in `uploads/` are included with the app and can be re-indexed after restart, but account databases and user-uploaded PDFs are not durable and may be lost on restart or redeploy. Public mode avoids keeping chat/search/quiz histories. Keep a separate copy of source PDFs. For persistent account uploads and databases, use the paid disk-backed Render configuration below.

## Paid public demo deployment (Render)

`render.yaml` configures one Render web service with a persistent disk mounted at `/var/data`. This is required: Render's free web service filesystem is ephemeral, and uploaded laws and the SQLite database would disappear on restart. The Blueprint uses a paid Starter web service and a 1 GB persistent disk; review current plan and storage charges in Render before creating it. A disk-backed service is single-instance and may briefly stop during deploys.

Before pushing the repository, place the text-based public law PDFs you want included in `uploads/`. PDFs in that folder are intentionally eligible for Git tracking, so they will be visible in the public repository. Never add `.env`, API keys, the SQLite `.db` file, private documents, or personal data. On first service start, Nyaya Mitra extracts and indexes the bundled starter PDFs once into the shared library under `/var/data/data/law_library/`. Admin uploads are saved in the shared library and immediately available to every visitor; the persistent disk keeps those PDFs and their index across restarts. The PDFs must be committed to Git for first-deploy seeding.

Create a new Render Blueprint from your GitHub repository and select `render.yaml`. The configured username is `NyayaMitra`; set the prompted `ADMIN_PASSWORD` and `OPENAI_API_KEY` in the private environment settings. The AI key is required for generated explanations and Hindi/Telugu translation. Native-script questions can then be expanded into English search terms, and user questions plus retrieved excerpts are sent to the configured AI provider.

The Blueprint enables `NYAYA_PUBLIC_MODE=1`: chat messages, search terms, and quiz answers are not saved as history. The admin account database, shared PDF library, and uploaded files remain on the persistent disk. This is still a single-instance public prototype, not a production legal service; back up the persistent volume and verify legal texts and amendments against official sources.

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| `python` not found | Install Python 3.10/3.11 and tick “Add python to PATH”. |
| Semantic retrieval packages install slowly | They are optional. Install `requirements-embeddings.txt` only if you plan to set `NYAYA_USE_EMBEDDINGS=1`. |
| Embedding model download hangs | Check internet, or leave `NYAYA_USE_EMBEDDINGS=0` to use keyword retrieval. |
| Admin sign-in always fails | Confirm Streamlit Cloud **App settings → Secrets** contains `ADMIN_USERNAME = "NyayaMitra"` and the intended `ADMIN_PASSWORD`. Check hosting environment variables too, because they override Secrets. Save and reboot the app. Do not commit the password. |
| Scanned PDF rejected | Provide a text-based PDF. OCR is not in this project. |
| LLM answers not appearing | Set `OPENAI_API_KEY` in private deployment Secrets or environment settings, verify the configured model is available to that key, then restart/reboot the app. |

## Disclaimer

Nyaya Mitra provides general legal information and citizen guidance only. It is not legal advice and does not guarantee outcomes. Confirm important matters with an official source and a qualified legal professional.
