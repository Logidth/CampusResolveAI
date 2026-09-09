// Dynamically detect API and WebSocket endpoints for production, local, and custom deployments
function getApiBase() {
  if (typeof window !== "undefined" && window.location) {
    // 0. Config file override (frontend/config.js)
    if (window.CAMPUSRESOLVE_API_URL && typeof window.CAMPUSRESOLVE_API_URL === "string" && window.CAMPUSRESOLVE_API_URL.trim()) {
      return window.CAMPUSRESOLVE_API_URL.trim().replace(/\/+$/, "");
    }

    // 1. URL Query Parameter override: ?api=https://my-backend.onrender.com
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const apiParam = urlParams.get("api") || urlParams.get("backend");
      if (apiParam) {
        const cleanApi = apiParam.replace(/\/+$/, "");
        localStorage.setItem("cr_api_base", cleanApi);
        return cleanApi;
      }
    } catch (e) {}

    // 2. LocalStorage override
    const storedApi = localStorage.getItem("cr_api_base");
    if (storedApi) {
      return storedApi;
    }

    // 3. If opened via file:// or separate dev servers (Live Server 5500, Vite 5173, etc.)
    if (window.location.protocol === "file:" || ["5500", "3000", "5173", "8080"].includes(window.location.port)) {
      return "http://127.0.0.1:8000";
    }

    // 4. Default: Current origin (production deployment or FastAPI on port 8000)
    return window.location.origin;
  }
  return "http://127.0.0.1:8000";
}

function getWsBase(apiBase) {
  try {
    const url = new URL(apiBase);
    const wsProto = url.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${url.host}`;
  } catch (e) {
    return "ws://127.0.0.1:8000";
  }
}

const API_BASE = getApiBase();
const WS_BASE = getWsBase(API_BASE);

// ==========================================
// 0. AUTHENTICATION & SESSION MANAGEMENT
// ==========================================

function getAuthToken() {
  return localStorage.getItem("cr_auth_token");
}

function getAuthUser() {
  try {
    const raw = localStorage.getItem("cr_auth_user");
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function setAuthSession(token, user) {
  localStorage.setItem("cr_auth_token", token);
  localStorage.setItem("cr_auth_user", JSON.stringify(user));
}

function clearAuthSession() {
  localStorage.removeItem("cr_auth_token");
  localStorage.removeItem("cr_auth_user");
}

async function handleGlobalLogout() {
  const token = getAuthToken();
  if (token) {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
    } catch (e) {
      // Ignore network errors on logout
    }
  }
  clearAuthSession();
  window.location.href = "dashboard.html";
}

// Student Portal Authentication & Session Helpers
function getStudentToken() {
  return localStorage.getItem("cr_student_token");
}

function getStudentUser() {
  try {
    const raw = localStorage.getItem("cr_student_user");
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function setStudentSession(token, user) {
  localStorage.setItem("cr_student_token", token);
  localStorage.setItem("cr_student_user", JSON.stringify(user));
}

function clearStudentSession() {
  localStorage.removeItem("cr_student_token");
  localStorage.removeItem("cr_student_user");
}

function handleStudentLogout() {
  clearStudentSession();
  window.location.reload();
}

function focusStudentAuth() {
  const card = document.getElementById("studentAuthCard");
  const emailInput = document.getElementById("stdLoginEmail");
  if (card) {
    card.scrollIntoView({ behavior: "smooth" });
    if (emailInput) emailInput.focus();
  }
}

// Helpers: Status & Badge Generators
function getStatusBadge(status) {
  const s = status ? status.toLowerCase() : "open";
  return `<span class="badge badge-${s}">${status || "open"}</span>`;
}

function getUrgencyBadge(urgency) {
  const u = urgency ? urgency.toLowerCase() : "medium";
  return `<span class="badge badge-${u}">${urgency || "medium"}</span>`;
}

function getEscalationBadge(level) {
  const lvl = level || 0;
  const cls = lvl === 0 ? "badge-esc-0" : (lvl === 1 ? "badge-esc-1" : "badge-esc-2");
  return `<span class="badge ${cls}">Level ${lvl}</span>`;
}

function formatDate(dateStr) {
  if (!dateStr) return "N/A";
  const d = new Date(dateStr);
  return d.toLocaleString([], { 
    month: "short", 
    day: "numeric", 
    hour: "2-digit", 
    minute: "2-digit" 
  });
}

function formatTerminalTimestamp(dateStr) {
  const d = dateStr ? new Date(dateStr) : new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}


// ==========================================
// 1. PAGE 1: STUDENT PORTAL (index.html)
// ==========================================

const complaintForm = document.getElementById("complaintForm");
const confirmationBox = document.getElementById("confirmationBox");
const trackComplaintLink = document.getElementById("trackComplaintLink");
const trackForm = document.getElementById("trackForm");
const trackIdInput = document.getElementById("trackIdInput");
const trackResultBox = document.getElementById("trackResultBox");
const studentLoginForm = document.getElementById("studentLoginForm");

let cachedStudentComplaints = [];

// Tab Switcher for Student Portal
window.switchStudentTab = function (tabName) {
  const tabs = {
    submit: { btn: "tabBtnSubmit", content: "tabContentSubmit" },
    history: { btn: "tabBtnHistory", content: "tabContentHistory" },
    search: { btn: "tabBtnSearch", content: "tabContentSearch" },
    dispute: { btn: "tabBtnDispute", content: "tabContentDispute" },
  };

  Object.keys(tabs).forEach((key) => {
    const b = document.getElementById(tabs[key].btn);
    const c = document.getElementById(tabs[key].content);
    if (b) b.classList.remove("active");
    if (c) c.style.display = "none";
  });

  const selected = tabs[tabName];
  if (selected) {
    const b = document.getElementById(selected.btn);
    const c = document.getElementById(selected.content);
    if (b) b.classList.add("active");
    if (c) c.style.display = "block";
    if (tabName === "history") {
      loadStudentHistory();
    } else if (tabName === "dispute") {
      populateTabDisputeTickets();
    }
  }
};

window.refreshStudentHistory = function () {
  loadStudentHistory();
};

window.viewStudentComplaintDetails = function (id) {
  switchStudentTab("search");
  if (trackIdInput) {
    trackIdInput.value = id;
    loadComplaintDetails(id);
    document.getElementById("trackingSection")?.scrollIntoView({ behavior: "smooth" });
  }
};

// Fetch student grievances history from backend
async function loadStudentHistory() {
  const user = getStudentUser();
  const token = getStudentToken();
  if (!user || !user.email) return;

  const tableBody = document.getElementById("studentHistoryTableBody");
  if (tableBody) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">
          Refreshing grievance history...
        </td>
      </tr>
    `;
  }

  try {
    const res = await fetch(`${API_BASE}/student/complaints?email=${encodeURIComponent(user.email)}`, {
      headers: token ? { "Authorization": `Bearer ${token}` } : {}
    });
    if (!res.ok) throw new Error("Unable to fetch grievance history.");
    const data = await res.json();
    cachedStudentComplaints = data.complaints || [];

    // Update Metric Counters
    if (document.getElementById("stdStatTotal")) document.getElementById("stdStatTotal").innerText = data.total || 0;
    if (document.getElementById("stdStatOpen")) document.getElementById("stdStatOpen").innerText = data.open_count || 0;
    if (document.getElementById("stdStatEscalated")) document.getElementById("stdStatEscalated").innerText = data.escalated_count || 0;
    if (document.getElementById("stdStatResolved")) document.getElementById("stdStatResolved").innerText = data.resolved_count || 0;
    if (document.getElementById("historyBadgeCount")) document.getElementById("historyBadgeCount").innerText = data.total || 0;

    renderStudentHistoryTable();
  } catch (err) {
    if (tableBody) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="9" style="text-align: center; color: var(--danger); padding: 2rem;">
            Error loading grievances: ${err.message}
          </td>
        </tr>
      `;
    }
  }
}

// Render the interactive history table
window.renderStudentHistoryTable = function () {
  const tableBody = document.getElementById("studentHistoryTableBody");
  if (!tableBody) return;

  const showOnlyOpen = document.getElementById("stdShowOnlyOpenCheckbox")?.checked;
  let list = cachedStudentComplaints;
  if (showOnlyOpen) {
    list = list.filter((c) => c.status === "open");
  }

  if (list.length === 0) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2.5rem 1rem;">
          <div style="font-size: 2rem; margin-bottom: 0.5rem;">📭</div>
          <p style="font-weight: 600; color: var(--text-main);">No grievances found</p>
          <p style="font-size: 0.85rem; margin-top: 0.25rem;">
            ${cachedStudentComplaints.length === 0 ? "You have not lodged any grievances yet." : "No open grievances match your filter."}
          </p>
          <button onclick="switchStudentTab('submit')" class="btn btn-sm btn-primary" style="margin-top: 0.75rem;">
             Lodge a new grievance &rarr;
          </button>
        </td>
      </tr>
    `;
    return;
  }

  tableBody.innerHTML = list.map((c) => {
    const isResolved = c.status === "resolved";
    const escLevel = c.escalation_level || 0;
    let escBadge = `<span class="badge" style="background: #f1f5f9; color: #64748b;">Normal (L0)</span>`;
    if (escLevel === 1) {
      escBadge = `<span class="badge" style="background: #fffbeb; color: #b45309; border: 1px solid #fde68a;">⚡ Level 1 (Dean/VP)</span>`;
    } else if (escLevel >= 2) {
      escBadge = `<span class="badge" style="background: #fef2f2; color: #b91c1c; border: 1px solid #fca5a5;">⚡ Level 2 (Principal)</span>`;
    }

    return `
      <tr>
        <td style="font-family: var(--font-mono); font-weight: 700; color: var(--primary);">
          ${c.ticket_id || ('#' + c.id)}
        </td>
        <td style="max-width: 250px; font-size: 0.88rem;">
          <div style="font-weight: 500; color: var(--text-main); margin-bottom: 0.25rem;">
            ${c.text.length > 80 ? c.text.substring(0, 80) + '...' : c.text}
          </div>
          ${c.resolution_remarks ? `
            <div class="resolution-box">
              <strong>Official Resolution Remarks:</strong><br/>
              ${c.resolution_remarks}
            </div>
          ` : ''}
          ${c.photo_url ? `
            <div style="margin-top: 0.35rem;">
              <button type="button" onclick="openPhotoModal('${c.photo_url}')" class="btn btn-sm" style="padding: 2px 7px; font-size: 0.72rem; background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 4px; display: inline-flex; align-items: center; gap: 4px; cursor: pointer;">
                📷 View Attached Photo
              </button>
            </div>
          ` : ''}
        </td>
        <td><span style="font-weight: 500;">${(c.category || 'General').toUpperCase()}</span></td>
        <td>${getUrgencyBadge(c.urgency)}</td>
        <td>
          <span style="font-weight: 600; color: var(--text-main);">${c.assigned_authority || 'Pending'}</span>
          ${c.initial_authority && c.initial_authority !== c.assigned_authority ? `
            <div style="font-size: 0.72rem; color: var(--danger); font-weight: 600;">Escalated from ${c.initial_authority}</div>
          ` : ''}
        </td>
        <td>${escBadge}</td>
        <td>${getStatusBadge(c.status)}</td>
        <td style="font-size: 0.8rem; color: var(--text-muted);">
          ${isResolved ? (c.resolved_at ? formatDate(c.resolved_at) : 'Resolved') : (c.sla_deadline ? formatDate(c.sla_deadline) : 'Standard SLA')}
        </td>
        <td style="text-align: right; white-space: nowrap;">
          <div style="display: inline-flex; gap: 0.35rem; align-items: center;">
            <button onclick="viewStudentComplaintDetails('${c.ticket_id || c.id}')" class="btn btn-outline btn-sm" title="View live timeline and audit trail">
              🔍 Timeline
            </button>
            <button onclick="openDisputeModal('${c.ticket_id || c.id}', '${(c.assigned_authority || '').replace(/'/g, "\\'")}')" class="btn btn-sm" style="background: #fef2f2; border: 1px solid #fca5a5; color: #b91c1c; font-weight: 600; font-size: 0.78rem; padding: 0.25rem 0.6rem;" title="Report authority or fake resolution to Principal">
              🚨 Report
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
};

// Initialize Student Portal View States
function initStudentPortal() {
  const studentAuthCard = document.getElementById("studentAuthCard");
  const studentAppSection = document.getElementById("studentAppSection");
  const studentUserPill = document.getElementById("studentUserPill");
  const navStudentLoginBtn = document.getElementById("navStudentLoginBtn");

  const studentUser = getStudentUser();
  const studentToken = getStudentToken();

  if (studentUser && studentToken) {
    if (studentAuthCard) studentAuthCard.style.display = "none";
    if (studentAppSection) studentAppSection.style.display = "block";
    if (studentUserPill) studentUserPill.style.display = "inline-flex";
    if (navStudentLoginBtn) navStudentLoginBtn.style.display = "none";

    const navEmail = document.getElementById("navStudentEmail");
    if (navEmail) navEmail.innerText = studentUser.email;

    const welcomeName = document.getElementById("studentDisplayName");
    if (welcomeName) welcomeName.innerText = studentUser.full_name || studentUser.username;

    const welcomeEmail = document.getElementById("studentDisplayEmail");
    if (welcomeEmail) welcomeEmail.innerText = studentUser.email;

    const formBadge = document.getElementById("formStudentBadge");
    if (formBadge) formBadge.innerText = studentUser.email;

    loadStudentHistory();
  } else {
    if (studentAuthCard) studentAuthCard.style.display = "block";
    if (studentAppSection) studentAppSection.style.display = "none";
    if (studentUserPill) studentUserPill.style.display = "none";
    if (navStudentLoginBtn) navStudentLoginBtn.style.display = "inline-flex";
  }
}

// Student Login Form Listener
if (studentLoginForm) {
  studentLoginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const emailInput = document.getElementById("stdLoginEmail");
    const passwordInput = document.getElementById("stdLoginPassword");
    const nameInput = document.getElementById("stdLoginName");
    const errorDiv = document.getElementById("stdLoginError");
    const submitBtn = document.getElementById("btnStudentLoginSubmit");

    const email = emailInput.value.trim().toLowerCase();
    const password = passwordInput.value;
    const fullName = nameInput ? nameInput.value.trim() : "";

    if (errorDiv) errorDiv.style.display = "none";

    // Strict domain check on client
    if (!email.endsWith("@kce.ac.in")) {
      if (errorDiv) {
        errorDiv.innerText = "Access restricted: Only official college institutional email addresses ending with @kce.ac.in are allowed.";
        errorDiv.style.display = "block";
      }
      return;
    }

    submitBtn.disabled = true;
    submitBtn.innerText = "Authenticating...";

    try {
      const res = await fetch(`${API_BASE}/auth/student-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email,
          password: password,
          full_name: fullName || undefined
        })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Authentication failed. Please check credentials.");
      }

      setStudentSession(data.access_token, data.user);
      initStudentPortal();
    } catch (err) {
      if (errorDiv) {
        errorDiv.innerText = err.message;
        errorDiv.style.display = "block";
      }
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerText = "🎓 Sign In / Register with @kce.ac.in";
    }
  });
}

