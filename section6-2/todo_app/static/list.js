// 一覧画面。表示はすべてtextContentで行い、入力値をHTMLとして解釈させない。
// 絞り込み(status)と並び順(sort)はURLのクエリに保持し、再読み込みしても維持する。
(() => {
  const statusEl = document.getElementById("status");
  const listEl = document.getElementById("todo-list");
  const filterEl = document.getElementById("status-filter");
  const sortEl = document.getElementById("sort");

  const STATUS_VALUES = ["open", "done", "all"];
  const SORT_VALUES = ["due", "importance"];
  const EMPTY_TEXT = { open: "未完了のTodoはありません。", done: "完了したTodoはありません。", all: "Todoはまだありません。" };
  const IMPORTANCE_CLASS = { 高: "imp-high", 中: "imp-mid", 低: "imp-low" };

  const params = new URLSearchParams(window.location.search);
  const state = {
    status: STATUS_VALUES.includes(params.get("status")) ? params.get("status") : "open",
    sort: SORT_VALUES.includes(params.get("sort")) ? params.get("sort") : "due",
  };

  function syncControls() {
    for (const btn of filterEl.querySelectorAll("button")) {
      btn.setAttribute("aria-checked", String(btn.dataset.status === state.status));
    }
    sortEl.value = state.sort;
    const q = new URLSearchParams({ status: state.status, sort: state.sort });
    window.history.replaceState(null, "", `/?${q}`);
  }

  function formatDue(due) {
    if (!due) return "期日なし";
    const [y, m, d] = due.split("-");
    return `期日 ${y}/${m}/${d}`;
  }

  function todayStr() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }

  function renderItem(todo) {
    const li = document.createElement("li");
    li.className = "todo-item" + (todo.completed ? " is-done" : "");

    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "todo-check";
    check.checked = todo.completed;
    check.setAttribute("aria-label", `${todo.title} を${todo.completed ? "未完了に戻す" : "完了にする"}`);
    check.addEventListener("change", () => toggleCompletion(todo, check, li));

    const link = document.createElement("a");
    link.className = "todo-card";
    link.href = `/todos/${encodeURIComponent(todo.id)}/edit`;

    const head = document.createElement("span");
    head.className = "todo-head";
    const badge = document.createElement("span");
    badge.className = `imp-badge ${IMPORTANCE_CLASS[todo.importance] || "imp-mid"}`;
    badge.textContent = todo.importance;
    const title = document.createElement("span");
    title.className = "todo-title";
    title.textContent = todo.title;
    head.append(badge, title);

    const due = document.createElement("span");
    const overdue = !todo.completed && todo.due_date && todo.due_date < todayStr();
    due.className = "todo-due" + (overdue ? " overdue" : "");
    due.textContent = formatDue(todo.due_date) + (overdue ? "(期限切れ)" : "");

    link.append(head, due);
    if (todo.content) {
      const content = document.createElement("span");
      content.className = "todo-content";
      content.textContent = todo.content;
      link.append(content);
    }
    li.append(check, link);
    return li;
  }

  async function toggleCompletion(todo, check, li) {
    const completed = check.checked;
    check.disabled = true;
    try {
      await api(`/api/todos/${encodeURIComponent(todo.id)}/completion`, {
        method: "PATCH",
        body: JSON.stringify({ completed }),
      });
      todo.completed = completed;
      if (state.status === "all") {
        li.classList.toggle("is-done", completed);
        check.setAttribute("aria-label", `${todo.title} を${completed ? "未完了に戻す" : "完了にする"}`);
      } else {
        // 今の絞り込み条件に合わなくなったので一覧から外す。
        li.remove();
        if (!listEl.children.length) statusEl.textContent = EMPTY_TEXT[state.status];
      }
    } catch (e) {
      check.checked = !completed;
      window.alert(e.message);
    } finally {
      check.disabled = false;
    }
  }

  async function load() {
    syncControls();
    listEl.replaceChildren();
    statusEl.classList.remove("error-text");
    statusEl.textContent = "読み込み中…";
    try {
      const q = new URLSearchParams({ status: state.status, sort: state.sort });
      const { items } = await api(`/api/todos?${q}`);
      statusEl.textContent = items.length ? "" : EMPTY_TEXT[state.status];
      listEl.append(...items.map(renderItem));
    } catch (e) {
      statusEl.textContent = e.message;
      statusEl.classList.add("error-text");
    }
  }

  filterEl.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-status]");
    if (!btn || btn.dataset.status === state.status) return;
    state.status = btn.dataset.status;
    load();
  });
  sortEl.addEventListener("change", () => {
    state.sort = sortEl.value;
    load();
  });

  load();
})();
