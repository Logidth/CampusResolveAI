"""
CampusResolve AI Agent Engine
Autonomous complaint classification powered by Google Gemini (gemini-3.8-flash) with structured output,
Groq secondary fallback, high-precision domain heuristics, multi-category triage,
content moderation guardrails, and auto-summarization.
"""

import os
import json
import re
import random
import logging
import concurrent.futures
from typing import Dict, Any, Optional, Tuple
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("CampusResolveAgent")

VALID_CATEGORIES = ["hostel", "mess", "academic", "infrastructure", "harassment", "irrelevant"]
VALID_URGENCIES = ["low", "medium", "high"]

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() in ["true", "1", "yes"]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "12.0"))


class ComplaintClassification(BaseModel):
    category: str
    secondary_category: Optional[str] = None
    urgency: str
    reasoning: str


# =====================================================================
# Domain Categorization Keyword Dictionaries
# =====================================================================

HARASSMENT_KWS = [
    "harass", "harassed", "harassing", "harassment",
    "ragging", "ragged", "rag",
    "bully", "bullied", "bullying", "bullies",
    "threat", "threats", "threatened", "threatening",
    "abuse", "abused", "abusing", "abusive",
    "safety", "stalk", "stalked", "stalking", "stalker",
    "inappropriate", "violence", "violent", "assault",
    "eve-teasing", "mental health", "depression", "anxiety",
    "counselor", "counseling", "suicide", "crying"
]

INFRA_KWS = [
    # Furniture & Carpentry
    "bench", "benches", "desk", "desks", "table", "tables", "chair", "chairs",
    "podium", "board", "blackboard", "whiteboard", "greenboard", "stage",
    "furniture", "broken bench", "broken chair", "broken desk", "broken table",
    # Campus Physical Spaces, Classrooms, Labs & Buildings
    "campus", "college", "classroom", "classrooms", "seminar hall",
    "auditorium", "library", "lab", "labs", "laboratory", "mech lab", "civil lab",
    "ece lab", "cse lab", "corridor", "pathway", "road", "parking", "ground",
    "campus gate", "security gate", "main building", "admin building", "admin block",
    "building", "c101", "c102", "c201", "c301", "c405", "a101", "a102", "b101",
    "b201", "b301", "lh1", "lh2", "lh3",
    # Maintenance, Repairs & Closures (Estate Works)
    "broken", "damaged", "repair", "repairs", "not working", "not closed", "is not closed",
    "open", "door open", "door not closed", "door", "doors", "window", "windows",
    "lock", "locks", "unlocked", "broken lock", "handle", "hinge", "glass",
    "ceiling", "roof", "floor", "tiles", "wall", "plumbing", "paint", "painting", "civil works",
    # Electrical & Fixtures
    "lift", "lifts", "elevator", "elevators", "electricity", "power cut",
    "power failure", "voltage", "generator", "sparking", "switch", "switches",
    "switchboard", "socket", "wire", "wires", "wiring", "light", "lights", "tube light",
    "fan", "fans", "ac", "air conditioner", "air conditioning", "projector",
    "projectors", "audio", "mic", "speaker", "wifi", "lan", "network", "estate office", "estate"
]

HOSTEL_KWS = [
    # Explicit Hostel Identifiers & Living Blocks
    "hostel", "hostels", "dorm", "dorms", "dormitory", "warden",
    "h-block", "a-block", "b-block", "d-block", "e-block", "f-block", "g-block",
    "h block", "a block", "b block", "d block", "e block", "f block", "g block",
    "hostel block", "boys hostel", "girls hostel", "ladies hostel", "mens hostel",
    "hostel room", "roommate", "roommates", "cot", "cots", "mattress", "cupboard", "almirah",
    "curfew", "in-time", "out-time", "night out", "gate pass", "hostel gate", "warden office",
    # Water Supply & Sanitation in Hostels
    "water", "water issue", "water problem", "water supply", "drinking water", "hot water", "cold water", "water shortage",
    "insufficient water", "no water in hostel", "hostel water", "tap", "taps",
    "washroom", "washrooms", "bathroom", "bathrooms", "toilet", "toilets", "flush",
    "drain", "drainage", "shower", "showers", "geyser", "geysers", "sweeper",
    "hostel cleaning", "hostel cleanliness", "housekeeping in hostel"
]

