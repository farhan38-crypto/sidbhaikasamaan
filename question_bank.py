"""
question_bank.py
----------------
Offline fallback so the app still works (e.g. during a demo with no internet
or no API key). Questions are picked from a curated bank and personalised with
the role and skills the user typed. Answer evaluation uses simple heuristics.
"""

import random
import re

# Each entry: (question template, difficulty, topic, why_asked, key_points, follow_up)
# {role} and {skill} are filled in at runtime.
BANK = {
    "Technical": [
        ("Explain the core concepts of {skill} as if you were teaching a new teammate.", "Easy", "{skill} fundamentals",
         "Checks depth of understanding and ability to explain clearly.",
         ["Defines the concept accurately", "Gives a concrete example", "Mentions where it is used in practice"],
         "What is a common mistake beginners make with {skill}?"),
        ("Describe a project where you used {skill}. What design decisions did you make and why?", "Medium", "{skill} in practice",
         "Verifies hands-on experience rather than textbook knowledge.",
         ["Clear problem statement", "Specific decisions and trade-offs", "Measurable result", "What you would change now"],
         "What would break first if usage grew 10x?"),
        ("How would you debug a {skill}-related issue that only appears in production?", "Hard", "Debugging",
         "Assesses systematic problem solving under real constraints.",
         ["Reproduce / gather logs and metrics", "Form and test hypotheses", "Minimise user impact", "Prevent recurrence (tests, monitoring)"],
         "How would you communicate the incident to stakeholders?"),
        ("What are the trade-offs between performance and readability when working with {skill}?", "Medium", "Trade-offs",
         "Tests engineering judgement.",
         ["Gives a concrete example", "Discusses when optimisation is justified", "Mentions profiling before optimising"],
         "Tell me about a time you chose readability over speed."),
        ("How do you test code or work involving {skill}? Walk me through your approach.", "Medium", "Testing",
         "Checks quality mindset.",
         ["Unit vs integration tests", "Edge cases", "Automation / CI", "How you decide what is worth testing"],
         "How do you handle flaky tests?"),
        ("Compare two alternative approaches or tools you could use instead of {skill}. When would you pick each?", "Hard", "Comparison",
         "Assesses breadth and ability to justify choices.",
         ["Names realistic alternatives", "Compares on concrete criteria", "Gives a recommendation with context"],
         "Which one would you choose for a 2-person startup?"),
    ],
    "Behavioral": [
        ("Tell me about a time you had to learn something new very quickly to finish a task.", "Easy", "Learning agility",
         "Evaluates adaptability and self-learning.",
         ["Situation and deadline", "How you learned (resources, people)", "Outcome", "What you learned about yourself"],
         "How do you keep your skills up to date now?"),
        ("Describe a conflict you had with a teammate. How did you resolve it?", "Medium", "Teamwork",
         "Checks collaboration and emotional maturity.",
         ["Neutral description of the conflict", "Your specific actions", "Resolution", "Relationship afterwards"],
         "What would you do if the conflict couldn't be resolved?"),
        ("Tell me about a time you failed or made a significant mistake.", "Medium", "Accountability",
         "Tests honesty, ownership and growth.",
         ["Owns the mistake without blaming others", "Impact", "How it was fixed", "Lesson and changed behaviour"],
         "How do you make sure it doesn't happen again?"),
        ("Give an example of when you took initiative without being asked.", "Medium", "Ownership",
         "Looks for proactive behaviour.",
         ["Spotted a problem/opportunity", "Actions taken", "Result with numbers if possible"],
         "Did anyone push back? How did you handle it?"),
        ("Describe a time you had to juggle multiple deadlines. How did you prioritise?", "Medium", "Time management",
         "Assesses planning and prioritisation.",
         ["Clear prioritisation method", "Communication with stakeholders", "Outcome"],
         "What would you drop first if you could only finish one task?"),
        ("Tell me about the most challenging project you've worked on as a {role}.", "Hard", "Resilience",
         "Gauges complexity handled and persistence.",
         ["Why it was hard", "Your specific contribution", "Result", "Reflection"],
         "What would you do differently?"),
    ],
    "HR": [
        ("Tell me about yourself.", "Easy", "Introduction",
         "First impression and communication skills.",
         ["Brief background", "Relevant skills/projects", "Why this role now", "Keep it under 2 minutes"],
         "What's something not on your resume?"),
        ("Why do you want to work as a {role} at our company?", "Easy", "Motivation",
         "Checks genuine interest and research.",
         ["Specific reasons about the company", "Link to your goals", "What you bring"],
         "What do you know about our products?"),
        ("Where do you see yourself in five years?", "Easy", "Career goals",
         "Checks ambition and fit with growth path.",
         ["Realistic goals", "Connects to this role", "Shows commitment to learning"],
         "What skills do you need to get there?"),
        ("What are your greatest strengths and weaknesses?", "Medium", "Self-awareness",
         "Evaluates self-awareness and honesty.",
         ["Strength with evidence", "Real weakness (not a disguised strength)", "Steps you're taking to improve"],
         "How would your friends describe you?"),
        ("Why should we hire you over other candidates?", "Medium", "Value proposition",
         "Tests confidence and understanding of the role.",
         ["Match skills to job needs", "Unique differentiator", "Concrete proof"],
         "What would you achieve in your first 90 days?"),
    ],
    "Situational": [
        ("You're a {role} and a deadline is two days away, but you discover a serious bug. What do you do?", "Medium", "Judgement",
         "Assesses priorities and communication under pressure.",
         ["Assess severity and impact", "Inform stakeholders early", "Propose options", "Decide with the team"],
         "What if your manager says ship anyway?"),
        ("A senior colleague insists on an approach you believe is wrong. How do you handle it?", "Medium", "Influence",
         "Checks respectful disagreement.",
         ["Understand their reasoning first", "Bring data/evidence", "Escalate appropriately", "Commit once decided"],
         "Has this ever happened to you?"),
        ("You're given a task with very unclear requirements. What are your first steps?", "Easy", "Ambiguity",
         "Tests how the candidate handles ambiguity.",
         ["Ask clarifying questions", "Write down assumptions", "Build a small prototype for feedback"],
         "Who would you go to for clarification?"),
    ],
    "Coding": [
        ("Write a function to find the first non-repeating character in a string. What is its time complexity?", "Easy", "Strings / hashing",
         "Checks basic coding and complexity analysis.",
         ["Uses a frequency map", "O(n) time", "Handles empty string / no answer"],
         "How would you do it in a single pass over a stream?"),
        ("Given an array of integers and a target, return indices of two numbers that add up to the target.", "Easy", "Arrays / hashing",
         "Classic warm-up testing hash map usage.",
         ["Brute force first, then optimise", "Hash map of value→index", "O(n) time, O(n) space"],
         "What if the array is sorted?"),
        ("Detect whether a linked list has a cycle, and find where the cycle starts.", "Medium", "Linked lists",
         "Tests pointer manipulation and a known algorithm.",
         ["Floyd's slow/fast pointers", "Explain why they meet", "O(1) extra space"],
         "How would you find the length of the cycle?"),
        ("Design an LRU cache with O(1) get and put operations.", "Hard", "Data structure design",
         "Tests combining data structures.",
         ["Hash map + doubly linked list", "Move-to-front on access", "Evict tail when full"],
         "How would you make it thread-safe?"),
    ],
    "System Design": [
        ("Design a URL shortener like bit.ly.", "Medium", "System design",
         "Evaluates high-level architecture skills.",
         ["Requirements and scale estimates", "ID generation strategy", "Database choice", "Caching and redirects"],
         "How would you add analytics on clicks?"),
        ("Design the backend for a college placement portal where companies post jobs and students apply.", "Medium", "System design",
         "Checks data modelling and API design.",
         ["Entities and relationships", "APIs", "Authentication/roles", "Handling deadline-day traffic spikes"],
         "How would you notify students of new jobs?"),
        ("How would you design a real-time chat application?", "Hard", "System design",
         "Assesses knowledge of real-time systems.",
         ["WebSockets vs polling", "Message storage", "Delivery/read receipts", "Scaling connections"],
         "How would you support group chats with 10,000 members?"),
    ],
}

