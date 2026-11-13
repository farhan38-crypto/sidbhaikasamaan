"""
problem_sources.py
------------------
Real coding practice problems from public platforms.

Sources
  * Codeforces  - official public API (codeforces.com/apiHelp), no key needed.
  * LeetCode    - the GraphQL endpoint used by leetcode.com itself (unofficial).
                  Falls back to a bundled curated list if it changes or is down.
  * Curated lists in data/ - well-known LeetCode / Codeforces problems, so the
                  feature still works fully offline.
  * GeeksforGeeks & GitHub prep repos - linked as reading resources only
                  (no scraping).

Only metadata is stored (title, difficulty, tags, link) - never the problem
statements, which belong to the platforms. Users open the original page.
Live data is cached on disk for 24 hours so the sites are called at most
once a day.
"""

import json
import os
import random
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests

DATA_DIR = Path(__file__).parent / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_TTL = 24 * 60 * 60  # seconds
HTTP_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (InterviewQuestionGenerator college project)"

# -------------------------------------------------------------------- topics
# Each topic maps to LeetCode tag slugs, Codeforces tags, and the words that
# trigger it when they appear in the role / skills / job description.
TOPICS = {
    "arrays":        {"label": "Arrays & Hashing", "lc": ["array", "hash-table", "prefix-sum"],
                      "cf": ["hashing"], "kw": ["array", "hash", "hashmap", "prefix sum"]},
    "strings":       {"label": "Strings", "lc": ["string"], "cf": ["strings"],
                      "kw": ["string", "text processing", "regex"]},
    "two_pointers":  {"label": "Two Pointers & Sliding Window", "lc": ["two-pointers", "sliding-window"],
                      "cf": ["two pointers"], "kw": ["two pointer", "sliding window"]},
    "binary_search": {"label": "Binary Search", "lc": ["binary-search"], "cf": ["binary search"],
                      "kw": ["binary search", "searching"]},
    "linked_list":   {"label": "Linked Lists", "lc": ["linked-list"], "cf": [],
                      "kw": ["linked list", "linkedlist"]},
    "stack_queue":   {"label": "Stacks & Queues", "lc": ["stack", "queue", "monotonic-stack"],
                      "cf": ["data structures"], "kw": ["stack", "queue"]},
    "trees":         {"label": "Trees & Tries", "lc": ["tree", "binary-tree", "binary-search-tree", "trie"],
                      "cf": ["trees"], "kw": ["tree", "bst", "trie"]},
    "graphs":        {"label": "Graphs", "lc": ["graph", "topological-sort", "shortest-path",
                                               "minimum-spanning-tree"],
                      "cf": ["graphs", "dfs and similar", "shortest paths", "dsu"],
                      "kw": ["graph", "bfs", "dfs", "dijkstra", "shortest path", "network flow"]},
    "dp":            {"label": "Dynamic Programming", "lc": ["dynamic-programming"], "cf": ["dp"],
                      "kw": ["dp", "dynamic programming", "memoization", "memoisation"]},
    "greedy":        {"label": "Greedy & Intervals", "lc": ["greedy", "intervals"], "cf": ["greedy"],
                      "kw": ["greedy", "interval", "scheduling"]},
    "heap":          {"label": "Heaps / Priority Queues", "lc": ["heap-priority-queue"],
                      "cf": ["data structures"], "kw": ["heap", "priority queue"]},
    "backtracking":  {"label": "Recursion & Backtracking", "lc": ["backtracking", "recursion"],
                      "cf": ["brute force"], "kw": ["backtracking", "recursion", "permutation", "combinations"]},
    "math":          {"label": "Math & Bit Manipulation", "lc": ["math", "bit-manipulation", "combinatorics"],
                      "cf": ["math", "number theory", "bitmasks", "combinatorics"],
                      "kw": ["math", "bit manipulation", "number theory", "probability", "combinatorics"]},
    "sorting":       {"label": "Sorting", "lc": ["sorting"], "cf": ["sortings"], "kw": ["sort"]},
    "design":        {"label": "Data Structure Design", "lc": ["design"], "cf": [],
                      "kw": ["oop", "object oriented", "low level design", "lld", "cache design"]},
    "sql":           {"label": "SQL / Databases", "lc": ["database"], "cf": [],
                      "kw": ["sql", "database", "dbms", "mysql", "postgres", "postgresql", "query", "queries"]},
}

