"use strict";
(() => {
  const $ = selector => document.querySelector(selector);
  const prefix = "/api/v1/attendance";
  let offset = 0, total = 0, busy = false, codeTimer;
  let faceMode = false, faceReady = false, faceBusy = false, faceSelection = null;
  const works = new Map();
  function message(text, error = false) {
    const box = $("#message"); box.textContent = text; box.classList.toggle("error", error); box.hidden = false;
  }
  async function api(path, options = {}) {
    let response;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 30000);
    try { response = await fetch(path, {credentials: "same-origin", cache: "no-store", ...options,
      signal: controller.signal, headers: {"X-Compac-Client": "web", ...(options.body ? {"Content-Type": "application/json"} : {})}}); }
    catch { throw Error("Sem conexão. Verifique a rede e atualize a lista antes de repetir uma ação."); }
    finally { clearTimeout(timeout); }
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
    const buttons = [...document.querySelectorAll("button")].filter(button => !button.closest("#face-reference-section")); buttons.forEach(button => button.disabled = true);
    faceControls();
    try { await operation(); } catch (error) { message(error.message, true); }
    finally { busy = false; $("#create-button").disabled = false; $("#refresh").disabled = false;
      $("#previous").disabled = offset === 0; $("#next").disabled = offset + 20 >= total;
      $("#copy-code").disabled = false; $("#reveal-code").disabled = false; $("#clear-code").disabled = false;
      faceControls();
      if (buttons.some(button => button.isConnected && button.closest("#terminals"))) load().catch(error => message(error.message, true)); }
  }
  function faceMessage(text, error = false) {
    const box = $("#face-message"); box.textContent = text; box.classList.toggle("error", error); box.hidden = !text;
  }
  function faceControls() {
    const locked = busy || faceBusy, selected = faceMode && !!faceSelection;
    $("#face-registration").disabled = locked;
    $("#face-lookup").disabled = locked || !faceMode;
    $("#face-purge-expired").disabled = locked || !faceMode;
    for (const id of ["#face-image", "#face-authorization-basis", "#face-retention-days", "#face-authorization-confirmed"]) $(id).disabled = locked || !selected || !faceReady;
    $("#face-save").disabled = locked || !selected || !faceReady;
    $("#face-delete").disabled = locked || !selected || !faceSelection.has_reference;
  }
  function clearFaceInput() { $("#face-image").value = ""; $("#face-authorization-confirmed").checked = false; }
  function invalidateFaceSelection() {
    faceSelection = null; clearFaceInput();
    $("#face-authorization-basis").value = "";
    $("#face-reference-status").textContent = "Consulte a matrícula para verificar a referência e sua validade.";
    $("#face-save").textContent = "Salvar referência autorizada";
    faceControls();
  }
  function showFaceMetadata(data) {
    faceSelection = {registration: data.registration, has_reference: data.has_reference === true};
    const identity = [data.registration, data.name, data.work_name].filter(Boolean).join(" · ");
    let state = "Sem referência facial cadastrada.";
    if (data.has_reference) {
      const validUntil = Date.parse(data.expires_at);
      state = Number.isFinite(validUntil) ? (validUntil > Date.now() ? "Referência cadastrada. Válida até " : "Referência expirada em ") + new Date(validUntil).toLocaleString("pt-BR") + "." : "Referência cadastrada. Confira a validade com o responsável.";
    }
    $("#face-reference-status").textContent = [identity, state].filter(Boolean).join(" — ");
    $("#face-save").textContent = data.has_reference ? "Atualizar referência autorizada" : "Salvar referência autorizada";
    faceControls();
  }
  async function lookupReference(registration) { return api(prefix + "/face-reference?registration=" + encodeURIComponent(registration)); }
  async function executeFace(operation) {
    if (busy || faceBusy || !faceMode) return;
    faceBusy = true; faceControls(); faceMessage("");
    try { await operation(); } catch (error) { faceMessage(error.message, true); }
    finally { faceBusy = false; faceControls(); }
  }
  function readReferenceFile(file) {
    if (!file || !["image/jpeg", "image/png"].includes(file.type) || file.size > 2 * 1024 * 1024 || file.size === 0) throw Error("Escolha uma fotografia JPEG ou PNG de até 2 MB.");
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => { const data = String(reader.result || ""); reader.onload = null; reader.onerror = null; resolve(data.slice(data.indexOf(",") + 1)); };
      reader.onerror = () => reject(Error("Não foi possível ler a fotografia selecionada."));
      reader.readAsDataURL(file);
    });
  }
  $("#face-registration").addEventListener("input", () => { invalidateFaceSelection(); faceMessage(""); });
  $("#face-reference-form").addEventListener("submit", event => {
    event.preventDefault(); const registration = $("#face-registration").value.trim();
    if (!registration) return;
    executeFace(async () => { invalidateFaceSelection(); showFaceMetadata(await lookupReference(registration)); });
  });
  $("#face-reference-upload-form").addEventListener("submit", event => {
    event.preventDefault();
    if (!faceSelection || !faceReady || !event.currentTarget.reportValidity()) return;
    const registration = faceSelection.registration;
    if (faceSelection.has_reference && !confirm("Atualizar a referência facial invalida as verificações pendentes da versão anterior. Confirma a atualização autorizada?")) return;
    executeFace(async () => {
      let image;
      try {
        image = await readReferenceFile($("#face-image").files[0]);
        await api(prefix + "/face-reference", {method: "POST", body: JSON.stringify({registration, image_base64: image,
          authorization_basis: $("#face-authorization-basis").value.trim(), retention_days: Number($("#face-retention-days").value),
          acknowledgement: "AUTORIZACAO_ORGANIZACIONAL_E_BASE_LEGAL_CONFIRMADAS"})});
        showFaceMetadata(await lookupReference(registration));
        $("#face-authorization-basis").value = "";
        faceMessage("Referência autorizada salva. A imagem não fica disponível por URL pública; verificações pendentes da versão anterior foram invalidadas.");
      } finally { image = null; clearFaceInput(); }
    });
  });
  $("#face-delete").addEventListener("click", () => {
    if (!faceSelection?.has_reference || !confirm("Excluir a referência facial e invalidar suas verificações pendentes? As marcações históricas serão preservadas.")) return;
    const registration = faceSelection.registration;
    executeFace(async () => {
      await api(prefix + "/face-reference?registration=" + encodeURIComponent(registration), {method: "DELETE"});
      clearFaceInput(); showFaceMetadata(await lookupReference(registration));
      faceMessage("Referência facial excluída. As marcações históricas foram preservadas. Siga o procedimento alternativo oficial de ponto quando necessário.");
    });
  });
  $("#face-purge-expired").addEventListener("click", () => {
    if (!confirm("Excluir todas as referências faciais expiradas e invalidar suas verificações pendentes? Marcações históricas serão preservadas.")) return;
    executeFace(async () => {
      const result = await api(prefix + "/face-references/purge-expired", {method: "POST"});
      const registration = faceSelection?.registration;
      if (registration) showFaceMetadata(await lookupReference(registration));
      faceMessage(`${result.deleted} referência(s) expirada(s) excluída(s). As marcações históricas foram preservadas.`);
    });
  });
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
  addEventListener("pagehide", () => { clearCode(); clearFaceInput(); faceSelection = null; });
  (async () => { try {
    const info = await api(prefix + "/status");
    if (!info.enabled) throw Error("O módulo de testes está desativado neste ambiente.");
    faceMode = info.mode === "facial"; faceReady = info.face_ready === true;
    $("#face-reference-section").hidden = !faceMode;
    if (faceMode) {
      $("#mode-intro").textContent = "Cadastre o dispositivo na obra correta e gere um código para ativá-lo. A comparação facial é experimental, exige referência autorizada e permanece restrita a testes supervisionados.";
      $("#mode-footer").textContent = "Protótipo experimental, sem proteção comprovada contra apresentação de fotos ou vídeos. Não substitui o ponto oficial da empresa.";
      $("#face-readiness").textContent = faceReady ? "Verificação facial disponível neste ambiente de teste. Cadastre somente referências cujo tratamento esteja autorizado." : "Verificação facial indisponível. O administrador do ambiente precisa concluir a configuração antes de cadastrar ou atualizar fotografias. A gestão de terminais permanece disponível.";
    }
    faceControls();
    const rows = await api("/api/catalog/works"); const select = $("#terminal-work"); select.replaceChildren(new Option("Selecione uma obra ativa", ""));
    for (const work of rows) { works.set(work.id, work.name); if (work.status === "ATIVA") select.append(new Option(work.name, String(work.id))); }
    await load();
  } catch (error) { message(error.message, true); $("#create-button").disabled = true; $("#refresh").disabled = true; faceMode = false; faceControls(); } })();
})();