// Student Grievance Submission
if (complaintForm) {
  complaintForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = document.getElementById("submitBtn");
    const complaintText = document.getElementById("complaintText").value.trim();
    if (!complaintText) return;

    const studentUser = getStudentUser();
    const studentToken = getStudentToken();

    submitBtn.disabled = true;
    submitBtn.innerText = "Submitting Grievance...";

    try {
      const payload = {
        text: complaintText,
        student_email: studentUser ? studentUser.email : null,
        student_name: studentUser ? studentUser.full_name : null,
        photo_url: selectedComplaintPhotoBase64 || null,
      };

      const res = await fetch(`${API_BASE}/complaints`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(studentToken ? { "Authorization": `Bearer ${studentToken}` } : {})
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error("Failed to submit grievance. Server error.");
      const data = await res.json();

      // Render Confirmation Details
      const displayTicket = data.ticket_id || ('#' + data.id);
      document.getElementById("resId").innerText = displayTicket;
      document.getElementById("resCategory").innerText = (data.category || "General").toUpperCase();
      document.getElementById("resUrgency").innerHTML = getUrgencyBadge(data.urgency);
      document.getElementById("resAuthority").innerText = data.assigned_authority || "Student Affairs";
      document.getElementById("resStatus").innerHTML = getStatusBadge(data.status);
      document.getElementById("resSla").innerText = formatDate(data.sla_deadline);

      // Show confirmation box
      confirmationBox.classList.add("show");

      // Configure "Track this complaint" link
      if (trackComplaintLink) {
        trackComplaintLink.onclick = (event) => {
          event.preventDefault();
          switchStudentTab("search");
          if (trackIdInput) {
            trackIdInput.value = data.ticket_id || data.id;
            loadComplaintDetails(data.ticket_id || data.id);
            document.getElementById("trackingSection")?.scrollIntoView({ behavior: "smooth" });
          }
        };
      }

      complaintForm.reset();
      if (window.clearComplaintPhoto) window.clearComplaintPhoto();
      // Auto-refresh history so it appears immediately in history tab
      loadStudentHistory();
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerText = "Submit Grievance";
    }
  });

  // Check URL query parameters for deep-linking: index.html?track=123
  const urlParams = new URLSearchParams(window.location.search);
  const trackParam = urlParams.get("track");
  if (trackParam && trackIdInput) {
    switchStudentTab("search");
    trackIdInput.value = trackParam;
    loadComplaintDetails(trackParam);
    document.getElementById("trackingSection")?.scrollIntoView({ behavior: "smooth" });
  }
}

