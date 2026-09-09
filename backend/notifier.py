"""
CampusResolve Email & Escalation Notification Engine
Handles automated email alerts upon complaint SLA escalation,
supports practical university email addresses, rich HTML templates with direct complaint deep-links,
and maintains simulated inboxes for dashboard visualization.
"""

import os
import smtplib
import json
import urllib.request
import urllib.error
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CampusResolveNotifier")

BASE_URL = (os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://campusresolveai.onrender.com").rstrip("/")

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
    "Exam Cell Admin": {
        "name": "Examination & Fee Administration Cell",
        "email": os.getenv("EMAIL_EXAM_CELL", "717824v101@kce.ac.in"),
        "tier": "Tier 1 — Operational (Marks, Semester & Fees)"
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
        "email": os.getenv("EMAIL_PRINCIPAL", "717824v132@kce.ac.in"),
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


_last_smtp_error = ""

def get_last_smtp_error() -> str:
    global _last_smtp_error
    return _last_smtp_error

_brevo_credits_cache = {"credits": None, "checked_at": 0}

def get_brevo_credits(api_key: str) -> int:
    """
    Checks the remaining email credits for the Brevo account.
    Returns available credits count (e.g. 300, 0), or -1 if check failed.
    Cached for 60 seconds to avoid repetitive API queries.
    """
    import time
    now = time.time()
    if _brevo_credits_cache["credits"] is not None and (now - _brevo_credits_cache["checked_at"]) < 60:
        return _brevo_credits_cache["credits"]
    try:
        resp = httpx.get("https://api.brevo.com/v3/account", headers={"api-key": api_key}, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            plan = data.get("plan", [])
            if plan and isinstance(plan, list):
                credits = plan[0].get("credits", 0)
                _brevo_credits_cache["credits"] = credits
                _brevo_credits_cache["checked_at"] = now
                logger.info(f"[BREVO ACCOUNT CHECK] Available credits: {credits}")
                return credits
        else:
            logger.warning(f"[BREVO ACCOUNT CHECK] HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"[BREVO ACCOUNT CHECK] Error checking credits: {e}")
    return -1


def _dispatch_smtp(recipient_email: str, subject: str, plain_body: str, html_body: str, also_notify_admin: bool = True) -> bool:
    """
    Dispatches outbound email using a resilient cascading fallback chain:
    1. Brevo REST API (if key present AND account has credits > 0)
    2. Resend REST API (if key present)
    3. Direct SMTP (Gmail / Custom Host: Port 465 SSL, then Port 587 STARTTLS)
    """
    global _last_smtp_error
    _last_smtp_error = ""

    smtp_host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    smtp_port = int((os.getenv("SMTP_PORT") or "465").strip())
    smtp_user = (os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME") or "").strip()
    smtp_pass = (os.getenv("SMTP_PASSWORD") or "").strip().replace(" ", "")
    smtp_from = (os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_FROM") or smtp_user or "alerts@campusresolve.edu").strip()

    resend_api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    brevo_api_key = (os.getenv("BREVO_API_KEY") or "").strip()
    force_smtp = os.getenv("FORCE_SMTP", "").lower() in ("true", "1", "yes")

    # Strictly dispatch to the intended authority recipient
    targets = [recipient_email]

    # PATH A: Brevo HTTPS REST API (Port 443 - Primary)
    if brevo_api_key and not force_smtp:
        credits = get_brevo_credits(brevo_api_key)
        if credits <= 0:
            logger.warning(
                f"[BREVO SKIPPED: 0 CREDITS] Brevo credit check returned {credits} (credits <= 0 or check failed). "
                "Bypassing Brevo API call and falling through to Resend/SMTP immediately."
            )
            _last_smtp_error = f"Brevo credits unavailable ({credits})"
        else:
            brevo_from_email = (os.getenv("BREVO_SENDER_EMAIL") or "abijithmohanan2006@gmail.com").strip()
            brevo_from_name = os.getenv("BREVO_SENDER_NAME", "CampusResolve Alerts")
            success_any = False
            brevo_errors = []
            for target in targets:
                try:
                    resp = httpx.post(
                        "https://api.brevo.com/v3/smtp/email",
                        json={
                            "sender": {"name": brevo_from_name, "email": brevo_from_email},
                            "to": [{"email": target}],
                            "subject": subject,
                            "htmlContent": html_body,
                            "textContent": plain_body
                        },
                        headers={
                            "api-key": brevo_api_key,
                            "Content-Type": "application/json"
                        },
                        timeout=15.0
                    )
                    if resp.status_code in (200, 201):
                        logger.info(f"[BREVO HTTPS SUCCESS] Real email delivered to {target} via Brevo API (port 443)")
                        success_any = True
                    else:
                        err_detail = f"Status {resp.status_code}: {resp.text}"
                        logger.error(f"[BREVO ERROR] Failed to send to {target}: {err_detail}")
                        brevo_errors.append(f"{target}: {err_detail}")
                except Exception as ex:
                    logger.error(f"[BREVO ERROR] Failed to send to {target}: {ex}")
                    brevo_errors.append(f"{target}: {ex}")

            if success_any:
                _last_smtp_error = ""
                return True
            else:
                logger.warning(f"[BREVO FAILED] Delivery via Brevo failed ({' | '.join(brevo_errors)}). Falling back to direct SMTP...")
                _last_smtp_error = "Brevo API error: " + " | ".join(brevo_errors)

    # PATH B: Resend HTTPS REST API (Port 443)
    if resend_api_key and not force_smtp:
        resend_from = (os.getenv("RESEND_FROM") or "CampusResolve <onboarding@resend.dev>").strip()
        success_any = False
        resend_errors = []
        for target in targets:
            try:
                resp = httpx.post(
                    "https://api.resend.com/emails",
                    json={
                        "from": resend_from,
                        "to": [target],
                        "subject": subject,
                        "html": html_body,
                        "text": plain_body
                    },
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=15.0
                )
                if resp.status_code in (200, 201):
                    logger.info(f"[RESEND HTTPS SUCCESS] Real email delivered to {target} via Resend API (port 443)")
                    success_any = True
                else:
                    err_detail = f"Status {resp.status_code}: {resp.text}"
                    if "only send testing emails to your own email address" in resp.text:
                        err_detail += " -> [Resend free domain only allows sending to registered email]"
                    logger.error(f"[RESEND ERROR] Failed to send to {target}: {err_detail}")
                    resend_errors.append(f"{target}: {err_detail}")
            except Exception as ex:
                logger.error(f"[RESEND ERROR] Failed to send to {target}: {ex}")
                resend_errors.append(f"{target}: {ex}")

        if success_any:
            _last_smtp_error = ""
            return True
        else:
            logger.warning(f"[RESEND FAILED] Delivery via Resend failed ({' | '.join(resend_errors)}). Falling back to direct SMTP...")
            _last_smtp_error = "Resend API error: " + " | ".join(resend_errors)

    # PATH C: Direct SMTP (Gmail / Custom Host via Port 465 SSL, then Port 587 STARTTLS)
    if not smtp_user or not smtp_pass:
        msg_err = f"No functional email transport available. ({_last_smtp_error} | SMTP_USER/PASSWORD missing)"
        _last_smtp_error = msg_err
        logger.warning(f"[EMAIL WARNING] Real email to {recipient_email} skipped: {msg_err}")
        return False

    success_any = False
    for target in targets:
        msg = MIMEMultipart("alternative")
        msg["From"] = smtp_from
        msg["To"] = target
        msg["Subject"] = subject

        part1 = MIMEText(plain_body, "plain")
        part2 = MIMEText(html_body, "html")
        msg.attach(part1)
        msg.attach(part2)
        sent = False
        smtp_errors = []

        # Try Port 465 SSL first
        try:
            with smtplib.SMTP_SSL(smtp_host, 465, timeout=12) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info(f"[SMTP SUCCESS] Real email delivered to {target} via SSL port 465")
            sent = True
        except Exception as e1:
            smtp_errors.append(f"Port 465 SSL: {e1}")
            logger.warning(f"[SMTP RETRY] SSL port 465 attempt failed for {target} ({e1}). Attempting port 587 STARTTLS fallback...")

        # Fallback to Port 587 STARTTLS
        if not sent:
            try:
                with smtplib.SMTP(smtp_host, 587, timeout=12) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                logger.info(f"[SMTP SUCCESS] Real email delivered to {target} via STARTTLS port 587")
                sent = True
            except Exception as e2:
                smtp_errors.append(f"Port 587 STARTTLS: {e2}")
                logger.error(f"[SMTP ERROR] Failed to deliver real email to {target}: {e2}")

        if sent:
            success_any = True
            _last_smtp_error = ""
        else:
            _last_smtp_error = " | ".join(smtp_errors)

    return success_any


def send_test_email(recipient: Optional[str] = None) -> Dict[str, Any]:
    """
    Sends a test verification email via SMTP to verify configuration and delivery.
    """
    smtp_user = os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME")
    target = recipient or smtp_user or "dlogidth4@gmail.com"
    subject = "🧪 [CampusResolve TEST] SMTP Dispatch Verification"
    timestamp_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    plain_body = f"""
CampusResolve System Test
Timestamp: {timestamp_str}
Target Recipient: {target}
SMTP Configured: True
Base URL: {BASE_URL}

This confirms that your SMTP email engine is fully functional and successfully delivering outbound alerts from CampusResolve.
"""
    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; background: #f8fafc; padding: 20px;">
  <div style="max-width: 500px; margin: 0 auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 24px;">
    <h2 style="color: #2563eb; margin-top: 0;">🧪 CampusResolve SMTP Verification</h2>
    <p>This email verifies that automated outbound notifications are operating correctly from the live portal.</p>
    <ul>
      <li><strong>Delivered To:</strong> {target}</li>
      <li><strong>Timestamp:</strong> {timestamp_str}</li>
      <li><strong>Portal URL:</strong> <a href="{BASE_URL}/app/dashboard.html">{BASE_URL}/app/dashboard.html</a></li>
    </ul>
    <div style="padding: 10px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 4px; color: #047857; font-size: 13px;">
      ✅ SMTP Handshake and Delivery Verified
    </div>
  </div>
</body>
</html>
"""
    success = _dispatch_smtp(target, subject, plain_body, html_body, also_notify_admin=False)
    err = get_last_smtp_error()
    return {
        "success": success,
        "recipient": target,
        "timestamp": timestamp_str,
        "message": f"Test email delivered successfully to {target}" if success else f"Delivery failed: {err}",
        "error": err if not success else None
    }


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


def send_complaint_resolved_email(
    complaint_id: int,
    complaint_text: str,
    category: str,
    assigned_authority: str,
    remarks: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constructs and dispatches an official resolution notification email upon complaint resolution.
    """
    recipient_email = get_authority_email(assigned_authority)
    recipient_info = AUTHORITY_DIRECTORY.get(assigned_authority, {})
    recipient_name = recipient_info.get("name", assigned_authority)

    subject = f"✅ [GRIEVANCE RESOLVED] Complaint #{complaint_id}: {category.upper()} resolved by {assigned_authority}"
    timestamp_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    student_track_link = f"{BASE_URL}/app/index.html?track={complaint_id}"
    remarks_text = remarks.strip() if remarks else "Resolution actions verified and completed by authority."

    plain_body = f"""
OFFICIAL RESOLUTION NOTICE — CampusResolve Automated Triage Engine
Complaint #{complaint_id} has been formally MARKED AS RESOLVED.

==================================================
RESOLUTION DETAILS
==================================================
Complaint ID: #{complaint_id}
Category: {category.upper()}
Resolving Authority: {assigned_authority} ({recipient_email})
Resolved At: {timestamp_str}
Official Remarks / Action Taken:
"{remarks_text}"

Original Grievance:
"{complaint_text}"

Tracking Link:
{student_track_link}
==================================================
"""

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #0f172a; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
    .header {{ background: #16a34a; color: #ffffff; padding: 18px 24px; }}
    .header h1 {{ margin: 0; font-size: 18px; font-weight: 700; }}
    .content {{ padding: 24px; }}
    .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
    .meta-table td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; font-size: 14px; }}
    .meta-table td.label {{ color: #64748b; font-weight: 600; width: 38%; }}
    .meta-table td.val {{ color: #0f172a; font-weight: 600; }}
    .remarks-box {{ background: #f0fdf4; border-left: 4px solid #16a34a; padding: 14px; margin: 16px 0; border-radius: 4px; font-size: 14px; color: #166534; }}
    .footer {{ background: #f8fafc; padding: 14px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>✅ Grievance Resolved</h1>
    </div>
    <div class="content">
      <p style="margin-top: 0; font-size: 14px; color: #475569;">
        Complaint <strong>#{complaint_id}</strong> has been inspected and formally closed.
      </p>
      <table class="meta-table">
        <tr><td class="label">Complaint ID:</td><td class="val">#{complaint_id}</td></tr>
        <tr><td class="label">Category:</td><td class="val">{category.upper()}</td></tr>
        <tr><td class="label">Resolved By:</td><td class="val">{assigned_authority}</td></tr>
        <tr><td class="label">Resolved On:</td><td class="val">{timestamp_str}</td></tr>
      </table>
      <div style="font-weight: 600; font-size: 13px; color: #64748b; text-transform: uppercase;">Official Remarks:</div>
      <div class="remarks-box">"{remarks_text}"</div>
    </div>
    <div class="footer">CampusResolve Autonomous Resolution Engine &copy; 2026</div>
  </div>
</body>
</html>
"""

    email_record = {
        "id": len(_sent_emails) + 1,
        "complaint_id": complaint_id,
        "recipient_name": recipient_name,
        "recipient_authority": assigned_authority,
        "recipient_email": recipient_email,
        "sender": "CampusResolve Alerts <alerts@campusresolve.edu>",
        "subject": subject,
        "body": plain_body.strip(),
        "html_body": html_body.strip(),
        "portal_link": f"{BASE_URL}/app/dashboard.html?complaint_id={complaint_id}",
        "track_link": student_track_link,
        "category": category,
        "type": "resolved",
        "timestamp": datetime.utcnow().isoformat()
    }
    _sent_emails.insert(0, email_record)
    logger.info(f"[EMAIL DISPATCH] Sent resolution notice to {assigned_authority} <{recipient_email}> for Complaint #{complaint_id}")
    _dispatch_smtp(recipient_email, subject, plain_body, html_body)
    return email_record


def send_authority_dispute_email_to_principal(
    complaint_id: int,
    ticket_id: Optional[str],
    complaint_text: str,
    reported_authority: str,
    dispute_reason: str,
    student_description: str,
    student_email: Optional[str] = None
) -> bool:
    """
    Directly dispatches an urgent grievance appeal/dispute email to the Principal (717824v132@kce.ac.in).
    Triggered when a student reports that an authority has failed to resolve an issue or falsely marked it resolved.
    """
    recipient_email = os.getenv("EMAIL_PRINCIPAL", "717824v132@kce.ac.in")
    principal_info = AUTHORITY_DIRECTORY.get("Principal", {})
    principal_name = principal_info.get("name", "Office of the Principal / Director")

    ticket_label = ticket_id or f"#{complaint_id}"
    subject = f"🚨 [STUDENT APPEAL TO PRINCIPAL] Dispute on {reported_authority}: Ticket {ticket_label} ({dispute_reason})"

    timestamp_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    authority_portal_link = f"{BASE_URL}/app/dashboard.html?complaint_id={complaint_id}"

    plain_body = f"""
URGENT: {principal_name}
Official Student Appeal — Misconduct / Resolution Dispute Notification

A student has submitted an official complaint and escalation to the Office of the Principal regarding {reported_authority}'s handling of their grievance.

==================================================
DISPUTE / APPEAL DETAILS
==================================================
Ticket Reference: {ticket_label} (Complaint #{complaint_id})
Reported Authority: {reported_authority}
Dispute Type: {dispute_reason}
Submitted On: {timestamp_str}

Student Statement / Evidence:
"{student_description}"

Original Grievance Text:
"{complaint_text}"

==================================================
DIRECT EXECUTIVE ACTION REQUIRED
==================================================
Please open the CampusResolve Authority Portal immediately to review the audit trail, examine the reported authority's resolution remarks, and take executive action:

👉 Review in Authority Portal:
{authority_portal_link}

==================================================
CampusResolve Institutional Oversight Engine
"""

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #0f172a; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ background: #991b1b; color: #ffffff; padding: 20px 24px; }}
    .header h1 {{ margin: 0; font-size: 18px; font-weight: 700; }}
    .content {{ padding: 24px; }}
    .alert-banner {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px; color: #991b1b; font-size: 14px; font-weight: 500; }}
    .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
    .meta-table td {{ padding: 8px 10px; border-bottom: 1px solid #f1f5f9; font-size: 14px; }}
    .meta-table td.label {{ color: #64748b; font-weight: 600; width: 40%; }}
    .meta-table td.val {{ color: #0f172a; font-weight: 600; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }}
    .badge-urgent {{ background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }}
    .statement-box {{ background: #fff1f2; border-left: 4px solid #e11d48; padding: 14px; margin: 16px 0; border-radius: 4px; font-size: 14px; line-height: 1.5; color: #881337; }}
    .original-box {{ background: #f8fafc; border-left: 4px solid #64748b; padding: 14px; margin: 16px 0; border-radius: 4px; font-size: 13px; line-height: 1.5; color: #334155; }}
    .btn-container {{ text-align: center; margin: 25px 0 15px 0; }}
    .btn {{ display: inline-block; background: #991b1b; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 14px; box-shadow: 0 2px 4px rgba(153,27,27,0.2); }}
    .btn:hover {{ background: #7f1d1d; }}
    .footer {{ background: #f8fafc; padding: 14px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🚨 Student Escalation & Appeal to Principal</h1>
    </div>
    <div class="content">
      <div class="alert-banner">
        <strong>Attention Office of the Principal:</strong> A student has lodged an official dispute regarding an authority failing to resolve or falsely marking their grievance as resolved.
      </div>

      <table class="meta-table">
        <tr>
          <td class="label">Ticket Reference</td>
          <td class="val"><strong>{ticket_label}</strong> (Complaint #{complaint_id})</td>
        </tr>
        <tr>
          <td class="label">Reported Authority</td>
          <td class="val"><span style="color: #b91c1c; font-weight: 700;">{reported_authority}</span></td>
        </tr>
        <tr>
          <td class="label">Dispute Reason</td>
          <td class="val"><span class="badge badge-urgent">{dispute_reason}</span></td>
        </tr>
        <tr>
          <td class="label">Dispatched On</td>
          <td class="val">{timestamp_str}</td>
        </tr>
      </table>

      <div style="font-weight: 700; color: #0f172a; margin-top: 16px; font-size: 14px;">
        📝 Student's Dispute Description / Evidence:
      </div>
      <div class="statement-box">
        "{student_description}"
      </div>

      <div style="font-weight: 600; color: #64748b; margin-top: 12px; font-size: 13px;">
        Original Student Grievance:
      </div>
      <div class="original-box">
        "{complaint_text}"
      </div>

      <div class="btn-container">
        <a href="{authority_portal_link}" class="btn">
          🔍 Inspect Ticket & Intervene as Principal &rarr;
        </a>
      </div>
    </div>
    <div class="footer">
      CampusResolve Autonomous Grievance Engine &middot; Executive Institutional Oversight
    </div>
  </div>
</body>
</html>
"""

    # Record in local sent email registry
    _sent_emails.insert(0, {
        "id": len(_sent_emails) + 1,
        "complaint_id": complaint_id,
        "type": "AUTHORITY_DISPUTE_APPEAL",
        "recipient_name": principal_name,
        "recipient_authority": "Principal",
        "recipient_email": recipient_email,
        "subject": subject,
        "body": plain_body.strip(),
        "html_body": html_body.strip(),
        "portal_link": authority_portal_link,
        "category": "appeal",
        "timestamp": datetime.utcnow().isoformat()
    })

    logger.info(
        f"[APPEAL DISPATCH] Sent to Principal <{recipient_email}>: Complaint #{complaint_id} ({ticket_label}) "
        f"dispute on '{reported_authority}' ({dispute_reason})"
    )

    return _dispatch_smtp(recipient_email, subject, plain_body, html_body)


def get_sent_emails(authority: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve sent email logs with optional authority filtering."""
    if authority and authority != "All":
        return [e for e in _sent_emails if e["recipient_authority"] == authority]
    return _sent_emails


def clear_sent_emails():
    """Clear sent email logs (for testing)."""
    global _sent_emails
    _sent_emails.clear()
