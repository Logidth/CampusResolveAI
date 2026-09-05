"""
CampusResolve AI Agent Engine
Autonomous complaint classification with robust error handling, timeout guardrails,
high-precision domain heuristics, and automated fallback to MOCK_MODE on API failure or rate limit.
"""

import os
import json
import re
import random
import logging
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("CampusResolveAgent")

VALID_CATEGORIES = ["hostel", "mess", "academic", "infrastructure", "harassment"]
VALID_URGENCIES = ["low", "medium", "high"]

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() in ["true", "1", "yes"]
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "8.0"))


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

    # Academic & Faculty (Handled by HOD)
    academic_kws = [
        "academic", "academics", "exam", "exams", "examination", "examinations",
        "grade", "grades", "grading", "mark", "marks", "result", "results",
        "attendance", "internal", "internals", "gpa", "cgpa", "re-evaluation",
        "revaluation", "professor", "professors", "faculty", "teacher", "teachers",
        "lecture", "lectures", "course", "courses", "curriculum", "syllabus",
        "assignment", "assignments", "semester", "timetable", "subject", "credits", "hod",
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

    # Select category with highest score
    best_category = max(scores, key=scores.get)
    if scores[best_category] > 0:
        category = best_category
    else:
        # Default fallback: physical repairs/breakages go to infrastructure
        category = "infrastructure" if ("broken" in lower_text or "damaged" in lower_text or "room" in lower_text or "campus" in lower_text) else "hostel"

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
    return {
        "category": category,
        "urgency": urgency,
        "reasoning": reasoning
    }


def classify_complaint(text: str) -> Dict[str, Any]:
    """
    Classify a student complaint using LLM function calling / tool use.
    Wraps API calls in strict timeout and exception handlers to automatically
    fallback to MOCK_MODE classification without crashing requests.
    """
    if MOCK_MODE or not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        logger.info("Executing complaint classification in MOCK_MODE")
        return _heuristic_mock_classify(text)

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY, timeout=API_TIMEOUT_SECONDS)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "classify_campus_complaint",
                    "description": "Classifies a student complaint into a domain category, urgency level, and one sentence rationale.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": VALID_CATEGORIES,
                                "description": "The domain of the complaint: 'infrastructure' (classroom benches, desks, doors, campus lifts, electricity, lab fixtures -> Estate Office), 'hostel' (hostel blocks, dorm rooms, hostel water supply -> Warden), 'mess' (food, dining, canteen -> Mess Committee), 'academic' (exams, grades, faculty, courses -> HOD), 'harassment' (safety, ragging, counseling -> Counseling Cell)."
                            },
                            "urgency": {
                                "type": "string",
                                "enum": VALID_URGENCIES,
                                "description": "Urgency rating (high, medium, low) according to safety, academic impact, or operational disruption."
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "A concise single-sentence explanation for the classification."
                            }
                        },
                        "required": ["category", "urgency", "reasoning"]
                    }
                }
            }
        ]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an AI grievance triage officer for a university campus. "
                    "Analyze the user's grievance and call the tool `classify_campus_complaint`. "
                    "Category Rules:\n"
                    "- 'infrastructure': Classrooms (e.g. C101, C405), benches, desks, chairs, tables, doors, windows, campus lifts, building power, lab equipment, electrical fixtures (assigned to Estate Office).\n"
                    "- 'hostel': Hostel residential blocks (e.g. H-block, hostel room), hostel water supply, warden matters, roommates (assigned to Warden).\n"
                    "- 'mess': Food quality, mess dining, unhygienic meals, catering, canteen (assigned to Mess Committee).\n"
                    "- 'academic': Exams, grades, grading errors, faculty, classes, syllabus, attendance, schedule, timetable, CIA (assigned to HOD).\n"
                    "- 'harassment': Bullying, ragging, stalking, abuse, safety disclosures (assigned to Counseling Cell, urgency always high).\n"
                    "Allowed urgencies: 'low', 'medium', 'high'."
                )
            },
            {
                "role": "user",
                "content": f"Student Complaint: {text}"
            }
        ]

        # First attempt: Tool calling
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "classify_campus_complaint"}},
                temperature=0.1
            )
            tool_calls = response.choices[0].message.tool_calls
            if tool_calls:
                arguments = json.loads(tool_calls[0].function.arguments)
                cat = arguments.get("category", "").lower()
                urg = arguments.get("urgency", "").lower()
                res = arguments.get("reasoning", "")

                if cat not in VALID_CATEGORIES:
                    cat = "infrastructure"
                if urg not in VALID_URGENCIES:
                    urg = "medium"

                return {
                    "category": cat,
                    "urgency": urg,
                    "reasoning": res or f"Classified under {cat} with {urg} urgency."
                }
        except Exception as tool_err:
            logger.info(f"Tool calling not supported for model {GROQ_MODEL} ({tool_err}), trying JSON format prompt...")
            # Second attempt: Direct JSON prompt
            json_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an AI grievance triage officer for a university campus. "
                        "Classify the student grievance. Respond ONLY with a valid JSON object in this exact format:\n"
                        "{\"category\": \"infrastructure\"|\"hostel\"|\"mess\"|\"academic\"|\"harassment\", \"urgency\": \"low\"|\"medium\"|\"high\", \"reasoning\": \"one sentence justification\"}\n\n"
                        "Rules:\n"
                        "- 'infrastructure': classrooms, benches, desks, chairs, doors, campus lifts, electricity (Estate Office)\n"
                        "- 'hostel': residential blocks, hostel water, cleanliness, rooms (Warden)\n"
                        "- 'mess': food, meals, dining, catering (Mess Committee)\n"
                        "- 'academic': exams, schedule, CIA, marks, faculty (HOD)\n"
                        "- 'harassment': bullying, ragging, abuse, safety (Counseling Cell, urgency high)"
                    )
                },
                {
                    "role": "user",
                    "content": f"Student Complaint: {text}"
                }
            ]
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=json_messages,
                temperature=0.1
            )
            raw_content = response.choices[0].message.content or ""
            # Extract JSON block
            json_match = re.search(r'\{[^{}]*\}', raw_content)
            if json_match:
                parsed = json.loads(json_match.group(0))
                cat = parsed.get("category", "").lower()
                urg = parsed.get("urgency", "").lower()
                res = parsed.get("reasoning", "")
                if cat in VALID_CATEGORIES and urg in VALID_URGENCIES:
                    return {
                        "category": cat,
                        "urgency": urg,
                        "reasoning": res or f"Classified under {cat} with {urg} urgency."
                    }

        logger.warning("No valid response returned by LLM; falling back to heuristic classification.")
        return _heuristic_mock_classify(text)

    except Exception as e:
        logger.warning(
            f"LLM API call failed or timed out ({type(e).__name__}: {e}); "
            "automatically falling back to MOCK_MODE classification without failing request."
        )
        return _heuristic_mock_classify(text)

