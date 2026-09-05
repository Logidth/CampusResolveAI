const API_BASE = "http://127.0.0.1:8000";

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
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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

// --- ADMIN DASHBOARD: LIST & RESOLVE COMPLAINTS ---
const complaintsTableBody = document.getElementById("complaintsTableBody");
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
        complaintsTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">No complaints found in database.</td></tr>`;
        return;
      }

      complaintsTableBody.innerHTML = list
        .map(
          (c) => `
        <tr>
          <td><strong style="color: #a5b4fc;">#${c.id}</strong></td>
          <td style="max-width: 260px; word-break: break-word;">${c.text}</td>
          <td>${c.category || 'General'}</td>
          <td>${getUrgencyPill(c.urgency)}</td>
          <td><small>${c.assigned_authority || 'Unassigned'}</small></td>
          <td><span style="color: ${c.escalation_level > 0 ? '#f87171' : 'var(--text-muted)'}; font-weight: 600;">Lvl ${c.escalation_level}</span></td>
          <td>${getStatusPill(c.status)}</td>
          <td><small>${formatDate(c.sla_deadline)}</small></td>
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
      complaintsTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: #f87171; padding: 2rem;">Backend offline. Run: uvicorn backend.main:app --reload</td></tr>`;
    }
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

  document.getElementById("refreshBtn")?.addEventListener("click", loadDashboardComplaints);

  // Initial load
  loadDashboardComplaints();
}
