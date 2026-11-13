"""
prompts.py
----------
All prompt engineering lives here, so it is easy to explain and tweak.

Techniques used:
  * Role prompting       - the model acts as an experienced interviewer / coach.
  * Exact quotas         - the app works out how many questions of each type and
                           difficulty to ask for, instead of leaving it vague.
  * Novelty              - questions the user has already seen are sent as an
                           "avoid" list, plus a random angle each time, so every
                           set is new.
  * Strict JSON schema   - the reply can be parsed and shown as cards.
  * Short fields         - keeps 10-15 questions fast to generate.
"""

import random

GENERATOR_SYSTEM = """You are a senior hiring manager who has interviewed hundreds of candidates.
You write realistic, specific interview questions that a real interviewer at a good company
would actually ask - not textbook or generic ones.
Every question you write is new: never repeat or lightly reword a question the user has seen.
Always reply with one valid JSON object and nothing else."""

EVALUATOR_SYSTEM = """You are a fair but demanding interview coach.
You evaluate a candidate's answer to an interview question, give a score out of 10,
and explain concretely how to improve. Be encouraging but honest.
Always reply with one valid JSON object and nothing else."""

TYPE_GUIDE = {
    "Technical": "concrete concepts and tools from the skills list; ask 'how' and 'why', not definitions",
    "Behavioral": "past experiences, answerable with the STAR method (Situation, Task, Action, Result)",
    "HR": "motivation, career goals, culture fit - phrased specifically for this role and company",
    "Situational": "a realistic 'what would you do if...' scenario from this job",
    "Coding": "a small, self-contained problem that can be solved in 20-30 minutes, with input/output stated",
    "System Design": "design a component or system relevant to this role, scaled to the experience level",
}

FRESH_ANGLES = [
    "a production incident or bug", "trade-offs between two approaches", "a recent project deep-dive",
    "edge cases and failure modes", "working with a difficult stakeholder", "performance and scale",
    "learning something new quickly", "ambiguous requirements", "code or design review",
    "a mistake and what was learned", "prioritising under a deadline", "explaining to a non-technical person",
    "security or data privacy", "testing and quality", "mentoring or teamwork",
]


def split_evenly(total: int, buckets: list) -> dict:
    """e.g. 12 questions over 3 types -> {A: 4, B: 4, C: 4}; remainders go to the first types."""
    base, extra = divmod(total, len(buckets))
    return {b: base + (1 if i < extra else 0) for i, b in enumerate(buckets)}


def difficulty_plan(total: int, difficulty: str) -> str:
    if difficulty != "Mixed":
        return f"all {total} questions should be {difficulty}"
    easy = round(total * 0.3)
    hard = round(total * 0.3)
    return f"{easy} Easy, {total - easy - hard} Medium and {hard} Hard"


def build_generation_prompt(p: dict, candidates=None, n_problems: int = 0, avoid=None) -> str:
    skills = ", ".join(p["skills"]) if p["skills"] else "not specified - infer typical skills for the role"
    jd = p["job_description"].strip() or "not provided"
    quotas = split_evenly(p["count"], p["types"])
    quota_lines = "\n".join(f"- {n} x {t}: {TYPE_GUIDE[t]}" for t, n in quotas.items() if n)
    angles = ", ".join(random.sample(FRESH_ANGLES, 3))

    avoid_section = ""
    if avoid:
        listed = "\n".join(f"- {q}" for q in avoid)
        avoid_section = f"""
The candidate has ALREADY seen these questions. Do not repeat them, reword them,
or ask about the same scenario:
{listed}
"""

    problems_section, problems_schema = "", ""
    if candidates and n_problems:
        listing = "\n".join(
            f"{c['id']}: [{c['source']}, {c['difficulty']}, tags: {', '.join(c['tags'])}] {c['title']}"
            for c in candidates
        )
        problems_section = f"""
Also pick the {n_problems} most relevant practice problems for this candidate from this list
of real LeetCode/Codeforces problems (vary the topics; use only ids from the list):
{listing}
For each, give "why" (one sentence: why it matters for this role) and "hint" (a nudge
towards the approach, never the full solution).
"""
        problems_schema = ',\n  "practice_problems": [{"id": "P1", "why": "...", "hint": "..."}]'

    return f"""Write exactly {p['count']} NEW interview questions for this candidate.

Candidate
- Job role: {p['role']}
- Experience level: {p['level']}
- Key skills / topics: {skills}
- Company or industry: {p['company'] or 'not specified'}
- Job description: {jd}

How many of each type
{quota_lines}

Difficulty: {difficulty_plan(p['count'], p['difficulty'])}.
For variety, include at least a few questions about: {angles}.
{avoid_section}
Rules
- Make every question specific to this role, level and skill set.
- Prefer less common, thought-provoking questions over the classic textbook ones.
- No two questions may test the same thing.
- Keep it short: each question under 45 words, "why_asked" under 20 words,
  3-4 "key_points" of under 15 words each, one short "follow_up".
{problems_section}
Return JSON in exactly this shape, with exactly {p['count']} items in "questions":
{{
  "questions": [
    {{
      "question": "the interview question",
      "type": "one of: {' | '.join(p['types'])}",
      "difficulty": "Easy | Medium | Hard",
      "topic": "short topic label, e.g. 'SQL joins'",
      "why_asked": "what the interviewer is assessing",
      "key_points": ["what a strong answer covers"],
      "follow_up": "a likely follow-up question"
    }}
  ],
  "tips": ["2-3 short preparation tips for this role"]{problems_schema}
}}"""


def build_evaluation_prompt(question: str, answer: str, role: str, level: str) -> str:
    return f"""Evaluate this interview answer.

Role: {role}
Experience level: {level or 'not specified'}
Question: {question}
Candidate's answer: {answer}

Return JSON in exactly this shape:
{{
  "score": <integer 0-10>,
  "verdict": "one short sentence summary",
  "strengths": ["what was good"],
  "improvements": ["specific things to add or fix"],
  "model_answer": "a concise, strong example answer (4-8 sentences)"
}}"""
