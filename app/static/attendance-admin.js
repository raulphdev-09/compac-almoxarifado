"use strict";
(() => {
  const $ = selector => document.querySelector(selector);
  const prefix = "/api/v1/attendance";
  let offset = 0, total = 0, busy = false, codeTimer;
  const works = new Map();
  function message(text, error = false) {
    const box = $("#message"); box.textContent = text; box.classList.toggle("error", error); box.hidden = false;
  }
  async function api(path, options = {}) {
    let response;
    try { response = await fetch(path, {credentials: "same-origin", cache: "no-store", ...options,
      headers: {"X-Compac-Client": "web", ...(options.body ? {"Content-Type": "application/json"} : {})}}); }
    catch { throw Error("Sem conexão. Verifique a rede e atualize a lista antes de repetir uma ação."); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(response.status === 401 ? "Entre no sistema com uma conta administrativa e reabra esta página." : typeof data.detail === "string" ? data.detail : "Não foi possível concluir a ação.");
    return data;
  }
  function clearCode() { clearTimeout(codeTimer); $("#activation-code").value = ""; $("#activation-code").type = "password"; $("#activation-panel").hidden = true; }
  async function load() {
    const page = await api(prefix + `/terminals?limit=20&offset=${offset}`);
    total = page.total; const body = $("#terminals"); body.replaceChildren();
    for (const terminal of page.items) {
      const row = document.createElement("tr");
      for (const value of [terminal.name, works.get(terminal.work_id) || `Obra #${terminal.work_id}`, terminal.active ? "Ativo" : "Revogado"]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      const cell = document.createElement("td"), actions = document.createElement("div"); actions.className = "actions";
      for (const [label, action] of [["Gerar novo código", "activate"], ["Revogar", "revoke"]]) {
        const button = document.createElement("button"); button.type = "button"; button.textContent = label;
        button.className = action === "revoke" ? "danger" : "secondary"; button.disabled = !terminal.active;
        button.addEventListener("click", () => execute(async () => {
          clearCode();
          if (action === "activate") {
            const data = await api(prefix + `/terminals/${terminal.id}/activation`, {method: "POST"});
            $("#activation-code").value = data.activation_code;
            $("#activation-description").textContent = `${terminal.name} · ${works.get(terminal.work_id) || "Obra cadastrada"}. Válido por até ${Math.ceil(data.expires_in / 60)} minutos; use uma única vez.`;
            $("#activation-panel").hidden = false; $("#reveal-code").textContent = "Mostrar código";
            codeTimer = setTimeout(clearCode, data.expires_in * 1000);
            $("#activation-panel").scrollIntoView({block: "nearest", behavior: "auto"});
            message("Código gerado. Os acessos anteriores deste terminal foram invalidados.");
          } else {
            await api(prefix + `/terminals/${terminal.id}/revoke`, {method: "POST"});
            message("Terminal revogado. Ele não poderá registrar novas marcações.");
          }
          await load();
        }));
        actions.append(button);
      }
      cell.append(actions); row.append(cell); body.append(row);
    }
    if (!page.items.length) { const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 4; cell.textContent = "Nenhum terminal cadastrado nesta página."; row.append(cell); body.append(row); }
    $("#previous").disabled = offset === 0; $("#next").disabled = offset + page.items.length >= total;
    $("#page-info").textContent = `${total ? offset + 1 : 0}–${offset + page.items.length} de ${total} terminais`;
  }
  async function execute(operation) {
    if (busy) return; busy = true;
    const buttons = [...document.querySelectorAll("button")]; buttons.forEach(button => button.disabled = true);
    try { await operation(); } catch (error) { message(error.message, true); }
    finally { busy = false; $("#create-button").disabled = false; $("#refresh").disabled = false;
      $("#previous").disabled = offset === 0; $("#next").disabled = offset + 20 >= total;
      $("#copy-code").disabled = false; $("#reveal-code").disabled = false; $("#clear-code").disabled = false;
      if (buttons.some(button => button.isConnected && button.closest("#terminals"))) load().catch(error => message(error.message, true)); }
  }
  $("#terminal-form").addEventListener("submit", event => { event.preventDefault(); execute(async () => {
    await api(prefix + "/terminals", {method: "POST", body: JSON.stringify({name: $("#terminal-name").value.trim(), work_id: Number($("#terminal-work").value)})});
    $("#terminal-name").value = ""; offset = 0; message("Terminal de teste cadastrado."); await load();
  }); });
  $("#refresh").addEventListener("click", () => execute(load));
  $("#previous").addEventListener("click", () => { offset = Math.max(0, offset - 20); execute(load); });
  $("#next").addEventListener("click", () => { offset += 20; execute(load); });
  $("#clear-code").addEventListener("click", clearCode);
  $("#reveal-code").addEventListener("click", () => { const field = $("#activation-code"); field.type = field.type === "password" ? "text" : "password"; $("#reveal-code").textContent = field.type === "password" ? "Mostrar código" : "Ocultar código"; });
  $("#copy-code").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#activation-code").value); message("Código copiado. Informe-o somente no dispositivo autorizado."); }
    catch { message("A cópia automática não está disponível. Revele e copie o código manualmente.", true); }
  });
  addEventListener("pagehide", clearCode);
  (async () => { try {
    const info = await api(prefix + "/status");
    if (!info.enabled) throw Error("O módulo de testes está desativado neste ambiente.");
    const rows = await api("/api/catalog/works"); const select = $("#terminal-work"); select.replaceChildren(new Option("Selecione uma obra ativa", ""));
    for (const work of rows) { works.set(work.id, work.name); if (work.status === "ATIVA") select.append(new Option(work.name, String(work.id))); }
    await load();
  } catch (error) { message(error.message, true); $("#create-button").disabled = true; $("#refresh").disabled = true; } })();
})();
