const API_BASE = "http://127.0.0.1:8000";
const WS_BASE = "ws://127.0.0.1:8000";

// Helper for status pills
function getStatusPill(status) {
  const s = status ? status.toLowerCase() : "open";
  return `<span class="pill pill-${s}">${status || "UNKNOWN"}</span>`;
}

// Helper for urgency/priority pills
function getUrgencyPill(urgency) {
  const u = urgency ? urgency.toLowerCase() : "medium";
  return `<span class="pill pill-${u}">${urgency || "NORMAL"}</span>`;
}

// Format Date
function formatDate(dateStr) {
  if (!dateStr) return "N/A";
  const d = new Date(dateStr);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// --- STUDENT PORTAL: SUBMIT COMPLAINT ---
const complaintForm = document.getElementById("complaintForm");
if (complaintForm) {
  complaintForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = document.getElementById("submitBtn");
    submitBtn.disabled = true;
    submitBtn.innerText = "Submitting & Triaging...";

    const text = document.getElementById("complaintText").value.trim();
    if (!text) return;

    try {
      const res = await fetch(`${API_BASE}/complaints`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (!res.ok) throw new Error("Failed to submit complaint");
      const data = await res.json();

      // Show result
      const resBox = document.getElementById("submissionResult");
      document.getElementById("resId").innerText = data.id;
      document.getElementById("resCategory").innerText = data.category || "General";
      document.getElementById("resUrgency").innerHTML = getUrgencyPill(data.urgency);
      document.getElementById("resAuthority").innerText = data.assigned_authority || "Student Affairs";
      document.getElementById("resStatus").innerHTML = getStatusPill(data.status);
      document.getElementById("resSla").innerText = formatDate(data.sla_deadline);

      resBox.classList.add("show");
      complaintForm.reset();
    } catch (err) {
      alert("Error submitting complaint: " + err.message + ". Make sure backend is running.");
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerText = "Submit Complaint";
    }
  });
}

// --- STUDENT PORTAL: TRACK COMPLAINT ---
const trackForm = document.getElementById("trackForm");
if (trackForm) {
  trackForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = document.getElementById("trackId").value.trim();
    if (!id) return;

    try {
      const res = await fetch(`${API_BASE}/complaints/${encodeURIComponent(id)}`);
      if (!res.ok) {
        if (res.status === 404) throw new Error("Complaint ID #" + id + " not found");
        throw new Error("Failed to fetch complaint details");
      }
      const data = await res.json();

      const trackBox = document.getElementById("trackResult");
      document.getElementById("trackTitle").innerText = `Complaint #${data.id}: "${data.text.substring(0, 50)}${data.text.length > 50 ? '...' : ''}"`;
      document.getElementById("trackStatus").innerHTML = getStatusPill(data.status);
      document.getElementById("trackCategory").innerText = data.category || "General";
      document.getElementById("trackUrgency").innerHTML = getUrgencyPill(data.urgency);
      document.getElementById("trackAuthority").innerText = data.assigned_authority || "Unassigned";
      document.getElementById("trackEscalation").innerText = `Level ${data.escalation_level}`;
      document.getElementById("trackSla").innerText = formatDate(data.sla_deadline);
      document.getElementById("trackResolvedAt").innerText = data.resolved_at ? formatDate(data.resolved_at) : "Pending";

      const logsList = document.getElementById("trackLogs");
      logsList.innerHTML = "";
      if (data.activity_logs && data.activity_logs.length > 0) {
        data.activity_logs.forEach((log) => {
          const li = document.createElement("li");
          li.style.marginBottom = "0.5rem";
          li.innerHTML = `<strong>${formatDate(log.timestamp)} [${log.action}]:</strong> ${log.details || ''}`;
          logsList.appendChild(li);
        });
      } else {
        logsList.innerHTML = "<li>No activity logs recorded yet.</li>";
      }

      trackBox.classList.add("show");
    } catch (err) {
      alert(err.message);
    }
  });
}

// --- ADMIN DASHBOARD: LIST, REAL-TIME WEBSOCKET & ACTIVITY FEED ---
const complaintsTableBody = document.getElementById("complaintsTableBody");
const activityFeedList = document.getElementById("activityFeedList");