GENERIC_SKILLS = {
    "software": ["data structures", "OOP", "REST APIs", "databases", "Git"],
    "web": ["JavaScript", "React", "HTML/CSS", "REST APIs", "web performance"],
    "data": ["SQL", "Python (pandas)", "statistics", "data visualisation", "A/B testing"],
    "machine learning": ["model evaluation", "feature engineering", "overfitting", "Python", "neural networks"],
    "ml": ["model evaluation", "feature engineering", "overfitting", "Python", "neural networks"],
    "android": ["Kotlin", "Android lifecycle", "Jetpack Compose", "REST APIs"],
    "devops": ["Docker", "CI/CD", "Linux", "cloud infrastructure", "monitoring"],
    "product": ["prioritisation", "user research", "metrics", "roadmapping"],
    "marketing": ["campaign analytics", "SEO", "brand positioning", "content strategy"],
}


def _skills_for(role: str, skills: list) -> list:
    if skills:
        return skills
    role_l = role.lower()
    for key, vals in GENERIC_SKILLS.items():
        if key in role_l:
            return vals
    return ["your core tools", "problem solving", "communication"]


def generate_offline(p: dict, avoid=()) -> dict:
    rng = random.Random()
    seen_before = {" ".join(q.lower().split()) for q in avoid}
    skills = _skills_for(p["role"], p["skills"])
    wanted = [t for t in p["types"] if t in BANK] or ["Technical", "Behavioral", "HR"]

    # Build a shuffled pool per type, filtered by difficulty if not "mixed"
    pools = {}
    for t in wanted:
        items = list(BANK[t])
        if p["difficulty"] != "Mixed":
            filtered = [i for i in items if i[1] == p["difficulty"]]
            items = filtered or items
        rng.shuffle(items)
        # questions the user hasn't seen go last, so pop() picks them first
        items.sort(key=lambda i: " ".join(i[0].lower().split()) not in seen_before)
        pools[t] = items

    questions, seen, i = [], set(), 0
    while len(questions) < p["count"] and any(pools.values()):
        t = wanted[i % len(wanted)]
        i += 1
        if not pools[t]:
            continue
        tmpl, diff, topic, why, points, follow = pools[t].pop()
        skill = rng.choice(skills)
        fill = lambda s: s.format(role=p["role"], skill=skill)
        q = fill(tmpl)
        if q in seen:
            continue
        seen.add(q)
        questions.append({
            "question": q, "type": t, "difficulty": diff, "topic": fill(topic),
            "why_asked": why, "key_points": [fill(x) for x in points], "follow_up": fill(follow),
        })

    tips = [
        f"Prepare 2-3 STAR stories that show your strengths as a {p['role']}.",
        f"Revise fundamentals of {', '.join(skills[:3])}.",
        "Research the company and prepare two thoughtful questions to ask the interviewer.",
    ]
    return {"questions": questions, "tips": tips}


