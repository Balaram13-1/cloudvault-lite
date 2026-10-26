(function () {
  "use strict";

  const MAX_BYTES = 10 * 1024 * 1024;
  const ALLOWED = ["pdf", "png", "jpg", "jpeg", "txt", "docx"];
  const FILE_ICON =
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5B6675" stroke-width="1.6" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>';
  const DOWNLOAD_ICON =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 11l5 5 5-5M5 20h14"/></svg>';
  const DELETE_ICON =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';

  const rows = document.getElementById("file-rows");
  const emptyState = document.getElementById("empty-state");
  const countEl = document.getElementById("file-count");
  const statusEl = document.getElementById("status");
  const fileInput = document.getElementById("file-input");
  const chooseBtn = document.getElementById("choose-btn");
  const dropzone = document.getElementById("dropzone");
  const progress = document.getElementById("progress");
  const logoutBtn = document.getElementById("logout-btn");

  function setStatus(message, kind) {
    statusEl.textContent = message || "";
    statusEl.className = "status" + (kind ? " status-" + kind : "");
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function api(url, options) {
    return fetch(url, options).then(function (res) {
      if (res.status === 401) {
        window.location.href = "/login";
        throw new Error("Session expired. Please sign in again.");
      }
      return res
        .json()
        .catch(function () { return {}; })
        .then(function (data) {
          if (!res.ok) throw new Error(data.error || "Request failed");
          return data;
        });
    });
  }

  function makeButton(label, className, icon, ariaLabel, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn " + className;
    button.setAttribute("aria-label", ariaLabel);
    button.innerHTML = icon;
    button.appendChild(document.createTextNode(label));
    button.addEventListener("click", onClick);
    return button;
  }

  function renderFiles(files) {
    rows.textContent = "";
    files
      .slice()
      .sort(function (a, b) { return new Date(b.modified) - new Date(a.modified); })
      .forEach(function (file) {
        const tr = document.createElement("tr");

        const nameTd = document.createElement("td");
        const nameWrap = document.createElement("div");
        nameWrap.className = "name-cell";
        nameWrap.innerHTML = FILE_ICON;
        const nameText = document.createElement("span");
        nameText.className = "name-text";
        nameText.textContent = file.name;
        nameText.title = file.name;
        nameWrap.appendChild(nameText);
        nameTd.appendChild(nameWrap);

        const sizeTd = document.createElement("td");
        sizeTd.textContent = formatSize(file.size);

        const dateTd = document.createElement("td");
        dateTd.className = "muted";
        dateTd.textContent = formatDate(file.modified);

        const actionsTd = document.createElement("td");
        const actions = document.createElement("div");
        actions.className = "actions";
        actions.appendChild(
          makeButton("Download", "btn-outline", DOWNLOAD_ICON, "Download " + file.name, function () {
            downloadFile(file.name);
          })
        );
        actions.appendChild(
          makeButton("Delete", "btn-danger", DELETE_ICON, "Delete " + file.name, function () {
            deleteFile(file.name);
          })
        );
        actionsTd.appendChild(actions);

        tr.appendChild(nameTd);
        tr.appendChild(sizeTd);
        tr.appendChild(dateTd);
        tr.appendChild(actionsTd);
        rows.appendChild(tr);
      });

    countEl.textContent = files.length + (files.length === 1 ? " file" : " files");
    emptyState.hidden = files.length > 0;
  }

  function loadFiles() {
    return api("/api/files")
      .then(function (data) { renderFiles(data.files); })
      .catch(function (err) { setStatus(err.message, "error"); });
  }

  function downloadFile(name) {
    setStatus("Preparing download...", "");
    api("/api/download/" + encodeURIComponent(name))
      .then(function (data) {
        setStatus("Download started. The link expires in " + data.expires_in + " seconds.", "ok");
        window.location.href = data.url;
      })
      .catch(function (err) { setStatus(err.message, "error"); });
  }

  function deleteFile(name) {
    if (!window.confirm('Delete "' + name + '"?\nIt stays recoverable through S3 versioning.')) return;
    api("/api/files/" + encodeURIComponent(name), { method: "DELETE" })
      .then(function () {
        setStatus('Deleted "' + name + '".', "ok");
        return loadFiles();
      })
      .catch(function (err) { setStatus(err.message, "error"); });
  }

  function uploadFile(file) {
    const dot = file.name.lastIndexOf(".");
    const ext = dot === -1 ? "" : file.name.slice(dot + 1).toLowerCase();
    if (ALLOWED.indexOf(ext) === -1) {
      setStatus("That file type is not allowed. Use PDF, PNG, JPG, TXT or DOCX.", "error");
      return;
    }
    if (file.size > MAX_BYTES) {
      setStatus("That file is larger than 10 MB.", "error");
      return;
    }

    const form = new FormData();
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) progress.value = Math.round((event.loaded / event.total) * 100);
    };
    xhr.onload = function () {
      progress.hidden = true;
      chooseBtn.disabled = false;
      if (xhr.status === 401) {
        window.location.href = "/login";
        return;
      }
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* non-JSON error page */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        setStatus('Uploaded "' + data.name + '".', "ok");
        loadFiles();
      } else {
        setStatus(data.error || "Upload failed.", "error");
      }
    };
    xhr.onerror = function () {
      progress.hidden = true;
      chooseBtn.disabled = false;
      setStatus("Upload failed. Check your connection and try again.", "error");
    };

    setStatus('Uploading "' + file.name + '"...', "");
    progress.value = 0;
    progress.hidden = false;
    chooseBtn.disabled = true;
    xhr.send(form);
  }

  chooseBtn.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    if (fileInput.files.length > 0) uploadFile(fileInput.files[0]);
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach(function (type) {
    dropzone.addEventListener(type, function (event) {
      event.preventDefault();
      dropzone.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    dropzone.addEventListener(type, function (event) {
      event.preventDefault();
      dropzone.classList.remove("is-over");
    });
  });
  dropzone.addEventListener("drop", function (event) {
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length > 0) uploadFile(files[0]);
  });

  logoutBtn.addEventListener("click", function () {
    fetch("/api/logout", { method: "POST" }).finally(function () {
      window.location.href = "/login";
    });
  });

  loadFiles();
})();
