"""
app.py — AI Interview Question Generator
----------------------------------------
Run:   python app.py      then open http://127.0.0.1:5000

Endpoints
  GET  /              -> the web interface
  GET  /api/status    -> which AI provider is active
  POST /api/generate  -> generate interview questions
  POST /api/evaluate  -> score a practice answer
  POST /api/problems  -> a fresh set of LeetCode / Codeforces practice problems
"""

import os
import re
from pathlib import Path

from flask import Flask, jsonify, render_template, request

try:  # load settings from the .env file next to this script (works from any folder)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

import problem_sources as ps
from ai_client import AIClient, AIError
from prompts import (EVALUATOR_SYSTEM, GENERATOR_SYSTEM, build_evaluation_prompt,
                     build_generation_prompt, split_evenly)
from question_bank import evaluate_offline, generate_offline

app = Flask(__name__)
ai = AIClient()

LEVELS = ["Fresher / Intern", "Junior (0-2 yrs)", "Mid-level (2-5 yrs)", "Senior (5+ yrs)"]
TYPES = ["Technical", "Behavioral", "HR", "Situational", "Coding", "System Design"]
DIFFICULTIES = ["Easy", "Medium", "Hard", "Mixed"]
MIN_QUESTIONS = 10
MAX_QUESTIONS = 15
DEFAULT_QUESTIONS = 12
MAX_PROBLEMS = 10
MAX_AVOID = 40          # previously seen questions sent to the AI so it writes new ones
SPARE_QUESTIONS = 2     # ask for a couple extra, in case some turn out to be repeats


# --------------------------------------------------------------- validation
def parse_generate_request(data: dict) -> dict:
    role = str(data.get("role", "")).strip()
    if not role:
        raise ValueError("Please enter a job role.")
    if len(role) > 100:
        raise ValueError("Job role is too long.")

    try:
        count = int(data.get("count", DEFAULT_QUESTIONS))
    except (TypeError, ValueError):
        count = DEFAULT_QUESTIONS
    count = max(MIN_QUESTIONS, min(MAX_QUESTIONS, count))

    types = [t for t in data.get("types", []) if t in TYPES] or ["Technical", "Behavioral", "HR"]
    level = data.get("level") if data.get("level") in LEVELS else LEVELS[0]
    difficulty = data.get("difficulty") if data.get("difficulty") in DIFFICULTIES else "Mixed"

    try:
        problem_count = int(data.get("problem_count", 5))
    except (TypeError, ValueError):
        problem_count = 5
    problem_count = max(0, min(MAX_PROBLEMS, problem_count))

    raw_skills = str(data.get("skills", ""))
    skills = [s.strip() for s in raw_skills.split(",") if s.strip()][:15]

    return {
        "role": role,
        "level": level,
        "types": types,
        "difficulty": difficulty,
        "count": count,
        "problem_count": problem_count,
        "skills": skills,
        "company": str(data.get("company", "")).strip()[:100],
        "job_description": str(data.get("job_description", ""))[:4000],
    }


def parse_avoid(data: dict) -> list:
    """Questions the user has already seen (sent by the browser), newest first."""
    raw = data.get("avoid", [])
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for q in raw:
        q = " ".join(str(q).split())[:200]
        if q and _norm(q) not in seen:
            seen.add(_norm(q))
            out.append(q)
        if len(out) == MAX_AVOID:
            break
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def clean_questions(result: dict, params: dict, avoid=()) -> dict:
    """Fill in missing fields, drop repeats, and trim the spares evenly across question types."""
    count = params["count"]
    questions = []
    seen = {_norm(q) for q in avoid}
    raw = result.get("questions", [])
    for q in raw if isinstance(raw, list) else []:
        if not isinstance(q, dict) or not q.get("question"):
            continue
        key = _norm(str(q["question"]))
        if key in seen:
            continue
        seen.add(key)
        kp = q.get("key_points", [])
        questions.append({
            "question": str(q["question"]).strip(),
            "type": str(q.get("type", "General")),
            "difficulty": str(q.get("difficulty", "Medium")),
            "topic": str(q.get("topic", "")),
            "why_asked": str(q.get("why_asked", "")),
            "key_points": [str(x) for x in kp] if isinstance(kp, list) else [str(kp)],
            "follow_up": str(q.get("follow_up", "")),
        })
    if not questions:
        raise AIError("The model did not return any questions.")

    # keep each type's share (e.g. 4/4/4), then fill any gaps with whatever is left
    quota = split_evenly(count, params["types"])
    keep, spare = [], []
    for q in questions:
        if quota.get(q["type"], 0) > 0:
            quota[q["type"]] -= 1
            keep.append(q)
        else:
            spare.append(q)
    keep += spare[: max(0, count - len(keep))]
    order = {id(q): i for i, q in enumerate(questions)}
    questions = sorted(keep, key=lambda q: order[id(q)])
    tips = result.get("tips", [])
    return {"questions": questions, "tips": [str(t) for t in tips] if isinstance(tips, list) else []}


def select_problems(raw: dict, candidates: list, n: int) -> list:
    """Keep the problems the AI picked (validating ids), topping up if it picked too few."""
    by_id = {c["id"]: c for c in candidates}
    chosen = []
    picks = raw.get("practice_problems", []) if isinstance(raw, dict) else []
    for pick in picks if isinstance(picks, list) else []:
        if not isinstance(pick, dict):
            continue
        card = by_id.pop(str(pick.get("id")), None)  # pop -> no duplicates, no invented ids
        if card:
            card = dict(card, why=str(pick.get("why", "")), hint=str(pick.get("hint", "")))
            chosen.append(card)
        if len(chosen) == n:
            break
    if len(chosen) < n:
        chosen += ps.default_annotations([dict(c) for c in list(by_id.values())[: n - len(chosen)]])
    return chosen


