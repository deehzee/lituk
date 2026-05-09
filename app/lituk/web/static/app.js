/* app.js — dispatches to per-page init based on data-page attribute */
"use strict";

const page = document.documentElement.dataset.page;

if (page === "home")      initHome();
else if (page === "session")   initSession();
else if (page === "dashboard") initDashboard();
else if (page === "missed")    initMissed();

/* =========================================================================
   HOME
   ========================================================================= */
function initHome() {
  const pill = document.getElementById("due-pill");
  fetch("/api/dashboard")
    .then(r => r.json())
    .then(d => {
      if (d.due_today > 0) {
        pill.textContent = d.due_today + " due";
        pill.classList.remove("hidden");
      }
    })
    .catch(() => {});

  fetch("/api/topics")
    .then(r => r.json())
    .then(topics => {
      const container = document.getElementById("chapter-checks");
      topics.forEach(t => {
        const label = document.createElement("label");
        label.style.marginRight = "0.75rem";
        label.innerHTML =
          `<input type="checkbox" name="chapters" value="${t.id}"> ${t.name}`;
        container.appendChild(label);
      });
    })
    .catch(() => {});

  document.getElementById("start-form").addEventListener("submit", e => {
    e.preventDefault();
    const form = e.target;
    const mode = form.querySelector("input[name=mode]:checked").value;
    const boxes = Array.from(form.querySelectorAll("input[name=chapters]:checked"));
    const chapters = boxes.map(b => parseInt(b.value, 10));
    fetch("/api/sessions", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({mode, chapters}),
    })
      .then(r => r.json())
      .then(d => { window.location.href = "/session?id=" + d.session_id; })
      .catch(err => alert("Failed to start session: " + err));
  });
}

/* =========================================================================
   SESSION
   ========================================================================= */
function initSession() {
  const params = new URLSearchParams(window.location.search);
  const sid = params.get("id");
  if (!sid) { window.location.href = "/"; return; }

  let lastVersion = -1;
  let cardCount = 0;

  function show(viewId) {
    ["view-prompt","view-feedback","view-summary","view-loading"].forEach(id => {
      document.getElementById(id).classList.add("hidden");
    });
    document.getElementById(viewId).classList.remove("hidden");
  }

  function renderPrompt(payload) {
    cardCount++;
    document.getElementById("session-progress").textContent =
      "Card " + cardCount;
    document.getElementById("question-text").textContent = payload.text;
    const choicesEl = document.getElementById("choices");
    choicesEl.innerHTML = "";
    const submitBtn = document.getElementById("submit-multi");
    submitBtn.classList.add("hidden");

    payload.choices.forEach((choice, i) => {
      const btn = document.createElement("button");
      btn.className = "choice-btn";
      btn.textContent = String.fromCharCode(65 + i) + ". " + choice;
      btn.dataset.index = i;

      if (payload.is_multi) {
        btn.addEventListener("click", () => {
          btn.classList.toggle("selected");
        });
        submitBtn.classList.remove("hidden");
      } else {
        btn.addEventListener("click", () => {
          const indices = [i];
          submitAnswer(indices);
        });
      }
      choicesEl.appendChild(btn);
    });

    submitBtn.onclick = () => {
      const selected = Array.from(
        choicesEl.querySelectorAll(".choice-btn.selected")
      ).map(b => parseInt(b.dataset.index, 10));
      if (selected.length === 0) return;
      submitAnswer(selected);
    };
    show("view-prompt");
  }

  function submitAnswer(indices) {
    fetch("/api/sessions/" + sid + "/answer", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({indices}),
    }).catch(() => {});
  }

  function renderFeedback(payload) {
    document.getElementById("fb-question-text").textContent =
      document.getElementById("question-text").textContent;
    const fbChoices = document.getElementById("fb-choices");
    fbChoices.innerHTML = "";

    payload.choices.forEach((choice, i) => {
      const btn = document.createElement("button");
      btn.className = "choice-btn";
      btn.textContent = String.fromCharCode(65 + i) + ". " + choice;
      btn.disabled = true;
      if (payload.correct_indices.includes(i)) {
        btn.classList.add("correct");
      }
      fbChoices.appendChild(btn);
    });

    const gradeArea = document.getElementById("grade-area");
    const gradeBtns = document.getElementById("grade-btns");
    const gradeLabel = document.getElementById("grade-label");
    gradeBtns.innerHTML = "";

    if (payload.correct) {
      gradeLabel.textContent = "How well did you know it?";
      [["Hard","3"],["Good","4"],["Easy","5"]].forEach(([label, grade]) => {
        const btn = document.createElement("button");
        btn.className = "grade-btn";
        btn.dataset.grade = grade;
        btn.textContent = label;
        btn.addEventListener("click", () => submitGrade(parseInt(grade, 10)));
        gradeBtns.appendChild(btn);
      });
    } else {
      gradeLabel.textContent = "Incorrect — the correct answer is highlighted.";
      const btn = document.createElement("button");
      btn.textContent = "Continue";
      btn.addEventListener("click", () => submitGrade(0));
      gradeBtns.appendChild(btn);
    }
    show("view-feedback");
  }

  function submitGrade(grade) {
    fetch("/api/sessions/" + sid + "/grade", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({grade}),
    }).catch(() => {});
  }

  function renderSummary(payload) {
    document.getElementById("summary-score").textContent =
      "Score: " + payload.correct + " / " + payload.total;
    const weak = payload.weak_facts.length;
    document.getElementById("summary-weak").textContent =
      weak ? weak + " card" + (weak === 1 ? "" : "s") + " need more work." : "Clean sheet!";
    show("view-summary");
  }

  function poll() {
    fetch("/api/sessions/" + sid + "/state")
      .then(r => r.json())
      .then(data => {
        if (data.version === lastVersion) return;
        lastVersion = data.version;
        if (data.kind === "prompt")   renderPrompt(data.payload);
        else if (data.kind === "feedback") renderFeedback(data.payload);
        else if (data.kind === "summary")  { renderSummary(data.payload); return; }
      })
      .catch(() => {});
  }

  show("view-loading");
  setInterval(poll, 300);
  poll();
}