if (complaintsTableBody) {
  async function loadDashboardComplaints() {
    try {
      const res = await fetch(`${API_BASE}/complaints`);
      if (!res.ok) throw new Error("Unable to fetch complaints");
      const list = await res.json();

      // Stats
      let total = list.length;
      let openCount = list.filter((c) => c.status === "open").length;
      let escalatedCount = list.filter((c) => c.escalation_level > 0).length;
      let resolvedCount = list.filter((c) => c.status === "resolved").length;

      document.getElementById("statTotal").innerText = total;
      document.getElementById("statOpen").innerText = openCount;
      document.getElementById("statEscalated").innerText = escalatedCount;
      document.getElementById("statResolved").innerText = resolvedCount;

      if (list.length === 0) {
        complaintsTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No complaints found in database.</td></tr>`;
        return;
      }

      complaintsTableBody.innerHTML = list
        .map(
          (c) => `
        <tr>
          <td><strong style="color: #a5b4fc;">#${c.id}</strong></td>
          <td style="max-width: 220px; word-break: break-word; font-size: 0.85rem;">${c.text}</td>
          <td>${c.category || 'General'}</td>
          <td>${getUrgencyPill(c.urgency)}</td>
          <td><small>${c.assigned_authority || 'Unassigned'}</small></td>
          <td><span style="color: ${c.escalation_level > 0 ? '#f87171' : 'var(--text-muted)'}; font-weight: 600;">Lvl ${c.escalation_level}</span></td>
          <td>${getStatusPill(c.status)}</td>
          <td>
            ${
              c.status !== "resolved"
                ? `<button onclick="resolveComplaint(${c.id})" class="btn btn-sm" style="background: rgba(16,185,129,0.2); color: #34d399;">Resolve</button>`
                : `<span style="color:#34d399; font-size:0.8rem; font-weight:600;">✓ Resolved</span>`
            }
          </td>
        </tr>
      `
        )
        .join("");
    } catch (err) {
      complaintsTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #f87171; padding: 2rem;">Backend offline. Run backend main.py!</td></tr>`;
    }
  }

  function renderFeedItem(item) {
    const isEscalation = item.action === "ESCALATED";
    const isResolved = item.action === "RESOLVED";
    const borderAccent = isEscalation ? "rgba(244, 63, 94, 0.4)" : (isResolved ? "rgba(16, 185, 129, 0.4)" : "rgba(99, 102, 241, 0.3)");
    const badgeColor = isEscalation ? "#f87171" : (isResolved ? "#34d399" : "#a5b4fc");

    return `
      <div style="background: rgba(17, 24, 39, 0.85); border: 1px solid ${borderAccent}; border-radius: 8px; padding: 0.75rem; font-size: 0.82rem; transition: all 0.3s ease;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
          <span style="font-weight: 700; color: ${badgeColor}; font-size: 0.75rem;">[${item.action}] #TICKET-${item.complaint_id}</span>
          <span style="color: var(--text-muted); font-size: 0.7rem;">${formatDate(item.timestamp)}</span>
        </div>
        <div style="color: #e5e7eb; margin-bottom: 0.35rem; font-weight: 500;">${item.details || ''}</div>
        <div style="color: var(--text-muted); font-size: 0.75rem; font-style: italic; border-top: 1px dashed rgba(255,255,255,0.06); padding-top: 0.3rem;">
          "${item.complaint_text || ''}"
        </div>
      </div>
    `;
  }

  async function loadActivityFeed() {
    if (!activityFeedList) return;
    try {
      const res = await fetch(`${API_BASE}/activity-feed`);
      if (!res.ok) throw new Error("Failed to load activity feed");
      const feed = await res.json();

      if (feed.length === 0) {
        activityFeedList.innerHTML = `<div style="color: var(--text-muted); font-size: 0.85rem; text-align: center; padding: 2rem;">No activities logged yet.</div>`;
        return;
      }

      activityFeedList.innerHTML = feed.map(renderFeedItem).join("");
    } catch (err) {
      activityFeedList.innerHTML = `<div style="color: #f87171; font-size: 0.85rem; padding: 1rem;">Failed to load activity feed.</div>`;
    }
  }

  // --- WebSocket Connection ---
  function initWebSocket() {
    const wsBadge = document.getElementById("wsStatusBadge");
    const ws = new WebSocket(`${WS_BASE}/ws/activity`);

    ws.onopen = () => {
      if (wsBadge) {
        wsBadge.innerHTML = `<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #34d399; margin-right: 4px;"></span> WebSocket Live`;
        wsBadge.style.color = "#34d399";
      }
    };

    ws.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data);
        if (activityFeedList) {
          const tempDiv = document.createElement("div");
          tempDiv.innerHTML = renderFeedItem(item);
          const firstChild = tempDiv.firstElementChild;
          firstChild.style.boxShadow = "0 0 12px rgba(99, 102, 241, 0.5)";
          
          if (activityFeedList.children.length === 1 && activityFeedList.children[0].textContent.includes("No activities")) {
            activityFeedList.innerHTML = "";
          }
          activityFeedList.prepend(firstChild);
          
          // Trim to top 50
          while (activityFeedList.children.length > 50) {
            activityFeedList.removeChild(activityFeedList.lastChild);
          }
        }
        // Auto-refresh table stats & data
        loadDashboardComplaints();
      } catch (e) {
        console.error("Error processing websocket activity:", e);
      }
    };

    ws.onclose = () => {
      if (wsBadge) {
        wsBadge.innerHTML = `<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #f87171; margin-right: 4px;"></span> Reconnecting...`;
        wsBadge.style.color = "#f87171";
      }
      setTimeout(initWebSocket, 3000);
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

  document.getElementById("refreshBtn")?.addEventListener("click", () => {
    loadDashboardComplaints();
    loadActivityFeed();
  });

  // Initial loads
  loadDashboardComplaints();
  loadActivityFeed();
  initWebSocket();
}
