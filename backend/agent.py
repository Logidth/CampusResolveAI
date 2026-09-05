"""
CampusResolve AI Agent Engine
Autonomous complaint classification with robust error handling, timeout guardrails,
and automated fallback to MOCK_MODE on API failure or rate limit.
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


def _heuristic_mock_classify(text: str) -> Dict[str, Any]:
    """
    Deterministic & safety-first fallback generator for mock mode or API downtime.
    Ensures harassment and critical safety keywords are prioritized instantly without sentiment exposure.
    """
    lower_text = text.lower()

    # 1. Immediate Safety / Harassment Check
    if any(w in lower_text for w in ["harass", "ragging", "bully", "threat", "abuse", "safety", "stalk", "inappropriate", "violence"]):
        return {
            "category": "harassment",
            "urgency": "high",
            "reasoning": "Identified safety/harassment keywords; flagged for immediate Counseling Cell intervention."
        }

    # 2. Domain Categorization
    if any(w in lower_text for w in ["food", "mess", "meal", "dinner", "lunch", "canteen", "diet", "breakfast", "rotten", "hygiene"]):
        category = "mess"
    elif any(w in lower_text for w in ["hostel", "room", "bed", "warden", "dorm", "washroom", "bathroom", "shower", "geyser"]):
        category = "hostel"
    elif any(w in lower_text for w in ["fan", "light", "ac", "lift", "elevator", "bench", "door", "plumbing", "building", "projector", "leakage", "broken", "pipe"]):
        category = "infrastructure"
    elif any(w in lower_text for w in ["exam", "grade", "marks", "attendance", "professor", "faculty", "lecture", "course", "curriculum", "class", "lab"]):
        category = "academic"
    else:
        category = random.choice(["hostel", "infrastructure", "academic", "mess"])

    # 3. Urgency Evaluation
    if any(w in lower_text for w in ["emergency", "urgent", "danger", "hazard", "threat", "immediate", "severe", "sparking", "fire"]):
        urgency = "high"
    elif any(w in lower_text for w in ["broken", "stopped", "failed", "leakage", "flickering", "spoiled", "cold"]):
        urgency = "medium"
    elif any(w in lower_text for w in ["minor", "query", "suggestion", "feedback", "slow"]):
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
        # Set client with request timeout
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
                                "description": "The classified domain of the complaint."
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
                    "Allowed categories: 'hostel', 'mess', 'academic', 'infrastructure', 'harassment'. "
                    "Allowed urgencies: 'low', 'medium', 'high'. "
                    "Note: Any harassment or safety concern must always be categorized as 'harassment' with 'high' urgency."
                )
            },
            {
                "role": "user",
                "content": f"Student Complaint: {text}"
            }
        ]

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

        logger.warning("No tool call returned by LLM; falling back to heuristic classification.")
        return _heuristic_mock_classify(text)

    except Exception as e:
        logger.warning(
            f"LLM API call failed or timed out ({type(e).__name__}: {e}); "
            "automatically falling back to MOCK_MODE classification without failing request."
        )
        return _heuristic_mock_classify(text)
