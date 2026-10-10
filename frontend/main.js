(() => {
  "use strict";

  const samples = {
    dependency: {
      log: "Run node scripts/generate-report.js\nnode:internal/modules/cjs/loader:1228\n  throw err;\nError: Cannot find module 'pdfkit'\nRequire stack:\n- /home/runner/work/report/scripts/generate-report.js\n    at Module._resolveFilename (node:internal/modules/cjs/loader:1225:15)\nNode.js v20.11.1\nError: Process completed with exit code 1.",
      workflow: "name: report\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm ci\n      - run: node scripts/generate-report.js",
      question: "What should I change?"
    },
    checkout: {
      log: "Run node scripts/generate-report.js\nError: ENOENT: no such file or directory, open 'scripts/config.json'\nError: Process completed with exit code 1.",
      workflow: "name: report\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: node scripts/generate-report.js",
      question: "Why might the file be missing?"
    },
    permissions: {
      log: "Run gh release create v1.2.0\nHTTP 403: Resource not accessible by integration\nError: Process completed with exit code 1.",
      workflow: "name: release\non: push\njobs:\n  release:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: gh release create v1.2.0",
      question: "Do I need a broader token?"
    },
    unclear: {
      log: "Run ./scripts/build.sh\nError: Process completed with exit code 1.",
      workflow: "name: build\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: ./scripts/build.sh",
      question: ""
    }
  };

  const config = window.ACTIONFIX_CONFIG || {};
  const queryApi = new URLSearchParams(window.location.search).get("api");
  const apiUrl = queryApi || config.apiUrl || "/diagnose";

  const form = document.querySelector("#diagnosis-form");
  const logsInput = document.querySelector("#logs");
  const workflowInput = document.querySelector("#workflow");
  const questionInput = document.querySelector("#question");
  const submitButton = document.querySelector("#submit-button");
  const formStatus = document.querySelector("#form-status");
  const resultPanel = document.querySelector("#result-panel");
  const modelNotice = document.querySelector("#model-notice");
  const commandList = document.querySelector("#command-list");

  const setCount = (input, target, max) => {
    target.textContent = `${input.value.length.toLocaleString()} / ${max.toLocaleString()}`;
  };

  const updateCounts = () => {
    setCount(logsInput, document.querySelector("#log-count"), 12000);
    setCount(workflowInput, document.querySelector("#workflow-count"), 8000);
  };

  const setFormStatus = (message, kind = "") => {
    formStatus.textContent = message;
    formStatus.className = `form-status ${kind}`.trim();
  };

  const setLoading = (loading) => {
    submitButton.disabled = loading;
    submitButton.classList.toggle("loading", loading);
    submitButton.querySelector(".button-label").textContent = loading ? "Reading the evidence…" : "Explain failure";
  };

  const text = (selector, value) => {
    const element = document.querySelector(selector);
    element.textContent = value || "";
  };

  const renderCommands = (commands) => {
    commandList.replaceChildren();
    if (!Array.isArray(commands) || commands.length === 0) {
      commandList.hidden = true;
      return;
    }
    commandList.hidden = false;
    commands.forEach((command) => {
      if (typeof command !== "string" || !command.trim()) return;
      const row = document.createElement("div");
      row.className = "command-row";
      const code = document.createElement("code");
      code.textContent = command;
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "copy-button";
      copy.textContent = "Copy";
      copy.setAttribute("aria-label", `Copy command: ${command}`);
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(command);
          copy.textContent = "Copied";
        } catch (_error) {
          copy.textContent = "Select manually";
        }
        window.setTimeout(() => { copy.textContent = "Copy"; }, 1800);
      });
      row.append(code, copy);
      commandList.append(row);
    });
  };

  const renderResult = (result) => {
    resultPanel.hidden = false;
    text("#result-problem", result.problem);
    text("#result-evidence", result.evidence);
    text("#result-first-fix", result.first_fix);
    text("#result-verify", result.verify);
    text("#result-why", result.why_this_works);
    text("#result-disclaimer", result.disclaimer);
    renderCommands(result.example_commands);

    const badge = document.querySelector("#confidence-badge");
    const confidence = ["low", "medium", "high"].includes(result.confidence) ? result.confidence : "unknown";
    badge.textContent = `${confidence} confidence`;
    badge.className = `confidence-badge ${confidence}`;

    const moreInfo = document.querySelector("#more-info-box");
    moreInfo.hidden = !result.needs_more_info;
    text("#result-question", result.question);

    modelNotice.hidden = !["unavailable", "not_configured"].includes(result.model_status);
    if (result.model_status === "unavailable") {
      modelNotice.textContent = "The full AI explanation is unavailable right now. This result is the deterministic evidence-based fallback.";
    } else if (result.model_status === "not_configured") {
      modelNotice.textContent = "AI explanation is not configured in this environment. This result uses the local evidence checks.";
    } else {
      modelNotice.textContent = "";
    }
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const loadExample = (name) => {
    const sample = samples[name];
    if (!sample) return;
    logsInput.value = sample.log;
    workflowInput.value = sample.workflow;
    questionInput.value = sample.question;
    updateCounts();
    setFormStatus("Example loaded. You can edit it before explaining.");
    logsInput.focus();
  };

  document.querySelectorAll("[data-example]").forEach((button) => {
    button.addEventListener("click", () => loadExample(button.dataset.example));
  });

  logsInput.addEventListener("input", updateCounts);
  workflowInput.addEventListener("input", updateCounts);

  document.querySelector("#clear-button").addEventListener("click", () => {
    form.reset();
    resultPanel.hidden = true;
    setFormStatus("");
    updateCounts();
    logsInput.focus();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!logsInput.value.trim()) {
      setFormStatus("Paste an error log first so I can look for evidence.", "error");
      logsInput.focus();
      return;
    }

    setLoading(true);
    setFormStatus("Checking the log and workflow without running either one…");
    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          log: logsInput.value,
          workflow: workflowInput.value,
          question: questionInput.value
        })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || `Request failed (${response.status})`);
      }
      renderResult(payload);
      setFormStatus(payload.status === "fallback" ? "Here is the evidence-based fallback." : "Diagnosis ready.", payload.status === "fallback" ? "warning" : "success");
    } catch (error) {
      resultPanel.hidden = true;
      setFormStatus(error instanceof Error ? error.message : "Could not reach ActionFix. Try again.", "error");
    } finally {
      setLoading(false);
    }
  });

  updateCounts();
})();