STAR_WORDS = ["situation", "task", "action", "result", "because", "so that", "learned", "achieved", "%", "improved"]


def evaluate_offline(question: str, answer: str) -> dict:
    """Very simple heuristic scoring used only when no AI is available."""
    words = re.findall(r"\w+", answer)
    n = len(words)
    lower = answer.lower()
    score = 2
    strengths, improvements = [], []

    if n >= 40:
        score += 2
        strengths.append("Answer has reasonable depth.")
    else:
        improvements.append("Expand your answer — aim for 60-150 words with a concrete example.")
    if n >= 90:
        score += 1
    if n > 250:
        score -= 1
        improvements.append("Answer is long; tighten it to the most important points.")

    structure_hits = sum(1 for w in STAR_WORDS if w in lower)
    if structure_hits >= 2:
        score += 2
        strengths.append("Uses structured, outcome-focused language.")
    else:
        improvements.append("Use the STAR structure: Situation, Task, Action, Result.")

    if re.search(r"\d", answer):
        score += 1
        strengths.append("Includes specific numbers or details.")
    else:
        improvements.append("Quantify impact where possible (time saved, % improvement, users).")

    q_terms = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", question)}
    overlap = sum(1 for w in q_terms if w in lower)
    if overlap >= 2:
        score += 2
        strengths.append("Stays relevant to the question.")
    else:
        improvements.append("Address the question more directly.")

    score = max(0, min(10, score))
    return {
        "score": score,
        "verdict": "Heuristic feedback (offline mode) — add an API key for detailed AI evaluation.",
        "strengths": strengths or ["You made an attempt — that's the first step!"],
        "improvements": improvements or ["Good structure. Practise delivering it confidently out loud."],
        "model_answer": "Model answers are available when an AI provider is configured.",
    }
