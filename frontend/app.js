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

if (complaintForm) {
  complaintForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = document.getElementById("submitBtn");
    const complaintText = document.getElementById("complaintText").value.trim();
    if (!complaintText) return;

    submitBtn.disabled = true;
    submitBtn.innerText = "Submitting Complaint...";

    try {
      const res = await fetch(`${API_BASE}/complaints`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: complaintText }),
      });

      if (!res.ok) throw new Error("Failed to submit complaint. Server error.");
      const data = await res.json();

      // Render Confirmation Details
      document.getElementById("resId").innerText = data.id;
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
          if (trackIdInput) {
            trackIdInput.value = data.id;
            loadComplaintDetails(data.id);
            document.getElementById("trackingSection")?.scrollIntoView({ behavior: "smooth" });
          }
        };
      }

      complaintForm.reset();
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerText = "Submit Complaint";
    }
  });

  // Check URL query parameters for deep-linking: index.html?track=123
  const urlParams = new URLSearchParams(window.location.search);
  const trackParam = urlParams.get("track");
  if (trackParam && trackIdInput) {
    trackIdInput.value = trackParam;
    loadComplaintDetails(trackParam);
    document.getElementById("trackingSection")?.scrollIntoView({ behavior: "smooth" });
  }
}

async function loadComplaintDetails(id) {
  if (!id) return;
  const trackBtn = document.getElementById("trackBtn");
  if (trackBtn) trackBtn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/complaints/${encodeURIComponent(id)}`);
    if (!res.ok) {
      if (res.status === 404) throw new Error(`Complaint ID #${id} not found.`);
      throw new Error("Unable to fetch complaint details.");
    }
    const data = await res.json();

    if (trackResultBox) {
      document.getElementById("trackComplaintHeading").innerText = `Complaint #${data.id}`;
      document.getElementById("trackComplaintText").innerText = `"${data.text}"`;
      document.getElementById("trackStatusBadge").innerHTML = getStatusBadge(data.status);
      document.getElementById("trackCategory").innerText = (data.category || "General").toUpperCase();
      document.getElementById("trackUrgency").innerHTML = getUrgencyBadge(data.urgency);
      document.getElementById("trackAuthority").innerText = data.assigned_authority || "Unassigned";
      document.getElementById("trackEscalation").innerText = `Level ${data.escalation_level}`;
      document.getElementById("trackSla").innerText = formatDate(data.sla_deadline);
      document.getElementById("trackResolvedAt").innerText = data.resolved_at ? formatDate(data.resolved_at) : "Open / In Progress";

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

      trackResultBox.style.display = "block";
    }
  } catch (err) {
    alert(err.message);
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
    "HOD": "717824v101@kce.ac.in",
    "Estate Office": "717824v134@kce.ac.in",
    "Dean of Student Affairs": "abijithmohanan2006@gmail.com",
    "Dean of Academics": "717824v101@kce.ac.in",
    "Vice Principal": "logidth78@gmail.com",
    "Principal": "717824v27@kce.ac.in",
    "Counseling Cell": "717824v152@kce.ac.in",
    "Admin": "717824v134@kce.ac.in",
    "All": "717824v134@kce.ac.in"
  };

  let currentAuthority = "All";

  // Check Auth State: Logged-in vs Logged-out
  if (!currentUser) {
    // Show Sign-in Form + Quick Demo Picker
    authLoggedOutView.style.display = "block";
    authLoggedInView.style.display = "none";
    initQuickDemoLogin();
  } else {
    // Show Full Authenticated Authority Dashboard
    authLoggedOutView.style.display = "none";
    authLoggedInView.style.display = "block";
    initAuthorityDashboard();
  }

  // -------------------------------------------------------------
  // A. Quick Demo Login Initializer (Signed-out View)
  // -------------------------------------------------------------
  async function initQuickDemoLogin() {
    const roleIcons = {
      "Warden": "🏢",
      "Mess Committee": "🍲",
      "HOD": "📚",
      "Estate Office": "⚡",
      "Dean of Student Affairs": "🎓",
      "Dean of Academics": "📖",
      "Vice Principal": "🏛️",
      "Principal": "👑",
      "Counseling Cell": "🛡️",
      "Admin": "⚙️"
    };

    try {
      const res = await fetch(`${API_BASE}/auth/accounts`);
      if (!res.ok) throw new Error("Failed to load demo accounts");
      const accounts = await res.json();

      quickAccountsList.innerHTML = accounts.map(acc => {
        const icon = roleIcons[acc.role] || "👤";
        return `
          <div class="quick-acc-card" onclick="quickLogin('${acc.username}', '${acc.password}')">
            <div>
              <div class="quick-acc-role">
                <span>${icon}</span>
                <span>${acc.full_name || acc.role}</span>
              </div>
              <div class="quick-acc-meta">
                ${acc.role} &middot; <span style="color: var(--primary); font-family: var(--font-mono); font-weight: 600;">${acc.email}</span>
              </div>
            </div>
            <span class="quick-acc-badge">
              ${acc.username}
            </span>
          </div>
        `;
      }).join("");
    } catch (e) {
      console.warn("Backend connectivity issue:", e);
      const fallbackAccounts = [
        { username: "warden", password: "warden123", role: "Warden", full_name: "Prof. R. K. Sharma (Warden)", email: "dlogidth4@gmail.com" },
        { username: "mess", password: "mess123", role: "Mess Committee", full_name: "Dr. Ananya Gupta (Mess Committee)", email: "dlogidth5@gmail.com" },
        { username: "hod", password: "hod123", role: "HOD", full_name: "Dr. Vikram Malhotra (HOD)", email: "717824v101@kce.ac.in" },
        { username: "estate", password: "estate123", role: "Estate Office", full_name: "Er. S. N. Roy (Estate Office)", email: "717824v134@kce.ac.in" },
        { username: "counselor", password: "counselor123", role: "Counseling Cell", full_name: "Dr. Sunita Rao (Chief Counselor)", email: "717824v152@kce.ac.in" },
        { username: "principal", password: "principal123", role: "Principal", full_name: "Dr. K. S. Pillai (Principal / Director)", email: "717824v27@kce.ac.in" },
        { username: "admin", password: "admin123", role: "Admin", full_name: "Central Institutional Administrator", email: "717824v134@kce.ac.in" }
      ];

      quickAccountsList.innerHTML = `
        <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; padding: 0.75rem; margin-bottom: 0.75rem; font-size: 0.8rem; color: var(--danger);">
          ⚠️ <strong>Backend Unreachable</strong> at <code>${API_BASE}</code>.<br>
          <span style="color: var(--text-muted); font-size: 0.75rem;">
            If running locally: start backend with <code>uvicorn backend.main:app --port 8000</code>.<br>
            If using deployed backend: append <code>?api=https://your-service.onrender.com</code> to URL.
          </span>
        </div>
      ` + fallbackAccounts.map(acc => {
        const icon = roleIcons[acc.role] || "👤";
        return `
          <div class="quick-acc-card" onclick="quickLogin('${acc.username}', '${acc.password}')">
            <div>
              <div class="quick-acc-role">
                <span>${icon}</span>
                <span>${acc.full_name || acc.role}</span>
              </div>
              <div class="quick-acc-meta">
                ${acc.role} &middot; <span style="color: var(--primary); font-family: var(--font-mono); font-weight: 600;">${acc.email}</span>
              </div>
            </div>
            <span class="quick-acc-badge">
              ${acc.username}
            </span>
          </div>
        `;
      }).join("");
    }

    // Quick Login Helper
    window.quickLogin = function(username, password) {
      document.getElementById("loginUsername").value = username;
      document.getElementById("loginPassword").value = password;
      executeLogin(username, password);
    };

    // Form submit handler
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
        if (!res.ok) throw new Error(data.detail || "Invalid credentials.");

        setAuthSession(data.access_token, data.user);
        window.location.reload();
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
      if (authoritySelector) {
        authoritySelector.value = "All";
        authoritySelector.disabled = false;
      }
      if (tabCounselorBtn) tabCounselorBtn.style.display = "inline-block";
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
      const displayList = showOnlyOpen ? openList : list;

      if (displayList.length === 0) {
        const msg = showOnlyOpen 
          ? `No open complaints assigned to ${currentAuthority}.` 
          : `No complaints recorded for ${currentAuthority}.`;
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
            return `
        <tr id="row-complaint-${c.id}" ${rowHighlight}>
          <td><strong style="color: var(--primary);">#${c.id}</strong></td>
          <td style="max-width: 240px; word-break: break-word; font-size: 0.85rem;" title="${c.text}">
            ${c.text.length > 70 ? c.text.substring(0, 70) + '...' : c.text}
          </td>
          <td><span style="font-weight: 500;">${c.category || 'General'}</span></td>
          <td>${getUrgencyBadge(c.urgency)}</td>
          <td><span style="font-weight: 600; color: var(--text-main);">${c.assigned_authority || 'Unassigned'}</span></td>
          <td>${getEscalationBadge(c.escalation_level)}</td>
          <td>${getStatusBadge(c.status)}</td>
          <td><span style="font-size: 0.8rem; color: var(--text-muted);">${formatDate(c.sla_deadline)}</span></td>
          <td style="text-align: right;">
            ${
              c.status !== "resolved"
                ? `<button onclick="resolveComplaint(${c.id})" class="btn btn-primary btn-sm">Resolve</button>`
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
}
