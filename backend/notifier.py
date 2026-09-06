"""
CampusResolve Email & Escalation Notification Engine
Handles automated email alerts upon complaint SLA escalation,
supports practical university email addresses, rich HTML templates with direct complaint deep-links,
and maintains simulated inboxes for dashboard visualization.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CampusResolveNotifier")

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

# Practical Authority Email Directory (Configured with real practical email addresses)
AUTHORITY_DIRECTORY = {
    "Warden": {
        "name": "Hostel Warden Office",
        "email": os.getenv("EMAIL_WARDEN", "dlogidth4@gmail.com"),
        "tier": "Tier 1 — Operational (Hostels)"
    },
    "Mess Committee": {
        "name": "Mess & Dining Committee",
        "email": os.getenv("EMAIL_MESS", "dlogidth5@gmail.com"),
        "tier": "Tier 1 — Operational (Dining & Catering)"
    },
    "HOD": {
        "name": "Head of Department (Academic)",
        "email": os.getenv("EMAIL_HOD", "717824v101@kce.ac.in"),
        "tier": "Tier 1 — Operational (Academic Affairs)"
    },
    "Estate Office": {
        "name": "Campus Facilities & Estate Office",
        "email": os.getenv("EMAIL_ESTATE", "717824v134@kce.ac.in"),
        "tier": "Tier 1 — Operational (Campus Infrastructure)"
    },
    "Dean of Student Affairs": {
        "name": "Office of the Dean (Student Affairs)",
        "email": os.getenv("EMAIL_DEAN_STUDENT", "abijithmohanan2006@gmail.com"),
        "tier": "Tier 2 — Executive Oversight (Hostels & Mess)"
    },
    "Dean of Academics": {
        "name": "Office of the Dean (Academic Affairs)",
        "email": os.getenv("EMAIL_DEAN_ACADEMIC", "717824v101@kce.ac.in"),
        "tier": "Tier 2 — Executive Oversight (Academics)"
    },
    "Vice Principal": {
        "name": "Office of the Vice Principal",
        "email": os.getenv("EMAIL_VICE_PRINCIPAL", "logidth78@gmail.com"),
        "tier": "Tier 2 — Executive Oversight (Infrastructure)"
    },
    "Principal": {
        "name": "Office of the Principal / Director",
        "email": os.getenv("EMAIL_PRINCIPAL", "717824v27@kce.ac.in"),
        "tier": "Tier 3 — Apex Institutional Authority"
    },
    "Counseling Cell": {
        "name": "Student Counseling & Anti-Harassment Cell",
        "email": os.getenv("EMAIL_COUNSELOR", "717824v152@kce.ac.in"),
        "tier": "Protected — Student Safety & Wellness"
    },
    "Admin": {
        "name": "Central Institutional Administrator",
        "email": os.getenv("EMAIL_ADMIN", "717824v134@kce.ac.in"),
        "tier": "Central Administration"
    }
}

# In-memory sent email registry for demo and dashboard viewing
_sent_emails: List[Dict[str, Any]] = []


def get_authority_email(authority_name: str) -> str:
    """Retrieve official email for an authority name."""
    info = AUTHORITY_DIRECTORY.get(authority_name)
    if info:
        return info["email"]
    return f"{authority_name.lower().replace(' ', '.')}@campus.edu"


def _dispatch_smtp(recipient_email: str, subject: str, plain_body: str, html_body: str) -> bool:
    """Helper to dispatch real SMTP emails with STARTTLS (port 587) and SSL (port 465) fallback."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_FROM") or smtp_user or "alerts@campusresolve.edu"

    if not smtp_user or not smtp_pass:
        logger.warning(
            f"[SMTP WARNING] Real email to {recipient_email} skipped: "
            f"SMTP_USER or SMTP_PASSWORD is not set in environment variables."
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_from
    msg["To"] = recipient_email
    msg["Subject"] = subject
    
    part1 = MIMEText(plain_body, "plain")
    part2 = MIMEText(html_body, "html")
    msg.attach(part1)
    msg.attach(part2)

    # Attempt 1: Configured port (usually 587 with STARTTLS)
    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        logger.info(f"[SMTP SUCCESS] Real email delivered to {recipient_email} via port {smtp_port}")
        return True
    except Exception as e1:
        logger.warning(f"[SMTP RETRY] Port {smtp_port} attempt failed ({e1}). Attempting SSL port 465 fallback...")

    # Attempt 2: Fallback to SSL on port 465 (handles networks blocking STARTTLS)
    try:
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=15) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        logger.info(f"[SMTP SUCCESS] Real email delivered to {recipient_email} via port 465 fallback")
        return True
    except Exception as e2:
        logger.error(f"[SMTP ERROR] Failed to deliver real email to {recipient_email}: {e2}")
        return False