TOPIC_HINTS = {
    "arrays": "Think about what a hash map lets you look up in O(1).",
    "strings": "Consider counting characters or comparing with a frequency map.",
    "two_pointers": "Can two indices moving towards (or with) each other avoid a nested loop?",
    "binary_search": "Look for a monotonic condition you can binary search on.",
    "linked_list": "Draw the pointers; slow/fast pointers and a dummy head often help.",
    "stack_queue": "Ask what you need to remember about earlier elements - a stack might hold it.",
    "trees": "Most tree problems are a recursive DFS returning one value per subtree.",
    "graphs": "Model it as nodes and edges first, then decide between BFS, DFS or Dijkstra.",
    "dp": "Define the state, write the recurrence, then decide top-down or bottom-up.",
    "greedy": "Sort first, then check that a local best choice never hurts later.",
    "heap": "Keep only the k items you care about in a heap.",
    "backtracking": "Choose, explore, un-choose - and prune early.",
    "math": "Try small cases by hand to spot the pattern or formula.",
    "sorting": "Would sorting the input make the problem easy?",
    "design": "List the operations and their required complexity before picking data structures.",
    "sql": "Work out the joins and the GROUP BY first; window functions help with ranking.",
}

# Topics used when the user did not name any, based on the role
ROLE_DEFAULTS = [
    (["data analyst", "business analyst", "analyst", "bi developer", "data engineer"], ["sql", "arrays"]),
    (["data scien", "machine learning", "ml ", "ml engineer", "ai engineer", "deep learning"], ["arrays", "math", "dp"]),
    (["frontend", "front-end", "front end", "web developer", "react", "javascript", "ui developer"], ["arrays", "strings", "stack_queue"]),
    (["backend", "back-end", "back end"], ["arrays", "design", "sql", "graphs"]),
    (["competitive", "cp "], ["dp", "greedy", "math", "graphs"]),
    (["database", "dba"], ["sql"]),
    (["software", "sde", "developer", "engineer", "programmer", "full stack", "fullstack", "intern", "coder"],
     ["arrays", "two_pointers", "trees", "graphs", "dp"]),
]

TECH_WORDS = ["software", "developer", "engineer", "sde", "programmer", "data", "ml", "machine learning",
              "backend", "frontend", "full stack", "fullstack", "devops", "android", "ios", "web", "coder",
              "analyst", "scientist", "intern", "tech", "it ", "qa", "test"]

# Reading resources (GitHub repos & sites) — links only
RESOURCES = {
    "general": [
        {"name": "Tech Interview Handbook", "url": "https://github.com/yangshun/tech-interview-handbook",
         "desc": "Free guide covering coding, behavioral and resume prep"},
        {"name": "Coding Interview University", "url": "https://github.com/jwasham/coding-interview-university",
         "desc": "Complete CS study plan for software engineering interviews"},
        {"name": "NeetCode Roadmap", "url": "https://neetcode.io/roadmap",
         "desc": "Structured order to practise the classic LeetCode patterns"},
    ],
    "system_design": [
        {"name": "System Design Primer", "url": "https://github.com/donnemartin/system-design-primer",
         "desc": "How to design large-scale systems, with practice questions"},
    ],
    "frontend": [
        {"name": "JavaScript Interview Questions", "url": "https://github.com/sudheerj/javascript-interview-questions",
         "desc": "Hundreds of JavaScript questions with answers"},
        {"name": "ReactJS Interview Questions", "url": "https://github.com/sudheerj/reactjs-interview-questions",
         "desc": "React questions with answers"},
    ],
    "data": [
        {"name": "Data Science Interviews", "url": "https://github.com/alexeygrigorev/data-science-interviews",
         "desc": "Theory and technical questions for data science roles"},
    ],
    "ml": [
        {"name": "ML Interviews Book", "url": "https://github.com/chiphuyen/ml-interviews-book",
         "desc": "Chip Huyen's book on machine learning interviews"},
    ],
    "cp": [
        {"name": "CP-Algorithms", "url": "https://cp-algorithms.com/",
         "desc": "Explanations of algorithms used in competitive programming"},
    ],
}

# Codeforces rating ranges for each difficulty
CF_RATINGS = {"Easy": (800, 1200), "Medium": (1300, 1700), "Hard": (1800, 2300), "Mixed": (800, 1900)}


# ===================================================================== cache
RETRY_AFTER = 10 * 60  # after a failed fetch, wait this long before trying the site again


