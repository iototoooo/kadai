// 通知設定画面。
(async () => {
  const form = document.getElementById("settings-form");
  const errorEl = document.getElementById("error");
  const messageEl = document.getElementById("message");
  const lineStatusEl = document.getElementById("line-status");
  const saveButton = document.getElementById("save");
  const testButton = document.getElementById("test");
  const fields = {
    day_before_enabled: document.getElementById("day_before_enabled"),
    day_before_hour: document.getElementById("day_before_hour"),
    same_day_enabled: document.getElementById("same_day_enabled"),
    same_day_hour: document.getElementById("same_day_hour"),
  };

  for (const select of [fields.day_before_hour, fields.same_day_hour]) {
    for (let h = 0; h < 24; h++) {
      const option = document.createElement("option");
      option.value = String(h);
      option.textContent = `${h}:00`;
      select.append(option);
    }
  }

  function syncDisabled() {
    fields.day_before_hour.disabled = !fields.day_before_enabled.checked;
    fields.same_day_hour.disabled = !fields.same_day_enabled.checked;
  }

  function apply(data) {
    const s = data.settings;
    fields.day_before_enabled.checked = s.day_before_enabled;
    fields.day_before_hour.value = String(s.day_before_hour);
    fields.same_day_enabled.checked = s.same_day_enabled;
    fields.same_day_hour.value = String(s.same_day_hour);
    lineStatusEl.textContent = data.line_configured ? "LINE連携: 設定済み" : "LINE連携: 未設定(通知は送信されません)";
    lineStatusEl.className = "small " + (data.line_configured ? "ok-text" : "error-text");
    testButton.disabled = !data.line_configured;
    syncDisabled();
  }

  fields.day_before_enabled.addEventListener("change", syncDisabled);
  fields.same_day_enabled.addEventListener("change", syncDisabled);

  saveButton.disabled = true;
  try {
    apply(await api("/api/settings/notifications"));
    saveButton.disabled = false;
  } catch (e) {
    errorEl.textContent = e.message;
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.textContent = "";
    messageEl.textContent = "";
    saveButton.disabled = true;
    try {
      const data = await api("/api/settings/notifications", {
        method: "PUT",
        body: JSON.stringify({
          day_before_enabled: fields.day_before_enabled.checked,
          day_before_hour: Number(fields.day_before_hour.value),
          same_day_enabled: fields.same_day_enabled.checked,
          same_day_hour: Number(fields.same_day_hour.value),
        }),
      });
      apply(data);
      messageEl.textContent = "保存しました";
    } catch (e) {
      errorEl.textContent = e.message;
    } finally {
      saveButton.disabled = false;
    }
  });

  testButton.addEventListener("click", async () => {
    errorEl.textContent = "";
    messageEl.textContent = "";
    testButton.disabled = true;
    try {
      await api("/api/notifications/test", { method: "POST", body: "{}" });
      messageEl.textContent = "テスト通知を送信しました。LINEを確認してください。";
    } catch (e) {
      errorEl.textContent = e.message;
    } finally {
      testButton.disabled = false;
    }
  });
})();
