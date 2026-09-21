/* Project context is explicit and persisted locally; planning never edits files. */
(() => {
  const panel = document.createElement("section");
  panel.className = "project-context";
  const style = document.createElement("style");
  style.textContent = `.project-context{padding:14px;border-bottom:1px solid #ddd;display:grid;gap:8px}
    .project-context input,.project-context select{width:100%;padding:7px;border:1px solid #aaa;border-radius:5px;box-sizing:border-box;color:#222;background:#fff}
    .project-context button,.project-plan button{padding:7px 12px;border-radius:5px;border:1px solid #aaa;cursor:pointer}
    .project-context label{font-size:12px}.project-context p{font-size:12px;overflow-wrap:anywhere;margin:0}
    .project-plan li{overflow-wrap:anywhere;margin:8px 0}.project-context details{font-size:13px}`;
  document.head.append(style);
  const sidebar = document.querySelector(".sidebar-scroll");
  sidebar.prepend(panel);
  function element(tag, text, parent = panel) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    parent.append(node);
    return node;
  }
  element("strong", "Project");
  function field(label, tag = "input", parent = panel) {
    const wrapper = element("label", label, parent);
    const node = element(tag, null, wrapper);
    node.setAttribute("aria-label", label);
    return node;
  }
  const project = field("Selected project", "select");
  const drawing = field("Drawing scope", "select");
  const tag = field("Component tag (optional)");
  tag.placeholder = "P-101";
  const scan = element("button", "Scan project");
  scan.type = "button";
  const find = element("button", "Find component");
  find.type = "button";
  const near = element("button", "Find within 100 mm");
  near.type = "button";
  const status = element("p", "");
  status.setAttribute("role", "status");
  const registration = element("details");
  element("summary", "Register a project folder", registration);
  const name = field("Project name", "input", registration);
  const root = field("Folder path", "input", registration);
  root.placeholder = "C:\\Drawings\\Plant";
  const register = element("button", "Register", registration);
  register.type = "button";
  const shown = new Set();

  async function api(path, method = "GET", body) {
    const response = await fetch(path, {method, headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
    return data;
  }
  function option(select, value, text) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = text;
    select.append(node);
  }
  async function refreshProjects(selected) {
    const data = await api("/api/projects");
    project.replaceChildren();
    option(project, "", "Current session (legacy workflows)");
    for (const p of data.projects) option(project, p.project_id, p.name);
    project.value = selected || "";
    if (project.selectedIndex < 0) project.value = "";
    await switchProject();
  }
  async function refreshDrawings() {
    drawing.replaceChildren();
    option(drawing, "", "All drawings containing the tag");
    if (!project.value) return;
    const data = await api(`/api/projects/${project.value}/drawings`);
    for (const d of data.drawings) option(drawing, d.drawing_id, `${d.filename} — ${d.scan_status}`);
  }
  async function switchProject() {
    try { localStorage.setItem("autocad_ai_project", project.value); } catch (_) {}
    drawing.disabled = tag.disabled = scan.disabled = find.disabled = near.disabled = !project.value;
    status.textContent = project.value ? "Scan the folder before requesting edits. Plans show affected files before applying." : "Select a project to use indexed, reversible edits.";
    await refreshDrawings();
    if (project.value) {
      const data = await api(`/api/projects/${project.value}/change-sets`);
      for (const change of data.change_sets) {
        if (["pending", "error", "applying", "reverting"].includes(change.status) && !shown.has(change.change_set_id)) {
          window.showChangeSet(await api(`/api/change-sets/${change.change_set_id}`));
          shown.add(change.change_set_id);
        }
      }
    }
  }
  function report(error) { status.textContent = error.message || String(error); }
  project.addEventListener("change", () => switchProject().catch(report));
  register.addEventListener("click", async () => {
    register.disabled = true;
    try {
      const result = await api("/api/projects", "POST", {name: name.value, root_path: root.value});
      registration.open = false;
      await refreshProjects(result.project_id);
    } catch (error) { report(error); }
    finally { register.disabled = false; }
  });
  scan.addEventListener("click", async () => {
    scan.disabled = true;
    const selected = project.value;
    status.textContent = "Scanning drawing files…";
    try {
      const result = await api(`/api/projects/${selected}/scan`, "POST");
      status.textContent = `${result.discovered} drawings; ${result.extracted} indexed; ${result.skipped} unchanged. ${result.errors.map(e => `${e.path}: ${e.error}`).join("; ")}`;
      if (project.value === selected) await refreshDrawings();
    } catch (error) { report(error); }
    finally { scan.disabled = !project.value; }
  });
  async function lookup(spatial) {
    if (!tag.value.trim()) throw new Error("Enter a component tag first.");
    const endpoint = spatial ? "nearby" : "entities";
    const data = await api(`/api/projects/${project.value}/${endpoint}?tag=${encodeURIComponent(tag.value.trim())}`);
    const rows = spatial ? data.results.flatMap(r => r.nearby.map(n => `${r.entity.path}: ${n.tag || n.handle} (${n.distance_mm.toFixed(2)} mm)`)) : data.entities.map(e => `${e.path}: ${e.tag} — ${e.entity_type}, handle ${e.handle}`);
    createMessage("assistant", rows.length ? rows.join("\n") : "No indexed matches in the selected project.");
  }
  find.addEventListener("click", () => lookup(false).catch(report));
  near.addEventListener("click", () => lookup(true).catch(report));
  window.projectChat = {
    selected: () => Boolean(project.value),
    async send(prompt) {
      const selected = project.value;
      const projectName = project.options[project.selectedIndex].textContent;
      const progress = createMessage("system", `Planning an edit in ${projectName}…`);
      const job = await api(`/api/projects/${selected}/plan`, "POST", {prompt, tag: tag.value.trim() || null, drawing_id: drawing.value || null});
      if (job.status === "clarify") {
        progress.textContent = "I need one detail before I can plan this edit.";
        createMessage("assistant", job.message);
        return;
      }
      progress.textContent = "Plan ready. Review the affected files before applying.";
      const card = createMessage("assistant", "");
      card.classList.add("project-plan");
      element("strong", `${projectName}: ${prompt}`, card);
      const list = element("ul", null, card);
      for (const item of job.items) {
        const payload = item.operation;
        const preview = payload.preview;
        const detail = preview ? `${preview.field}: ${preview.before} → ${preview.after}` : JSON.stringify(payload.operation);
        element("li", `${payload.operation.target_dwg_path}\n${detail}`, list);
      }
      const button = element("button", `Apply to ${new Set(job.items.map(i => i.drawing_id)).size} drawing(s)`, card);
      button.type = "button";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const result = await api(`/api/projects/jobs/${job.job_id}/execute`, "POST");
          if (result.change_set) {
            window.showChangeSet(result.change_set);
            shown.add(result.change_set.change_set_id);
          }
          button.textContent = result.status === "done" ? "Applied" : "Stopped — review the changeset";
        } catch (error) {
          element("p", error.message, card);
          button.textContent = "Execution stopped. Refresh to review pending changes.";
        }
      });
    }
  };
  let saved = "";
  try { saved = localStorage.getItem("autocad_ai_project") || ""; } catch (_) {}
  refreshProjects(saved).catch(report);
})();