async function loadComplaintDetails(id) {
  if (!id) return;
  const trackBtn = document.getElementById("trackBtn");
  const trackErrorBox = document.getElementById("trackErrorBox");
  const trackErrorMessage = document.getElementById("trackErrorMessage");
  const trackErrorTitle = document.getElementById("trackErrorTitle");

  if (trackBtn) trackBtn.disabled = true;
  if (trackErrorBox) trackErrorBox.style.display = "none";

  try {
    const studentToken = getStudentToken();
    const authToken = getAuthToken();
    const activeToken = studentToken || authToken;

    const res = await fetch(`${API_BASE}/complaints/${encodeURIComponent(id)}`, {
      headers: {
        ...(activeToken ? { "Authorization": `Bearer ${activeToken}` } : {})
      }
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      if (res.status === 403) {
        throw new Error(errData.detail || "Access restricted: You can only inspect grievances filed under your own student account.");
      }
      if (res.status === 401) {
        throw new Error(errData.detail || "Authentication required: Please sign in with your student credentials to view this grievance.");
      }
      if (res.status === 404) {
        throw new Error(errData.detail || `Ticket '${id}' not found. Please verify your ticket ID.`);
      }
      throw new Error(errData.detail || "Unable to fetch complaint details.");
    }
    const data = await res.json();

    if (trackResultBox) {
      const displayHeading = data.ticket_id || `#${data.id}`;
      document.getElementById("trackComplaintHeading").innerText = `Complaint Ticket ${displayHeading}`;
      document.getElementById("trackComplaintText").innerText = `"${data.text}"`;
      document.getElementById("trackStatusBadge").innerHTML = getStatusBadge(data.status);
      document.getElementById("trackCategory").innerText = (data.category || "General").toUpperCase();
      document.getElementById("trackUrgency").innerHTML = getUrgencyBadge(data.urgency);
      document.getElementById("trackAuthority").innerText = data.assigned_authority || "Unassigned";
      document.getElementById("trackEscalation").innerText = `Level ${data.escalation_level}`;
      document.getElementById("trackSla").innerText = formatDate(data.sla_deadline);
      document.getElementById("trackResolvedAt").innerText = data.resolved_at ? formatDate(data.resolved_at) : "Open / In Progress";

      // Display attached photo if present
      const trackPhotoContainer = document.getElementById("trackPhotoContainer");
      const trackPhotoImg = document.getElementById("trackPhotoImg");
      if (trackPhotoContainer && trackPhotoImg) {
        if (data.photo_url) {
          trackPhotoImg.src = data.photo_url;
          trackPhotoContainer.style.display = "block";
        } else {
          trackPhotoContainer.style.display = "none";
          trackPhotoImg.src = "";
        }
      }

      const timelineEl = document.getElementById("trackTimeline");
      timelineEl.innerHTML = "";
      if (data.activity_logs && data.activity_logs.length > 0) {
        data.activity_logs.forEach((log) => {
          const li = document.createElement("li");
          li.className = "timeline-item";
          li.innerHTML = `
            <div><strong>${log.action}</strong> &middot; <span class="time">${formatDate(log.timestamp)}</span></div>
            <div style="color: var(--text-muted); margin-top: 0.15rem;">${log.details || ''}</div>
          `;
          timelineEl.appendChild(li);
        });
      } else {
        timelineEl.innerHTML = `<li class="timeline-item">No activity logs recorded.</li>`;
      }

      currentTrackedTicket = data.ticket_id || data.id;
      currentTrackedAuthority = data.assigned_authority || "Assigned Authority";

      trackResultBox.style.display = "block";
    }
  } catch (err) {
    if (trackResultBox) trackResultBox.style.display = "none";
    if (trackErrorBox && trackErrorMessage) {
      trackErrorMessage.innerText = err.message;
      if (trackErrorTitle) {
        trackErrorTitle.innerText = err.message.includes("restricted") ? "Access Restricted" : "Search Error";
      }
      trackErrorBox.style.display = "block";
    } else {
      alert(err.message);
    }
  } finally {
    if (trackBtn) trackBtn.disabled = false;
  }
}

if (trackForm) {
  trackForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const id = trackIdInput.value.trim();
    if (id) {
      loadComplaintDetails(id);
    }
  });
}

// =======================================================
// DISPUTE & REPORT AUTHORITY TO PRINCIPAL HANDLERS
// =======================================================
let currentTrackedTicket = "";
let currentTrackedAuthority = "";

window.populateTabDisputeTickets = function() {
  const select = document.getElementById("tabDisputeTicketSelect");
  if (!select) return;

  select.innerHTML = '<option value="">-- Choose from your submitted grievances or type ticket ID below --</option>';

  if (cachedStudentComplaints && cachedStudentComplaints.length > 0) {
    cachedStudentComplaints.forEach((c) => {
      const opt = document.createElement("option");
      const ticketRef = c.ticket_id || c.id;
      opt.value = ticketRef;
      opt.setAttribute("data-auth", c.assigned_authority || "Estate Office");
      const statusText = (c.status || "open").toUpperCase();
      const snippet = c.text.length > 50 ? c.text.substring(0, 50) + "..." : c.text;
      opt.innerText = `[${ticketRef}] ${statusText} - ${snippet} (${c.assigned_authority || 'Unassigned'})`;
      select.appendChild(opt);
    });
  }
};

window.handleTabDisputeTicketChange = function(val) {
  const input = document.getElementById("tabDisputeTicketInput");
  const authSelect = document.getElementById("tabDisputeAuthoritySelect");
  const select = document.getElementById("tabDisputeTicketSelect");

  if (input) input.value = val || "";
  if (val && select && authSelect) {
    const opt = select.options[select.selectedIndex];
    const assignedAuth = opt ? opt.getAttribute("data-auth") : "";
    if (assignedAuth) {
      authSelect.value = assignedAuth;
    }
  }
};

window.submitTabDispute = async function(e) {
  e.preventDefault();
  const ticketInput = document.getElementById("tabDisputeTicketInput");
  const authSelect = document.getElementById("tabDisputeAuthoritySelect");
  const reasonSelect = document.getElementById("tabDisputeReasonSelect");
  const descInput = document.getElementById("tabDisputeDescInput");
  const statusAlert = document.getElementById("tabDisputeStatusAlert");
  const submitBtn = document.getElementById("btnTabDisputeSubmit");

  const ticketRef = ticketInput ? ticketInput.value.trim() : "";
  const reportedAuth = authSelect ? authSelect.value : "Warden";
  const reason = reasonSelect ? reasonSelect.value : "Fake Resolution";
  const description = descInput ? descInput.value.trim() : "";

  if (!ticketRef) {
    alert("Please enter or choose a Complaint Ticket ID.");
    if (ticketInput) ticketInput.focus();
    return;
  }
  if (!description) {
    alert("Please explain why you are reporting this authority to the Principal.");
    if (descInput) descInput.focus();
    return;
  }

  const studentUser = getStudentUser();
  const studentToken = getStudentToken() || getAuthToken();

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerText = "🚨 Dispatching Report to Principal (717824v132@kce.ac.in)...";
  }

  if (statusAlert) statusAlert.style.display = "none";

  try {
    const res = await fetch(`${API_BASE}/complaints/${encodeURIComponent(ticketRef)}/dispute`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(studentToken ? { "Authorization": `Bearer ${studentToken}` } : {})
      },
      body: JSON.stringify({
        reason: reason,
        description: description,
        reported_authority: reportedAuth,
        student_email: studentUser ? studentUser.email : undefined
      })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Failed to submit report to Principal.");
    }

    if (statusAlert) {
      statusAlert.style.display = "block";
      statusAlert.style.background = "#f0fdf4";
      statusAlert.style.border = "1px solid #86efac";
      statusAlert.style.color = "#15803d";
      statusAlert.innerHTML = `
        <div style="font-weight: 700; font-size: 1rem; margin-bottom: 0.35rem;">✅ Report Dispatched Directly to Principal!</div>
        <div style="font-size: 0.9rem; line-height: 1.4;">${data.message || 'The complaint has been escalated to Level 2 under the Principal with an urgent executive SLA.'}</div>
      `;
    }

    if (descInput) descInput.value = "";
    loadStudentHistory();
    setTimeout(() => {
      switchStudentTab("history");
    }, 2200);
  } catch (err) {
    if (statusAlert) {
      statusAlert.style.display = "block";
      statusAlert.style.background = "#fef2f2";
      statusAlert.style.border = "1px solid #fca5a5";
      statusAlert.style.color = "#b91c1c";
      statusAlert.innerHTML = `<strong>Submission Error:</strong> ${err.message}`;
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerText = "🚨 Send Official Report to Principal (717824v132@kce.ac.in)";
    }
  }
};

