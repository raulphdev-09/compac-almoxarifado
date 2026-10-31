(() => {
  "use strict";
  let installPrompt = null;
  let registration = null;
  let reloadAfterUpdate = false;
  let statusTimeout;
  const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const isApple = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(navigator.userAgent);

  function start() {
    const layer = document.createElement("div");
    layer.className = "compac-pwa-layer";
    layer.innerHTML = `
      <section class="compac-pwa-status" role="status" aria-live="polite" hidden>
        <span class="compac-pwa-status-text"></span>
        <button type="button" class="compac-pwa-dismiss" aria-label="Fechar aviso">×</button>
      </section>
      <section class="compac-pwa-update" aria-label="Atualização do aplicativo" hidden>
        <p>Há uma atualização do COMPAC. Salve o que estiver preenchendo antes de atualizar.</p>
        <button type="button" class="compac-pwa-update-open">Ver atualização</button>
        <button type="button" class="compac-pwa-update-dismiss" aria-label="Fechar aviso de atualização">×</button>
      </section>
      <dialog class="compac-pwa-dialog" aria-labelledby="compac-pwa-dialog-title">
        <div class="compac-pwa-dialog-header">
          <span class="compac-pwa-eyebrow">COMPAC · ALMOXARIFADO</span>
          <button type="button" class="compac-pwa-dialog-close" aria-label="Fechar">×</button>
        </div>
        <h2 id="compac-pwa-dialog-title"></h2>
        <div class="compac-pwa-dialog-content"></div>
        <div class="compac-pwa-dialog-actions"></div>
      </dialog>`;
    document.body.append(layer);
    const status = layer.querySelector(".compac-pwa-status");
    const statusText = layer.querySelector(".compac-pwa-status-text");
    const update = layer.querySelector(".compac-pwa-update");
    const dialog = layer.querySelector("dialog");
    const title = layer.querySelector("h2");
    const content = layer.querySelector(".compac-pwa-dialog-content");
    const actions = layer.querySelector(".compac-pwa-dialog-actions");

    function showStatus(message, timeout = 0) {
      window.clearTimeout(statusTimeout);
      statusText.textContent = message;
      status.hidden = false;
      if (timeout) statusTimeout = window.setTimeout(() => { status.hidden = true; }, timeout);
    }
    function closeDialog() {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
    function openDialog(heading, html, buttons) {
      title.textContent = heading;
      content.innerHTML = html;
      actions.replaceChildren();
      for (const button of buttons) {
        const element = document.createElement("button");
        element.type = "button";
        element.textContent = button.label;
        element.className = button.primary ? "compac-pwa-primary" : "compac-pwa-secondary";
        element.addEventListener("click", button.action);
        actions.append(element);
      }
      if (typeof dialog.showModal === "function") {
        if (!dialog.open) dialog.showModal();
      } else dialog.setAttribute("open", "");
    }
    function openInstall() {
      if (isStandalone()) {
        openDialog("O COMPAC já está instalado", "<p>Você está usando o aplicativo instalado. Para consultar dados e salvar alterações, mantenha a conexão com a internet.</p>", [{ label: "Entendi", primary: true, action: closeDialog }]);
        return;
      }
      let instructions;
      if (isApple) instructions = "<ol><li>Abra este endereço no <strong>Safari</strong>.</li><li>Toque em <strong>Compartilhar</strong> (quadrado com seta para cima).</li><li>Escolha <strong>Adicionar à Tela de Início</strong> e confirme em <strong>Adicionar</strong>.</li></ol>";
      else if (isAndroid) instructions = "<ol><li>Abra este endereço no <strong>Chrome</strong>.</li><li>Toque no menu <strong>⋮</strong>.</li><li>Escolha <strong>Instalar aplicativo</strong> ou <strong>Adicionar à tela inicial</strong> e confirme.</li></ol>";
      else instructions = "<p>No Chrome ou Edge, procure o ícone de instalação na barra de endereços ou a opção <strong>Instalar COMPAC</strong> no menu do navegador.</p>";
      const buttons = [{ label: "Fechar", action: closeDialog }];
      if (installPrompt) buttons.unshift({
        label: "Instalar aplicativo", primary: true,
        action: async () => {
          const prompt = installPrompt;
          if (!prompt) return;
          installPrompt = null;
          closeDialog();
          try {
            await prompt.prompt();
            const choice = await prompt.userChoice;
            if (choice.outcome === "accepted") showStatus("Instalação solicitada. Conclua a confirmação do navegador.", 7000);
          } catch { showStatus("A instalação não foi concluída. Você pode tentar novamente pelo menu do navegador.", 8000); }
        },
      });
      openDialog("COMPAC na sua tela inicial", `<p>Acesse o almoxarifado pelo ícone do aplicativo, sem procurar o endereço no navegador.</p>${instructions}<p class="compac-pwa-note"><strong>Os dados exigem internet.</strong> Sem conexão, não é possível consultar ou salvar movimentações. Nenhuma ação fica em uma fila para envio posterior.</p>`, buttons);
    }
    function openUpdate() {
      openDialog("Atualizar o aplicativo", "<p>A atualização recarrega esta página. Salve ou conclua o formulário que estiver aberto antes de continuar.</p>", [
        { label: "Agora não", action: closeDialog },
        { label: "Recarregar e atualizar", primary: true, action: () => {
          closeDialog();
          if (!navigator.onLine) { showStatus("Conecte-se à internet para atualizar. Seu formulário não foi recarregado."); return; }
          if (registration?.waiting) {
            reloadAfterUpdate = true;
            registration.waiting.postMessage({ type: "COMPAC_ACTIVATE_UPDATE" });
          } else {
            update.hidden = true;
            showStatus("A atualização será usada na próxima abertura do aplicativo.", 6000);
          }
        } },
      ]);
    }
    layer.querySelector(".compac-pwa-dismiss").addEventListener("click", () => { status.hidden = true; });
    layer.querySelector(".compac-pwa-dialog-close").addEventListener("click", closeDialog);
    layer.querySelector(".compac-pwa-update-open").addEventListener("click", openUpdate);
    layer.querySelector(".compac-pwa-update-dismiss").addEventListener("click", () => { update.hidden = true; });
    document.addEventListener("click", (event) => {
      if (event.target instanceof Element && event.target.closest("[data-install-app]")) { event.preventDefault(); openInstall(); }
    });
    window.addEventListener("beforeinstallprompt", (event) => { event.preventDefault(); installPrompt = event; });
    window.addEventListener("appinstalled", () => {
      installPrompt = null;
      closeDialog();
      showStatus("COMPAC instalado. Use o ícone na tela inicial para abrir.", 7000);
    });
    window.addEventListener("offline", () => showStatus("Você está sem conexão. Conecte-se para consultar ou salvar dados."));
    window.addEventListener("online", () => showStatus("Conexão restabelecida. Você pode tentar a ação novamente.", 6000));
    if (!navigator.onLine) showStatus("Você está sem conexão. Conecte-se para consultar ou salvar dados.");
    if ("serviceWorker" in navigator && window.isSecureContext) {
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (reloadAfterUpdate) { reloadAfterUpdate = false; window.location.reload(); }
      });
      navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).then((result) => {
        registration = result;
        if (result.waiting) update.hidden = false;
        result.addEventListener("updatefound", () => {
          const worker = result.installing;
          if (worker) worker.addEventListener("statechange", () => {
            if (worker.state === "installed" && navigator.serviceWorker.controller) update.hidden = false;
          });
        });
      }).catch(() => { /* Browser access remains available if installation is unsupported. */ });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
