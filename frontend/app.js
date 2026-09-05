const API_BASE = "http://127.0.0.1:8000";

// Helper for status pills
function getStatusPill(status) {
  const s = status ? status.toLowerCase() : "submitted";
  return `<span class="pill pill-${s}">${status || "UNKNOWN"}</span>`;
}

// Helper for priority pills
function getPriorityPill(priority) {
  const p = priority ? priority.toLowerCase() : "medium";
  return `<span class="pill pill-${p}">${priority || "NORMAL"}</span>`;
}

// Format Date
function formatDate(dateStr) {
  if (!dateStr) return "N/A";
  const d = new Date(dateStr);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// --- STUDENT PORTAL LOGIC ---
const grievanceForm = document.getElementById("grievanceForm");
if (grievanceForm) {
  grievanceForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = document.getElementById("submitBtn");
    submitBtn.disabled = true;
    submitBtn.innerText = "Agent Analyzing & Routing...";

    const payload = {
      student_name: document.getElementById("student_name").value,
      student_email: document.getElementById("student_email").value,
      student_id: document.getElementById("student_id").value || null,
      title: document.getElementById("title").value,
      description: document.getElementById("description").value,
    };

    try {
      const res = await fetch(`${API_BASE}/api/grievances`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error("Failed to submit grievance");
      const data = await res.json();

      // Show result
      const resBox = document.getElementById("submissionResult");
      document.getElementById("resTicketId").innerText = data.ticket_id;
      document.getElementById("resCategory").innerText = data.category;
      document.getElementById("resPriority").innerHTML = getPriorityPill(data.priority);
      document.getElementById("resDepartment").innerText = data.assigned_department;
      document.getElementById("resSummary").innerText = data.ai_summary;
      document.getElementById("resSla").innerText = formatDate(data.sla_deadline);

      resBox.classList.add("show");
      grievanceForm.reset();
    } catch (err) {
      alert("Error submitting grievance: " + err.message + ". Make sure backend is running.");
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerText = "Submit to AI Agent";
    }
  });
}

// --- TRACK TICKET LOGIC ---
const trackForm = document.getElementById("trackForm");
if (trackForm) {
  trackForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticketId = document.getElementById("trackTicketId").value.trim();
    if (!ticketId) return;

    try {
      const res = await fetch(`${API_BASE}/api/grievances/${encodeURIComponent(ticketId)}`);
      if (!res.ok) throw new Error("Ticket not found or backend unavailable");
      const data = await res.json();

      const trackBox = document.getElementById("trackResult");
      document.getElementById("trackTitle").innerText = `[${data.ticket_id}] ${data.title}`;
      document.getElementById("trackStatus").innerHTML = getStatusPill(data.status);
      document.getElementById("trackCategory").innerText = data.category;
      document.getElementById("trackPriority").innerHTML = getPriorityPill(data.priority);
      document.getElementById("trackDepartment").innerText = data.assigned_department || "Pending Triage";
      document.getElementById("trackSla").innerText = formatDate(data.sla_deadline);

      const logsList = document.getElementById("trackLogs");
      logsList.innerHTML = "";
      if (data.logs && data.logs.length > 0) {
        data.logs.forEach((log) => {
          const li = document.createElement("li");
          li.style.marginBottom = "0.5rem";
          li.innerHTML = `<strong>${formatDate(log.timestamp)} [${log.actor}]:</strong> ${log.details}`;
          logsList.appendChild(li);
        });
      } else {
        logsList.innerHTML = "<li>No audit trail yet.</li>";
      }

      trackBox.classList.add("show");
    } catch (err) {
      alert(err.message);
    }
  });
}

// --- ADMIN DASHBOARD LOGIC ---
const grievancesTableBody = document.getElementById("grievancesTableBody");
if (grievancesTableBody) {
  async function loadDashboardGrievances() {
    const filterStatus = document.getElementById("filterStatus")?.value || "";
    let url = `${API_BASE}/api/grievances`;
    if (filterStatus) {
      url += `?status=${encodeURIComponent(filterStatus)}`;
    }

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("Unable to fetch grievances");
      const list = await res.json();

      // Update statistics
      let total = list.length;
      let active = list.filter((g) => ["SUBMITTED", "ASSIGNED", "IN_PROGRESS"].includes(g.status)).length;
      let escalated = list.filter((g) => g.status === "ESCALATED").length;
      let resolved = list.filter((g) => g.status === "RESOLVED").length;

      document.getElementById("statTotal").innerText = total;
      document.getElementById("statActive").innerText = active;
      document.getElementById("statEscalated").innerText = escalated;
      document.getElementById("statResolved").innerText = resolved;

      // Render table
      if (list.length === 0) {
        grievancesTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">No grievances logged yet.</td></tr>`;
        return;
      }

      grievancesTableBody.innerHTML = list
        .map(
          (g) => `
        <tr>
          <td><strong style="color: #a5b4fc;">${g.ticket_id}</strong></td>
          <td>${g.student_name}<br><small style="color:var(--text-muted);">${g.student_email}</small></td>
          <td>${g.title}</td>
          <td>${g.category}</td>
          <td>${getPriorityPill(g.priority)}</td>
          <td><small>${g.assigned_department || 'Unassigned'}</small></td>
          <td>${getStatusPill(g.status)}</td>
          <td><small>${formatDate(g.sla_deadline)}</small></td>
          <td>
            ${
              g.status !== "RESOLVED"
                ? `<button onclick="resolveTicket('${g.ticket_id}')" class="btn btn-sm" style="background: rgba(16,185,129,0.2); color: #34d399;">Resolve</button>`
                : `<span style="color:#34d399; font-size:0.8rem;">✓ Closed</span>`
            }
          </td>
        </tr>
      `
        )
        .join("");
    } catch (err) {
      grievancesTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: #f87171; padding: 2rem;">Backend offline or error loading data. Run backend main.py!</td></tr>`;
    }
  }

  window.resolveTicket = async function (ticketId) {
    const notes = prompt("Enter resolution summary / action taken:", "Issue addressed and resolved by department.");
    if (notes === null) return;

    try {
      const res = await fetch(`${API_BASE}/api/grievances/${ticketId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution_notes: notes, resolved_by: "Admin" }),
      });
      if (!res.ok) throw new Error("Failed to resolve grievance");
      loadDashboardGrievances();
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  document.getElementById("filterStatus")?.addEventListener("change", loadDashboardGrievances);
  document.getElementById("refreshBtn")?.addEventListener("click", loadDashboardGrievances);

  document.getElementById("triggerEscalationBtn")?.addEventListener("click", async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scheduler/check-escalations`, { method: "POST" });
      if (res.ok) {
        alert("Escalation check triggered successfully!");
        loadDashboardGrievances();
      }
    } catch (err) {
      alert("Error: " + err.message);
    }
  });

  // Initial load
  loadDashboardGrievances();
}
