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

VALID_CATEGORIES = ["hostel", "mess", "academic", "infrastructure", "harassment"]
VALID_URGENCIES = ["low", "medium", "high"]

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() in ["true", "1", "yes"]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "8.0"))


class ComplaintClassification(BaseModel):
    category: str
    secondary_category: Optional[str] = None
    urgency: str
    reasoning: str


def _word_match(keywords: list, text: str) -> bool:
    """Check if any keyword matches as a full word boundary or phrase in text."""
    for k in keywords:
        pattern = r'\b' + re.escape(k) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _count_matches(keywords: list, text: str) -> int:
    """Count how many keywords or phrases match in the text."""
    count = 0
    for k in keywords:
        pattern = r'\b' + re.escape(k) + r'\b'
        matches = re.findall(pattern, text, re.IGNORECASE)
        count += len(matches)
    return count


def _heuristic_mock_classify(text: str) -> Dict[str, Any]:
    """
    Deterministic & safety-first triage classifier using weighted keyword density matching.
    Supports multi-category triage (secondary_category set if runner-up score is within 30% of top score).
    Harassment is always the sole/priority category (never paired with a secondary).
    """
    lower_text = text.lower()

    # 1. Immediate Safety / Harassment Check (Highest Priority -> Counseling Cell)
    harassment_kws = [
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
    if _word_match(harassment_kws, lower_text):
        return {
            "category": "harassment",
            "secondary_category": None,
            "urgency": "high",
            "reasoning": "Identified safety/harassment keywords; flagged for immediate Counseling Cell intervention."
        }

    # 2. Domain Categorization Keyword Dictionaries

    # Campus Infrastructure, Furniture, Classrooms, Labs & Works (Handled by Estate Office)
    infra_kws = [
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

    # Explicit Hostel Living & Resident Life (Handled by Warden)
    hostel_kws = [
        # Explicit Hostel Identifiers & Living Blocks
        "hostel", "hostels", "dorm", "dorms", "dormitory", "warden",
        "h-block", "a-block", "b-block", "d-block", "e-block", "f-block", "g-block",
        "h block", "a block", "b block", "d block", "e block", "f block", "g block",
        "hostel block", "boys hostel", "girls hostel", "ladies hostel", "mens hostel",
        "hostel room", "roommate", "roommates", "cot", "cots", "mattress", "cupboard", "almirah",
        "curfew", "in-time", "out-time", "night out", "gate pass", "hostel gate", "warden office",
        # Water Supply & Sanitation in Hostels
        "water supply", "drinking water", "hot water", "cold water", "water shortage",
        "insufficient water", "no water in hostel", "hostel water", "tap", "taps",
        "washroom", "washrooms", "bathroom", "bathrooms", "toilet", "toilets", "flush",
        "drain", "drainage", "shower", "showers", "geyser", "geysers", "sweeper",
        "hostel cleaning", "hostel cleanliness", "housekeeping in hostel"
    ]

    # Mess & Food Dining (Handled by Mess Committee)
    mess_kws = [
        "mess", "food", "meal", "meals", "dinner", "lunch", "breakfast",
        "canteen", "diet", "tiffin", "dining", "catering", "cook", "cooked",
        "uncooked", "rotten", "hygiene in mess", "stale", "taste", "mess food",
        "dining hall", "mess hall", "mess staff", "mess bill", "caterer", "insect in food",
        "curry", "rice", "chapati", "snack", "snacks", "tea", "coffee", "cafeteria"
    ]

    # Academic, Examination & Fee Matters (Handled by Exam Cell Admin)
    academic_kws = [
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

    # Calculate weighted scores
    scores = {
        "infrastructure": _count_matches(infra_kws, lower_text) * 4,
        "hostel": _count_matches(hostel_kws, lower_text) * 4,
        "mess": _count_matches(mess_kws, lower_text) * 4,
        "academic": _count_matches(academic_kws, lower_text) * 4
    }

    # Contextual boosts
    if "bench" in lower_text or "desk" in lower_text or "chair" in lower_text or "projector" in lower_text or "lift" in lower_text:
        scores["infrastructure"] += 6

    if "water" in lower_text and ("hostel" in lower_text or "block" in lower_text or "warden" in lower_text):
        scores["hostel"] += 6

    # Sort categories by score descending
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_cat, top_score = sorted_scores[0]
    runner_up_cat, runner_up_score = sorted_scores[1]

    if top_score > 0:
        category = top_cat
    else:
        # Default fallback: physical repairs/breakages go to infrastructure
        category = "infrastructure" if ("broken" in lower_text or "damaged" in lower_text or "room" in lower_text or "campus" in lower_text) else "hostel"

    # Multi-category heuristic: runner-up within 30% of top score
    secondary_category = None
    if top_score > 0 and runner_up_score > 0 and runner_up_cat != category:
        if runner_up_score >= (0.70 * top_score):
            secondary_category = runner_up_cat

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
        "Multi-Category Rules:\n"
        "- 'harassment' must ALWAYS be the sole primary category when detected. Never pair harassment with a secondary category or demote it.\n"
        "- For non-harassment grievances, set 'secondary_category' ONLY if the complaint clearly spans two distinct domains (e.g., hostel room + broken electrical infrastructure, or mess food + hostel dining hall). Otherwise set secondary_category to null.\n"
        "Allowed categories: 'infrastructure', 'hostel', 'mess', 'academic', 'harassment'.\n"
        "Allowed urgencies: 'low', 'medium', 'high'."
    )

    # 1. Primary Path: Google Gemini 3.8 Flash with Structured Output
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=GEMINI_API_KEY)

            def _call_gemini():
                return client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=f"Student Complaint: {text}",
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=ComplaintClassification,
                        temperature=0.1
                    )
                )

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
    "loser", "losers", "dick", "dicks", "crap", "damn"
]


def moderate_content(text: str) -> Tuple[bool, str]:
    """
    Flags abusive, profane, or inappropriate language used BY the student in their complaint text.
    Distinct from the student reporting harassment/abuse against themselves.
    Uses fast keyword matching first, with an optional Gemini check for ambiguous aggressive context.
    Returns: (is_flagged: bool, reason: str)
    """
    lower_text = text.lower()

    # 1. Primary Method: Fast keyword-based check
    for kw in PROFANITY_KEYWORDS:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, lower_text):
            return True, f"Inappropriate language detected: '{kw}'"

    # 2. Optional Gemini-based check for ambiguous abusive cases
    if not MOCK_MODE and GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=GEMINI_API_KEY)

            prompt = (
                "You are an automated university content moderator. Analyze if the student author of the following "
                "complaint text is using abusive, profane, vulgar, or threatening language in their submission. "
                "IMPORTANT: Do NOT flag if they are simply reporting that someone else harassed or mistreated them. "
                "Only flag if the student's OWN language contains aggressive obscenities, slurs, or vulgar abuse.\n\n"
                f"Text: \"{text}\"\n\n"
                "Respond in JSON format with keys: {\"is_inappropriate\": bool, \"reason\": \"short reason or empty string\"}"
            )

            def _call_mod():
                return client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0
                    )
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_mod)
                resp = future.result(timeout=API_TIMEOUT_SECONDS)

            if resp.text:
                data = json.loads(resp.text)
                if data.get("is_inappropriate") is True:
                    return True, data.get("reason", "Inappropriate or abusive language detected.")
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
            return client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1)
            )

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
