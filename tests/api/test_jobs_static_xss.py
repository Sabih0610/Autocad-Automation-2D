from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest


class _RenderedRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tags.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.tags.append(tag)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def test_job_row_renders_server_values_as_inert_text() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available for static UI XSS check")

    html = Path("src/api/static/jobs.html").read_text(encoding="utf-8")
    page_script = html.split("  <script>", 1)[1].split("  </script>", 1)[0]
    page_script = page_script.replace(
        "    refreshPageData();",
        "    globalThis.renderPromise = refreshPageData();",
    )
    payload = "<img src=x onerror=globalThis.xss=true>"
    job = {
        "timestamp_start": payload,
        "source": payload,
        "use_case": payload,
        "status": payload,
        "duration_seconds": payload,
        "error_message": payload,
        "job_id": payload,
    }
    harness = r"""
class FakeElement {
  constructor() {
    this.children = [];
    this.value = "";
    this._innerHTML = "";
  }
  set textContent(value) {
    const text = value == null ? "" : String(value);
    this._innerHTML = text
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(value) { this._innerHTML = String(value); }
  appendChild(child) { this.children.push(child); }
  addEventListener() {}
}
const elements = Object.fromEntries(
  ["jobs-body", "job-detail", "use_case", "status", "limit", "refresh"]
    .map((id) => [id, new FakeElement()])
);
elements.limit.value = "50";
globalThis.document = {
  getElementById: (id) => elements[id],
  createElement: () => new FakeElement(),
};
globalThis.window = { location: { search: "" } };
"""
    node_script = (
        harness
        + "\nconst maliciousJobs = "
        + json.dumps([job])
        + ";\nglobalThis.fetch = async () => ({ ok: true, json: async () => maliciousJobs });\n"
        + page_script
        + "\nglobalThis.renderPromise.then(() => {\n"
        + "  const row = elements['jobs-body'].children[0];\n"
        + "  console.log(JSON.stringify({ html: row.innerHTML, xss: globalThis.xss || false }));\n"
        + "});\n"
    )

    completed = subprocess.run(
        [node, "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = json.loads(completed.stdout)
    parser = _RenderedRowParser()
    parser.feed(rendered["html"])

    assert rendered["xss"] is False
    assert "img" not in parser.tags
    assert payload in "".join(parser.text)
    assert "&lt;img src=x onerror=globalThis.xss=true&gt;" in rendered["html"]
    assert "%3Cimg%20src%3Dx%20onerror%3DglobalThis.xss%3Dtrue%3E" in rendered["html"]
