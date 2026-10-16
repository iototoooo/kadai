// 一覧画面。表示はすべてtextContentで行い、入力値をHTMLとして解釈させない。
(async () => {
  const statusEl = document.getElementById("status");
  const listEl = document.getElementById("todo-list");

  function formatDue(due) {
    if (!due) return "期日なし";
    const [y, m, d] = due.split("-");
    return `期日 ${y}/${m}/${d}`;
  }

  function isOverdue(due) {
    if (!due) return false;
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    return due < today;
  }

  try {
    const { items } = await api("/api/todos");
    if (items.length === 0) {
      statusEl.textContent = "Todoはまだありません。";
      return;
    }
    statusEl.textContent = "";
    for (const todo of items) {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.className = "todo-card";
      link.href = `/todos/${encodeURIComponent(todo.id)}/edit`;

      const title = document.createElement("span");
      title.className = "todo-title";
      title.textContent = todo.title;

      const due = document.createElement("span");
      due.className = "todo-due" + (isOverdue(todo.due_date) ? " overdue" : "");
      due.textContent = formatDue(todo.due_date);

      link.append(title, due);
      if (todo.content) {
        const content = document.createElement("span");
        content.className = "todo-content";
        content.textContent = todo.content;
        link.append(content);
      }
      li.append(link);
      listEl.append(li);
    }
  } catch (e) {
    statusEl.textContent = e.message;
    statusEl.classList.add("error-text");
  }
})();
