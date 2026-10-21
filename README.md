# Nyaya Mitra — legal information and citizen guidance prototype

Nyaya Mitra is a local Streamlit application for searching and asking questions about **Indian legal documents that you actually index**. It is a final-year B.Tech demonstration prototype. It is **not** an official government service, **not** a substitute for a lawyer, and it does **not** claim complete legal or multilingual accuracy.

Answers are limited to retrieved passages. If the indexed documents are insufficient, the application says so.

## What is implemented

- Home library updates, Act name/Act number search, indexed PDF browsing, chat assistant, quiz, and admin upload
- English, Hindi, and Telugu **interface** labels (legal quotations stay in the source language)
- PDF ingestion with SHA-256 duplicate detection, page numbers, conservative section detection, and FAISS retrieval when embeddings load
- Extractive answers when no LLM API key is configured
- Optional OpenAI-compatible RAG with timeout and extractive fallback
- SQLite persistence for documents, chunks, chats, quiz attempts, and admin password hashes
- Persisted chat history that administrators/users of this local instance can reopen or delete
- Admin-managed quiz questions with validation, editing, and removal
- Act-specific quiz rounds generated from uploaded PDF section openings: 10 questions per set, fresh sections in the next set, completion tracking for the active app session, and retakes
- Administrator sign-in (PBKDF2 password hashing). Admin pages are hidden and server-checked

## What is not claimed

- Official verification of uploaded PDFs
- OCR for scanned PDFs (not implemented)
- Per-user private accounts (history is local to this computer)
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
- Set `OPENAI_API_KEY` to an OpenAI-compatible API key if you want generated legal explanations and Hindi/Telugu answer translation. Without it the app still starts with an offline source-reference response; arbitrary PDF passages cannot be translated offline.

Launch:

```bat
streamlit run app.py
```

Or double-click `run_windows.bat`. The batch file creates `.venv` if needed, installs dependencies, copies `.env.example` to `.env` when `.env` is missing, and starts Streamlit. If a step fails it prints the error and waits.

The app uses offline keyword retrieval by default so startup does not wait for a model download. To use semantic retrieval, set `NYAYA_USE_EMBEDDINGS=1` in `.env`; the first launch then downloads `intfloat/multilingual-e5-small` (internet required that one time). If the download fails, the app falls back to keyword search. The interface uses system fonts and does not need Google Fonts to load.

## Administrator access

1. Put `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env` (not in a source file).
2. Restart the app. The password is stored as a PBKDF2 hash in SQLite.
3. Use **Administrator sign-in** in the sidebar.
4. Admin Dashboard and Upload Documents appear only after a successful sign-in. Hiding the menu is not the only control: upload, reprocess, and delete also check `st.session_state.is_admin`.

Limitations: this is session-based Streamlit auth for a **local demo**, not a multi-user internet deployment. Do not expose the app on a public URL.

## PDF upload

1. Sign in as administrator.
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

SQLite file: `data/nyay_mitra.db` (ignored by git). Restarting the app keeps indexed documents, quiz results, and chat rows. Chat history is **not** private per user; anyone with this computer and the app can see recent questions stored locally.

## Public demo deployment (Render)

`render.yaml` configures one Render web service with a persistent disk mounted at `/var/data`. This is required: Render's free web service filesystem is ephemeral, and uploaded laws and the SQLite database would disappear on restart. The Blueprint uses a paid Starter web service and a 1 GB persistent disk; review current plan and storage charges in Render before creating it. A disk-backed service is single-instance and may briefly stop during deploys.

Before pushing the repository, place the text-based public law PDFs you want indexed in `uploads/`. PDFs in that folder are intentionally eligible for Git tracking, so they will be visible in the public repository. Never add `.env`, API keys, the SQLite `.db` file, private documents, or personal data. On first service start, Nyaya Mitra extracts and indexes bundled PDFs into `/var/data`; later uploads from the administrator page are saved there as well. The PDFs must be committed to Git for first-deploy seeding.

Create a new Render Blueprint from your GitHub repository and select `render.yaml`. Set the prompted `ADMIN_PASSWORD` to a unique strong password. `OPENAI_API_KEY` is optional; without it, the app uses its offline source-based answer mode and cannot automatically translate arbitrary answers. If supplied, public users' questions and retrieved excerpts are sent to the configured AI provider to generate answers.

The Blueprint enables `NYAYA_PUBLIC_MODE=1`: chats, search terms, and quiz answers are not saved as user history, and shared recent chats are hidden. Indexed legal documents and uploaded PDFs remain on the persistent disk. This is still a single-instance public prototype, not a production legal service: it has no visitor accounts, per-user private storage, request rate limiting, or guaranteed legal currency. Back up the persistent volume and verify legal texts and amendments against official sources.

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| `python` not found | Install Python 3.10/3.11 and tick “Add python to PATH”. |
| `faiss-cpu` install fails | Confirm you are in `.venv` and using 64-bit Python. |
| Embedding model download hangs | Check internet, or set `NYAYA_USE_EMBEDDINGS=0`. |
| Admin sign-in always fails | Confirm `.env` has `ADMIN_PASSWORD`, then restart. Delete `data/nyay_mitra.db` only if you accept losing local data. |
| Scanned PDF rejected | Provide a text-based PDF. OCR is not in this project. |
| LLM answers not appearing | Expected without `OPENAI_API_KEY`. Extractive answers still run. |

## Disclaimer

Nyaya Mitra provides general legal information and citizen guidance only. It is not legal advice and does not guarantee outcomes. Confirm important matters with an official source and a qualified legal professional.
