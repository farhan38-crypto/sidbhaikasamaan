# AI Interview Question Generator

A web app that uses Generative AI to create **tailored interview questions** for any job role,
lets candidates **practice answering** them and get **AI feedback with a score out of 10**, and
recommends **real coding problems from LeetCode and Codeforces** to practise.

Built with **Python (Flask)** on the backend and **HTML / CSS / JavaScript** on the frontend.
Uses **Google Gemini** as the main AI with **Groq** (or any OpenAI-compatible API) as an automatic
backup, and has an **offline demo mode** so it runs even without internet or an API key.

---

## Features

| Feature | Description |
|---|---|
| Role-based generation | Enter any job role (e.g. "Data Analyst"), experience level and skills |
| 6 question types | Technical, Behavioral, HR, Situational, Coding, System Design |
| Difficulty control | Easy / Medium / Hard / Mixed, 10–15 questions per set |
| Always new questions | Click **New set** for another 10–15 questions; ones you've already seen for that role are never repeated |
| Job description input | Paste a real job posting for highly relevant questions |
| Answer guide | For each question: why it's asked, key points to cover, a likely follow-up |
| Practice mode | Type an answer → AI scores it (0–10), lists strengths, improvements and gives a model answer |
| Real coding problems | 3–10 practice problems from **LeetCode** and **Codeforces**, matched to the role's topics and difficulty, with AI-written "why this matters" and a hint (never the solution) |
| Topic reading | One-click links to read up on each topic on **GeeksforGeeks** |
| Prep resources | Hand-picked free GitHub prep repos (Tech Interview Handbook, System Design Primer, …) chosen by role |
| Filter by type | Quickly view only Technical / HR / etc. questions |
| Export | Copy all, download as `.txt`, or print / save as PDF |
| History | Last 10 generated sets saved in the browser (localStorage) |
| Fallback | If the AI fails (no key, no internet, quota exceeded) the app switches to a built-in question bank |
| Sign-in | Demo account (Sid Rawat) or Google sign-in |

---

## How to run

**Requirements:** Python 3.9+

```bash
# 1. Go into the project folder
cd interview-question-generator

# 2. (Recommended) create a virtual environment
python -m venv venv
# Windows:      venv\Scripts\activate
# Mac / Linux:  source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add an API key (optional — skip to run in offline demo mode)
#    Copy .env.example to .env and paste your key
cp .env.example .env          # Windows: copy .env.example .env

# 5. Start the app
python app.py
```

Open **http://127.0.0.1:5000** in your browser.
The badge in the top-right corner shows whether the AI is connected or the app is in offline mode.

### API keys (`.env`)

| Setting | What it does |
|---|---|
| `GEMINI_API_KEY` | Main AI. Free key from <https://aistudio.google.com/apikey> (new keys start with `AQ.`, older ones with `AIza` — both work) |
| `GEMINI_MODEL` | Models to try, in order. Default `gemini-flash-lite-latest,gemini-flash-latest` (fast first, stronger backup) |
| `OPENAI_API_KEY` | Backup AI. A free Groq key from <https://console.groq.com/keys> (starts with `gsk_`) is detected automatically |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | Default Groq + `openai/gpt-oss-120b`; change for OpenAI or OpenRouter |
| `AI_PROVIDER` | Which AI to try first: `gemini`, `openai`, or `offline` to switch AI off |
| `AI_TIMEOUT` | Seconds to wait for each model before moving to the next (default 45) |

When you start `python app.py`, the terminal prints which AI and backups are active.
If every AI fails, the yellow notice above the questions says exactly why
(invalid key, quota used up, model overloaded, timed out, …).

### Sign-in

**Continue as Sid Rawat** opens the local demo workspace. The Google button uses the OAuth client ID
in `app.py` (or `GOOGLE_CLIENT_ID` in `.env`); add `http://127.0.0.1:5000` to that client's
*Authorized JavaScript origins* in Google Cloud Console. Sign-in only personalises the browser
session — nothing is stored on the server.

---

## Project structure

```
interview-question-generator/
├── app.py              # Flask server: routes, input validation, fallback logic
├── ai_client.py        # Talks to the AI provider (Gemini / OpenAI-compatible), parses JSON
├── prompts.py          # Prompt engineering: system + user prompts for generation & evaluation
├── question_bank.py    # Offline question bank + heuristic answer scoring
├── problem_sources.py  # LeetCode + Codeforces problems, topic detection, caching, resources
├── data/
│   ├── leetcode_curated.json    # 176 well-known LeetCode problems (incl. 36 SQL) – offline backup
│   ├── codeforces_curated.json  # well-known Codeforces problems – offline backup
│   └── cache/                   # auto-created: live data saved for 24 h
├── templates/
│   └── index.html      # Page layout (Jinja2 template)
├── static/
│   ├── style.css       # Styling, responsive layout, dark mode, print styles
│   └── script.js       # UI logic: API calls, rendering, practice mode, export, history
├── requirements.txt
├── .env                # Your API keys (private, not committed)
├── .env.example        # Template for API keys
└── README.md
```

---

## Architecture

