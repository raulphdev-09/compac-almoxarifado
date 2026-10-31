(() => {
  "use strict";
  const status = document.querySelector("[data-connection-status]");
  function updateStatus() {
    status.textContent = navigator.onLine
      ? "Rede detectada. Toque em tentar novamente para acessar o COMPAC."
      : "Você está sem conexão com a internet.";
  }
  document.querySelector("[data-offline-retry]").addEventListener("click", () => window.location.reload());
  window.addEventListener("online", updateStatus);
  window.addEventListener("offline", updateStatus);
  updateStatus();
})();