MESS_KWS = [
    "mess", "food", "meal", "meals", "dinner", "lunch", "breakfast",
    "canteen", "diet", "tiffin", "dining", "catering", "cook", "cooked",
    "uncooked", "rotten", "hygiene in mess", "stale", "taste", "mess food",
    "dining hall", "mess hall", "mess staff", "mess bill", "caterer", "insect in food",
    "curry", "rice", "chapati", "snack", "snacks", "tea", "coffee", "cafeteria"
]

ACADEMIC_KWS = [
    "academic", "academics", "exam", "exams", "examination", "examinations",
    "grade", "grades", "grading", "mark", "marks", "result", "results",
    "attendance", "internal", "internals", "gpa", "cgpa", "re-evaluation",
    "revaluation", "professor", "professors", "faculty", "teacher", "teachers",
    "lecture", "lectures", "course", "courses", "curriculum", "syllabus",
    "assignment", "assignments", "semester", "timetable", "subject", "credits", "exam cell",
    "fee", "fees", "exam fee", "semester fee", "tuition fee", "hall ticket", "hallticket",
    "fine", "fines", "arrear", "arrears", "supplementary", "marksheet", "transcript",
    "schedule", "scheduled", "cia", "cia-i", "cia-ii", "cia-1", "cia-2"
]

GENERIC_GRIEVANCE_INDICATORS = [
    "issue", "issues", "problem", "problems", "complaint", "complaints", "grievance", "grievances",
    "broken", "damage", "damaged", "repair", "repairs", "not working", "faulty", "failed", "failure",
    "leak", "leaking", "leakage", "dirty", "unclean", "stink", "smell", "rotten",
    "shortage", "insufficient", "hazard", "danger", "urgent", "emergency", "noise", "clean"
]


def _word_match(keywords: list, text: str) -> bool:
    """Check if any keyword matches as a full word boundary or phrase in text."""
    for k in keywords:
        pattern = r'\b' + re.escape(k) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _count_matches(keywords: list, text: str) -> int:
    """Count how many non-overlapping keywords or phrases match in the text."""
    sorted_kws = sorted(set(keywords), key=lambda x: len(x), reverse=True)
    matched_spans = []
    count = 0
    for k in sorted_kws:
        pattern = r'\b' + re.escape(k) + r'\b'
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start, end = match.span()
            if not any(max(start, m_start) < min(end, m_end) for m_start, m_end in matched_spans):
                matched_spans.append((start, end))
                count += 1
    return count


def _heuristic_mock_classify(text: str) -> Dict[str, Any]:
    """
    Deterministic & safety-first triage classifier using weighted keyword density matching.
    Supports multi-category triage (secondary_category set if runner-up score is within 30% of top score).
    Harassment is always the sole/priority category (never paired with a secondary).
    If no campus grievance keywords are present, classifies as 'irrelevant'.
    """
    lower_text = text.lower()

    # 1. Immediate Safety / Harassment Check (Highest Priority -> Counseling Cell)
    if _word_match(HARASSMENT_KWS, lower_text):
        return {
            "category": "harassment",
            "secondary_category": None,
            "urgency": "high",
            "reasoning": "Identified safety/harassment keywords; flagged for immediate Counseling Cell intervention."
        }

    # 2. Calculate weighted scores
    scores = {
        "infrastructure": _count_matches(INFRA_KWS, lower_text) * 4,
        "hostel": _count_matches(HOSTEL_KWS, lower_text) * 4,
        "mess": _count_matches(MESS_KWS, lower_text) * 4,
        "academic": _count_matches(ACADEMIC_KWS, lower_text) * 4
    }

    # Store base keyword scores for multi-category runner-up evaluation
    base_scores = dict(scores)

    # Contextual boosts for primary category tie-breaking
    if "bench" in lower_text or "desk" in lower_text or "chair" in lower_text or "projector" in lower_text or "lift" in lower_text:
        scores["infrastructure"] += 6

    if "water" in lower_text and ("hostel" in lower_text or "block" in lower_text or "warden" in lower_text):
        scores["hostel"] += 6

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_cat, top_score = sorted_scores[0]

    if top_score > 0:
        category = top_cat
    else:
        # Check if generic repair words are present with physical campus spaces
        if any(w in lower_text for w in ["broken", "damaged", "repair", "not working", "leakage", "leak"]):
            category = "infrastructure"
        else:
            # Completely unrelated to campus grievance categories
            category = "irrelevant"

    if category == "irrelevant":
        return {
            "category": "irrelevant",
            "secondary_category": None,
            "urgency": "low",
            "reasoning": "No actionable campus grievance keywords found in submission."
        }

    # Multi-category heuristic: runner-up within 30% of top score based on keyword match density
    sorted_base = sorted(base_scores.items(), key=lambda x: x[1], reverse=True)
    secondary_category = None
    if len(sorted_base) > 1 and sorted_base[0][1] > 0:
        candidate_item = next(((cat, sc) for cat, sc in sorted_base if cat != category and sc > 0), None)
        if candidate_item:
            cand_name, cand_score = candidate_item
            top_ref = base_scores.get(category, 0)
            ref_score = max(top_ref, sorted_base[0][1])
            if ref_score > 0 and cand_score >= (0.65 * ref_score):
                secondary_category = cand_name

    # 3. Urgency Evaluation
    high_urgency_kws = ["emergency", "urgent", "danger", "hazard", "threat", "immediate", "severe", "sparking", "fire", "smoke", "contamination", "no water"]
    med_urgency_kws = ["broken", "stopped", "failed", "leakage", "leaking", "flickering", "spoiled", "cold", "error", "insufficient", "shortage", "dirty", "unhygienic", "damaged"]
    low_urgency_kws = ["minor", "query", "suggestion", "feedback", "slow", "delay"]

    if _word_match(high_urgency_kws, lower_text):
        urgency = "high"
    elif _word_match(med_urgency_kws, lower_text):
        urgency = "medium"
    elif _word_match(low_urgency_kws, lower_text):
        urgency = "low"
    else:
        urgency = "medium"

    reasoning = f"Categorized as {category} with {urgency} priority based on issue description."
    if secondary_category:
        reasoning += f" Secondary domain identified: {secondary_category}."

    return {
        "category": category,
        "secondary_category": secondary_category,
        "urgency": urgency,
        "reasoning": reasoning
    }