window.openDisputeFromTracker = function() {
  if (currentTrackedTicket) {
    openDisputeModal(currentTrackedTicket, currentTrackedAuthority);
  } else {
    const entered = trackIdInput ? trackIdInput.value.trim() : "";
    openDisputeModal(entered || "", "Assigned Authority");
  }
};

window.openDisputeModal = function(ticketRef, authorityName) {
  const modal = document.getElementById("disputeAuthorityModal");
  if (!modal) return;

  const ticketInput = document.getElementById("disputeTicketId");
  const authSelect = document.getElementById("disputeAuthorityName");
  const descInput = document.getElementById("disputeDescription");
  const statusMsg = document.getElementById("disputeStatusMsg");

  if (statusMsg) statusMsg.style.display = "none";
  if (descInput) descInput.value = "";

  if (ticketInput) ticketInput.value = ticketRef || "";
  if (authSelect && authorityName) {
    for (let i = 0; i < authSelect.options.length; i++) {
      if (authSelect.options[i].value === authorityName || authorityName.includes(authSelect.options[i].value)) {
        authSelect.selectedIndex = i;
        break;
      }
    }
  }

  modal.style.display = "flex";
  if (!ticketRef && ticketInput) {
    setTimeout(() => ticketInput.focus(), 150);
  }
};

window.closeDisputeModal = function() {
  const modal = document.getElementById("disputeAuthorityModal");
  if (modal) modal.style.display = "none";
};

window.submitDisputeAuthority = async function(e) {
  e.preventDefault();
  const ticketInput = document.getElementById("disputeTicketId");
  const authSelect = document.getElementById("disputeAuthorityName");
  const reasonSelect = document.getElementById("disputeReason");
  const descInput = document.getElementById("disputeDescription");
  const statusMsg = document.getElementById("disputeStatusMsg");
  const submitBtn = document.getElementById("disputeSubmitBtn");

  const ticketRef = ticketInput ? ticketInput.value.trim() : "";
  const reportedAuth = authSelect ? authSelect.value : undefined;
  const reason = reasonSelect ? reasonSelect.value : "Fake Resolution";
  const description = descInput ? descInput.value.trim() : "";

  if (!ticketRef) {
    alert("Please enter the Complaint Ticket ID.");
    if (ticketInput) ticketInput.focus();
    return;
  }
  if (!description) {
    alert("Please provide details explaining why you are reporting this authority to the Principal.");
    if (descInput) descInput.focus();
    return;
  }

  const studentUser = getStudentUser();
  const token = getStudentToken() || getAuthToken();

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerText = "Dispatching report to Principal...";
  }

  try {
    const res = await fetch(`${API_BASE}/complaints/${encodeURIComponent(ticketRef)}/dispute`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "Authorization": `Bearer ${token}` } : {})
      },
      body: JSON.stringify({
        reason: reason,
        description: description,
        reported_authority: reportedAuth,
        student_email: studentUser ? studentUser.email : undefined
      })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Failed to submit dispute to Principal.");
    }

    if (statusMsg) {
      statusMsg.style.display = "block";
      statusMsg.style.background = "#f0fdf4";
      statusMsg.style.border = "1px solid #86efac";
      statusMsg.style.color = "#15803d";
      statusMsg.innerHTML = `<strong>Escalation Successful:</strong> ${data.message || "Dispatched directly to Principal (717824v132@kce.ac.in)."}`;
    }

    setTimeout(() => {
      closeDisputeModal();
      loadStudentHistory();
      if (trackIdInput && trackIdInput.value === ticketRef) {
        loadComplaintDetails(ticketRef);
      }
    }, 1800);
  } catch (err) {
    if (statusMsg) {
      statusMsg.style.display = "block";
      statusMsg.style.background = "#fef2f2";
      statusMsg.style.border = "1px solid #fecaca";
      statusMsg.style.color = "#991b1b";
      statusMsg.innerHTML = `<strong>Error:</strong> ${err.message}`;
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerText = "🚨 Send Report to Principal";
    }
  }
};

// Automatically boot student portal states if on index.html
if (document.getElementById("studentAuthCard") || document.getElementById("studentAppSection")) {
  initStudentPortal();
  initComplaintPhotoUpload();
}

// Global Photo Lightbox Modal
window.openPhotoModal = function (url) {
  if (!url) return;
  const modal = document.getElementById("photoLightboxModal");
  const img = document.getElementById("photoLightboxImg");
  if (modal && img) {
    img.src = url;
    modal.style.display = "flex";
  }
};

window.closePhotoModal = function () {
  const modal = document.getElementById("photoLightboxModal");
  const img = document.getElementById("photoLightboxImg");
  if (modal) modal.style.display = "none";
  if (img) img.src = "";
};

// Client-side photo attachment and compression handler
let selectedComplaintPhotoBase64 = null;

function initComplaintPhotoUpload() {
  const dropZone = document.getElementById("photoDropZone");
  const fileInput = document.getElementById("complaintPhotoInput");
  const placeholder = document.getElementById("photoPlaceholder");
  const previewContainer = document.getElementById("photoPreviewContainer");
  const previewImg = document.getElementById("photoPreviewImg");
  const fileNameEl = document.getElementById("photoFileName");
  const removeBtn = document.getElementById("btnRemovePhoto");

  if (!dropZone || !fileInput) return;

  dropZone.addEventListener("click", (e) => {
    if (e.target.id === "btnRemovePhoto" || e.target.closest("#btnRemovePhoto")) return;
    fileInput.click();
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.style.borderColor = "var(--primary)";
    dropZone.style.background = "#eff6ff";
  });

  dropZone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dropZone.style.borderColor = "var(--border-color)";
    dropZone.style.background = "#fafafa";
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.style.borderColor = "var(--border-color)";
    dropZone.style.background = "#fafafa";
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handlePhotoFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      handlePhotoFile(e.target.files[0]);
    }
  });

  if (removeBtn) {
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      window.clearComplaintPhoto();
    });
  }

  function handlePhotoFile(file) {
    if (!file.type.startsWith("image/")) {
      alert("Please upload an image file (PNG, JPG, or WebP).");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      alert("Selected photo is larger than 5MB. Please choose a smaller image.");
      return;
    }

    const reader = new FileReader();
    reader.onload = function (evt) {
      const rawDataUrl = evt.target.result;
      compressImage(rawDataUrl, 1280, 0.85, (compressed) => {
        selectedComplaintPhotoBase64 = compressed;
        if (previewImg) previewImg.src = compressed;
        if (fileNameEl) fileNameEl.innerText = file.name;
        if (placeholder) placeholder.style.display = "none";
        if (previewContainer) previewContainer.style.display = "flex";
      });
    };
    reader.readAsDataURL(file);
  }

  window.clearComplaintPhoto = function () {
    selectedComplaintPhotoBase64 = null;
    if (fileInput) fileInput.value = "";
    if (previewImg) previewImg.src = "";
    if (placeholder) placeholder.style.display = "block";
    if (previewContainer) previewContainer.style.display = "none";
  };
}

function compressImage(src, maxDim, quality, callback) {
  const img = new Image();
  img.onload = function () {
    let width = img.width;
    let height = img.height;
    if (width > maxDim || height > maxDim) {
      if (width > height) {
        height = Math.round((height * maxDim) / width);
        width = maxDim;
      } else {
        width = Math.round((width * maxDim) / height);
        height = maxDim;
      }
    }
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, width, height);
    callback(canvas.toDataURL("image/jpeg", quality));
  };
  img.src = src;
}


// =======================================================
// 2. PAGE 2: UNIFIED AUTHORITY PORTAL (dashboard.html)
// =======================================================

const authLoggedOutView = document.getElementById("authLoggedOutView");
const authLoggedInView = document.getElementById("authLoggedInView");
const authLoginForm = document.getElementById("authLoginForm");
const quickAccountsList = document.getElementById("quickAccountsList");
const loginErrorAlert = document.getElementById("loginErrorAlert");
const loginSubmitBtn = document.getElementById("loginSubmitBtn");

const complaintsTableBody = document.getElementById("complaintsTableBody");
const counselorTableBody = document.getElementById("counselorTableBody");
const terminalBody = document.getElementById("terminalBody");
const authoritySelector = document.getElementById("authoritySelector");
const authorityEmailBadge = document.getElementById("authorityEmailBadge");
const roleLockIndicator = document.getElementById("roleLockIndicator");
const terminalTitleLabel = document.getElementById("terminalTitleLabel");
const tableHeaderTitle = document.getElementById("tableHeaderTitle");
const showOnlyOpenCheckbox = document.getElementById("showOnlyOpen");
const showOnlyEscalatedCheckbox = document.getElementById("showOnlyEscalated");
const statBoxEscalated = document.getElementById("statBoxEscalated");
const counselorCountBadge = document.getElementById("counselorCountBadge");

