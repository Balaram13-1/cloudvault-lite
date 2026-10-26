(function () {
  "use strict";

  const form = document.getElementById("login-form");
  const usernameInput = document.getElementById("username");
  const passwordInput = document.getElementById("password");
  const errorEl = document.getElementById("login-error");
  const button = document.getElementById("login-btn");

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    errorEl.textContent = "";

    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    if (!username || !password) {
      errorEl.textContent = "Enter your email and password.";
      return;
    }

    button.disabled = true;
    fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username, password: password }),
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (result) {
        if (result.ok) {
          window.location.href = "/";
          return;
        }
        errorEl.textContent = result.data.error || "Sign in failed.";
        passwordInput.value = "";
        passwordInput.focus();
        button.disabled = false;
      })
      .catch(function () {
        errorEl.textContent = "Could not reach the server. Try again.";
        button.disabled = false;
      });
  });
})();