def classify_complaint(text: str) -> Dict[str, Any]:
    """
    Classify a student complaint using LLM.
    Priority 1: Google Gemini 3.8 Flash (structured output with response_schema)
    Priority 2: Groq LLM fallback
    Priority 3 / Offline: Deterministic keyword heuristics (_heuristic_mock_classify)
    Enforces strict API timeout to guarantee safe fallback without failing requests.
    """
    if MOCK_MODE:
        logger.info("Executing complaint classification in MOCK_MODE")
        return _heuristic_mock_classify(text)

    system_instruction = (
        "You are an AI grievance triage officer for a university campus. "
        "Analyze the user's grievance and categorize it into primary category, optional secondary category, urgency level, and reasoning.\n"
        "Category Rules:\n"
        "- 'infrastructure': Classrooms (e.g. C101, C405), benches, desks, chairs, tables, doors, windows, campus lifts, building power, lab equipment, electrical fixtures (assigned to Estate Office).\n"
        "- 'hostel': Hostel residential blocks (e.g. H-block, hostel room), hostel water supply, warden matters, roommates (assigned to Warden).\n"
        "- 'mess': Food quality, mess dining, unhygienic meals, catering, canteen (assigned to Mess Committee).\n"
        "- 'academic': Marks, semester exams, grading errors, exam fees, tuition fees, semester registration, hall tickets, revaluation, syllabus, attendance (assigned to Exam Cell Admin).\n"
        "- 'harassment': Bullying, ragging, stalking, abuse, safety disclosures (assigned to Counseling Cell, urgency always high).\n"
        "- 'irrelevant': Casual chatter (e.g. 'aswath is my friend'), social greetings (e.g. 'happy birthday'), jokes, sports, or random text that does NOT describe an actionable campus grievance.\n"
        "Multi-Category Rules:\n"
        "- 'harassment' must ALWAYS be the sole primary category when detected. Never pair harassment with a secondary category or demote it.\n"
        "- 'irrelevant' must ALWAYS be the sole primary category if the text does not contain a legitimate campus grievance. Never pair irrelevant with a secondary category.\n"
        "- For non-harassment grievances, set 'secondary_category' ONLY if the complaint clearly spans two distinct domains (e.g., hostel room + broken electrical infrastructure, or mess food + hostel dining hall). Otherwise set secondary_category to null.\n"
        "Allowed categories: 'infrastructure', 'hostel', 'mess', 'academic', 'harassment', 'irrelevant'.\n"
        "Allowed urgencies: 'low', 'medium', 'high'."
    )

    # 1. Primary Path: Google Gemini 3.8 Flash with Structured Output
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=GEMINI_API_KEY)

            def _call_gemini():
                models_to_try = [GEMINI_MODEL]
                for alt in ["gemini-3.6-flash", "gemini-3-flash-preview", "gemini-flash-latest"]:
                    if alt not in models_to_try:
                        models_to_try.append(alt)
                
                last_exc = None
                for m in models_to_try:
                    try:
                        return client.models.generate_content(
                            model=m,
                            contents=f"Student Complaint: {text}",
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                response_mime_type="application/json",
                                response_schema=ComplaintClassification,
                                temperature=0.1
                            )
                        )
                    except Exception as err:
                        last_exc = err
                        logger.info(f"Gemini model '{m}' failed ({err}), attempting fallback...")
                raise last_exc

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_gemini)
                gemini_resp = future.result(timeout=API_TIMEOUT_SECONDS)

            if gemini_resp.text:
                parsed = json.loads(gemini_resp.text)
                cat = str(parsed.get("category", "")).strip().lower()
                sec_cat = parsed.get("secondary_category")
                if sec_cat:
                    sec_cat = str(sec_cat).strip().lower()
                urg = str(parsed.get("urgency", "")).strip().lower()
                res = parsed.get("reasoning", "")

                # Harassment Safety Enforcements
                if cat == "harassment" or sec_cat == "harassment":
                    cat = "harassment"
                    sec_cat = None
                    urg = "high"
                else:
                    if cat not in VALID_CATEGORIES:
                        cat = "infrastructure"
                    if sec_cat not in VALID_CATEGORIES or sec_cat == cat:
                        sec_cat = None
                    if urg not in VALID_URGENCIES:
                        urg = "medium"

                return {
                    "category": cat,
                    "secondary_category": sec_cat,
                    "urgency": urg,
                    "reasoning": res or f"Classified under {cat} with {urg} urgency."
                }

        except Exception as e:
            logger.warning(
                f"Primary Gemini API call failed or timed out ({type(e).__name__}: {e}); "
                "attempting secondary Groq fallback if configured..."
            )

    # 2. Secondary Path: Groq LLM Fallback
    if GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here":
        try:
            from groq import Groq
            groq_client = Groq(api_key=GROQ_API_KEY, timeout=API_TIMEOUT_SECONDS)

            json_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an AI grievance triage officer for a university campus. "
                        "Classify the student grievance into JSON format:\n"
                        "{\"category\": \"infrastructure\"|\"hostel\"|\"mess\"|\"academic\"|\"harassment\", "
                        "\"secondary_category\": null|\"infrastructure\"|\"hostel\"|\"mess\"|\"academic\", "
                        "\"urgency\": \"low\"|\"medium\"|\"high\", \"reasoning\": \"one sentence justification\"}\n\n"
                        "Rule: harassment is always sole category, secondary_category must be null."
                    )
                },
                {
                    "role": "user",
                    "content": f"Student Complaint: {text}"
                }
            ]
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=json_messages,
                temperature=0.1
            )
            raw_content = response.choices[0].message.content or ""
            json_match = re.search(r'\{[^{}]*\}', raw_content)
            if json_match:
                parsed = json.loads(json_match.group(0))
                cat = str(parsed.get("category", "")).strip().lower()
                sec_cat = parsed.get("secondary_category")
                if sec_cat:
                    sec_cat = str(sec_cat).strip().lower()
                urg = str(parsed.get("urgency", "")).strip().lower()
                res = parsed.get("reasoning", "")

                if cat == "harassment" or sec_cat == "harassment":
                    cat = "harassment"
                    sec_cat = None
                    urg = "high"
                else:
                    if cat not in VALID_CATEGORIES:
                        cat = "infrastructure"
                    if sec_cat not in VALID_CATEGORIES or sec_cat == cat:
                        sec_cat = None
                    if urg not in VALID_URGENCIES:
                        urg = "medium"

                return {
                    "category": cat,
                    "secondary_category": sec_cat,
                    "urgency": urg,
                    "reasoning": res or f"Classified under {cat} with {urg} urgency."
                }
        except Exception as e:
            logger.warning(
                f"Secondary Groq API call failed or timed out ({type(e).__name__}: {e}); "
                "falling back to heuristic classification."
            )

    # 3. Tertiary Path: Deterministic Heuristic Classification
    logger.info("Executing deterministic heuristic classification.")
    return _heuristic_mock_classify(text)


