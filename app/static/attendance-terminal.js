"use strict";
(() => {
  const $ = selector => document.querySelector(selector), prefix = "/api/v1/attendance/terminal";
  let paired = false, stream = null, cameraReady = false, busy = false, intent = null, resetTimer, idleTimer;
  let serverOffset = 0, timeZone = "America/Sao_Paulo";
  const labels = {ENTRADA: "Entrada", INICIO_INTERVALO: "Início do intervalo", RETORNO_INTERVALO: "Retorno do intervalo", SAIDA: "Saída"};
  function message(text, info = false) { $("#message").textContent = text; $("#message").classList.toggle("info", info); $("#message").hidden = !text; }
  async function api(path, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(prefix + path, {credentials: "same-origin", cache: "no-store", signal: controller.signal, ...options,
        headers: {"X-Compac-Client": "web", ...(options.body ? {"Content-Type": "application/json"} : {}), ...options.headers}});
      const result = await response.json().catch(() => ({}));
      if (!response.ok) { const error = Error(typeof result.detail === "string" ? result.detail : "Não foi possível concluir. Confira os dados e tente novamente."); error.status = response.status; throw error; }
      return result;
    } catch (error) {
      if (error.status) throw error;
      const failure = Error("Não foi possível confirmar a resposta do servidor. Verifique a conexão."); failure.uncertain = true; throw failure;
    } finally { clearTimeout(timer); }
  }
  function syncClock(data) {
    const timestamp = Date.parse(data.server_time); if (Number.isFinite(timestamp)) serverOffset = timestamp - Date.now();
    if (data.time_zone) timeZone = data.time_zone;
    clock();
  }
  function clock() {
    const now = new Date(Date.now() + serverOffset);
    $("#clock-date").textContent = now.toLocaleDateString("pt-BR", {timeZone, day: "2-digit", month: "long", year: "numeric"});
    $("#clock-time").textContent = now.toLocaleTimeString("pt-BR", {timeZone});
  }
  function controls() {
    $("#mark-button").disabled = !paired || busy || !cameraReady || !navigator.onLine || !$("#success").hidden;
    $("#disconnect").disabled = busy || !!intent;
    $("#review-reset").hidden = !intent;
    $("#review-reset").disabled = busy;
    $("#start-camera").disabled = busy;
    $("#mark-fields").disabled = busy || !!intent || !$("#success").hidden;
    $("#mark-button").textContent = intent ? "Confirmar a mesma marcação de teste" : "Registrar ponto de teste";
    $("#connection-status").textContent = navigator.onLine ? "O horário da marcação será definido pelo servidor." : "Sem internet. Nenhum ponto será enfileirado ou enviado automaticamente.";
  }
  function stopCamera() { cameraReady = false; if (stream) stream.getTracks().forEach(track => track.stop()); stream = null; $("#camera").srcObject = null; $("#camera-status").textContent = "Câmera desligada."; controls(); }
  async function startCamera() {
    if (!paired || busy) return;
    stopCamera();
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      $("#camera-status").textContent = "A câmera exige HTTPS ou localhost e um navegador compatível."; return;
    }
    $("#start-camera").disabled = true; $("#camera-status").textContent = "Solicitando acesso à câmera…";
    try {
      const media = await navigator.mediaDevices.getUserMedia({video: {facingMode: "user"}, audio: false});
      if (!paired) { media.getTracks().forEach(track => track.stop()); return; }
      stream = media; $("#camera").srcObject = stream; await $("#camera").play(); cameraReady = true;
      $("#camera-status").textContent = "Câmera ativa. Pré-visualização local, sem identificação facial.";
      stream.getVideoTracks().forEach(track => track.addEventListener("ended", () => { cameraReady = false; $("#camera-status").textContent = "Câmera interrompida. Ative-a novamente."; controls(); }));
    } catch (error) {
      stopCamera();
      $("#camera-status").textContent = ["NotAllowedError", "SecurityError"].includes(error.name) ? "Permissão de câmera negada. Libere o acesso no navegador e tente novamente." : error.name === "NotFoundError" ? "Nenhuma câmera encontrada. Conecte uma câmera e tente novamente." : "Não foi possível abrir a câmera. Verifique se ela está em uso e tente novamente.";
    } finally { controls(); }
  }
  function showPaired(data) { paired = true; $("#activation-panel").hidden = true; $("#terminal-panel").hidden = false; $("#work-name").textContent = data.work_name; $("#terminal-name").textContent = data.terminal_name; syncClock(data); controls(); }
  function showUnpaired(error) {
    paired = false; stopCamera(); $("#terminal-panel").hidden = true;
    $("#activation-panel").hidden = error?.status === 404;
    if (error) message(error.status === 404 ? "O terminal experimental está desativado neste ambiente." : error.message);
    if (intent) message("Acesso encerrado com uma marcação sem resposta. Solicite ao supervisor a conferência do histórico antes de iniciar outro teste.");
  }
  function resetForm() {
    clearTimeout(resetTimer); intent = null; $("#registration").value = ""; $("#mark-type").value = "ENTRADA"; $("#supervision").checked = false;
    $("#success").hidden = true; controls(); if (paired) $("#registration").focus();
  }
  function idle() { clearTimeout(idleTimer); if (!intent && !busy) idleTimer = setTimeout(() => { if (!intent && !busy) resetForm(); }, 60000); }
  $("#activation-form").addEventListener("submit", async event => {
    event.preventDefault(); if (busy || !navigator.onLine) { message("Conecte o dispositivo à internet para ativá-lo."); return; }
    busy = true; $("#activate-button").disabled = true; const activation_code = $("#activation-code").value.trim(); $("#activation-code").value = "";
    try { const data = await api("/activate", {method: "POST", body: JSON.stringify({activation_code})}); intent = null; resetForm(); showPaired(data); message("Dispositivo ativado. O administrador saiu deste navegador. Ative a câmera para iniciar o teste.", true); }
    catch (error) { message(error.uncertain ? "Ativação sem resposta. Atualize a página para conferir o acesso; se necessário, peça um novo código ao administrador." : error.message); }
    finally { busy = false; $("#activate-button").disabled = false; controls(); }
  });
  $("#start-camera").addEventListener("click", startCamera);
  $("#mark-form").addEventListener("submit", async event => {
    event.preventDefault(); if (busy || !paired || !cameraReady || !navigator.onLine) { controls(); return; }
    if (!intent && !event.currentTarget.reportValidity()) return;
    busy = true; clearTimeout(idleTimer); controls(); message("");
    try {
      if (!intent) {
        const authorization = await api("/test-authorizations", {method: "POST", body: JSON.stringify({registration: $("#registration").value.trim(), acknowledgement: "TESTE_SUPERVISIONADO"})});
        intent = {authorization: authorization.authorization, mark_type: $("#mark-type").value, key: crypto.randomUUID()};
      }
      const result = await api("/mark", {method: "POST", headers: {"Idempotency-Key": intent.key}, body: JSON.stringify({authorization: intent.authorization, mark_type: intent.mark_type})});
      intent = null; $("#registration").value = ""; $("#supervision").checked = false;
      $("#success-detail").textContent = `${labels[result.mark_type] || "Marcação"} · ${new Date(result.marked_at).toLocaleString("pt-BR", {timeZone})}. Resultado simulado.`;
      $("#success").hidden = false; resetTimer = setTimeout(resetForm, 4000);
    } catch (error) {
      if (error.status === 401 || error.status === 403) {
        if (intent) message("Não foi possível confirmar esta marcação. Solicite ao supervisor a conferência antes de outro teste.");
        else message(error.message);
        if (error.status === 401) showUnpaired(error);
      } else if (intent && error.status === 409 && /expirad/i.test(error.message)) {
        intent = null; $("#supervision").checked = false;
        message("A autorização expirou sem confirmar esta tentativa. Confira o resultado com o supervisor antes de iniciar outro teste.");
      } else if (intent) message("Resultado ainda não confirmado. Use o mesmo botão para confirmar a mesma marcação; não refaça em outra janela. " + error.message);
      else message(error.message);
    } finally { busy = false; controls(); if (!intent) idle(); }
  });
  $("#disconnect").addEventListener("click", async () => {
    if (busy || intent) return; busy = true; controls();
    try { await api("/logout", {method: "POST"}); resetForm(); showUnpaired(); message("Dispositivo desconectado.", true); }
    catch (error) { message(error.message); }
    finally { busy = false; controls(); }
  });
  $("#review-reset").addEventListener("click", () => {
    if (busy || !intent) return;
    if (!confirm("O supervisor conferiu no histórico se esta marcação foi registrada? Encerrar a tentativa não apaga registros do servidor.")) return;
    resetForm(); message("Tentativa encerrada após conferência. Nenhum registro do servidor foi apagado.", true);
  });
  $("#registration").addEventListener("input", idle); $("#mark-type").addEventListener("change", idle);
  addEventListener("online", controls); addEventListener("offline", () => { message("Sem internet. Nenhuma marcação será enviada automaticamente."); controls(); });
  const clockTimer = setInterval(clock, 1000);
  const pollTimer = setInterval(async () => { if (!paired || busy || !navigator.onLine) return; try { syncClock(await api("/status")); } catch (error) { if (error.status) showUnpaired(error); } }, 30000);
  addEventListener("pagehide", () => { clearInterval(clockTimer); clearInterval(pollTimer); clearTimeout(idleTimer); clearTimeout(resetTimer); stopCamera(); });
  clock(); controls();
  api("/status").then(showPaired).catch(showUnpaired);
})();
