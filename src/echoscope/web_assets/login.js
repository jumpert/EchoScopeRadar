"use strict";
const form = document.getElementById("login");
const statusLine = document.getElementById("login-status");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.submitter;
  submit.disabled = true;
  statusLine.textContent = "Verificando acceso…";
  const input = document.getElementById("login-password");
  try {
    const response = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: document.getElementById("login-name").value.trim(), password: input.value }) });
    if (!response.ok) throw new Error((await response.json()).error);
    window.location.reload();
  } catch (error) { statusLine.textContent = error.message || "No se pudo iniciar sesión."; }
  finally { input.value = ""; submit.disabled = false; }
});
