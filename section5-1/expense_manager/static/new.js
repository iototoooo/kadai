(function () {
  const fileInput = document.getElementById("fileInput");
  const preview = document.getElementById("preview");
  const analyzeBtn = document.getElementById("analyzeBtn");
  const analyzeError = document.getElementById("analyzeError");
  const registerBtn = document.getElementById("registerBtn");
  const registerError = document.getElementById("registerError");
  const duplicateWarning = document.getElementById("duplicateWarning");

  const stepUpload = document.getElementById("step-upload");
  const stepConfirm = document.getElementById("step-confirm");
  const stepComplete = document.getElementById("step-complete");

  const accountCategorySelect = document.getElementById("f_account_category");
  const businessSegmentSelect = document.getElementById("f_business_segment");

  let selectedFile = null;
  let requestId = null;
  let overrideHashDuplicate = false;
  let overridePossibleDuplicate = false;

  const NETWORK_ERROR_MESSAGE =
    "通信が不安定なため、処理結果を受信できませんでした。電波状況の良い場所でもう一度お試しください。";

  // fetch()自体が失敗した場合(iOS Safariの"Load failed"、Chromeの"Failed to fetch"等)は
  // ブラウザ実装依存のTypeErrorとして投げられる。HTTPレスポンスとして返ってきた4xx/5xxの
  // JSON(409の重複警告や503のGemini混雑メッセージ等)はここでは対象外で、この場合fetch()は
  // 例外を投げず解決するため、再送されない。TypeErrorの場合のみ、同じ引数で1回だけ自動再送する。
  async function fetchWithNetworkRetry(url, options) {
    try {
      return await fetch(url, options);
    } catch (e) {
      if (!(e instanceof TypeError)) throw e;
      return await fetch(url, options);
    }
  }

  async function loadChoices() {
    const res = await fetch("/api/choices", { credentials: "include" });
    if (!res.ok) return;
    const body = await res.json();
    for (const c of body.account_categories) {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      accountCategorySelect.appendChild(opt);
    }
    for (const s of body.business_segments) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      businessSegmentSelect.appendChild(opt);
    }
  }

  fileInput.addEventListener("change", () => {
    selectedFile = fileInput.files[0] || null;
    analyzeBtn.disabled = !selectedFile;
    if (selectedFile && selectedFile.type.startsWith("image/")) {
      preview.src = URL.createObjectURL(selectedFile);
      preview.style.display = "block";
    } else {
      preview.style.display = "none";
    }
  });

  function fillForm(fields) {
    document.getElementById("f_transaction_date").value = fields.transaction_date || "";
    document.getElementById("f_payee").value = fields.payee || "";
    document.getElementById("f_amount").value = fields.amount ?? "";
    document.getElementById("f_tax_amount").value = fields.tax_amount ?? "";
    document.getElementById("f_tax_rate").value = fields.tax_rate || "";
    document.getElementById("f_tax_rate_10_base").value = fields.tax_rate_10_base ?? "";
    document.getElementById("f_tax_rate_10_amount").value = fields.tax_rate_10_amount ?? "";
    document.getElementById("f_tax_rate_8_base").value = fields.tax_rate_8_base ?? "";
    document.getElementById("f_tax_rate_8_amount").value = fields.tax_rate_8_amount ?? "";
    document.getElementById("f_invoice_registration_number").value = fields.invoice_registration_number || "";
    document.getElementById("f_description").value = fields.description || "";
    accountCategorySelect.value = fields.account_category || "";
    businessSegmentSelect.value = fields.business_segment || "";
    document.getElementById("f_memo").value = fields.memo || "";
    document.getElementById("f_payment_method").value = fields.payment_method || "";
  }

  function readForm() {
    return {
      transaction_date: document.getElementById("f_transaction_date").value || "",
      payee: document.getElementById("f_payee").value || "",
      amount: document.getElementById("f_amount").value || "",
      tax_amount: document.getElementById("f_tax_amount").value || "",
      tax_rate: document.getElementById("f_tax_rate").value || "",
      tax_rate_10_base: document.getElementById("f_tax_rate_10_base").value || "",
      tax_rate_10_amount: document.getElementById("f_tax_rate_10_amount").value || "",
      tax_rate_8_base: document.getElementById("f_tax_rate_8_base").value || "",
      tax_rate_8_amount: document.getElementById("f_tax_rate_8_amount").value || "",
      invoice_registration_number: document.getElementById("f_invoice_registration_number").value || "",
      description: document.getElementById("f_description").value || "",
      account_category: accountCategorySelect.value || "",
      business_segment: businessSegmentSelect.value || "",
      memo: document.getElementById("f_memo").value || "",
      payment_method: document.getElementById("f_payment_method").value || "",
    };
  }

  analyzeBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    analyzeError.textContent = "";
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "解析中...";
    try {
      const fd = new FormData();
      fd.append("file", selectedFile);
      const res = await fetchWithNetworkRetry("/api/analyze", { method: "POST", credentials: "include", body: fd });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || "解析に失敗しました");

      requestId = body.request_id;
      fillForm(body.fields);
      stepUpload.style.display = "none";
      stepConfirm.style.display = "block";
    } catch (e) {
      // TypeErrorはfetch()自体の失敗(ネットワーク層)を表す。ブラウザの生メッセージ
      // (Load failed / Failed to fetch等)はそのまま出さず、安全な日本語文言に置き換える。
      analyzeError.textContent = e instanceof TypeError ? NETWORK_ERROR_MESSAGE : e.message;
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "解析する";
    }
  });

  function showDuplicateWarning(html) {
    // 重複警告の表示中は、選択肢を「重複ではないので登録する(または同一画像でも登録する)」
    // 「登録をやめる」の2つだけに絞り、通常の緑色「登録する」ボタンは非表示にする
    // (誤ってそのまま押せてしまう見た目上の紛らわしさをなくすため)。
    duplicateWarning.innerHTML = html;
    duplicateWarning.style.display = "block";
    registerBtn.style.display = "none";
  }

  function hideDuplicateWarning() {
    duplicateWarning.style.display = "none";
    duplicateWarning.innerHTML = "";
    registerBtn.style.display = "";
  }

  async function submitRegister() {
    registerError.textContent = "";
    hideDuplicateWarning();
    registerBtn.disabled = true;
    registerBtn.textContent = "登録中...";
    try {
      const fd = new FormData();
      fd.append("file", selectedFile);
      fd.append("request_id", requestId);
      const form = readForm();
      for (const [key, value] of Object.entries(form)) {
        fd.append(key, value);
      }
      fd.append("override_hash_duplicate", overrideHashDuplicate ? "true" : "false");
      fd.append("override_possible_duplicate", overridePossibleDuplicate ? "true" : "false");

      const res = await fetchWithNetworkRetry("/api/register", { method: "POST", credentials: "include", body: fd });
      const body = await res.json();

      if (res.status === 409) {
        // 重複の警告。ユーザーの明示的な確認を経てから再送する。
        // 警告中は通常の「登録する」を隠し、2択(上書き登録 / 登録をやめる)のみ表示する。
        if (body.reason === "duplicate_hash") {
          showDuplicateWarning(
            `${body.message}` +
              `<div class="btn-group">` +
              `<button id="forceHash" class="btn">同一画像でも登録する</button>` +
              `<button id="cancelHash" class="btn">登録をやめる</button>` +
              `</div>`
          );
          document.getElementById("forceHash").addEventListener("click", () => {
            overrideHashDuplicate = true;
            submitRegister();
          });
          document.getElementById("cancelHash").addEventListener("click", () => {
            hideDuplicateWarning();
          });
        } else if (body.reason === "possible_duplicate") {
          // 候補1件ずつをカード形式で読みやすく表示する(スマホ幅でも折り返しが破綻しないように)。
          const candidates = body.duplicate_candidates
            .map(
              (c) =>
                `<div class="duplicate-candidate">` +
                `<div><strong>${c.management_number}</strong> ${c.transaction_date}</div>` +
                `<div>${c.payee} / ¥${c.amount.toLocaleString()}</div>` +
                `<div>勘定科目: ${c.account_category} / 事業区分: ${c.business_segment}</div>` +
                `</div>`
            )
            .join("");
          showDuplicateWarning(
            `${body.message}${candidates}` +
              `<div class="btn-group">` +
              `<button id="forcePossible" class="btn">重複ではないので登録する</button>` +
              `<button id="cancelPossible" class="btn">登録をやめる</button>` +
              `</div>`
          );
          document.getElementById("forcePossible").addEventListener("click", () => {
            overridePossibleDuplicate = true;
            submitRegister();
          });
          document.getElementById("cancelPossible").addEventListener("click", () => {
            hideDuplicateWarning();
          });
        } else {
          registerError.textContent = body.message || "登録できませんでした";
        }
        return;
      }

      if (res.status === 503 && body.reason === "drive_auth_expired") {
        registerError.textContent = `${body.error}(管理者による再認可が必要です。しばらくしてから再度お試しください)`;
        return;
      }

      if (!res.ok) throw new Error(body.error || "登録に失敗しました");

      document.getElementById("completeManagementNumber").textContent = body.management_number;
      const link = document.getElementById("completeDriveLink");
      link.href = body.drive_file_url;
      stepConfirm.style.display = "none";
      stepComplete.style.display = "block";
    } catch (e) {
      // analyzeBtn側と同じ方針: fetch()自体の失敗(TypeError)はブラウザの生メッセージを
      // 出さず、安全な日本語文言に置き換える。
      registerError.textContent = e instanceof TypeError ? NETWORK_ERROR_MESSAGE : e.message;
    } finally {
      registerBtn.disabled = false;
      registerBtn.textContent = "登録する";
    }
  }

  registerBtn.addEventListener("click", submitRegister);

  document.getElementById("nextBtn").addEventListener("click", () => {
    selectedFile = null;
    requestId = null;
    overrideHashDuplicate = false;
    overridePossibleDuplicate = false;
    hideDuplicateWarning();
    fileInput.value = "";
    preview.style.display = "none";
    analyzeBtn.disabled = true;
    stepComplete.style.display = "none";
    stepUpload.style.display = "block";
  });

  loadChoices();
})();