def send_new_complaint_email(
    complaint_id: int,
    complaint_text: str,
    category: str,
    urgency: str,
    assigned_authority: str,
    sla_deadline: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Constructs and dispatches an immediate notification email to the assigned authority upon new complaint creation,
    including the complete grievance text and direct clickable deep-links to the authority queue.
    """
    recipient_email = get_authority_email(assigned_authority)
    recipient_info = AUTHORITY_DIRECTORY.get(assigned_authority, {})
    recipient_name = recipient_info.get("name", assigned_authority)
    tier_label = recipient_info.get("tier", "Initial Tier (Operational)")

    subject = f"📬 [NEW GRIEVANCE ASSIGNED] Complaint #{complaint_id}: {category.upper()} — Assigned to {assigned_authority}"
    
    timestamp_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    sla_str = sla_deadline.strftime("%Y-%m-%d %H:%M:%S UTC") if sla_deadline else "Standard SLA"

    # Direct links to complaint page
    authority_portal_link = f"{BASE_URL}/app/dashboard.html?complaint_id={complaint_id}"
    student_track_link = f"{BASE_URL}/app/index.html?track={complaint_id}"

    # Plain Text Email Body
    plain_body = f"""
ATTENTION: {recipient_name} ({assigned_authority})
Official Assignment Notice — CampusResolve Automated Triage Engine

A new student grievance has been submitted and AUTONOMOUSLY ROUTED to your office for review and resolution.

==================================================
TICKET DETAILS
==================================================
Complaint ID: #{complaint_id}
Category: {category.upper()}
Urgency Level: {urgency.upper()}
Assigned Authority: {assigned_authority} ({recipient_email})
Escalation Tier: Level 0 ({tier_label})
Filed On: {timestamp_str}
SLA Resolution Target: {sla_str}

Grievance Statement:
"{complaint_text}"

==================================================
DIRECT COMPLAINT ACCESS & ACTIONS
==================================================
👉 Open and Review Complaint in Authority Portal:
{authority_portal_link}

👉 Student Public Tracking Link:
{student_track_link}

Please log in to the CampusResolve Authority Portal to review the grievance and execute timely resolution before SLA breach.
==================================================
CampusResolve Autonomous Grievance Resolution Engine
"""

    # Rich HTML Email Body with Buttons and Styling
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #0f172a; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ background: #2563eb; color: #ffffff; padding: 18px 24px; }}
    .header h1 {{ margin: 0; font-size: 18px; font-weight: 700; }}
    .content {{ padding: 24px; }}
    .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
    .meta-table td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; font-size: 14px; }}
    .meta-table td.label {{ color: #64748b; font-weight: 600; width: 38%; }}
    .meta-table td.val {{ color: #0f172a; font-weight: 600; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }}
    .badge-primary {{ background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }}
    .statement-box {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 14px; margin: 16px 0; border-radius: 4px; font-size: 14px; line-height: 1.5; color: #1e293b; }}
    .btn-container {{ text-align: center; margin: 25px 0 15px 0; }}
    .btn {{ display: inline-block; background: #2563eb; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 14px; box-shadow: 0 2px 4px rgba(37,99,235,0.2); }}
    .btn:hover {{ background: #1d4ed8; }}
    .footer {{ background: #f8fafc; padding: 14px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>📬 New Grievance Assigned</h1>
    </div>
    <div class="content">
      <p style="margin-top: 0; font-size: 14px; color: #475569;">
        <strong>Attention:</strong> {recipient_name} (<code>{recipient_email}</code>)<br>
        A student grievance has been assigned to your jurisdiction for review and resolution.
      </p>

      <table class="meta-table">
        <tr>
          <td class="label">Complaint ID:</td>
          <td class="val"><strong>#{complaint_id}</strong></td>
        </tr>
        <tr>
          <td class="label">Category:</td>
          <td class="val"><span class="badge badge-primary">{category.upper()}</span></td>
        </tr>
        <tr>
          <td class="label">Urgency Priority:</td>
          <td class="val"><strong>{urgency.upper()}</strong></td>
        </tr>
        <tr>
          <td class="label">Assigned Authority:</td>
          <td class="val"><strong>{assigned_authority}</strong></td>
        </tr>
        <tr>
          <td class="label">Escalation Tier:</td>
          <td class="val">Level 0 ({tier_label})</td>
        </tr>
        <tr>
          <td class="label">Filed On:</td>
          <td class="val">{timestamp_str}</td>
        </tr>
        <tr>
          <td class="label">SLA Target:</td>
          <td class="val" style="color:#2563eb;"><strong>{sla_str}</strong></td>
        </tr>
      </table>

      <div style="font-weight: 600; font-size: 13px; color: #64748b; text-transform: uppercase;">Grievance Statement:</div>
      <div class="statement-box">
        "{complaint_text}"
      </div>

      <div class="btn-container">
        <a href="{authority_portal_link}" class="btn">👉 Open Complaint in Authority Portal</a>
      </div>
      
      <p style="text-align: center; font-size: 12px; color: #64748b;">
        Student Public Tracking Link: <a href="{student_track_link}" style="color: #2563eb;">{student_track_link}</a>
      </p>
    </div>
    <div class="footer">
      CampusResolve Autonomous Grievance Engine &copy; 2026 &middot; Automated Institutional Monitor
    </div>
  </div>
</body>
</html>
"""

    email_record = {
        "id": len(_sent_emails) + 1,
        "complaint_id": complaint_id,
        "type": "new_complaint",
        "recipient_name": recipient_name,
        "recipient_authority": assigned_authority,
        "recipient_email": recipient_email,
        "sender": "CampusResolve Alerts <alerts@campusresolve.edu>",
        "subject": subject,
        "body": plain_body.strip(),
        "html_body": html_body.strip(),
        "portal_link": authority_portal_link,
        "track_link": student_track_link,
        "category": category,
        "escalation_level": 0,
        "old_authority": None,
        "new_authority": assigned_authority,
        "timestamp": datetime.utcnow().isoformat()
    }

    _sent_emails.insert(0, email_record)

    # Server Console Log
    logger.info(
        f"[EMAIL DISPATCH] Sent to {assigned_authority} <{recipient_email}>: "
        f"New Complaint #{complaint_id} assigned ({category}/{urgency}) | Link: {authority_portal_link}"
    )

    # Optional real SMTP sending if environment configured
    _dispatch_smtp(recipient_email, subject, plain_body, html_body)

    return email_record


def send_escalation_email(
    complaint_id: int,
    complaint_text: str,
    category: str,
    urgency: str,
    old_authority: str,
    new_authority: str,
    escalation_level: int,
    new_sla: datetime
) -> Dict[str, Any]:
    """
    Constructs and dispatches an urgent SLA escalation email to the newly assigned authority,
    including the complete grievance text and a direct clickable URL to the complaint page.
    """
    recipient_email = get_authority_email(new_authority)
    recipient_info = AUTHORITY_DIRECTORY.get(new_authority, {})
    recipient_name = recipient_info.get("name", new_authority)
    tier_label = recipient_info.get("tier", f"Tier {escalation_level}")

    subject = f"🚨 [SLA ESCALATION NOTICE] Complaint #{complaint_id} Escalated to {new_authority} (Level {escalation_level})"
    
    timestamp_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    sla_str = new_sla.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Direct links to complaint page
    authority_portal_link = f"{BASE_URL}/app/dashboard.html?complaint_id={complaint_id}"
    student_track_link = f"{BASE_URL}/app/index.html?track={complaint_id}"

    # Plain Text Email Body
    plain_body = f"""
ATTENTION: {recipient_name} ({new_authority})
Official Escalation Notice — CampusResolve Automated SLA Monitor

A student grievance has breached its resolution SLA at {old_authority} and has been AUTONOMOUSLY ESCALATED to your office.

==================================================
TICKET DETAILS
==================================================
Complaint ID: #{complaint_id}
Category: {category.upper()}
Urgency Level: {urgency.upper()}
Escalation Level: Level {escalation_level} ({tier_label})
Previous Authority: {old_authority}
Newly Assigned Authority: {new_authority}
Escalated On: {timestamp_str}
New SLA Resolution Target: {sla_str}

Grievance Statement:
"{complaint_text}"

==================================================
DIRECT COMPLAINT ACCESS & ACTIONS
==================================================
👉 Open and Review Complaint in Authority Portal:
{authority_portal_link}

👉 Student Public Tracking Link:
{student_track_link}

Please log in to the CampusResolve Authority Portal immediately to review the audit trail and execute resolution.
==================================================
CampusResolve Autonomous Grievance Resolution Engine
"""

    # Rich HTML Email Body with Buttons and Styling
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #0f172a; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ background: #dc2626; color: #ffffff; padding: 18px 24px; }}
    .header h1 {{ margin: 0; font-size: 18px; font-weight: 700; }}
    .content {{ padding: 24px; }}
    .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
    .meta-table td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; font-size: 14px; }}
    .meta-table td.label {{ color: #64748b; font-weight: 600; width: 38%; }}
    .meta-table td.val {{ color: #0f172a; font-weight: 600; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }}
    .badge-danger {{ background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }}
    .statement-box {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 14px; margin: 16px 0; border-radius: 4px; font-size: 14px; line-height: 1.5; color: #1e293b; }}
    .btn-container {{ text-align: center; margin: 25px 0 15px 0; }}
    .btn {{ display: inline-block; background: #2563eb; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 14px; box-shadow: 0 2px 4px rgba(37,99,235,0.2); }}
    .btn:hover {{ background: #1d4ed8; }}
    .footer {{ background: #f8fafc; padding: 14px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🚨 Grievance SLA Escalation Alert</h1>
    </div>
    <div class="content">
      <p style="margin-top: 0; font-size: 14px; color: #475569;">
        <strong>Attention:</strong> {recipient_name} (<code>{recipient_email}</code>)<br>
        A student grievance has breached its resolution SLA at <strong>{old_authority}</strong> and has been escalated to your office.
      </p>

      <table class="meta-table">
        <tr>
          <td class="label">Complaint ID:</td>
          <td class="val"><strong>#{complaint_id}</strong></td>
        </tr>
        <tr>
          <td class="label">Category:</td>
          <td class="val"><span class="badge" style="background:#eff6ff; color:#2563eb;">{category.upper()}</span></td>
        </tr>
        <tr>
          <td class="label">Urgency Priority:</td>
          <td class="val"><span class="badge badge-danger">{urgency.upper()}</span></td>
        </tr>
        <tr>
          <td class="label">Escalation Tier:</td>
          <td class="val"><strong>Level {escalation_level}</strong> ({tier_label})</td>
        </tr>
        <tr>
          <td class="label">Previous Authority:</td>
          <td class="val">{old_authority}</td>
        </tr>
        <tr>
          <td class="label">Newly Assigned:</td>
          <td class="val"><strong>{new_authority}</strong></td>
        </tr>
        <tr>
          <td class="label">Escalated On:</td>
          <td class="val">{timestamp_str}</td>
        </tr>
        <tr>
          <td class="label">New SLA Target:</td>
          <td class="val" style="color:#dc2626;"><strong>{sla_str}</strong></td>
        </tr>
      </table>

      <div style="font-weight: 600; font-size: 13px; color: #64748b; text-transform: uppercase;">Grievance Statement:</div>
      <div class="statement-box">
        "{complaint_text}"
      </div>

      <div class="btn-container">
        <a href="{authority_portal_link}" class="btn">👉 Review Complaint in Authority Portal</a>
      </div>
      
      <p style="text-align: center; font-size: 12px; color: #64748b;">
        Student Public Tracking Link: <a href="{student_track_link}" style="color: #2563eb;">{student_track_link}</a>
      </p>
    </div>
    <div class="footer">
      CampusResolve Autonomous Grievance Engine &copy; 2026 &middot; Automated Institutional Monitor
    </div>
  </div>
</body>
</html>
"""

    email_record = {
        "id": len(_sent_emails) + 1,
        "complaint_id": complaint_id,
        "recipient_name": recipient_name,
        "recipient_authority": new_authority,
        "recipient_email": recipient_email,
        "sender": "CampusResolve Alerts <alerts@campusresolve.edu>",
        "subject": subject,
        "body": plain_body.strip(),
        "html_body": html_body.strip(),
        "portal_link": authority_portal_link,
        "track_link": student_track_link,
        "category": category,
        "escalation_level": escalation_level,
        "old_authority": old_authority,
        "new_authority": new_authority,
        "type": "escalation",
        "timestamp": datetime.utcnow().isoformat()
    }

    _sent_emails.insert(0, email_record)

    # Server Console Log
    logger.info(
        f"[EMAIL DISPATCH] Sent to {new_authority} <{recipient_email}>: "
        f"Complaint #{complaint_id} escalated from {old_authority} (Level {escalation_level}) | Link: {authority_portal_link}"
    )

    # Optional real SMTP sending if environment configured
    _dispatch_smtp(recipient_email, subject, plain_body, html_body)

    return email_record


def get_sent_emails(authority: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve sent email logs with optional authority filtering."""
    if authority and authority != "All":
        return [e for e in _sent_emails if e["recipient_authority"] == authority]
    return _sent_emails


def clear_sent_emails():
    """Clear sent email logs (for testing)."""
    global _sent_emails
    _sent_emails.clear()