/* =========================================================================
   DASHBOARD
   ========================================================================= */
function initDashboard() {
  fetch("/api/dashboard")
    .then(r => r.json())
    .then(d => {
      // Tiles
      const cov = d.coverage;
      document.getElementById("tile-coverage").textContent =
        cov.pct_seen + "%";
      document.getElementById("tile-coverage-detail").textContent =
        cov.seen + " / " + cov.total + " facts seen";
      document.getElementById("tile-streak").textContent = d.streak;
      document.getElementById("tile-due").textContent = d.due_today;

      // Chapter bars
      const bars = document.getElementById("chapter-bars");
      bars.removeAttribute("aria-busy");
      bars.innerHTML = "";
      d.by_chapter.forEach(ch => {
        const pct = ch.pct_correct;
        const row = document.createElement("div");
        row.className = "bar-row";
        row.innerHTML =
          `<span class="bar-label">${ch.chapter_name}</span>
           <div class="bar-track">
             <div class="bar-fill" style="width:${pct}%"></div>
           </div>
           <span class="bar-pct">${pct}%</span>`;
        bars.appendChild(row);
      });

      // Recent sessions
      const tbody = document.getElementById("sessions-body");
      tbody.innerHTML = "";
      if (d.recent.length === 0) {
        tbody.innerHTML = "<tr><td colspan='2'>No sessions yet.</td></tr>";
      } else {
        d.recent.forEach(s => {
          const dt = new Date(s.started_at).toLocaleDateString();
          const tr = document.createElement("tr");
          tr.innerHTML =
            `<td>${dt}</td><td>${s.correct} / ${s.total}</td>`;
          tbody.appendChild(tr);
        });
      }

      // Weak facts
      const list = document.getElementById("weak-list");
      list.removeAttribute("aria-busy");
      list.innerHTML = "";
      if (d.weak.length === 0) {
        list.innerHTML = "<li>No weak facts yet — keep reviewing!</li>";
      } else {
        d.weak.forEach(f => {
          const li = document.createElement("li");
          li.innerHTML =
            `<a href="/missed?fact=${f.fact_id}">${escHtml(f.question_text)}</a>
             <small> (${f.lapses} lapse${f.lapses === 1 ? "" : "s"})</small>`;
          list.appendChild(li);
        });
      }
    })
    .catch(err => {
      document.querySelector("main").innerHTML +=
        "<p>Failed to load dashboard: " + err + "</p>";
    });
}

/* =========================================================================
   MISSED
   ========================================================================= */
function initMissed() {
  // Load chapter checkboxes
  fetch("/api/topics")
    .then(r => r.json())
    .then(topics => {
      const container = document.getElementById("miss-chapter-checks");
      topics.forEach(t => {
        const label = document.createElement("label");
        label.style.marginRight = "0.5rem";
        label.innerHTML =
          `<input type="checkbox" name="miss-chapters" value="${t.id}"> Ch${t.id}`;
        container.appendChild(label);
      });
    })
    .catch(() => {});

  function loadMissed() {
    const boxes = Array.from(
      document.querySelectorAll("input[name=miss-chapters]:checked")
    ).map(b => b.value);
    const since = document.getElementById("miss-since").value;
    let url = "/api/missed";
    const parts = [];
    if (boxes.length) parts.push("chapters=" + boxes.join(","));
    if (since)        parts.push("since=" + since);
    if (parts.length) url += "?" + parts.join("&");

    fetch(url)
      .then(r => r.json())
      .then(rows => {
        const tbody = document.getElementById("missed-body");
        tbody.innerHTML = "";
        if (rows.length === 0) {
          tbody.innerHTML = "<tr><td colspan='4'>No missed questions.</td></tr>";
          return;
        }
        rows.forEach(r => {
          let correctText = "—";
          try {
            const choices = JSON.parse(r.choices);
            const letters = JSON.parse(r.correct_letters);
            correctText = letters
              .map(l => choices[l.charCodeAt(0) - 65] || l)
              .join(", ");
          } catch (_) {}
          const dt = new Date(r.reviewed_at).toLocaleDateString();
          const tr = document.createElement("tr");
          tr.innerHTML =
            `<td>${escHtml(r.question_text)}</td>
             <td>${escHtml(correctText)}</td>
             <td>${dt}</td>
             <td>${r.miss_count}</td>`;
          tbody.appendChild(tr);
        });
      })
      .catch(err => {
        document.getElementById("missed-body").innerHTML =
          "<tr><td colspan='4'>Error: " + err + "</td></tr>";
      });
  }

  document.getElementById("filter-form").addEventListener("submit", e => {
    e.preventDefault();
    loadMissed();
  });

  document.getElementById("drill-btn").addEventListener("click", () => {
    const boxes = Array.from(
      document.querySelectorAll("input[name=miss-chapters]:checked")
    ).map(b => parseInt(b.value, 10));
    fetch("/api/sessions", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({mode: "drill", chapters: boxes}),
    })
      .then(r => r.json())
      .then(d => { window.location.href = "/session?id=" + d.session_id; })
      .catch(err => alert("Failed to start drill: " + err));
  });

  loadMissed();
}

/* =========================================================================
   Utilities
   ========================================================================= */
function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