// User Session Banner Elements
const sessionUserName = document.getElementById("sessionUserName");
const sessionRoleBadge = document.getElementById("sessionRoleBadge");
const sessionTierBadge = document.getElementById("sessionTierBadge");
const sessionEmailText = document.getElementById("sessionEmailText");
const sessionLogoutBtn = document.getElementById("sessionLogoutBtn");
const userAvatarCircle = document.getElementById("userAvatarCircle");

// Tabs
const tabComplaintsBtn = document.getElementById("tabComplaintsBtn");
const tabCounselorBtn = document.getElementById("tabCounselorBtn");
const complaintsTabContent = document.getElementById("complaintsTabContent");
const counselorTabContent = document.getElementById("counselorTabContent");

if (authLoggedOutView && authLoggedInView) {

  const currentUser = getAuthUser();

  // Practical Authority Emails Lookup
  const AUTHORITY_EMAILS = {
    "Warden": "dlogidth4@gmail.com",
    "Mess Committee": "dlogidth5@gmail.com",
    "Exam Cell Admin": "717824v101@kce.ac.in",
    "HOD": "717824v101@kce.ac.in",
    "Estate Office": "717824v134@kce.ac.in",
    "Dean of Student Affairs": "abijithmohanan2006@gmail.com",
    "Dean of Academics": "717824v101@kce.ac.in",
    "Vice Principal": "logidth78@gmail.com",
    "Principal": "717824v132@kce.ac.in",
    "Counseling Cell": "717824v152@kce.ac.in",
    "Admin": "717824v134@kce.ac.in",
    "All": "717824v134@kce.ac.in"
  };

  let currentAuthority = "All";

  // Check Auth State: Logged-in vs Logged-out
  if (!currentUser) {
    // Show Secure Sign-in Form
    authLoggedOutView.style.display = "block";
    authLoggedInView.style.display = "none";
    initSecureLogin();
  } else {
    // Check if user must change password before accessing dashboard
    if (currentUser.must_change_password) {
      authLoggedOutView.style.display = "none";
      authLoggedInView.style.display = "none";
      showFirstLoginModal(getAuthToken(), currentUser);
    } else {
      // Show Full Authenticated Authority Dashboard
      authLoggedOutView.style.display = "none";
      authLoggedInView.style.display = "block";
      initAuthorityDashboard();
    }
  }

  // -------------------------------------------------------------
  // A. Enterprise Secure Sign-in Handler
  // -------------------------------------------------------------
  function initSecureLogin() {
    authLoginForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      const u = document.getElementById("loginUsername").value.trim();
      const p = document.getElementById("loginPassword").value.trim();
      if (u && p) executeLogin(u, p);
    });

    async function executeLogin(username, password) {
      if (loginErrorAlert) loginErrorAlert.style.display = "none";
      if (loginSubmitBtn) {
        loginSubmitBtn.disabled = true;
        loginSubmitBtn.innerText = "Authenticating Authority...";
      }

      try {
        const res = await fetch(`${API_BASE}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Invalid credentials. Please verify your username and password.");

        setAuthSession(data.access_token, data.user);
        
        if (data.user.must_change_password) {
          authLoggedOutView.style.display = "none";
          showFirstLoginModal(data.access_token, data.user);
        } else {
          window.location.reload();
        }
      } catch (err) {
        if (loginErrorAlert) {
          loginErrorAlert.innerText = err.message;
          loginErrorAlert.style.display = "block";
        } else {
          alert(err.message);
        }
      } finally {
        if (loginSubmitBtn) {
          loginSubmitBtn.disabled = false;
          loginSubmitBtn.innerText = "Sign In to Authority Dashboard";
        }
      }
    }
  }

  // First-Login Password Change Modal Controller
  function showFirstLoginModal(token, user) {
    const modal = document.getElementById("firstLoginModal");
    if (!modal) return;
    modal.style.display = "flex";

    const form = document.getElementById("firstLoginForm");
    const errBox = document.getElementById("firstLoginErrorAlert");
    const submitBtn = document.getElementById("firstLoginSubmitBtn");

    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (errBox) errBox.style.display = "none";

      const p1 = document.getElementById("firstLoginNewPass").value.trim();
      const p2 = document.getElementById("firstLoginConfirmPass").value.trim();

      if (p1.length < 4) {
        if (errBox) {
          errBox.innerText = "Password must be at least 4 characters long.";
          errBox.style.display = "block";
        }
        return;
      }
      if (p1 !== p2) {
        if (errBox) {
          errBox.innerText = "New passwords do not match. Please re-enter.";
          errBox.style.display = "block";
        }
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerText = "Saving New Password...";
      }

      try {
        const res = await fetch(`${API_BASE}/auth/change-password`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token || getAuthToken()}`
          },
          body: JSON.stringify({ new_password: p1, confirm_password: p2 })
        });
        const resData = await res.json();
        if (!res.ok) throw new Error(resData.detail || "Failed to update password.");

        alert("✅ Password established successfully! Welcome to your authority dashboard.");
        const updatedUser = resData.user || { ...user, must_change_password: false };
        updatedUser.must_change_password = false;
        setAuthSession(token || getAuthToken(), updatedUser);
        modal.style.display = "none";
        window.location.reload();
      } catch (err) {
        if (errBox) {
          errBox.innerText = err.message;
          errBox.style.display = "block";
        } else {
          alert(err.message);
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerText = "Save Password & Continue";
        }
      }
    });
  }

  // -------------------------------------------------------------
  // B. Authenticated Authority Dashboard Initializer
  // -------------------------------------------------------------
  function initAuthorityDashboard() {
    // Populate Session Banner
    if (sessionUserName) sessionUserName.innerText = currentUser.full_name || currentUser.username;
    if (sessionRoleBadge) sessionRoleBadge.innerText = currentUser.role;
    if (sessionTierBadge) sessionTierBadge.innerText = currentUser.tier || "Authority Tier";
    if (sessionEmailText) sessionEmailText.innerText = currentUser.email || AUTHORITY_EMAILS[currentUser.role] || "";
    if (userAvatarCircle) {
      const initials = (currentUser.full_name || currentUser.username)
        .split(" ")
        .map(n => n[0])
        .join("")
        .substring(0, 2)
        .toUpperCase();
      userAvatarCircle.innerText = initials || "AU";
    }

    if (sessionLogoutBtn) {
      sessionLogoutBtn.onclick = handleGlobalLogout;
    }

    // Role-based isolation & tab configuration
    if (currentUser.role === "Counseling Cell") {
      currentAuthority = "Counseling Cell";
      if (authoritySelector) {
        authoritySelector.value = "Counseling Cell";
        authoritySelector.disabled = true;
      }
      if (roleLockIndicator) {
        roleLockIndicator.style.display = "inline-block";
        roleLockIndicator.innerText = "🔒 Locked: Counseling Cell";
      }
      if (tabCounselorBtn) {
        tabCounselorBtn.style.display = "inline-block";
        switchTab("counselor");
      }
    } else if (currentUser.role === "Admin") {
      currentAuthority = "All";
      if (tabCounselorBtn) tabCounselorBtn.style.display = "inline-block";
      const adminBtn = document.getElementById("adminPortalBtn");
      if (adminBtn) adminBtn.style.display = "inline-block";
    } else if (currentUser.assigned_authority) {
      currentAuthority = currentUser.assigned_authority;
      if (authoritySelector) {
        authoritySelector.value = currentAuthority;
        authoritySelector.disabled = true; // Lock authority dropdown
      }
      if (roleLockIndicator) {
        roleLockIndicator.style.display = "inline-block";
        roleLockIndicator.innerText = `🔒 Locked: ${currentUser.role}`;
      }
    }

    function updateAuthorityHeaders() {
      if (authorityEmailBadge) {
        authorityEmailBadge.innerText = AUTHORITY_EMAILS[currentAuthority] || currentUser.email || "authority@campus.edu";
      }
      if (terminalTitleLabel) {
        terminalTitleLabel.innerText = `● /ws/activity ~ real-time monitoring stream (${currentAuthority})`;
      }
      if (tableHeaderTitle) {
        tableHeaderTitle.innerText = currentAuthority === "All" ? "Complaints Queue (Central Admin View)" : `${currentAuthority} — Assigned Queue`;
      }
    }

    updateAuthorityHeaders();

    // Tab Event Listeners
    tabComplaintsBtn?.addEventListener("click", () => switchTab("complaints"));
    tabCounselorBtn?.addEventListener("click", () => {
      switchTab("counselor");
      loadCounselorComplaints();
    });

    function switchTab(tabName) {
      tabComplaintsBtn.className = tabName === "complaints" ? "btn btn-sm btn-primary" : "btn btn-sm btn-outline";
      if (tabCounselorBtn) tabCounselorBtn.className = tabName === "counselor" ? "btn btn-sm btn-primary" : "btn btn-sm btn-outline";

      complaintsTabContent.style.display = tabName === "complaints" ? "block" : "none";
      if (counselorTabContent) counselorTabContent.style.display = tabName === "counselor" ? "block" : "none";
    }

    authoritySelector?.addEventListener("change", (e) => {
      currentAuthority = e.target.value;
      updateAuthorityHeaders();
      loadDashboardComplaints();
      loadInitialTerminalLogs();
    });

    // Check Deep Linking: dashboard.html?complaint_id=123
    const urlParams = new URLSearchParams(window.location.search);
    const deepComplaintId = urlParams.get("complaint_id");
    if (deepComplaintId) {
      switchTab("complaints");
    }

    loadDashboardComplaints();
    loadInitialTerminalLogs();
    if (currentUser.role === "Counseling Cell" || currentUser.role === "Admin") {
      loadCounselorComplaints();
    }
    initTerminalWebSocket();
    setInterval(loadDashboardComplaints, 5000);
  }

  // -------------------------------------------------------------
  // C. Terminal & Complaints Rendering
  // -------------------------------------------------------------
  function createTerminalLogElement(item) {
    const actionStr = (item.action || "").toUpperCase();
    
    let tagClass = "term-tag-classified";
    let tagLabel = "CLASSIFIED";

    if (actionStr.includes("ESCALAT")) {
      tagClass = "term-tag-escalated";
      tagLabel = "ESCALATED";
    } else if (actionStr.includes("RESOLV")) {
      tagClass = "term-tag-resolved";
      tagLabel = "RESOLVED";
    } else if (actionStr.includes("CLASS") || actionStr.includes("CREATE")) {
      tagClass = "term-tag-classified";
      tagLabel = "CLASSIFIED";
    } else {
      tagClass = "term-tag-classified";
      tagLabel = actionStr || "INFO";
    }

    const timeStr = formatTerminalTimestamp(item.timestamp);
    const complaintRef = item.complaint_id ? `#TICKET-${item.complaint_id}` : "#SYS";
    const details = item.details || "";
    const textSnippet = item.complaint_text ? ` [text: "${item.complaint_text}"]` : "";

    const div = document.createElement("div");
    div.className = "term-line";
    div.innerHTML = `
      <span class="term-timestamp">[${timeStr}]</span>
      <span class="term-tag ${tagClass}">[${tagLabel}]</span>
      <span class="term-ticket-id">${complaintRef}:</span>
      <span class="term-msg">${details}</span>
      <span style="color: #64748b; font-size: 0.775rem;">${textSnippet}</span>
    `;
    return div;
  }

  function appendTerminalLog(item, isPrepend = false) {
    if (currentAuthority !== "All" && item.assigned_authority && item.assigned_authority !== currentAuthority) {
      return;
    }

    if (terminalBody.children.length === 1 && terminalBody.children[0].classList.contains("term-empty")) {
      terminalBody.innerHTML = "";
    }

    const logEl = createTerminalLogElement(item);
    if (isPrepend) {
      terminalBody.insertBefore(logEl, terminalBody.firstChild);
    } else {
      terminalBody.appendChild(logEl);
      terminalBody.scrollTop = terminalBody.scrollHeight;
    }

    while (terminalBody.children.length > 100) {
      terminalBody.removeChild(terminalBody.firstChild);
    }
  }

  async function loadInitialTerminalLogs() {
    try {
      let url = `${API_BASE}/activity-feed`;
      if (currentAuthority !== "All") {
        url += `?assigned_authority=${encodeURIComponent(currentAuthority)}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to load activity logs");
      const feed = await res.json();

      if (feed.length === 0) {
        terminalBody.innerHTML = `<div class="term-empty">Console initialized. No activity logged for ${currentAuthority}.</div>`;
        return;
      }

      terminalBody.innerHTML = "";
      const chronological = feed.slice().reverse();
      chronological.forEach((item) => appendTerminalLog(item, false));
    } catch (err) {
      terminalBody.innerHTML = `<div class="term-empty" style="color: #f87171;">Stream connection error: ${err.message}</div>`;
    }
  }

  async function loadDashboardComplaints() {
    try {
      let url = `${API_BASE}/complaints`;
      if (currentAuthority !== "All") {
        url += `?assigned_authority=${encodeURIComponent(currentAuthority)}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error("Unable to fetch complaints");
      const list = await res.json();

      const total = list.length;
      const openList = list.filter((c) => c.status === "open");
      const openCount = openList.length;
      const escalatedCount = list.filter((c) => c.escalation_level > 0 && c.status === "open").length;
      const resolvedCount = list.filter((c) => c.status === "resolved").length;

      document.getElementById("statTotal").innerText = total;
      document.getElementById("statOpen").innerText = openCount;
      document.getElementById("statEscalated").innerText = escalatedCount;
      document.getElementById("statResolved").innerText = resolvedCount;

      const showOnlyOpen = showOnlyOpenCheckbox ? showOnlyOpenCheckbox.checked : true;
      const showOnlyEscalated = showOnlyEscalatedCheckbox ? showOnlyEscalatedCheckbox.checked : false;

      let displayList = list;
      if (showOnlyOpen) {
        displayList = displayList.filter((c) => c.status === "open");
      }
      if (showOnlyEscalated) {
        displayList = displayList.filter((c) => c.escalation_level > 0);
      }

      if (displayList.length === 0) {
        let msg = `No complaints recorded for ${currentAuthority}.`;
        if (showOnlyEscalated) {
          msg = `No escalated grievances recorded for ${currentAuthority}.`;
        } else if (showOnlyOpen) {
          msg = `No open complaints assigned to ${currentAuthority}.`;
        }
        complaintsTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">${msg}</td></tr>`;
        return;
      }

      // Check for deep-linked complaint to highlight
      const urlParams = new URLSearchParams(window.location.search);
      const deepId = parseInt(urlParams.get("complaint_id"), 10);

      complaintsTableBody.innerHTML = displayList
        .map(
          (c) => {
            const isDeepMatch = deepId && c.id === deepId;
            const rowHighlight = isDeepMatch ? `style="background: #eff6ff; border-left: 4px solid var(--primary);"` : "";
            const isEscalatedFromSelf = c.initial_authority && c.initial_authority !== c.assigned_authority;
            return `
        <tr id="row-complaint-${c.id}" ${rowHighlight}>
          <td><strong style="color: var(--primary);">#${c.id}</strong></td>
          <td style="max-width: 240px; word-break: break-word; font-size: 0.85rem;" title="${c.text}">
            ${c.text.length > 70 ? c.text.substring(0, 70) + '...' : c.text}
            ${c.photo_url ? `
              <div style="margin-top: 4px;">
                <button type="button" onclick="openPhotoModal('${c.photo_url}')" class="btn btn-sm" style="padding: 2px 7px; font-size: 0.72rem; background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; border-radius: 4px; display: inline-flex; align-items: center; gap: 4px; cursor: pointer;">
                  📷 Photo Evidence
                </button>
              </div>
            ` : ''}
          </td>
          <td><span style="font-weight: 500;">${c.category || 'General'}</span></td>
          <td>${getUrgencyBadge(c.urgency)}</td>
          <td>
            <span style="font-weight: 600; color: var(--text-main);">${c.assigned_authority || 'Unassigned'}</span>
            ${isEscalatedFromSelf ? `<div style="font-size: 0.72rem; color: #dc2626; font-weight: 600; margin-top: 2px;">⚡ Escalated from ${c.initial_authority}</div>` : ''}
          </td>
          <td>${getEscalationBadge(c.escalation_level)}</td>
          <td>${getStatusBadge(c.status)}</td>
          <td><span style="font-size: 0.8rem; color: var(--text-muted);">${formatDate(c.sla_deadline)}</span></td>
          <td style="text-align: right; white-space: nowrap;">
            ${
              c.status !== "resolved"
                ? `<button onclick="resolveComplaint(${c.id})" class="btn btn-primary btn-sm">Resolve</button>
                   ${!c.no_auto_escalation ? `<button onclick="simulateBreach(${c.id})" class="btn btn-sm" title="Simulate SLA breach to immediately escalate to higher authority tier" style="margin-left: 4px; background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5;">⚡ Escalate</button>` : ''}`
                : `<span style="color: var(--success); font-size: 0.8rem; font-weight: 600;">✓ Resolved</span>`
            }
          </td>
        </tr>
      `;
          }
        )
        .join("");

      if (deepId) {
        const targetEl = document.getElementById(`row-complaint-${deepId}`);
        if (targetEl) {
          targetEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }
    } catch (err) {
      complaintsTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--danger); padding: 2rem;">Backend connection error.</td></tr>`;
    }
  }



  // Load Protected Counselor Complaints
  async function loadCounselorComplaints() {
    if (!counselorTableBody) return;
    try {
      const res = await fetch(`${API_BASE}/counselor/complaints`);
      if (!res.ok) throw new Error("Failed to load confidential counseling records");
      const list = await res.json();

      if (counselorCountBadge) {
        counselorCountBadge.innerText = `${list.length} Confidential Case${list.length === 1 ? '' : 's'}`;
      }

      if (list.length === 0) {
        counselorTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No confidential harassment or safety records filed.</td></tr>`;
        return;
      }

      counselorTableBody.innerHTML = list
        .map(
          (c) => `
        <tr>
          <td><strong style="color: #e11d48;">#CASE-${c.id}</strong></td>
          <td style="max-width: 300px; word-break: break-word; font-weight: 500;">
            ${c.text}
          </td>
          <td>${getUrgencyBadge(c.urgency)}</td>
          <td><span style="font-weight: 600; color: #e11d48;">${c.assigned_authority}</span></td>
          <td><span class="badge" style="background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0;">🛡️ Locked (No Auto-Escalation)</span></td>
          <td>${getStatusBadge(c.status)}</td>
          <td><span style="font-size: 0.8rem; color: var(--text-muted);">${formatDate(c.created_at)}</span></td>
          <td style="text-align: right;">
            ${
              c.status !== "resolved"
                ? `<button onclick="resolveComplaint(${c.id})" class="btn btn-sm" style="background: #e11d48; color: #fff;">Resolve Case</button>`
                : `<span style="color: var(--success); font-weight: 600; font-size: 0.8rem;">✓ Closed</span>`
            }
          </td>
        </tr>
      `
        )
        .join("");
    } catch (err) {
      counselorTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--danger); padding: 2rem;">Error: ${err.message}</td></tr>`;
    }
  }

  // Load Sent Authority Emails for Activity Stream
  async function loadAuthorityEmails() {
    try {
      const res = await fetch(`${API_BASE}/authority/emails`);
      if (!res.ok) return;
      const emails = await res.json();
      console.log(`[CampusResolve] Loaded ${emails.length} authority emails.`);
    } catch (e) {
      console.warn("Could not load authority emails:", e);
    }
  }

  // Resolve Complaint with Official Remarks & Resolution Email Dispatch
  window.resolveComplaint = async function (complaintId) {
    const remarks = prompt(`Mark Complaint #${complaintId} as resolved.\nEnter official resolution remarks / action taken (optional):`, "Issue inspected and resolved by authority.");
    if (remarks === null) return; // User cancelled

    try {
      const res = await fetch(`${API_BASE}/complaints/${complaintId}/resolve`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remarks: remarks.trim() || null })
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to resolve complaint");
      }
      alert(`✅ Complaint #${complaintId} marked as RESOLVED!\n\nOfficial resolution notification email has been dispatched.`);
      loadDashboardComplaints();
      loadCounselorComplaints();
      loadAuthorityEmails();
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  // 1-Click SMTP Test Dispatch
  window.testSendEmail = async function () {
    const btn = document.getElementById("testEmailBtn");
    const origText = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerText = "⏳ Dispatching...";
    }
    try {
      const res = await fetch(`${API_BASE}/authority/test-email`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (data.success) {
        alert(`✅ Test email delivered successfully to ${data.recipient}!\n\nPlease check your inbox and spam folder.`);
      } else {
        alert(`⚠️ Email dispatch failed: ${data.message || 'Check SMTP configuration on Render'}`);
      }
    } catch (err) {
      alert(`⚠️ Connection error sending test email: ${err.message}`);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origText;
      }
    }
  };

  // Simulate SLA Breach & Autonomous Tier Escalation
  window.simulateBreach = async function (complaintId) {
    if (!confirm(`Simulate SLA Breach for Complaint #${complaintId}?\n\nThis will immediately force an SLA timeout, execute hierarchical escalation to the next authority tier, and dispatch a real alert email to their inbox.`)) {
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/complaints/${complaintId}/simulate-breach`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to escalate complaint");
      }
      alert(`⚡ ESCALATION SUCCESSFUL!\n\n` +
            `Ticket #${data.complaint_id} escalated to Level ${data.escalation_level}!\n` +
            `New Authority: ${data.assigned_authority}\n` +
            `Recipient: ${data.assigned_email}\n\n` +
            `Real escalation email has been dispatched via Brevo.`);
      loadDashboardComplaints();
      loadAuthorityEmails();
      loadInitialTerminalLogs();
    } catch (err) {
      alert("Escalation Error: " + err.message);
    }
  };

  // On-demand SLA Check Scan
  window.triggerSlaScan = async function () {
    try {
      const res = await fetch(`${API_BASE}/admin/escalate-check`, { method: "POST" });
      const data = await res.json();
      alert(`⚡ Escalation scan completed!\nProcessed ${data.processed_count} overdue complaints.`);
      loadDashboardComplaints();
      loadInitialTerminalLogs();
      loadAuthorityEmails();
    } catch (err) {
      alert("Error scanning escalations: " + err.message);
    }
  };

  function initTerminalWebSocket() {
    const termStatus = document.getElementById("termStatusBadge");
    const ws = new WebSocket(`${WS_BASE}/ws/activity`);

    ws.onopen = () => {
      if (termStatus) {
        termStatus.className = "terminal-status-badge";
        termStatus.innerHTML = `<span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--term-green);"></span> STREAM ACTIVE`;
      }
    };

    ws.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data);
        appendTerminalLog(item, false);
        loadDashboardComplaints();
        loadAuthorityEmails();
      } catch (e) {
        console.error("Websocket activity error:", e);
      }
    };

    ws.onclose = () => {
      if (termStatus) {
        termStatus.className = "terminal-status-badge reconnecting";
        termStatus.innerHTML = `<span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #ef4444;"></span> RECONNECTING...`;
      }
      setTimeout(initTerminalWebSocket, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  document.getElementById("clearTerminalBtn")?.addEventListener("click", () => {
    terminalBody.innerHTML = `<div class="term-empty">Terminal cleared. Waiting for new activity...</div>`;
  });

  document.getElementById("manualRefreshBtn")?.addEventListener("click", () => {
    loadDashboardComplaints();
    loadAuthorityEmails();
    loadCounselorComplaints();
  });
  
  showOnlyOpenCheckbox?.addEventListener("change", () => {
    loadDashboardComplaints();
  });

  showOnlyEscalatedCheckbox?.addEventListener("change", () => {
    loadDashboardComplaints();
  });

  statBoxEscalated?.addEventListener("click", () => {
    if (showOnlyEscalatedCheckbox) {
      showOnlyEscalatedCheckbox.checked = !showOnlyEscalatedCheckbox.checked;
      loadDashboardComplaints();
    }
  });
}

// =======================================================
// D. Central Admin Console (admin.html)
// =======================================================
const adminUsersTableBody = document.getElementById("adminUsersTableBody");
if (adminUsersTableBody) {
  const currentAdminUser = getAuthUser();
  const currentToken = getAuthToken();
  const deniedBox = document.getElementById("adminAccessDeniedAlert");
  const contentBox = document.getElementById("adminMainContent");

  const inlineLoginForm = document.getElementById("adminInlineLoginForm");
  const inlineLoginErr = document.getElementById("adminInlineLoginError");
  const inlineLoginBtn = document.getElementById("adminInlineLoginBtn");

  inlineLoginForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (inlineLoginErr) inlineLoginErr.style.display = "none";
    if (inlineLoginBtn) {
      inlineLoginBtn.disabled = true;
      inlineLoginBtn.innerText = "Authenticating...";
    }

    const username = document.getElementById("adminInlineUsername").value.trim();
    const password = document.getElementById("adminInlinePassword").value.trim();

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Authentication failed. Please check credentials.");

      if (data.user.role !== "Admin") {
        throw new Error("Access forbidden: Central Administrator role required (logi).");
      }

      setAuthSession(data.access_token, data.user);
      if (deniedBox) deniedBox.style.display = "none";
      if (contentBox) contentBox.style.display = "block";
      initAdminConsole();
    } catch (err) {
      if (inlineLoginErr) {
        inlineLoginErr.innerText = err.message;
        inlineLoginErr.style.display = "block";
      } else {
        alert(err.message);
      }
    } finally {
      if (inlineLoginBtn) {
        inlineLoginBtn.disabled = false;
        inlineLoginBtn.innerText = "🔐 Sign In as Administrator";
      }
    }
  });

  if (!currentAdminUser || currentAdminUser.role !== "Admin" || !currentToken) {
    if (deniedBox) deniedBox.style.display = "block";
    if (contentBox) contentBox.style.display = "none";
  } else {
    if (deniedBox) deniedBox.style.display = "none";
    if (contentBox) contentBox.style.display = "block";
    initAdminConsole();
  }

  function initAdminConsole() {
    const logoutBtn = document.getElementById("adminLogoutBtn");
    if (logoutBtn) logoutBtn.onclick = handleGlobalLogout;

    const refreshBtn = document.getElementById("btnRefreshUsers");
    if (refreshBtn) refreshBtn.onclick = loadAdminUsers;

    // Modals
    const addModal = document.getElementById("addUserModal");
    const openAddModalBtn = document.getElementById("btnOpenAddUserModal");
    const closeAddModalBtn = document.getElementById("closeAddUserModal");
    const cancelAddBtn = document.getElementById("cancelAddUserBtn");
    const addUserForm = document.getElementById("addUserForm");
    const addUserErr = document.getElementById("addUserError");

    openAddModalBtn?.addEventListener("click", () => {
      if (addUserErr) addUserErr.style.display = "none";
      addUserForm?.reset();
      const cb = document.getElementById("newMustChangePass");
      if (cb) cb.checked = true;
      if (addModal) addModal.style.display = "flex";
    });

    const closeAdd = () => { if (addModal) addModal.style.display = "none"; };
    closeAddModalBtn?.addEventListener("click", closeAdd);
    cancelAddBtn?.addEventListener("click", closeAdd);

    addUserForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (addUserErr) addUserErr.style.display = "none";

      const username = document.getElementById("newUsername").value.trim();
      const password = document.getElementById("newPassword").value.trim();
      const full_name = document.getElementById("newFullName").value.trim();
      const role = document.getElementById("newRole").value;
      const email = document.getElementById("newEmail").value.trim();
      const tier = document.getElementById("newTier").value.trim();
      const must_change_password = document.getElementById("newMustChangePass").checked;

      const submitBtn = document.getElementById("submitAddUserBtn");
      if (submitBtn) { submitBtn.disabled = true; submitBtn.innerText = "Creating..."; }

      try {
        const res = await fetch(`${API_BASE}/admin/users`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${getAuthToken()}`
          },
          body: JSON.stringify({
            username,
            password,
            full_name,
            role,
            assigned_authority: role,
            email,
            tier: tier || undefined,
            must_change_password
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to create authority account");

        alert(`✅ Authority account '${data.username}' created successfully!`);
        closeAdd();
        loadAdminUsers();
      } catch (err) {
        if (addUserErr) {
          addUserErr.innerText = err.message;
          addUserErr.style.display = "block";
        } else {
          alert(err.message);
        }
      } finally {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.innerText = "Create Authority"; }
      }
    });

    // Reset Password Modal
    const resetModal = document.getElementById("resetPasswordModal");
    const closeResetModal = document.getElementById("closeResetModal");
    const cancelResetBtn = document.getElementById("cancelResetBtn");
    const resetPasswordForm = document.getElementById("resetPasswordForm");

    const closeReset = () => { if (resetModal) resetModal.style.display = "none"; };
    closeResetModal?.addEventListener("click", closeReset);
    cancelResetBtn?.addEventListener("click", closeReset);

    resetPasswordForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const uid = document.getElementById("resetUserId").value;
      const new_password = document.getElementById("resetNewPass").value.trim();
      const must_change_password = document.getElementById("resetMustChange").checked;

      try {
        const res = await fetch(`${API_BASE}/admin/users/${uid}/reset-password`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${getAuthToken()}`
          },
          body: JSON.stringify({ new_password, must_change_password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to reset password");

        alert(`✅ ${data.message}`);
        closeReset();
        loadAdminUsers();
      } catch (err) {
        alert("Reset Error: " + err.message);
      }
    });

    // Role select auto-suggest email & tier
    const roleSelect = document.getElementById("newRole");
    roleSelect?.addEventListener("change", (e) => {
      const val = e.target.value;
      const tierInput = document.getElementById("newTier");
      const emailInput = document.getElementById("newEmail");
      if (val === "Exam Cell Admin") {
        if (tierInput) tierInput.value = "Tier 1 — Operational (Marks, Semester & Fees)";
        if (emailInput && !emailInput.value) emailInput.value = "717824v101@kce.ac.in";
      } else if (val === "Warden") {
        if (tierInput) tierInput.value = "Tier 1 — Operational (Hostels)";
        if (emailInput && !emailInput.value) emailInput.value = "dlogidth4@gmail.com";
      } else if (val === "Mess Committee") {
        if (tierInput) tierInput.value = "Tier 1 — Operational (Dining & Catering)";
        if (emailInput && !emailInput.value) emailInput.value = "dlogidth5@gmail.com";
      } else if (val === "Estate Office") {
        if (tierInput) tierInput.value = "Tier 1 — Operational (Campus Facilities)";
        if (emailInput && !emailInput.value) emailInput.value = "717824v134@kce.ac.in";
      } else if (val.includes("Dean")) {
        if (tierInput) tierInput.value = "Tier 2 — Executive Oversight";
      } else if (val === "Principal") {
        if (tierInput) tierInput.value = "Tier 3 — Apex Institutional Authority";
        if (emailInput && !emailInput.value) emailInput.value = "717824v132@kce.ac.in";
      } else if (val === "Counseling Cell") {
        if (tierInput) tierInput.value = "Protected — Student Safety & Wellness";
        if (emailInput && !emailInput.value) emailInput.value = "717824v152@kce.ac.in";
      }
    });

    loadAdminUsers();
  }

  async function loadAdminUsers() {
    try {
      const token = getAuthToken();
      if (!token) {
        clearAuthSession();
        if (deniedBox) deniedBox.style.display = "block";
        if (contentBox) contentBox.style.display = "none";
        return;
      }
      const res = await fetch(`${API_BASE}/admin/users`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 401 || res.status === 403) {
        clearAuthSession();
        if (deniedBox) deniedBox.style.display = "block";
        if (contentBox) contentBox.style.display = "none";
        const inlineErr = document.getElementById("adminInlineLoginError");
        if (inlineErr) {
          inlineErr.innerText = "Session expired or unauthorized. Please sign in with administrator credentials.";
          inlineErr.style.display = "block";
        }
        return;
      }
      if (!res.ok) throw new Error("Failed to load authority directory");
      const users = await res.json();

      const totalEl = document.getElementById("statTotalUsers");
      const pendingEl = document.getElementById("statPendingLogins");
      if (totalEl) totalEl.innerText = users.length;
      if (pendingEl) pendingEl.innerText = users.filter(u => u.must_change_password).length;

      if (users.length === 0) {
        adminUsersTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:var(--text-muted);">No authorities found.</td></tr>`;
        return;
      }

      adminUsersTableBody.innerHTML = users.map(u => {
        const isSelf = u.username === "logi";
        const statusBadge = u.must_change_password
          ? `<span class="badge" style="background:#fef3c7; color:#d97706; border:1px solid #fde68a;">⚠️ Change Required</span>`
          : `<span class="badge" style="background:#ecfdf5; color:#047857; border:1px solid #a7f3d0;">✓ Secured</span>`;

        return `
          <tr>
            <td>
              <div style="font-weight:700; color:var(--text-main); font-size:0.95rem;">${u.full_name}</div>
              <code style="font-size:0.8rem; color:var(--primary); font-family:var(--font-mono); font-weight:600;">@${u.username}</code>
            </td>
            <td>
              <span class="badge" style="background:#eff6ff; color:#1d4ed8; font-weight:600;">${u.role}</span>
              ${u.assigned_authority && u.assigned_authority !== u.role ? `<div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${u.assigned_authority}</div>` : ''}
            </td>
            <td>
              <span style="font-family:var(--font-mono); font-size:0.825rem; color:var(--text-main);">${u.email}</span>
            </td>
            <td>
              <span style="font-size:0.8rem; color:var(--text-muted);">${u.tier || 'Authority Tier'}</span>
            </td>
            <td>${statusBadge}</td>
            <td style="text-align:right; white-space:nowrap;">
              <button onclick="openResetPasswordModal(${u.id}, '${u.username}')" class="btn btn-outline btn-sm" title="Reset temporary password for this authority">🔑 Reset</button>
              ${!isSelf ? `<button onclick="adminDeleteUser(${u.id}, '${u.username}')" class="btn btn-sm" title="Delete authority account" style="background:#fee2e2; color:#b91c1c; border:1px solid #fca5a5; margin-left:4px;">🗑️ Delete</button>` : ''}
            </td>
          </tr>
        `;
      }).join("");

    } catch (err) {
      adminUsersTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--danger); padding:2rem;">Error: ${err.message}</td></tr>`;
    }
  }

  window.openResetPasswordModal = function(userId, username) {
    document.getElementById("resetUserId").value = userId;
    const sub = document.getElementById("resetModalSubtitle");
    if (sub) sub.innerText = `Setting new temporary credentials for @${username}.`;
    document.getElementById("resetNewPass").value = "";
    document.getElementById("resetMustChange").checked = false;
    const modal = document.getElementById("resetPasswordModal");
    if (modal) modal.style.display = "flex";
  };

  window.adminDeleteUser = async function(userId, username) {
    if (!confirm(`Are you sure you want to delete authority account '@${username}'?\n\nThis will remove their portal access permanently.`)) {
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/admin/users/${userId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${getAuthToken()}` }
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to delete user");
      alert(`✅ ${data.message}`);
      loadAdminUsers();
    } catch (err) {
      alert("Delete Error: " + err.message);
    }
  };
}
