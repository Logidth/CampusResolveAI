"""
CampusResolve AI Agent Engine
Handles autonomous complaint classification, severity analysis, authority routing, and SLA determination.
"""

import re
from typing import Dict, Any
from datetime import datetime, timedelta


class GrievanceAgent:
    """Core Agent responsible for triaging and resolving campus complaints."""

    CATEGORY_KEYWORDS = {
        "Academic": ["classroom", "class", "grade", "exam", "syllabus", "marks", "attendance", "course", "professor", "faculty", "lecture", "projector", "lab"],
        "Hostel": ["hostel", "mess", "food", "warden", "water", "electricity", "dorm", "bed", "washroom", "room"],
        "Maintenance": ["fan", "light", "ac", "broken", "leakage", "door", "bench", "lift", "elevator", "plumbing", "repairs"],
        "Finance": ["fee", "scholarship", "refund", "receipt", "fine", "dues", "payment", "tuition"],
        "Anti-Ragging/Safety": ["ragging", "bully", "threat", "harass", "abuse", "safety", "discrimination", "violence"],
        "Transport": ["bus", "shuttle", "parking", "driver", "route", "timing"],
    }

    AUTHORITY_MAP = {
        "Academic": "Academic Dean & Controller of Examinations",
        "Hostel": "Hostel Administration & Warden Office",
        "Maintenance": "Campus Facilities & Estate Office",
        "Finance": "Finance & Accounts Office",
        "Anti-Ragging/Safety": "Anti-Ragging & Internal Complaints Committee",
        "Transport": "Transport & Logistics Office",
        "General": "Student Affairs Grievance Cell",
    }

    SLA_HOURS = {
        "critical": 6,
        "high": 24,
        "medium": 48,
        "low": 72,
    }

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Agentic analysis of student complaint text using regex word matching.
        """
        lower_text = text.lower()

        # 1. Category Detection (word-boundary matched)
        detected_category = "General"
        for cat, keywords in self.CATEGORY_KEYWORDS.items():
            pattern = r'\b(' + '|'.join(re.escape(kw) for kw in keywords) + r')\b'
            if re.search(pattern, lower_text):
                detected_category = cat
                break

        # 2. Urgency Detection
        urgency = "medium"
        critical_pattern = r'\b(ragging|threat|emergency|urgent|danger|hazard|harass|abuse|immediate)\b'
        high_pattern = r'\b(broken|failed|severe|refund|leakage|stopped|flickering)\b'
        low_pattern = r'\b(minor|query|suggestion|feedback)\b'

        if detected_category == "Anti-Ragging/Safety" or re.search(critical_pattern, lower_text):
            urgency = "critical"
        elif re.search(high_pattern, lower_text):
            urgency = "high"
        elif re.search(low_pattern, lower_text):
            urgency = "low"

        # 3. Assigned Authority
        assigned_authority = self.AUTHORITY_MAP.get(detected_category, "Student Affairs Grievance Cell")

        # 4. SLA Deadline
        sla_hours = self.SLA_HOURS.get(urgency, 48)
        sla_deadline = datetime.utcnow() + timedelta(hours=sla_hours)

        return {
            "category": detected_category,
            "urgency": urgency,
            "assigned_authority": assigned_authority,
            "sla_deadline": sla_deadline,
        }


# Singleton agent instance
agent = GrievanceAgent()
