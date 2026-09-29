(async function () {
  const statusEl = document.getElementById("status");
  const listEl = document.getElementById("list");
  const segmentSelect = document.getElementById("filterSegment");

  async function loadChoices() {
    const res = await fetch("/api/choices", { credentials: "include" });
    if (!res.ok) return;
    const body = await res.json();
    for (const seg of body.business_segments) {
      const opt = document.createElement("option");
      opt.value = seg;
      opt.textContent = seg;
      segmentSelect.appendChild(opt);
    }
  }

  function currentQuery() {
    const params = new URLSearchParams();
    const year = document.getElementById("filterYear").value;
    const month = document.getElementById("filterMonth").value;
    const segment = segmentSelect.value;
    if (year) params.set("year", year);
    if (month) params.set("month", month.padStart(2, "0"));
    if (segment) params.set("business_segment", segment);
    return params.toString();
  }

  async function loadList() {
    statusEl.textContent = "読み込み中...";
    listEl.innerHTML = "";
    try {
      const res = await fetch(`/api/expenses?${currentQuery()}`, { credentials: "include" });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "取得に失敗しました");
      const body = await res.json();
      if (body.items.length === 0) {
        statusEl.textContent = "該当する経費がありません";
        return;
      }
      statusEl.textContent = "";
      for (const item of body.items) {
        const row = document.createElement("div");
        row.className = "expense-row";
        row.innerHTML = `
          <div class="expense-row-main">
            <div><strong>${item.management_number}</strong> ${item.transaction_date || ""}</div>
            <div>${item.payee || ""} / ¥${(item.amount ?? 0).toLocaleString()}</div>
            <div style="color:var(--text-muted);font-size:13px">${item.account_category} / ${item.business_segment}</div>
          </div>
          <div class="expense-row-link">${item.drive_file_url ? `<a href="${item.drive_file_url}" target="_blank" rel="noreferrer">証憑</a>` : ""}</div>
        `;
        listEl.appendChild(row);
      }
    } catch (e) {
      statusEl.textContent = e.message;
    }
  }

  document.getElementById("applyFilter").addEventListener("click", loadList);
  document.getElementById("downloadCsv").addEventListener("click", () => {
    window.location.href = `/api/expenses/export.csv?${currentQuery()}`;
  });

  await loadChoices();
  await loadList();
})();