def _read_cache(name):
    path = CACHE_DIR / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, time.time() - data.get("fetched_at", 0)
    except (OSError, ValueError):
        return None, None


def _write_cache(name, problems):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_DIR / f"{name}.json.tmp"
        tmp.write_text(json.dumps({"fetched_at": time.time(), "problems": problems}), encoding="utf-8")
        os.replace(tmp, CACHE_DIR / f"{name}.json")
    except OSError:
        pass  # caching is an optimisation only


def _load_bundled(filename):
    try:
        return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))["problems"]
    except (OSError, ValueError, KeyError):
        return []


# ================================================================ Codeforces
class CodeforcesSource:
    API_URL = "https://codeforces.com/api/problemset.problems"
    name = "Codeforces"

    def __init__(self):
        self.status = "not loaded"
        self._lock = threading.Lock()
        self._last_fail = 0.0
        self._fallback = None

    def _fetch(self):
        resp = requests.get(self.API_URL, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK":
            raise ValueError(data.get("comment", "Codeforces API error"))
        solved = {(s["contestId"], s["index"]): s.get("solvedCount", 0)
                  for s in data["result"].get("problemStatistics", [])}
        problems = []
        for p in data["result"]["problems"]:
            if "rating" not in p or "contestId" not in p or "*special" in p.get("tags", []):
                continue
            problems.append({
                "contestId": p["contestId"], "index": p["index"], "name": p["name"],
                "rating": p["rating"], "tags": p.get("tags", []),
                "solvedCount": solved.get((p["contestId"], p["index"]), 0),
            })
        if not problems:
            raise ValueError("Codeforces returned no problems")
        return problems

    def problems(self):
        with self._lock:
            cached, age = _read_cache("codeforces")
            if cached and age < CACHE_TTL:
                self.status = "live (updated today)"
                return cached["problems"]
            if self._fallback is not None and time.time() - self._last_fail < RETRY_AFTER:
                return self._fallback
            try:
                fresh = self._fetch()
                _write_cache("codeforces", fresh)
                self.status = "live"
                return fresh
            except (requests.RequestException, ValueError, KeyError) as exc:
                self._last_fail = time.time()
                if cached:
                    self.status = f"offline - using saved copy from {int(age // 3600)}h ago"
                    self._fallback = cached["problems"]
                else:
                    self.status = "offline - using bundled list"
                    print(f"  [Codeforces] live fetch failed: {exc}")
                    self._fallback = _load_bundled("codeforces_curated.json")
                return self._fallback

    @staticmethod
    def to_card(p):
        return {
            "source": "Codeforces",
            "title": p["name"],
            "url": f"https://codeforces.com/problemset/problem/{p['contestId']}/{p['index']}",
            "code": f"{p['contestId']}{p['index']}",
            "difficulty": f"Rating {p['rating']}",
            "tags": p["tags"][:5],
        }


# ================================================================== LeetCode
class LeetCodeSource:
    GRAPHQL_URL = "https://leetcode.com/graphql"
    name = "LeetCode"
    QUERY = """
    query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
      problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
        total: totalNum
        questions: data {
          acRate
          difficulty
          frontendQuestionId: questionFrontendId
          paidOnly: isPaidOnly
          title
          titleSlug
          topicTags { slug }
        }
      }
    }"""
    PAGE = 1000

    def __init__(self):
        self.status = "not loaded"
        self._lock = threading.Lock()
        self._last_fail = 0.0
        self._fallback = None

    def _fetch(self):
        headers = {"Content-Type": "application/json", "Referer": "https://leetcode.com/problemset/",
                   "User-Agent": USER_AGENT}
        problems, skip, total = [], 0, None
        while total is None or skip < total:
            body = {"query": self.QUERY, "variables": {"categorySlug": "", "limit": self.PAGE,
                                                       "skip": skip, "filters": {}}}
            resp = requests.post(self.GRAPHQL_URL, json=body, headers=headers, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            block = resp.json()["data"]["problemsetQuestionList"]
            total = min(block["total"], 6000)
            batch = block["questions"] or []
            for q in batch:
                if q.get("paidOnly"):
                    continue  # premium problems can't be opened by most students
                problems.append({
                    "id": q.get("frontendQuestionId"), "slug": q["titleSlug"], "title": q["title"],
                    "difficulty": q["difficulty"].capitalize(),
                    "tags": [t["slug"] for t in q.get("topicTags") or []],
                    "acRate": round(float(q.get("acRate") or 0), 1),
                })
            if not batch:
                break
            skip += len(batch)
        if not problems:
            raise ValueError("LeetCode returned no problems")
        return problems

    def problems(self):
        """Returns (live_problems_by_slug or None)."""
        with self._lock:
            cached, age = _read_cache("leetcode")
            if cached and age < CACHE_TTL:
                self.status = "live (updated today)"
                return {p["slug"]: p for p in cached["problems"]}
            if self._last_fail and time.time() - self._last_fail < RETRY_AFTER:
                return self._fallback
            try:
                fresh = self._fetch()
                _write_cache("leetcode", fresh)
                self.status = "live"
                return {p["slug"]: p for p in fresh}
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                self._last_fail = time.time()
                if cached:
                    self.status = f"offline - using saved copy from {int(age // 3600)}h ago"
                    self._fallback = {p["slug"]: p for p in cached["problems"]}
                else:
                    self.status = "offline - using bundled list"
                    print(f"  [LeetCode] live fetch failed: {exc}")
                    self._fallback = None
                return self._fallback

    @staticmethod
    def to_card(p, curated=False):
        card = {
            "source": "LeetCode",
            "title": p["title"],
            "url": f"https://leetcode.com/problems/{p['slug']}/",
            "difficulty": p["difficulty"],
            "tags": [t.replace("-", " ") for t in p["tags"][:5]],
            "classic": curated,
        }
        if p.get("acRate"):
            card["acceptance"] = p["acRate"]
        return card


codeforces = CodeforcesSource()
leetcode = LeetCodeSource()
CURATED_LC = _load_bundled("leetcode_curated.json")


def warm_cache_in_background():
    """Fetch both sources once at startup so the first request is fast."""
    def run():
        codeforces.problems()
        leetcode.problems()
    threading.Thread(target=run, daemon=True).start()


def sources_status():
    return {"codeforces": codeforces.status, "leetcode": leetcode.status}


# ============================================================ topic detection
def detect_topics(params):
    text = " ".join([params["role"], " ".join(params["skills"]), params.get("job_description", "")]).lower()
    # phrases that contain topic words but don't mean the topic
    for phrase in ("full stack", "full-stack", "fullstack", "tech stack", "jquery"):
        text = text.replace(phrase, " ")
    text = f" {text} "
    found = [key for key, t in TOPICS.items()
             if any(re.search(r"\b" + re.escape(k), text) for k in t["kw"])]
    # topics the user named come first, then the usual topics for the role
    role_text = f" {params['role'].lower()} "
    for words, defaults in ROLE_DEFAULTS:
        if any(w in role_text for w in words):
            found += [t for t in defaults if t not in found]
            break
    if not found and "Coding" in params["types"]:
        found = ["arrays", "strings", "two_pointers"]
    return found[:5]


def is_technical(params, topics):
    text = f" {params['role'].lower()} {' '.join(params['skills']).lower()} "
    return bool(topics) and (any(w in text for w in TECH_WORDS) or "Coding" in params["types"]
                             or bool(params["skills"]))


# ================================================================ selection
def _lc_difficulties(difficulty, level):
    if difficulty != "Mixed":
        return {difficulty}
    if level.startswith("Fresher") or level.startswith("Junior"):
        return {"Easy", "Medium"}
    return {"Easy", "Medium", "Hard"}


def _cf_range(difficulty, level):
    lo, hi = CF_RATINGS[difficulty]
    if difficulty == "Mixed" and (level.startswith("Fresher") or level.startswith("Junior")):
        hi = 1500
    if level.startswith("Senior") and difficulty != "Easy":
        lo, hi = lo + 200, hi + 300
    return lo, hi


def _main_topic(tags, topics, kind):
    for key in topics:
        if set(TOPICS[key][kind]) & set(tags):
            return key
    return topics[0] if topics else None


def find_candidates(params, n_wanted, rng=None):
    """Return candidate problems (more than needed, so the AI can choose) plus context."""
    rng = rng or random.Random()
    topics = detect_topics(params)
    if not topics or not is_technical(params, topics):
        return {"candidates": [], "topics": topics}

    lc_tags = {t for k in topics for t in TOPICS[k]["lc"]}
    cf_tags = {t for k in topics for t in TOPICS[k]["cf"]}
    diffs = _lc_difficulties(params["difficulty"], params["level"])

    # ---- LeetCode: curated classics first, enriched / extended with live data
    live = leetcode.problems()
    buckets = {k: [] for k in topics}
    for p in CURATED_LC:
        if p["difficulty"] in diffs and lc_tags & set(p["tags"]):
            info = dict(p)
            if live and p["slug"] in live:
                info["acRate"] = live[p["slug"]]["acRate"]
            elif live is not None and p["slug"] not in live:
                continue  # problem renamed or went premium
            buckets[_main_topic(p["tags"], topics, "lc")].append(("classic", info))
    for b in buckets.values():
        rng.shuffle(b)
    if live:
        curated_slugs = {p["slug"] for p in CURATED_LC}
        extra = [p for p in live.values()
                 if p["slug"] not in curated_slugs and p["difficulty"] in diffs and lc_tags & set(p["tags"])]
        # favour widely-solved problems: sample from the top half by acceptance
        extra.sort(key=lambda p: p["acRate"], reverse=True)
        extra = extra[: max(20, len(extra) // 2)]
        rng.shuffle(extra)
        for p in extra[: n_wanted * 2]:
            buckets[_main_topic(p["tags"], topics, "lc")].append(("live", p))
    # take one problem from each topic in turn (earlier topics first)
    lc_pool = []
    while any(buckets.values()):
        for k in topics:
            if buckets[k]:
                lc_pool.append(buckets[k].pop(0))

    # ---- Codeforces
    cf_pool = []
    analyst_role = any(w in params["role"].lower() for w in ("analyst", "dba", "database"))
    if cf_tags and not analyst_role:  # analyst roles don't need contest problems
        lo, hi = _cf_range(params["difficulty"], params["level"])
        cf_all = [p for p in codeforces.problems() if lo <= p["rating"] <= hi and cf_tags & set(p["tags"])]
        cf_all.sort(key=lambda p: p.get("solvedCount", 0), reverse=True)
        cf_all = cf_all[:150]  # popular ones only
        rng.shuffle(cf_all)
        cf_pool = cf_all

    # ---- interleave: roughly 2 LeetCode : 1 Codeforces
    target = max(n_wanted * 2, n_wanted + 4)
    candidates, li, ci = [], 0, 0
    while len(candidates) < target and (li < len(lc_pool) or ci < len(cf_pool)):
        for _ in range(2):
            if li < len(lc_pool):
                kind, p = lc_pool[li]
                li += 1
                card = LeetCodeSource.to_card(p, curated=(kind == "classic"))
                card["topic"] = _main_topic(p["tags"], topics, "lc")
                candidates.append(card)
        if ci < len(cf_pool):
            p = cf_pool[ci]
            ci += 1
            card = CodeforcesSource.to_card(p)
            card["topic"] = _main_topic(p["tags"], topics, "cf")
            candidates.append(card)

    for i, c in enumerate(candidates, 1):
        c["id"] = f"P{i}"
    return {"candidates": candidates[:target], "topics": topics}


def default_annotations(cards):
    """Used when no AI is available: explain the problem from its tags."""
    for c in cards:
        topic = c.get("topic")
        label = TOPICS[topic]["label"] if topic else "problem solving"
        c.setdefault("why", f"Practises {label.lower()} - a common interview pattern.")
        c.setdefault("hint", TOPIC_HINTS.get(topic, "Start with a brute-force solution, then optimise."))
    return cards


def topic_links(topics):
    """GeeksforGeeks reading links per topic (a search link - no scraping)."""
    return [{"label": TOPICS[t]["label"],
             "gfg_url": "https://www.google.com/search?q=" + quote_plus(f"geeksforgeeks {TOPICS[t]['label']}")}
            for t in topics]


def pick_resources(params, topics):
    text = f" {params['role'].lower()} {' '.join(params['skills']).lower()} "
    out = list(RESOURCES["general"]) if is_technical(params, topics) else []
    if "System Design" in params["types"] or "senior" in params["level"].lower() or "backend" in text:
        out += RESOURCES["system_design"]
    if any(w in text for w in ["frontend", "front-end", "react", "javascript", "web"]):
        out += RESOURCES["frontend"]
    if any(w in text for w in ["data", "analyst", "scien"]):
        out += RESOURCES["data"]
    if any(w in text for w in ["machine learning", " ml", "ai ", "deep learning"]):
        out += RESOURCES["ml"]
    if any(w in text for w in ["competitive", "cp "]) or "graphs" in topics or "dp" in topics:
        out += RESOURCES["cp"]
    return out
