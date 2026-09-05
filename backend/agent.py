"""
CampusResolve AI Agent Engine
Autonomous complaint classification using Groq LLM API with function calling/tool use and mock fallback mode.
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


def _heuristic_mock_classify(text: str) -> Dict[str, Any]:
    """Fallback generator for mock mode or API downtime."""
    lower_text = text.lower()

    # Category matching
    if any(w in lower_text for w in ["harass", "ragging", "bully", "threat", "abuse", "safety", "stalk", "inappropriate"]):
        category = "harassment"
    elif any(w in lower_text for w in ["food", "mess", "meal", "dinner", "lunch", "canteen", "diet", "breakfast", "rotten", "hygiene"]):
        category = "mess"
    elif any(w in lower_text for w in ["hostel", "room", "bed", "warden", "dorm", "washroom", "bathroom", "shower"]):
        category = "hostel"
    elif any(w in lower_text for w in ["fan", "light", "ac", "lift", "elevator", "bench", "door", "plumbing", "building", "projector", "leakage", "broken"]):
        category = "infrastructure"
    elif any(w in lower_text for w in ["exam", "grade", "marks", "attendance", "professor", "faculty", "lecture", "course", "curriculum", "class"]):
        category = "academic"
    else:
        # Plausible random pick if no keywords matched
        category = random.choice(["hostel", "infrastructure", "academic", "mess"])

    # Urgency matching
    if category == "harassment" or any(w in lower_text for w in ["emergency", "urgent", "danger", "hazard", "threat", "immediate", "severe"]):
        urgency = "high"
    elif any(w in lower_text for w in ["broken", "stopped", "failed", "leakage", "flickering", "spoiled", "cold"]):
        urgency = "medium"
    elif any(w in lower_text for w in ["minor", "query", "suggestion", "feedback", "slow"]):
        urgency = "low"
    else:
        urgency = random.choice(["medium", "low"])

    reasoning = f"Identified as {category} issue with {urgency} urgency based on keywords and impact severity."
    return {
        "category": category,
        "urgency": urgency,
        "reasoning": reasoning
    }


def classify_complaint(text: str) -> Dict[str, Any]:
    """
    Classify a student complaint using Groq API tool use / function calling.
    Falls back to mock classification when MOCK_MODE=True or if the API is unavailable.
    """
    if MOCK_MODE or not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        logger.info("Running complaint classification in MOCK_MODE")
        return _heuristic_mock_classify(text)

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "classify_campus_complaint",
                    "description": "Classifies a student complaint into a specific category, urgency level, and one sentence reasoning.",
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
                                "description": "Urgency rating (high, medium, low) according to safety, academic impact, or disruption."
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "A single sentence explaining the reasoning behind the classification."
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
                    "Analyze the user's grievance and call the tool `classify_campus_complaint` with appropriate category, urgency, and concise one-sentence reasoning. "
                    "Allowed categories: 'hostel', 'mess', 'academic', 'infrastructure', 'harassment'. "
                    "Allowed urgencies: 'low', 'medium', 'high'."
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

        # Fallback if no tool call returned
        return _heuristic_mock_classify(text)

    except Exception as e:
        logger.warning(f"Groq API call failed or unavailable ({e}); falling back to heuristic mock classifier.")
        return _heuristic_mock_classify(text)
