// 新規登録・編集画面(data-todo-idが空なら新規)。
(async () => {
  const form = document.getElementById("todo-form");
  const todoId = form.dataset.todoId;
  const errorEl = document.getElementById("error");
  const metaEl = document.getElementById("meta");
  const saveButton = document.getElementById("save");
  const fields = {
    title: document.getElementById("title"),
    content: document.getElementById("content"),
    due_date: document.getElementById("due_date"),
  };

  function setImportance(value) {
    for (const radio of form.elements.importance) radio.checked = radio.value === value;
  }

  if (todoId) {
    saveButton.disabled = true;
    try {
      const todo = await api(`/api/todos/${encodeURIComponent(todoId)}`);
      fields.title.value = todo.title;
      fields.content.value = todo.content;
      fields.due_date.value = todo.due_date;
      setImportance(todo.importance);
      metaEl.textContent = `登録 ${todo.created_at} ／ 更新 ${todo.updated_at}`;
      saveButton.disabled = false;
    } catch (e) {
      errorEl.textContent = e.message;
      return;
    }
  } else {
    fields.title.focus();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.textContent = "";
    const payload = {
      title: fields.title.value.trim(),
      content: fields.content.value,
      due_date: fields.due_date.value,
      importance: form.elements.importance.value || "中",
    };
    if (!payload.title) {
      errorEl.textContent = "タイトルを入力してください";
      fields.title.focus();
      return;
    }

    saveButton.disabled = true;
    saveButton.textContent = "保存中…";
    try {
      if (todoId) {
        await api(`/api/todos/${encodeURIComponent(todoId)}`, { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api("/api/todos", { method: "POST", body: JSON.stringify(payload) });
      }
      window.location.href = "/";
    } catch (e) {
      errorEl.textContent = e.message;
      saveButton.disabled = false;
      saveButton.textContent = "保存";
    }
  });
})();
