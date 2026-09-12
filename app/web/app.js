"use strict";

const $ = (id) => document.getElementById(id);

// ---------- API 狀態 ----------
fetch("/api/health").then(r => r.json()).then(d => {
  const el = $("apiStatus");
  if (d.gemini) { el.textContent = "🟢 Gemini 已連線"; el.classList.add("ok"); }
  else { el.textContent = "🟡 未設 API（BM25 檢索＋模板草稿）"; el.classList.add("off"); }
}).catch(() => { $("apiStatus").textContent = "⚠️ 後端未連線"; });

// ---------- 進件模式切換 ----------
document.querySelectorAll('input[name="mode"]').forEach(r => {
  r.addEventListener("change", () => {
    const mode = document.querySelector('input[name="mode"]:checked').value;
    $("pdfArea").classList.toggle("hidden", mode !== "pdf");
    $("manualArea").classList.toggle("hidden", mode !== "manual");
  });
});

// ---------- PDF 拖曳/選擇 ----------
const dz = $("dropzone"), pdfInput = $("pdfInput");
pdfInput.addEventListener("change", () => {
  if (pdfInput.files.length) $("pdfName").textContent = "已選擇：" + pdfInput.files[0].name;
});
["dragover", "dragenter"].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", ev => {
  if (ev.dataTransfer.files.length) {
    pdfInput.files = ev.dataTransfer.files;
    $("pdfName").textContent = "已選擇：" + ev.dataTransfer.files[0].name;
  }
});

// ---------- Loading ----------
function showLoading(text) { $("loadingText").textContent = text || "分析中…"; $("loading").classList.remove("hidden"); }
function hideLoading() { $("loading").classList.add("hidden"); }

// ---------- 開始分析 ----------
$("analyzeBtn").addEventListener("click", async () => {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const fd = new FormData();
  fd.append("mode", mode);
  fd.append("use_llm", $("useLlm").checked);

  if (mode === "pdf") {
    if (!pdfInput.files.length) { alert("請先選擇 PDF 檔案"); return; }
    fd.append("pdf", pdfInput.files[0]);
  } else {
    fd.append("case_type", $("m_case_type").value);
    fd.append("appellant", $("m_appellant").value);
    fd.append("original_authority", $("m_authority").value);
    fd.append("disposition_no", $("m_dispno").value);
    fd.append("behavior_date_roc", $("m_behavior").value);
    fd.append("disposition_date_roc", $("m_disposition").value);
    fd.append("facts", $("m_facts").value);
    fd.append("claims", $("m_claims").value);
    if (!$("m_case_type").value && !$("m_facts").value) { alert("請至少填寫案件類型或違規事實"); return; }
  }

  showLoading($("useLlm").checked ? "分析中（含 AI 擷取）…" : "分析中…");
  try {
    const res = await fetch("/api/analyze", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || "分析失敗");
    const data = await res.json();
    renderResults(data);
    $("placeholder").classList.add("hidden");
    $("resultArea").classList.remove("hidden");
    // 重置草稿區
    $("blockDraft").innerHTML = "";
    $("docxBtn").disabled = true;
  } catch (e) {
    alert("錯誤：" + e.message);
  } finally { hideLoading(); }
});

// ---------- 渲染 ----------
function esc(s) { return (s == null ? "" : String(s)).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }

