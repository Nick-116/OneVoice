"use strict";
// Sign-in for the Raspberry Pi web interface (served by webserver.py).
document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("loginBtn");
  const err = document.getElementById("loginError");
  btn.disabled = true;
  err.textContent = "";
  try {
    const res = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-OneVoice": "1" },
      body: JSON.stringify({
        username: document.getElementById("username").value.trim(),
        password: document.getElementById("password").value,
      }),
    });
    if (res.ok) {
      location.href = "/";
      return;
    }
    const data = await res.json().catch(() => ({}));
    err.textContent = data.error || "Sign-in failed";
  } catch {
    err.textContent = "Can't reach the Pi";
  } finally {
    btn.disabled = false;
  }
});
