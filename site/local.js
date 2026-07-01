/* 病理热力图对比查看器 — Zoomify 瓦片版（带构建进度 & 配对规则）
   功能：
     - 路径输入 → 一键构建瓦片（后端执行 tile_folder.py）
     - 实时进度轮询（进度条 + 日志）
     - 配对规则配置（分隔符模式 / 正则模式）
     - 并排对比 / 叠加 两种查看模式
     - 并排对比中间分隔线
*/
(function () {
  "use strict";

  var currentCase = "";
  var mode = "side";
  var cases = [];
  var pollTimer = null;
  var isBuilding = false;
  var buildStartTime = 0;  // 记录构建开始时间，防止误判

  function $(id) { return document.getElementById(id); }

  // ─── 配对规则 UI 切换 ──────────────────────────────────────────
  window.togglePairMode = function () {
    var radios = document.getElementsByName("pairMode");
    var selected = "delim";
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) { selected = radios[i].value; break; }
    }
    $("delimFields").style.display = selected === "delim" ? "" : "none";
    $("regexFields").style.display = selected === "regex" ? "" : "none";
    updatePairPreview();
  };

  function updatePairPreview() {
    var preview = $("pairPreview");
    var radios = document.getElementsByName("pairMode");
    var selected = "delim";
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) { selected = radios[i].value; break; }
    }
    if (selected === "delim") {
      var delim = $("pairDelim").value || "_";
      var kw = $("pairKeywords").value || "orig,original,HE";
      preview.textContent = "分隔符: \"" + delim + "\" | 原图关键词: " + kw;
    } else {
      var regex = $("pairRegex").value || "";
      preview.textContent = "正则: " + (regex || "（未设置）");
    }
  }

  // 监听配对规则输入变化
  ["pairDelim", "pairKeywords", "pairRegex"].forEach(function (id) {
    var el = $(id);
    if (el) el.addEventListener("input", updatePairPreview);
  });
  updatePairPreview();

  // ─── 构建瓦片 ──────────────────────────────────────────────────
  function getPairParams() {
    var radios = document.getElementsByName("pairMode");
    var pairMode = "delim";
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) { pairMode = radios[i].value; break; }
    }
    var params = { pairMode: pairMode };
    if (pairMode === "delim") {
      params.pairDelim = $("pairDelim").value || "_";
      params.pairKeywords = $("pairKeywords").value || null;
    } else {
      params.pairRegex = $("pairRegex").value || null;
    }
    return params;
  }

  window.startBuild = function () {
    var folder = $("folderPath").value.trim();
    if (!folder) { alert("请先输入文件夹路径"); return; }
    if (isBuilding) { alert("构建正在进行中，请勿重复触发"); return; }

    isBuilding = true;
    $("btnBuild").disabled = true;
    $("btnBuild").textContent = "构建中…";

    // 显示进度区，清空日志
    $("progressArea").classList.add("visible");
    $("progressLog").innerHTML = "";
    $("progressBar").style.width = "0%";
    $("progressLabel").textContent = "等待开始…";
    $("progressPercent").textContent = "0%";

    var body = Object.assign({
      folder: folder,
      force: $("chkForce").checked
    }, getPairParams());

    fetch("/api/build-tiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          addLog(data.error, "log-err");
          resetBuildBtn();
          return;
        }
        addLog("构建已启动: " + folder, "");
        // 开始轮询进度
        startPolling();
      })
      .catch(function (err) {
        addLog("请求失败: " + err.message, "log-err");
        resetBuildBtn();
      });
  };

  function resetBuildBtn() {
    isBuilding = false;
    $("btnBuild").disabled = false;
    $("btnBuild").textContent = "构建瓦片";
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    buildStartTime = Date.now();  // 记录构建开始时间
    var lastCase = "";  // 追踪当前处理的 case，避免重复日志

    // 禁用下拉框并清空选择
    var sel = $("caseSelect");
    sel.innerHTML = '<option value="">构建中，请稍候…</option>';
    sel.disabled = true;

    pollTimer = setInterval(function () {
      fetch("/api/tile-status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data) {
            // 构建开始后 5 秒内得到 null → 进度文件还没写入，继续等待
            if (Date.now() - buildStartTime < 5000) return;
            // 5 秒后仍为 null → 构建已完成
            clearInterval(pollTimer);
            pollTimer = null;
            onBuildComplete();
            return;
          }

          // 处理 "starting" 状态
          if (data.status === "starting") {
            $("progressBar").style.width = "2%";
            $("progressPercent").textContent = "启动中…";
            $("progressLabel").textContent = "正在初始化构建…";
            return;
          }

          var pct = data.percent || 0;
          $("progressBar").style.width = pct + "%";
          $("progressPercent").textContent = Math.round(pct) + "%";

          if (data.status === "done") {
            $("progressBar").style.width = "100%";
            $("progressPercent").textContent = "100%";
            $("progressLabel").textContent = "构建完成！共 " + data.total + " 个步骤";
            clearInterval(pollTimer);
            pollTimer = null;
            onBuildComplete();
            return;
          }

          // 计算剩余时间
          var elapsed = (Date.now() - buildStartTime) / 1000;
          var remaining = "";
          if (pct > 5 && data.current > 0) {
            var totalEstimated = elapsed / (data.current / data.total);
            var remainingSec = Math.max(0, totalEstimated - elapsed);
            if (remainingSec > 60) {
              remaining = " | 剩余约 " + Math.ceil(remainingSec / 60) + " 分钟";
            } else {
              remaining = " | 剩余约 " + Math.ceil(remainingSec) + " 秒";
            }
          }

          if (data.status === "processing" && data.case) {
            var label = "正在处理：" + data.case + "/" + data.role;
            if (data.tiles) label += " → " + data.tiles.toLocaleString() + " 瓦片";
            label += " (" + data.current + "/" + data.total + ")";
            $("progressLabel").textContent = label + remaining;

            // 只在 case 变化时添加日志，避免刷屏
            if (data.case !== lastCase) {
              lastCase = data.case;
              addLog("[" + data.current + "/" + data.total + "] 开始处理 " + data.case, "");
            }
          } else if (data.status === "skip") {
            $("progressLabel").textContent = "跳过 " + data.case + "/" + data.role + " (" + data.current + "/" + data.total + ")" + remaining;
            if (data.case !== lastCase) {
              lastCase = data.case;
              addLog("[" + data.current + "/" + data.total + "] " + data.case + " 已存在，跳过", "log-skip");
            }
          }
        })
        .catch(function () { /* 静默重试 */ });
    }, 1000);
  }

  function addLog(msg, cls) {
    var log = $("progressLog");
    var div = document.createElement("div");
    if (cls) div.className = cls;
    div.textContent = msg;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function onBuildComplete() {
    resetBuildBtn();
    addLog("✓ 构建完成！", "log-done");
    loadCaseList();
  }

  // ─── 加载病理图列表 ─────────────────────────────────────────────
  function loadCaseList() {
    fetch("/api/case-list")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        cases = data.cases || [];
        var sel = $("caseSelect");
        if (!cases.length) {
          sel.innerHTML = '<option value="">未找到瓦片数据</option>';
          sel.disabled = true;
          return;
        }
        sel.disabled = false;
        sel.innerHTML = '<option value="">— 选择病理图（共 ' + cases.length + " 个）—</option>" +
          cases.map(function (c) {
            var flag = (c.orig ? "" : " [缺原图]") + (c.heat ? "" : " [缺热力图]");
            return '<option value="' + c.case + '">' + c.case + flag + "</option>";
          }).join("");
      })
      .catch(function () {
        $("caseSelect").innerHTML = '<option value="">加载失败</option>';
      });
  }

  // ─── Zoomify 查看器（iframe 隔离）───────────────────────────────
  function render() {
    var hint = $("emptyHint");
    if (!currentCase) {
      if (hint) hint.style.display = "";
      updateSeparator();
      return;
    }
    if (hint) hint.style.display = "none";

    var container = $("zoomifyContainer");
    container.innerHTML = '<iframe id="viewerFrame" style="width:100%;height:100%;border:none;" src="viewer-frame.html"></iframe>';
    // 重新添加分隔线
    var sep = document.createElement("div");
    sep.className = "separator-overlay" + (mode === "side" ? " visible" : "");
    sep.id = "sepOverlay";
    container.appendChild(sep);

    setTimeout(function () {
      try {
        var frame = document.getElementById("viewerFrame");
        if (frame && frame.contentWindow) {
          frame.contentWindow.postMessage({
            action: "load",
            case: currentCase,
            mode: mode,
            xmlPath: "tiles/" + currentCase + "/" + (mode === "side" ? "comparison.xml" : "overlay.xml")
          }, "*");
        }
      } catch (err) {
        /* ignore cross-origin */
      }
    }, 300);

    updateSeparator();
  }

  function updateSeparator() {
    var sep = $("sepOverlay");
    if (sep) sep.className = "separator-overlay" + (mode === "side" && currentCase ? " visible" : "");
  }

  // ─── 模式切换 ──────────────────────────────────────────────────
  window.setMode = function (m) {
    mode = m;
    $("btnSide").classList.toggle("active", m === "side");
    $("btnOverlay").classList.toggle("active", m === "overlay");
    $("opacityRow").style.display = (m === "overlay") ? "flex" : "none";
    updateSeparator();
    render();
  };

  // ─── 初始化 ────────────────────────────────────────────────────
  function boot() {
    $("caseSelect").addEventListener("change", function () {
      currentCase = this.value;
      render();
    });

    // 初始加载已有瓦片列表
    loadCaseList();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
