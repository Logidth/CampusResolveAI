"""
CampusResolve AI Agent Engine
Handles autonomous grievance classification, severity analysis, department routing, and automated response drafting.
"""

from typing import Dict, Any
from datetime import datetime, timedelta
from backend.models import GrievanceCategory, PriorityLevel, GrievanceStatus


class GrievanceAgent:
    """Core Agent responsible for triaging and resolving campus grievances."""

    CATEGORY_KEYWORDS = {
        GrievanceCategory.HOSTEL: ["room", "hostel", "mess", "food", "warden", "water", "electricity", "dorm"],
        GrievanceCategory.ACADEMIC: ["grade", "exam", "syllabus", "marks", "attendance", "course", "professor", "class"],
        GrievanceCategory.MAINTENANCE: ["fan", "light", "ac", "broken", "leakage", "door", "bench", "lift", "elevator"],
        GrievanceCategory.FINANCIAL: ["fee", "scholarship", "refund", "receipt", "fine", "dues", "payment"],
        GrievanceCategory.HARASSMENT: ["ragging", "bully", "threat", "harass", "abuse", "safety", "discrimination"],
        GrievanceCategory.TRANSPORT: ["bus", "shuttle", "parking", "driver", "route", "timing"],
    }

    DEPARTMENT_MAP = {
        GrievanceCategory.HOSTEL: "Hostel Administration & Warden Office",
        GrievanceCategory.ACADEMIC: "Academic Dean & Controller of Examinations",
        GrievanceCategory.MAINTENANCE: "Campus Facilities & Estate Office",
        GrievanceCategory.FINANCIAL: "Finance & Accounts Office",
        GrievanceCategory.HARASSMENT: "Anti-Ragging & Internal Complaints Committee (ICC)",
        GrievanceCategory.TRANSPORT: "Transport & Logistics Office",
        GrievanceCategory.OTHER: "General Student Affairs Grievance Cell",
    }

    SLA_HOURS = {
        PriorityLevel.CRITICAL: 6,
        PriorityLevel.HIGH: 24,
        PriorityLevel.MEDIUM: 48,
        PriorityLevel.LOW: 72,
    }

    def analyze_grievance(self, title: str, description: str) -> Dict[str, Any]:
        """
        Agentic analysis of student grievance.
        In hackathon mode, uses heuristic fallback + LLM integration ready hooks.
        """
        combined_text = f"{title.lower()} {description.lower()}"
        
        # 1. Determine Category
        detected_category = GrievanceCategory.OTHER
        for cat, keywords in self.CATEGORY_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                detected_category = cat
                break

        # 2. Determine Priority & Urgency
        priority = PriorityLevel.MEDIUM
        if detected_category == GrievanceCategory.HARASSMENT or any(w in combined_text for w in ["emergency", "urgent", "danger", "hazard", "threat"]):
            priority = PriorityLevel.CRITICAL
        elif any(w in combined_text for w in ["broken", "immediate", "failed", "severe", "refund"]):
            priority = PriorityLevel.HIGH
        elif any(w in combined_text for w in ["minor", "query", "suggestion", "feedback"]):
            priority = PriorityLevel.LOW

        # 3. Target Department
        assigned_department = self.DEPARTMENT_MAP.get(detected_category, "General Student Affairs Grievance Cell")

        # 4. Calculate SLA Deadline
        sla_hours = self.SLA_HOURS.get(priority, 48)
        sla_deadline = datetime.utcnow() + timedelta(hours=sla_hours)

        # 5. Suggested Action & AI Summary
        ai_summary = f"Student reports issue concerning {detected_category.value.lower()}: '{title}'. Automated triage tagged priority as {priority.value}."
        suggested_action = f"Forward to {assigned_department} with {sla_hours}h SLA resolution window. Auto-notify student on progress."

        return {
            "category": detected_category,
            "priority": priority,
            "assigned_department": assigned_department,
            "sentiment_score": "NEGATIVE" if priority in [PriorityLevel.CRITICAL, PriorityLevel.HIGH] else "NEUTRAL",
            "ai_summary": ai_summary,
            "suggested_action": suggested_action,
            "sla_deadline": sla_deadline,
            "initial_status": GrievanceStatus.ASSIGNED,
        }


# Singleton agent instance
agent = GrievanceAgent()
