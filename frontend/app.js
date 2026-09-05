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

// ==========================================
// 1. STUDENT PORTAL (index.html)
// ==========================================

const complaintForm = document.getElementById("complaintForm");
const confirmationBox = document.getElementById("confirmationBox");
const trackComplaintLink = document.getElementById("trackComplaintLink");
const trackForm = document.getElementById("trackForm");
const trackIdInput = document.getElementById("trackIdInput");
const trackResultBox = document.getElementById("trackResultBox");

// --- Submit Complaint ---
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

// --- Fetch & Render Complaint Status ---
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

      // Render timeline
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

// --- Track Form Submit ---
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
// 2. ADMIN DASHBOARD (dashboard.html)
// ==========================================

const complaintsTableBody = document.getElementById("complaintsTableBody");
const activityFeedList = document.getElementById("activityFeedList");

if (complaintsTableBody) {
  async function loadDashboardComplaints() {
    try {
      const res = await fetch(`${API_BASE}/complaints`);
      if (!res.ok) throw new Error("Unable to fetch complaints");
      const list = await res.json();

      let total = list.length;
      let openCount = list.filter((c) => c.status === "open").length;
      let escalatedCount = list.filter((c) => c.escalation_level > 0).length;
      let resolvedCount = list.filter((c) => c.status === "resolved").length;

      document.getElementById("statTotal").innerText = total;
      document.getElementById("statOpen").innerText = openCount;
      document.getElementById("statEscalated").innerText = escalatedCount;
      document.getElementById("statResolved").innerText = resolvedCount;

      if (list.length === 0) {
        complaintsTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No complaints found in registry.</td></tr>`;
        return;
      }

      complaintsTableBody.innerHTML = list
        .map(
          (c) => `
        <tr>
          <td><strong style="color: var(--primary);">#${c.id}</strong></td>
          <td style="max-width: 220px; word-break: break-word; font-size: 0.85rem;">${c.text}</td>
          <td>${c.category || 'General'}</td>
          <td>${getUrgencyBadge(c.urgency)}</td>
          <td><small>${c.assigned_authority || 'Unassigned'}</small></td>
          <td><span style="color: ${c.escalation_level > 0 ? 'var(--danger)' : 'var(--text-muted)'}; font-weight: 600;">Lvl ${c.escalation_level}</span></td>
          <td>${getStatusBadge(c.status)}</td>
          <td>
            ${
              c.status !== "resolved"
                ? `<button onclick="resolveComplaint(${c.id})" class="btn btn-outline" style="padding: 0.25rem 0.6rem; font-size: 0.75rem;">Resolve</button>`
                : `<span style="color: var(--success); font-size: 0.8rem; font-weight: 600;">✓ Resolved</span>`
            }
          </td>
        </tr>
      `
        )
        .join("");
    } catch (err) {
      complaintsTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--danger); padding: 2rem;">Backend offline. Run backend main.py!</td></tr>`;
    }
  }

  function renderFeedItem(item) {
    const isEscalation = item.action === "ESCALATED";
    const isResolved = item.action === "RESOLVED";
    const badgeBg = isEscalation ? "var(--danger-bg)" : (isResolved ? "var(--success-bg)" : "var(--primary-light)");
    const badgeColor = isEscalation ? "var(--danger)" : (isResolved ? "var(--success)" : "var(--primary)");

    return `
      <div style="background: #ffffff; border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 0.75rem; font-size: 0.825rem; transition: var(--transition);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
          <span style="font-weight: 700; color: ${badgeColor}; font-size: 0.75rem; background: ${badgeBg}; padding: 0.1rem 0.4rem; border-radius: 4px;">
            [${item.action}] #TICKET-${item.complaint_id}
          </span>
          <span style="color: var(--text-light); font-size: 0.7rem;">${formatDate(item.timestamp)}</span>
        </div>
        <div style="color: var(--text-main); margin-bottom: 0.25rem; font-weight: 500;">${item.details || ''}</div>
        <div style="color: var(--text-muted); font-size: 0.75rem; font-style: italic; border-top: 1px dashed var(--border-color); padding-top: 0.25rem;">
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
      activityFeedList.innerHTML = `<div style="color: var(--danger); font-size: 0.85rem; padding: 1rem;">Failed to load activity feed.</div>`;
    }
  }

  // --- WebSocket Connection ---
  function initWebSocket() {
    const wsBadge = document.getElementById("wsStatusBadge");
    const ws = new WebSocket(`${WS_BASE}/ws/activity`);

    ws.onopen = () => {
      if (wsBadge) {
        wsBadge.style.color = "var(--success)";
        wsBadge.style.background = "var(--success-bg)";
        wsBadge.style.borderColor = "var(--success-border)";
      }
    };

    ws.onmessage = (event) => {
      try {
        const item = JSON.parse(event.data);
        if (activityFeedList) {
          const tempDiv = document.createElement("div");
          tempDiv.innerHTML = renderFeedItem(item);
          const firstChild = tempDiv.firstElementChild;
          firstChild.style.boxShadow = "0 0 8px rgba(37, 99, 235, 0.25)";
          
          if (activityFeedList.children.length === 1 && activityFeedList.children[0].textContent.includes("No activities")) {
            activityFeedList.innerHTML = "";
          }
          activityFeedList.prepend(firstChild);

          while (activityFeedList.children.length > 50) {
            activityFeedList.removeChild(activityFeedList.lastChild);
          }
        }
        loadDashboardComplaints();
      } catch (e) {
        console.error("Error processing websocket activity:", e);
      }
    };

    ws.onclose = () => {
      if (wsBadge) {
        wsBadge.style.color = "var(--danger)";
        wsBadge.style.background = "var(--danger-bg)";
        wsBadge.style.borderColor = "var(--danger-border)";
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