PROFANITY_KEYWORDS = [
    "fuck", "fucking", "fucked", "fucker", "fuckers",
    "shit", "shitty", "bullshit", "horseshit",
    "bitch", "bitches", "asshole", "assholes",
    "bastard", "bastards", "moron", "morons",
    "idiot", "idiots", "scumbag", "scumbags",
    "loser", "losers", "dick", "dicks", "crap", "damn",
    "stupid", "dumb", "shut up", "wtf", "stfu", "hate you",
    "suck", "sucks", "nude", "porn", "sex", "piss off"
]

IRRELEVANT_PATTERNS = [
    # Birthday & greetings
    r"\bhappy\s+birthday\b", r"\bhbd\b", r"\bhappy\s+bday\b",
    r"\bhappy\s+new\s+year\b", r"\bhappy\s+anniversary\b",
    r"\bcongratulations\b", r"\bcongrats\b",
    r"\bhappy\s+diwali\b", r"\bhappy\s+pongal\b", r"\bmerry\s+christmas\b", r"\bhappy\s+holi\b",
    r"\bgood\s+morning\b", r"\bgood\s+afternoon\b", r"\bgood\s+evening\b", r"\bgood\s+night\b",
    r"\bhave\s+a\s+(?:great|nice|good)\s+day\b",
    # Casual conversation, social statements, friendships & relationships
    r"\bhow\s+are\s+you\b", r"\bwhat(?:'s|\s+is)\s+up\b", r"\bwassup\b", r"\bsup\s+bro\b",
    r"\btell\s+me\s+a\s+joke\b", r"\bsing\s+a\s+song\b", r"\bwho\s+are\s+you\b",
    r"\bi\s+love\s+you\b", r"\bmarry\s+me\b",
    r"\b(?:[a-zA-Z]+\s+)?(?:is|was|are|were)\s+(?:my|our)\s+(?:best\s+)?(?:friend|buddy|pal|enemy|homie|roomie|classmate|bro|sister|brother|gf|bf|girlfriend|boyfriend)\b",
    r"\bmy\s+(?:friend|best\s+friend|buddy|pal|name)\s+(?:is|are)\b",
    r"\bwe\s+are\s+(?:friends|best\s+friends|buddies)\b",
    r"\b(?:he|she|they)\s+is\s+(?:good|bad|nice|awesome|great|cute|smart|kind|cool)\b",
    r"\b(?:i|we)\s+(?:love|like|hate|miss)\s+(?:you|him|her|them|[a-zA-Z]+)\b",
    # Test & dummy spam
    r"\btest(?:ing)?\s+(?:123|test|check)\b", r"\bhello\s+world\b",
    r"\blorem\s+ipsum\b", r"\bbla\s+bla\b", r"\bblah\s+blah\b"
]