```
 Browser (HTML/CSS/JS)
   │  1. user fills form → POST /api/generate  (JSON)
   ▼
 Flask backend (app.py)
   │  2. validates input
   │  3. builds a prompt (prompts.py)
   ▼
 AI client (ai_client.py) ──► Gemini / OpenAI-compatible LLM
   │  4. model returns JSON (questions, key points, follow-ups)
   │  5. JSON is cleaned & validated
   │     └─ on any failure → question_bank.py (offline fallback)
   ▼
 Browser renders question cards
   │  6. user types a practice answer → POST /api/evaluate
   ▼
 LLM scores the answer → score, strengths, improvements, model answer
```

### API endpoints

| Method | Route | Body | Returns |
|---|---|---|---|
| GET | `/` | – | Web page |
| GET | `/api/status` | – | Active AI provider and model |
| POST | `/api/generate` | `role, level, difficulty, types[], skills, company, count (10–15), problem_count, job_description, avoid[]` | `questions[]`, `tips[]`, `practice`, `source`, `model` |
| POST | `/api/evaluate` | `question, answer, role, level` | `score, verdict, strengths[], improvements[], model_answer` |
| POST | `/api/problems` | same as `/api/generate` + `exclude[]` | a fresh set of practice problems (no AI call) |

---

## Where the practice problems come from

| Source | How | If it's unavailable |
|---|---|---|
| **Codeforces** | Official public API `codeforces.com/api/problemset.problems` (no key needed). Filtered by tag (dp, graphs, …) and rating (800–2300), preferring problems solved by many people | Uses the last saved copy, else a bundled list of well-known problems |
| **LeetCode** | The GraphQL endpoint leetcode.com itself uses (unofficial). Premium problems are skipped. A curated list of classic interview problems is used first; live data adds acceptance rates, removes anything renamed/premium, and adds more problems | Uses the last saved copy, else the bundled curated list |
| **GeeksforGeeks** | Topic reading links only — **no scraping** | – |
| **GitHub repos** | Links to well-known free prep repos, chosen by role | – |

- **Only metadata is stored** (title, difficulty, tags, link) — never problem statements, which belong to
  the platforms. Clicking a problem opens it on the original site.
- **Caching:** live lists are fetched once at startup and saved in `data/cache/` for 24 hours, so each site
  is contacted at most once a day. After a failed fetch the app waits 10 minutes before retrying.
- **Topic detection:** keywords in the role / skills / job description (e.g. "SQL", "trees", "DP") map to
  LeetCode tags and Codeforces tags. If none are given, defaults are chosen by role
  (e.g. Data Analyst → SQL + arrays, SDE → arrays, two pointers, trees, graphs, DP).
  Problems are balanced across topics. Non-technical roles get no coding problems.
- **AI + real data (retrieval-augmented generation):** the app sends the AI a shortlist of real candidate
  problems; the AI picks the most relevant ones and writes the "why" and hint. The app checks every id
  the AI returns, so the AI can't invent problems or links.

---

## How the AI part works (for the viva)

1. **Prompt engineering** – `prompts.py` gives the model a *role* (senior hiring manager), the
   candidate's details, an **exact quota** of questions per type and difficulty
   (e.g. 12 questions → 4 Technical, 4 Behavioral, 4 HR; 30 % easy / 40 % medium / 30 % hard),
   short-length limits so 15 questions still come back in seconds, and a **JSON schema** to reply in.
   - **Novelty:** the browser sends the questions already shown for that role (up to 40), and the
     prompt tells the AI not to repeat or reword them. A random "angle" (e.g. *production incident*,
     *trade-offs*, *ambiguous requirements*) is added each time for variety. The server also drops
     any exact repeats the AI still returns.
2. **Structured output** – the request asks the model for `application/json`, so the reply
   can be parsed and rendered as cards instead of a block of text.
3. **Robust parsing** – `extract_json()` strips markdown code fences and extra text in case
   the model adds them; `clean_questions()` fills in any missing fields.
4. **Temperature** – `0.8` for generation (more variety), `0.3` for evaluation (more consistent scoring).
5. **Reliability** – `ai_client.py` tries a chain of models: Gemini Flash-Lite → Gemini Flash →
   Groq. "Thinking" is kept low (`thinkingLevel`/`reasoning_effort`) so answers arrive in seconds,
   each model gets a 45 s timeout, and if everything fails the app falls back to the offline
   question bank, so a live demo never breaks.
6. **Security** – the API key stays on the server (in `.env`), never sent to the browser.
   All AI text is inserted with `textContent`, not `innerHTML`, which prevents script injection.

7. **Grounding** – practice problems come from real LeetCode/Codeforces data; the AI only chooses
   among them and explains them (a simple form of retrieval-augmented generation).

### Possible future enhancements
- Voice mode: speech-to-text for answers and text-to-speech for questions
- Resume upload (PDF) → questions generated from the candidate's own projects
- A database to track each user's progress over time
- Timed mock-interview mode with a final report

---

## Tech stack
Python · Flask · Requests · Google Gemini API / OpenAI-compatible API · Codeforces API · LeetCode GraphQL · HTML5 · CSS3 · Vanilla JavaScript