def build_practice(params: dict, pack: dict, problems: list) -> dict:
    topics = pack.get("topics", [])
    if params["problem_count"] == 0:  # user chose "None"
        return {"problems": [], "topics": [], "resources": [], "sources": {}, "note": None}
    note = None
    if not problems:
        note = ("No coding practice problems for this role - add technical skills "
                "(e.g. 'arrays, SQL') or select the Coding question type to get some.")
    return {
        "problems": problems,
        "topics": ps.topic_links(topics),
        "resources": ps.pick_resources(params, topics),
        "sources": ps.sources_status(),
        "note": note,
    }


# ------------------------------------------------------------------ routes
@app.route("/")
def index():
    return render_template("index.html", levels=LEVELS, types=TYPES, difficulties=DIFFICULTIES,
                           min_questions=MIN_QUESTIONS, max_questions=MAX_QUESTIONS,
                           default_questions=DEFAULT_QUESTIONS,
                           google_client_id=os.getenv(
                               "GOOGLE_CLIENT_ID",
                               "400815208102-our5oiq3f5oeg451tv3bm355uuf6ng1p.apps.googleusercontent.com",
                           ).strip())


@app.get("/api/status")
def status():
    return jsonify({**ai.describe(), "problem_sources": ps.sources_status()})


@app.post("/api/generate")
def generate():
    try:
        params = parse_generate_request(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    avoid = parse_avoid(request.get_json(silent=True) or {})
    n_problems = params["problem_count"]
    pack = ps.find_candidates(params, n_problems) if n_problems else {"candidates": [], "topics": []}
    candidates = pack["candidates"]

    notice = None
    if ai.is_online:
        try:
            ask = dict(params, count=params["count"] + SPARE_QUESTIONS)
            raw, model_used = ai.generate_json(
                GENERATOR_SYSTEM, build_generation_prompt(ask, candidates, n_problems, avoid))
            result = clean_questions(raw, params, avoid)
            problems = select_problems(raw, candidates, n_problems)
            if len(result["questions"]) < params["count"]:
                notice = (f"The AI returned {len(result['questions'])} new questions instead of "
                          f"{params['count']}. Click \"New set\" for more.")
            result.update(source="ai", model=model_used, params=params, notice=notice,
                          practice=build_practice(params, pack, problems))
            return jsonify(result)
        except AIError as exc:
            app.logger.warning("AI generation failed, falling back to offline bank: %s", exc)
            notice = f"AI unavailable - {exc} Showing questions from the offline bank instead."
    else:
        notice = ai.describe().get("reason") or None

    result = generate_offline(params, avoid)
    problems = ps.default_annotations([dict(c) for c in candidates[:n_problems]])
    result.update(source="offline", params=params, notice=notice,
                  practice=build_practice(params, pack, problems))
    return jsonify(result)


@app.post("/api/problems")
def problems():
    """A fresh random set of practice problems (no AI call, to save API quota)."""
    data = request.get_json(silent=True) or {}
    try:
        params = parse_generate_request(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if params["problem_count"] == 0:
        params["problem_count"] = 5
    pack = ps.find_candidates(params, params["problem_count"])
    exclude = set(data.get("exclude", []))
    fresh = [c for c in pack["candidates"] if c["url"] not in exclude] or pack["candidates"]
    chosen = ps.default_annotations([dict(c) for c in fresh[: params["problem_count"]]])
    return jsonify(build_practice(params, pack, chosen))


@app.post("/api/evaluate")
def evaluate():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()
    answer = str(data.get("answer", "")).strip()
    role = str(data.get("role", "candidate")).strip() or "candidate"
    level = str(data.get("level", "")).strip()

    if not question or not answer:
        return jsonify({"error": "Both question and answer are required."}), 400
    if len(answer) > 5000:
        return jsonify({"error": "Answer is too long (max 5000 characters)."}), 400

    if ai.is_online:
        try:
            raw, _ = ai.generate_json(EVALUATOR_SYSTEM,
                                      build_evaluation_prompt(question, answer, role, level),
                                      temperature=0.3, max_tokens=2048)
            score = int(raw.get("score", 0))
            return jsonify({
                "score": max(0, min(10, score)),
                "verdict": str(raw.get("verdict", "")),
                "strengths": [str(s) for s in raw.get("strengths", [])],
                "improvements": [str(s) for s in raw.get("improvements", [])],
                "model_answer": str(raw.get("model_answer", "")),
                "source": "ai",
            })
        except (AIError, ValueError, TypeError) as exc:
            app.logger.warning("AI evaluation failed, using heuristic: %s", exc)

    result = evaluate_offline(question, answer)
    result["source"] = "offline"
    return jsonify(result)


if __name__ == "__main__":
    info = ai.describe()
    ps.warm_cache_in_background()  # pre-load LeetCode / Codeforces problem lists
    print(f"\n  AI provider: {info['provider']}  |  model: {info['model']}")
    if info.get("fallbacks"):
        print(f"  Backups:     {', '.join(info['fallbacks'])}")
    if info.get("reason"):
        print(f"  Note:        {info['reason']}")
    print("  Open http://127.0.0.1:5000 in your browser\n")
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=int(os.getenv("PORT", 5000)))