def moderate_content(text: str) -> Tuple[bool, str]:
    """
    Flags abusive, profane, or irrelevant/inappropriate text submitted by the student.
    Covers:
    - Profanity, slurs, or vulgar abuse
    - Irrelevant text like 'happy birthday', social greetings, jokes, pranks, test spam
    - Casual statements ('aswath is my friend', 'i like pizza') with zero connection to campus domains
    - Irrelevant paragraphs wholly unrelated to university complaints
    Returns: (is_flagged: bool, reason: str)
    """
    lower_text = text.lower().strip()

    # 1. Fast Profanity Check
    for kw in PROFANITY_KEYWORDS:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, lower_text):
            return True, f"Inappropriate language detected: '{kw}'"

    # 2. Fast Irrelevant Greetings / Spam Patterns
    for pat in IRRELEVANT_PATTERNS:
        match = re.search(pat, lower_text)
        if match:
            return True, f"Irrelevant content: '{match.group(0)}' is not a campus grievance"

    # 3. Very Short Non-Grievance Filler / Greetings
    words = lower_text.split()
    if len(words) <= 2 and all(w in ["hi", "hello", "hey", "test", "testing", "ok", "okay", "bye", "cool", "yo", "sup", "thanks"] for w in words):
        return True, "Irrelevant content: Casual greeting or test text does not state a campus grievance"

    # 4. Universal Domain Relevance & Absence Check
    # A genuine college grievance MUST have at least one keyword matching campus domains
    # (infrastructure, hostel, mess, academic, safety/harassment).
    has_category_kw = (
        _count_matches(INFRA_KWS, lower_text) > 0 or
        _count_matches(HOSTEL_KWS, lower_text) > 0 or
        _count_matches(MESS_KWS, lower_text) > 0 or
        _count_matches(ACADEMIC_KWS, lower_text) > 0 or
        _word_match(HARASSMENT_KWS, lower_text)
    )

    if not has_category_kw:
        return True, "Irrelevant content: Submission has no connection to campus infrastructure, hostel, mess, academic affairs, or student safety."

    # 4. Gemini AI Compliance & Irrelevant Paragraph Evaluation
    if not MOCK_MODE and GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=GEMINI_API_KEY)

            prompt = (
                "You are an automated university institutional compliance officer for CampusResolve, an official college grievance portal. "
                "Students should ONLY submit legitimate campus grievances regarding: "
                "campus infrastructure (classrooms, furniture, electrical, labs), hostel facilities (rooms, water, curfew), "
                "mess dining food quality, academic/examination affairs, or student safety/harassment/ragging.\n\n"
                "Analyze if the student submission is INAPPROPRIATE or IRRELEVANT:\n"
                "1. IRRELEVANT: Social greetings (e.g. 'happy birthday', 'good morning'), casual conversation, jokes, pranks, "
                "gibberish, test text, song lyrics, creative writing, sports commentary, movie discussions, promotional spam, "
                "or ANY paragraph that is not a genuine grievance related to college operations.\n"
                "2. INAPPROPRIATE: Abusive, profane, vulgar, derogatory, or threatening language directed by the author.\n\n"
                "CRITICAL SAFETY NOTE: Do NOT flag legitimate complaints, even if critical of staff or facilities, or reports of harassment/ragging.\n\n"
                f"Submission: \"{text}\"\n\n"
                "Respond strictly in JSON format with keys:\n"
                "{\"is_inappropriate\": bool, \"reason\": \"concise reason explaining why it is inappropriate or irrelevant\"}"
            )

            def _call_mod():
                models_to_try = [GEMINI_MODEL]
                for alt in ["gemini-3.6-flash", "gemini-3-flash-preview", "gemini-flash-latest"]:
                    if alt not in models_to_try:
                        models_to_try.append(alt)

                last_exc = None
                for m in models_to_try:
                    try:
                        return client.models.generate_content(
                            model=m,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.0
                            )
                        )
                    except Exception as err:
                        last_exc = err
                        logger.info(f"Gemini moderation model '{m}' failed ({err}), attempting fallback...")
                raise last_exc

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_mod)
                resp = future.result(timeout=API_TIMEOUT_SECONDS)

            if resp.text:
                data = json.loads(resp.text)
                if data.get("is_inappropriate") is True:
                    return True, data.get("reason", "Inappropriate or irrelevant text detected.")
        except Exception as e:
            logger.debug(f"Gemini moderation check skipped or timed out: {e}")

    return False, ""


