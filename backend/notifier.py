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


_last_smtp_error = ""

def get_last_smtp_error() -> str:
    global _last_smtp_error
    return _last_smtp_error

def _dispatch_smtp(recipient_email: str, subject: str, plain_body: str, html_body: str, also_notify_admin: bool = True) -> bool:
    """Helper to dispatch real SMTP emails with STARTTLS (port 587) and SSL (port 465) fallback."""
    global _last_smtp_error
    _last_smtp_error = ""

    smtp_host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    smtp_port = int((os.getenv("SMTP_PORT") or "465").strip())
    smtp_user = (os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME") or "").strip()
    smtp_pass = (os.getenv("SMTP_PASSWORD") or "").strip().replace(" ", "")
    smtp_from = (os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_FROM") or smtp_user or "alerts@campusresolve.edu").strip()

    resend_api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    brevo_api_key = (os.getenv("BREVO_API_KEY") or "").strip()

    # Collect recipient list: primary authority plus admin/tester copy if different
    targets = [recipient_email]
    if also_notify_admin and smtp_user and smtp_user.lower() != recipient_email.lower():
        targets.append(smtp_user)

    # PATH A: Resend HTTPS REST API (Port 443 - 100% permitted on Render & cloud hosts)
    if resend_api_key:
        resend_from = (os.getenv("RESEND_FROM") or "CampusResolve <onboarding@resend.dev>").strip()
        success_any = False
        for target in targets:
            try:
                payload = json.dumps({
                    "from": resend_from,
                    "to": [target],
                    "subject": subject,
                    "html": html_body,
                    "text": plain_body
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.resend.com/emails",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json"
                    }
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"[RESEND HTTPS SUCCESS] Real email delivered to {target} via Resend API (port 443)")
                        success_any = True
            except Exception as ex:
                logger.error(f"[RESEND ERROR] Failed to send to {target}: {ex}")
                _last_smtp_error = f"Resend API error: {ex}"
        if success_any:
            return True

    # PATH B: Brevo HTTPS REST API (Port 443)
    if brevo_api_key:
        success_any = False
        for target in targets:
            try:
                payload = json.dumps({
                    "sender": {"name": "CampusResolve", "email": smtp_from or "alerts@campusresolve.edu"},
                    "to": [{"email": target}],
                    "subject": subject,
                    "htmlContent": html_body,
                    "textContent": plain_body
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.brevo.com/v3/smtp/email",
                    data=payload,
                    headers={
                        "api-key": brevo_api_key,
                        "Content-Type": "application/json"
                    }
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"[BREVO HTTPS SUCCESS] Real email delivered to {target} via Brevo API (port 443)")
                        success_any = True
            except Exception as ex:
                logger.error(f"[BREVO ERROR] Failed to send to {target}: {ex}")
                _last_smtp_error = f"Brevo API error: {ex}"
        if success_any:
            return True

    # PATH C: Standard SMTP (port 465 SSL / 587 STARTTLS)
    if not smtp_user or not smtp_pass:
        _last_smtp_error = "Neither RESEND_API_KEY, BREVO_API_KEY, nor SMTP_USER/SMTP_PASSWORD are configured in environment variables."
        logger.warning(
            f"[EMAIL WARNING] Real email to {recipient_email} skipped: {_last_smtp_error}"
        )
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
        e1_err = ""
        # Attempt 1: Port 465 with SSL (direct SMTPS - standard & reliable for cloud hosts)
        try:
            with smtplib.SMTP_SSL(smtp_host, 465, timeout=12) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info(f"[SMTP SUCCESS] Real email delivered to {target} via SSL port 465")
            sent = True
        except Exception as e1:
            e1_err = str(e1)
            logger.warning(f"[SMTP RETRY] SSL port 465 attempt failed for {target} ({e1}). Attempting port 587 STARTTLS fallback...")

        # Attempt 2: Fallback to port 587 with STARTTLS
        if not sent:
            try:
                with smtplib.SMTP(smtp_host, 587, timeout=12) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                logger.info(f"[SMTP SUCCESS] Real email delivered to {target} via port 587")
                sent = True
            except Exception as e2:
                logger.error(f"[SMTP ERROR] Failed to deliver real email to {target}: {e2}")
                _last_smtp_error = f"Port 465: {e1_err} | Port 587: {e2}"
                if "Network is unreachable" in _last_smtp_error:
                    _last_smtp_error += " | Note: Render Free Tier blocks outbound SMTP (ports 465/587). Add RESEND_API_KEY in Render Environment Variables for HTTPS delivery on port 443, or test locally."

        if sent:
            success_any = True

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


def get_sent_emails(authority: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve sent email logs with optional authority filtering."""
    if authority and authority != "All":
        return [e for e in _sent_emails if e["recipient_authority"] == authority]
    return _sent_emails


def clear_sent_emails():
    """Clear sent email logs (for testing)."""
    global _sent_emails
    _sent_emails.clear()
