/* Shared changeset card used by project chat. Text is always rendered as text. */
window.renderChangeSet = function renderChangeSet(container, initial) {
  let change = initial;
  async function decide(action) {
    container.querySelectorAll("button").forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(`/api/change-sets/${encodeURIComponent(change.change_set_id)}/${action}`, {method: "POST"});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not update changeset");
      change = data;
      draw();
    } catch (error) {
      draw();
      const message = document.createElement("p");
      message.textContent = error.message;
      message.setAttribute("role", "alert");
      container.append(message);
    }
  }
  function draw() {
    container.replaceChildren();
    const title = document.createElement("p");
    title.textContent = `${change.summary} — ${change.status}`;
    container.append(title);
    const list = document.createElement("ul");
    for (const item of change.items || []) {
      const row = document.createElement("li");
      row.textContent = `${item.field}: ${JSON.stringify(item.before_value)} → ${JSON.stringify(item.after_value)}`;
      list.append(row);
    }
    container.append(list);
    for (const validation of change.validation || []) {
      if (!validation.passed) {
        const error = document.createElement("p");
        error.textContent = validation.message;
        container.append(error);
      }
    }
    if (["pending", "error", "applying", "reverting"].includes(change.status)) {
      for (const action of ["keep", "revert"]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = action === "keep" ? "Keep" : "Revert";
        button.disabled = action === "keep" && change.status !== "pending";
        button.addEventListener("click", () => decide(action));
        container.append(button);
      }
    }
  }
  draw();
};

window.showChangeSet = function showChangeSet(change) {
  const card = createMessage("assistant", "");
  window.renderChangeSet(card, change);
};