def summarize_complaint(text: str) -> Optional[str]:
    """
    Summarize student complaints that exceed 50 words into 1-2 concise sentences.
    If len(text.split()) <= 50, returns None.
    If Gemini call fails, times out, or MOCK_MODE is on, falls back to first 50 words + '…'.
    The full original text is always preserved in the database.
    """
    words = text.split()
    if len(words) <= 50:
        return None

    heuristic_summary = " ".join(words[:50]) + "…"

    if MOCK_MODE or not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return heuristic_summary

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = (
            "Summarize the following campus grievance in 1 to 2 clear, factual sentences "
            "highlighting the core problem, location, and urgency:\n\n"
            f"{text}"
        )

        def _call_sum():
            models_to_try = [GEMINI_MODEL]
            for alt in ["gemini-3.6-flash", "gemini-3-flash-preview", "gemini-flash-latest"]:
                if alt not in models_to_try:
                    models_to_try.append(alt)
            
            last_exc = None
            for m in models_to_try:
                try:
                    return client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=0.1)
                    )
                except Exception as err:
                    last_exc = err
            raise last_exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call_sum)
            resp = future.result(timeout=API_TIMEOUT_SECONDS)

        if resp.text and resp.text.strip():
            return resp.text.strip()
        return heuristic_summary

    except Exception as e:
        logger.warning(
            f"Gemini summarization failed or timed out ({type(e).__name__}: {e}); "
            "falling back to heuristic summary."
        )
        return heuristic_summary
