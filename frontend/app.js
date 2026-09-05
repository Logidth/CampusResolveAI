const API_BASE = "http://127.0.0.1:8000";
const WS_BASE = "ws://127.0.0.1:8000";

// Helper: Status badge generator
function getStatusBadge(status) {
  const s = status ? status.toLowerCase() : "open";
  return `<span class="badge badge-${s}">${status || "open"}</span>`;
}

// Helper: Urgency badge generator
function getUrgencyBadge(urgency) {
  const u = urgency ? urgency.toLowerCase() : "medium";
  return `<span class="badge badge-${u}">${urgency || "medium"}</span>`;
}

// Helper: Escalation level badge generator
function getEscalationBadge(level) {
  const lvl = level || 0;
  const cls = lvl === 0 ? "badge-esc-0" : (lvl === 1 ? "badge-esc-1" : "badge-esc-2");
  return `<span class="badge ${cls}">Level ${lvl}</span>`;
}

// Helper: Date formatter
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

// Helper: Terminal log timestamp formatter [YYYY-MM-DD HH:MM:SS]
function formatTerminalTimestamp(dateStr) {
  const d = dateStr ? new Date(dateStr) : new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// ==========================================
// 1. STUDENT PORTAL (index.html)
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
      document.getElementById("resCategory").innerText = data.category || "General";
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
      document.getElementById("trackCategory").innerText = data.category || "General";
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

// ==========================================
// 2. ADMIN MONITORING DASHBOARD (dashboard.html)
// ==========================================

const complaintsTableBody = document.getElementById("complaintsTableBody");
const terminalBody = document.getElementById("terminalBody");
const showOnlyOpenCheckbox = document.getElementById("showOnlyOpen");

if (complaintsTableBody && terminalBody) {

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
      const res = await fetch(`${API_BASE}/activity-feed`);
      if (!res.ok) throw new Error("Failed to load initial terminal logs");
      const feed = await res.json();

      if (feed.length === 0) {
        terminalBody.innerHTML = `<div class="term-empty">Console initialized. No grievance activity logged yet.</div>`;
        return;
      }

      terminalBody.innerHTML = "";
      const chronological = feed.slice().reverse();
      chronological.forEach((item) => {
        appendTerminalLog(item, false);
      });
    } catch (err) {
      terminalBody.innerHTML = `<div class="term-empty" style="color: #f87171;">Failed to connect to activity feed: ${err.message}</div>`;
    }
  }

  // Auto-refreshes every 5 seconds (Excludes confidential harassment records from general view)
  async function loadDashboardComplaints() {
    try {
      // GET /complaints excludes harassment by default for privacy
      const res = await fetch(`${API_BASE}/complaints`);
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
        const msg = showOnlyOpen ? "No active open complaints in general queue." : "No general complaints recorded.";
        complaintsTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">${msg}</td></tr>`;
        return;
      }

      complaintsTableBody.innerHTML = displayList
        .map(
          (c) => `
        <tr>
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
      `
        )
        .join("");
    } catch (err) {
      complaintsTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--danger); padding: 2rem;">Backend connection error. Ensure FastAPI server is running.</td></tr>`;
    }
  }

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
      } catch (e) {
        console.error("Error processing websocket activity:", e);
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

  window.resolveComplaint = async function (complaintId) {
    if (!confirm(`Mark Complaint #${complaintId} as resolved?`)) return;

    try {
      const res = await fetch(`${API_BASE}/complaints/${complaintId}/resolve`, {
        method: "PATCH",
      });
      if (!res.ok) throw new Error("Failed to resolve complaint");
      loadDashboardComplaints();
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  document.getElementById("clearTerminalBtn")?.addEventListener("click", () => {
    terminalBody.innerHTML = `<div class="term-empty">Terminal cleared. Waiting for new activity...</div>`;
  });

  document.getElementById("manualRefreshBtn")?.addEventListener("click", () => {
    loadDashboardComplaints();
  });
  
  showOnlyOpenCheckbox?.addEventListener("change", () => {
    loadDashboardComplaints();
  });

  loadDashboardComplaints();
  loadInitialTerminalLogs();
  initTerminalWebSocket();
  setInterval(loadDashboardComplaints, 5000);
}

// ==========================================
// 3. PROTECTED COUNSELOR PORTAL (counselor.html)
// ==========================================

const counselorLoginForm = document.getElementById("counselorLoginForm");
const counselorAuthGate = document.getElementById("counselorAuthGate");
const counselorProtectedView = document.getElementById("counselorProtectedView");
const counselorTableBody = document.getElementById("counselorTableBody");
const counselorCountBadge = document.getElementById("counselorCountBadge");

if (counselorLoginForm) {
  const COUNSELOR_PASSCODE = "counselor2026";

  // Check existing session
  if (sessionStorage.getItem("counselor_authenticated") === "true") {
    showCounselorDashboard();
  }

  counselorLoginForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const pin = document.getElementById("counselorPin").value.trim();
    if (pin === COUNSELOR_PASSCODE) {
      sessionStorage.setItem("counselor_authenticated", "true");
      showCounselorDashboard();
    } else {
      alert("Incorrect Counselor Passcode. (Demo passcode: counselor2026)");
    }
  });

  document.getElementById("counselorLogoutBtn")?.addEventListener("click", () => {
    sessionStorage.removeItem("counselor_authenticated");
    counselorProtectedView.style.display = "none";
    counselorAuthGate.style.display = "block";
    document.getElementById("counselorPin").value = "";
  });

  document.getElementById("counselorRefreshBtn")?.addEventListener("click", () => {
    loadCounselorComplaints();
  });

  function showCounselorDashboard() {
    counselorAuthGate.style.display = "none";
    counselorProtectedView.style.display = "block";
    loadCounselorComplaints();
  }

  async function loadCounselorComplaints() {
    try {
      const res = await fetch(`${API_BASE}/counselor/complaints`);
      if (!res.ok) throw new Error("Failed to load counseling records");
      const list = await res.json();

      if (counselorCountBadge) {
        counselorCountBadge.innerText = `${list.length} Confidential Case${list.length === 1 ? '' : 's'}`;
      }

      if (list.length === 0) {
        counselorTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No harassment or safety records filed.</td></tr>`;
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
                ? `<button onclick="resolveCounselorCase(${c.id})" class="btn btn-sm" style="background: #e11d48; color: #fff;">Resolve Case</button>`
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

  window.resolveCounselorCase = async function (caseId) {
    if (!confirm(`Mark Confidential Case #CASE-${caseId} as resolved by Counseling Cell?`)) return;

    try {
      const res = await fetch(`${API_BASE}/complaints/${caseId}/resolve`, {
        method: "PATCH",
      });
      if (!res.ok) throw new Error("Failed to resolve case");
      loadCounselorComplaints();
    } catch (err) {
      alert("Error: " + err.message);
    }
  };
}