function renderResults(d) {
  // ① 分類與擷取
  const a = d.appeal;
  $("blockClassify").innerHTML = `
    <div class="classify-badge">${esc(a.case_type) || "未能自動判定，請確認"}</div>
    <div class="kv-grid">
      <div class="kv"><div class="k">訴願人</div><div class="v">${esc(a.appellant) || "—"}</div></div>
      <div class="kv"><div class="k">原處分機關</div><div class="v">${esc(a.original_authority) || "—"}</div></div>
      <div class="kv"><div class="k">原處分書文號</div><div class="v">${esc(a.disposition_no) || "—"}</div></div>
      <div class="kv"><div class="k">行為時 / 處分時</div><div class="v">民國 ${a.behavior_date_roc || "?"} / ${a.disposition_date_roc || "?"} 年</div></div>
      <div class="kv kv-full"><div class="k">違規事實摘要</div><div class="v" style="font-weight:400">${esc(a.facts) || "<span style='color:#c0392b'>（未提供 — 請於進件時填寫或上傳含事實的訴願書）</span>"}</div></div>
      <div class="kv kv-full"><div class="k">訴願人主張／爭點</div><div class="v" style="font-weight:400">${esc(a.claims) || "<span style='color:#c0392b'>（未提供 — 請於進件時填寫或上傳含主張的訴願書）</span>"}</div></div>
    </div>`;

  // ② 法規 + 時效
  let sHtml = "";
  d.statutes.forEach(s => {
    sHtml += `<details class="statute"><summary><span>📖 ${esc(s.statute_name)} ${esc(s.article_no)}</span><span class="score">相關度 ${s.score}</span></summary><div class="content">${esc(s.content)}${s.amend_date ? `\n\n（修正日期：${esc(s.amend_date)}）` : ""}</div></details>`;
  });
  if (d.refs && d.refs.length) {
    sHtml += `<div class="refs"><b>相關函釋／判解</b>`;
    d.refs.forEach(r => {
      const kind = r.source === "interpretation" ? "函釋" : "判解";
      const meta = [r.statute_name, r.article_no].filter(Boolean).join("　·　");
      sHtml += `<details class="statute" style="margin-top:8px">
        <summary><span><span class="tag">${kind}</span>${esc(r.doc_id)}</span><span class="score" style="background:var(--muted)">相關度 ${r.score}</span></summary>
        <div class="content">${meta ? `<div style="color:var(--muted);font-size:12px;margin-bottom:8px">${esc(meta)}</div>` : ""}${esc(r.content) || "（無摘要）"}
        <div style="margin-top:10px"><a class="sim-link" href="/api/reference/${encodeURIComponent(r.doc_id)}" target="_blank" rel="noopener">🔍 查看完整原文 →</a></div>
        </div>
      </details>`;
    });
    sHtml += `</div>`;
  }
  const t = d.timeliness;
  sHtml += `<div class="alert ${t.triggered ? "on" : "off"}">${t.triggered ? "⚠️ " : "ℹ️ "}${esc(t.message)}</div>`;
  $("blockStatutes").innerHTML = sHtml;

  // ③ 相似案例
  let simHtml = "";
  const dist = d.distribution && d.distribution.distribution;
  if (dist && Object.keys(dist).length) {
    simHtml += `<div class="dist">`;
    for (const [res, info] of Object.entries(dist)) {
      simHtml += `<div class="metric"><div class="pct">${Math.round(info.ratio * 100)}%</div><div class="lbl">${esc(res)}（${info.count}件）</div></div>`;
    }
    simHtml += `</div>`;
  }
  d.similar.forEach((c, i) => {
    const shared = (c.shared_statutes && c.shared_statutes.length) ? c.shared_statutes.join("、") : "無共同實體法條";
    const dm = c.dimension_scores || {};
    simHtml += `
      <div class="sim">
        <div class="sim-head">
          <span class="sim-title">${i + 1}. ${c.year}年 ｜ ${esc(c.case_type)}</span>
          <span><span class="result-pill ${esc(c.result)}">${esc(c.result)}</span> <span class="sim-sim">相似度 ${c.similarity}</span></span>
        </div>
        <div class="shared">🔗 與本案共同法條：${esc(shared)}</div>
        <div class="dims">法條重疊 ${dm["法條重疊"] ?? "-"}　·　案件類型 ${dm["案件類型"] ?? "-"}　·　事實語意 ${dm["事實語意"] ?? "-"}</div>
        <div style="margin-top:8px"><a class="sim-link" href="/api/decision/${encodeURIComponent(c.doc_id)}" target="_blank" rel="noopener">🔍 查看完整決定書原文 →</a></div>
      </div>`;
  });
  $("blockSimilar").innerHTML = simHtml;
}

// ---------- 生成草稿 ----------
$("draftBtn").addEventListener("click", async () => {
  showLoading($("useLlm").checked ? "AI 生成草稿中…" : "產生草稿中…");
  try {
    const res = await fetch("/api/draft", { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail || "生成失敗");
    const d = await res.json();
    const mode = d.mode === "llm" ? "AI 三段論生成" : "模板產生（未使用 AI）";
    $("blockDraft").innerHTML = `
      <div class="draft-mode">生成方式：${mode}</div>
      <div class="draft-doc">
        <h4>新北市政府訴願決定書（草稿）</h4>
        <div class="draft-sec"><div class="sh">主　文</div><div class="sb">${esc(d.main)}</div></div>
        <div class="draft-sec"><div class="sh">事　實</div><div class="sb">${esc(d.fact)}</div></div>
        <div class="draft-sec"><div class="sh">理　由</div><div class="sb">${esc(d.reason)}</div></div>
      </div>
      <div class="draft-disclaimer">⚠️ 本草稿由系統輔助生成，法條均取自知識庫原文；仍須承辦人審核確認後定稿。</div>`;
    $("docxBtn").disabled = false;
  } catch (e) { alert("錯誤：" + e.message); }
  finally { hideLoading(); }
});

// ---------- Word 匯出 ----------
$("docxBtn").addEventListener("click", async () => {
  showLoading("產生 Word…");
  try {
    const res = await fetch("/api/draft/docx", { method: "POST" });
    if (!res.ok) throw new Error("匯出失敗");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "訴願決定書草稿.docx";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) { alert("錯誤：" + e.message); }
  finally { hideLoading(); }
});
