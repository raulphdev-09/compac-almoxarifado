"use strict";
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const E = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const S = {
    user: null,
    schema: {},
    cache: {},
    route: "dashboard",
    version: 0,
    setup: false,
    setupToken: false,
    tab: "movements",
    filter: "",
  };
  const paths = {
    grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    box: "m12 3 9 5-9 5-9-5 9-5Z M3 8v10l9 5 9-5V8 M12 13v10 M7.5 5.5l9 5",
    layers: "m12 3 10 5-10 5L2 8l10-5Z M2 12l10 5 10-5 M2 16l10 5 10-5",
    arrows: "M4 7h16m-4-4 4 4-4 4 M20 17H4m4-4-4 4 4 4",
    arrowUp: "M12 20V4m-6 6 6-6 6 6",
    arrowDown: "M12 4v16m-6-6 6 6 6-6",
    arrowRight: "M4 12h16m-6-6 6 6-6 6",
    arrowUpRight: "M6 18 18 6M6 6h12v12",
    chevron: "m9 5 7 7-7 7",
    clipboard: "M9 4H5v17h14V4h-4 M9 2h6v5H9z M8 12h8 M8 16h5",
    ticket:
      "M3 5h18v5a2 2 0 0 0 0 4v5H3v-5a2 2 0 0 0 0-4V5Z M15 5v3m0 3v2m0 3v3",
    wrench:
      "M14.5 6.5a5.5 5.5 0 0 0-7 7L2 19l3 3 5.5-5.5a5.5 5.5 0 0 0 7-7l-3 3-3-3 3-3Z",
    briefcase: "M8 7V3h8v4 M3 7h18v14H3z M3 12c5 3 13 3 18 0 M10 12h4v4h-4z",
    users:
      "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8",
    user: "M20 21v-2a7 7 0 0 0-14 0v2 M13 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
    wallet:
      "M20 8V5H4a2 2 0 0 1 0-4h14v4 M4 5a2 2 0 0 0-2 2v13h20V8H4 M22 12h-7v5h7 M18 14.5h.01",
    chart: "M3 3v18h18 M7 16v-5 M12 16V7 M17 16V4",
    bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4",
    settings:
      "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3l-.6 2-2 .9-1.8-.6-2 3.4 1.5 1.3v2.3L2.6 14l2 3.4 1.9-.5 2 1 .5 2.1h4l.6-2.1 2-1 1.9.5 2-3.4-1.5-1.4v-2.2l1.5-1.4-2-3.4-1.9.6-2-1L13 3H9Z",
    folder: "M2 5h7l2 3h11v13H2V5Z",
    search: "M21 21l-6-6 M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14",
    plus: "M12 5v14 M5 12h14",
    close: "M6 6l12 12 M6 18 18 6",
    menu: "M3 6h18 M3 12h18 M3 18h18",
    calendar:
      "M4 5h16v16H4z M8 2v6 M16 2v6 M4 10h16 M8 14h.01 M12 14h.01 M16 14h.01 M8 18h.01 M12 18h.01",
    check: "m5 12 4 4L19 6",
    checkCircle: "m8 12 3 3 5-6 M21 12a9 9 0 1 1-5-8",
    warning: "m12 3 10 18H2L12 3Z M12 9v4 M12 17h.01",
    info: "M12 11v6 M12 7h.01 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    download: "M12 3v12m-5-5 5 5 5-5 M4 16v5h16v-5",
    logout: "M9 3H3v18h6 M9 12h12m-5-5 5 5-5 5",
    refresh: "M20 7v5h-5 M4 17v-5h5 M6 5a8 8 0 0 1 14 7 M18 19a8 8 0 0 1-14-7",
    edit: "m15 4 5 5 M3 21l5-1L21 7a2.1 2.1 0 0 0-4-4L4 16l-1 5Z",
    eye: "M2 12c5-10 15-10 20 0-5 10-15 10-20 0Z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
    lock: "M7 10V7a5 5 0 0 1 10 0v3 M5 10h14v12H5z M12 14v4",
    clock: "M12 7v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    pin: "M19 10c0 5-7 12-7 12S5 15 5 10a7 7 0 1 1 14 0Z M12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
    message: "M21 3H3v15h6l3 4 3-4h6V3Z M7 8h10 M7 12h7",
    shield: "M12 2 3 6v6c0 6 9 10 9 10s9-4 9-10V6l-9-4Z m-4 10 3 3 5-6",
    activity: "M2 12h5l3-9 4 18 3-9h5",
    trash: "M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7",
    building: "M4 22V3h12v19 M16 9h4v13 M8 7h4 M8 11h4 M8 15h4 M9 22v-4h3v4",
    target:
      "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0 M12 10v4m-2-2h4",
    history: "M3 3v6h6 M3 9a9 9 0 1 1 0 6 M12 7v5l3 2",
    tag: "M3 3h8l10 10-8 8L3 11V3Z M7 7h.01",
  };
  const icon = (name, cls = "") =>
    `<svg${cls ? ` class="${E(cls)}"` : ""} viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.box}"></path></svg>`;
  const fmt = (v) =>
    new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 }).format(
      Number(v) || 0,
    );
  const money = (v) =>
    new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency: "BRL",
    }).format(Number(v) || 0);
  const date = (v, withTime = false) => {
    if (!v) return "—";
    const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(v) ? v + "T12:00:00" : v);
    return Number.isNaN(d.getTime())
      ? E(v)
      : d.toLocaleString(
          "pt-BR",
          withTime
            ? {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              }
            : { day: "2-digit", month: "2-digit", year: "numeric" },
        );
  };
  const initials = (v) =>
    String(v || "C")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase();
  const canWrite = () => S.user && S.user.role !== "CONSULTA";
  const isAdmin = () => S.user?.role === "ADMIN";
  const roleLabel = (role) =>
    ({
      ADMIN: "Administrador",
      OPERADOR: "Operador",
      CONSULTA: "Somente consulta",
    })[role] || role;
  const entityInfo = {
    works: {
      title: "Obras",
      singular: "obra",
      icon: "building",
      description: "Obras, contratos e frentes de trabalho.",
    },
    categories: {
      title: "Categorias",
      singular: "categoria",
      icon: "tag",
      description: "Organização dos materiais por categoria.",
    },
    locations: {
      title: "Locais de estoque",
      singular: "local",
      icon: "pin",
      description: "Almoxarifados e pontos de armazenamento.",
    },
    employees: {
      title: "Funcionários",
      singular: "funcionário",
      icon: "users",
      description: "Equipes e responsáveis pelos materiais.",
    },
    materials: {
      title: "Materiais",
      singular: "material",
      icon: "box",
      description: "Materiais, unidades e níveis de estoque.",
    },
    equipment: {
      title: "Equipamentos",
      singular: "equipamento",
      icon: "wrench",
      description: "Patrimônio, condições e disponibilidade.",
    },
    expenses: {
      title: "Despesas",
      singular: "despesa",
      icon: "wallet",
      description: "Custos registrados por obra e categoria.",
    },
    consumption_profiles: {
      title: "Perfis de consumo",
      singular: "perfil de consumo",
      icon: "target",
      description: "Consumo de material por unidade produzida.",
    },
    production: {
      title: "Produção",
      singular: "registro de produção",
      icon: "chart",
      description: "Acompanhamento das atividades executadas.",
    },
  };
  const labels = {
    ABERTO: "Aberto",
    EM_ANDAMENTO: "Em andamento",
    RESOLVIDO: "Resolvido",
    CANCELADO: "Cancelado",
    PENDENTE: "Pendente",
    APROVADA: "Aprovada",
    APROVADO: "Aprovado",
    ATENDIDA: "Atendida",
    ATENDIDO: "Atendido",
    CANCELADA: "Cancelada",
    ABERTA: "Aberta",
    FECHADA: "Concluída",
    FECHADO: "Concluído",
    CONCLUIDA: "Concluída",
    NORMAL: "Normal",
    BAIXA: "Baixa",
    ALTA: "Alta",
    URGENTE: "Urgente",
    ENTRADA: "Entrada",
    SAIDA: "Saída",
    DEVOLUCAO: "Devolução",
    TRANSFERENCIA: "Transferência",
    AJUSTE: "Ajuste",
    BOA: "Boa",
    REGULAR: "Regular",
    RUIM: "Ruim",
    DISPONIVEL: "Disponível",
    EM_USO: "Em uso",
    MANUTENCAO: "Em manutenção",
    INATIVO: "Inativo",
    ATIVO: "Ativo",
    PREVENTIVA: "Preventiva",
    CORRETIVA: "Corretiva",
    PLANEJADA: "Planejada",
    FINALIZADA: "Finalizada",
  };
  const human = (v) =>
    labels[v] ||
    String(v ?? "")
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/^./, (c) => c.toUpperCase());
  const badge = (v, force) => {
    const color =
      force ||
      {
        ABERTO: "amber",
        EM_ANDAMENTO: "blue",
        RESOLVIDO: "green",
        CANCELADO: "neutral",
        PENDENTE: "amber",
        APROVADA: "blue",
        APROVADO: "blue",
        ATENDIDA: "green",
        ATENDIDO: "green",
        CANCELADA: "neutral",
        ABERTA: "amber",
        FECHADA: "green",
        FECHADO: "green",
        CONCLUIDA: "green",
        URGENTE: "red",
        ALTA: "amber",
        NORMAL: "blue",
        BAIXA: "neutral",
        ENTRADA: "green",
        SAIDA: "amber",
        DEVOLUCAO: "blue",
        TRANSFERENCIA: "blue",
        AJUSTE: "neutral",
        BOA: "green",
        REGULAR: "amber",
        RUIM: "red",
        DISPONIVEL: "green",
        EM_USO: "blue",
        MANUTENCAO: "amber",
        INATIVO: "neutral",
        ATIVO: "green",
      }[v] ||
      "neutral";
    return `<span class="badge ${color}">${E(human(v))}</span>`;
  };
  function extractError(data) {
    let d =
      data?.detail || data?.message || "Não foi possível concluir a operação.";
    if (Array.isArray(d))
      return d
        .map(
          (x) =>
            `${(x.loc || []).filter((p) => p !== "body").join(" · ")}: ${x.msg || x}`,
        )
        .join("; ");
    return typeof d === "object" ? JSON.stringify(d) : String(d);
  }
  async function api(path, options = {}) {
    const opt = {
      credentials: "same-origin",
      ...options,
      headers: {
        "X-Compac-Client": "web",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    };
    if (opt.body && typeof opt.body !== "string")
      opt.body = JSON.stringify(opt.body);
    let response;
    try {
      response = await fetch("/api" + path, opt);
    } catch (e) {
      throw new Error(
        "Não foi possível conectar. Verifique sua conexão e tente novamente.",
      );
    }
    let data;
    try {
      data = await response.json();
    } catch (e) {
      data = {};
    }
    if (!response.ok) {
      if (response.status === 401 && S.user) {
        S.user = null;
        showAuth();
        toast("Sua sessão terminou. Entre novamente para continuar.", "error");
      }
      throw new Error(extractError(data));
    }
    return data;
  }
  function toast(message, type = "success") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.innerHTML = `${icon(type === "error" ? "warning" : "checkCircle")}<span>${E(message)}</span><button type="button" aria-label="Dispensar">${icon("close")}</button>`;
    $("#toast-region").append(el);
    const limit = window.matchMedia("(max-width: 760px)").matches ? 1 : 3;
    while ($("#toast-region").children.length > limit)
      $("#toast-region").firstElementChild.remove();
    $("button", el).onclick = () => el.remove();
    setTimeout(() => el.remove(), 6500);
  }
  async function catalog(entity, force = false) {
    if (!force && S.cache[entity]) return S.cache[entity];
    const rows = await api("/catalog/" + entity);
    S.cache[entity] = Array.isArray(rows) ? rows : rows.items || [];
    return S.cache[entity];
  }
  async function loadRelations(entity) {
    const fields = S.schema[entity]?.fields || {};
    await Promise.all(
      [
        ...new Set(
          Object.values(fields)
            .map((f) => f.relation)
            .filter(Boolean),
        ),
      ].map((k) => (k === "users" ? loadUsers() : catalog(k))),
    );
  }
  async function loadUsers() {
    if (!S.cache.users) S.cache.users = await api("/users");
    return S.cache.users;
  }
  function recordName(row) {
    return (
      row?.name ||
      row?.description ||
      row?.asset_tag ||
      row?.code ||
      `#${row?.id ?? ""}`
    );
  }
  function lookup(entity, id) {
    if (id === null || id === undefined || id === "") return "—";
    const row = (S.cache[entity] || []).find(
      (r) => String(r.id) === String(id),
    );
    return row ? recordName(row) : `#${id}`;
  }
  function options(rows, selected, placeholder = "Selecione…") {
    return (
      `<option value="">${E(placeholder)}</option>` +
      rows
        .map(
          (r) =>
            `<option value="${E(r.id)}"${String(r.id) === String(selected) ? " selected" : ""}${r.active === false && String(r.id) !== String(selected) ? " disabled" : ""}>${E(recordName(r))}${r.active === false ? " (inativo)" : ""}</option>`,
        )
        .join("")
    );
  }
  function enumOptions(values, selected) {
    return values
      .map((v) => {
        const value = typeof v === "object" ? (v.value ?? v.id) : v;
        const label = typeof v === "object" ? (v.label ?? v.name) : human(v);
        return `<option value="${E(value)}"${String(selected) === String(value) ? " selected" : ""}>${E(label)}</option>`;
      })
      .join("");
  }
  function pageHead(
    title,
    description,
    actions = "",
    eyebrow = "OPERAÇÃO EM FOCO",
  ) {
    return `<div class="page-header"><div class="page-heading"><span class="eyebrow">${E(eyebrow)}</span><h1>${E(title)}</h1><p>${E(description)}</p></div><div class="page-actions">${actions}</div></div>`;
  }
  function empty(
    title,
    description,
    ico = "box",
    action = "",
    compact = false,
  ) {
    return `<div class="empty-state${compact ? " compact" : ""}"><div class="empty-icon">${icon(ico)}</div><h3>${E(title)}</h3><p>${E(description)}</p>${action}</div>`;
  }
  const addButton = (text, action, extra = "") =>
    canWrite()
      ? `<button type="button" class="button primary" data-action="${E(action)}" ${extra}>${icon("plus")}${E(text)}</button>`
      : "";
  const exportButton = (type) =>
    `<a class="button export-button" href="/api/export/${E(type)}" download>${icon("download")}Exportar</a>`;
  function table(headers, rows, cls = "") {
    const filterable = rows.some((row) => row.includes("data-search="));
    return `<div class="table-wrap"><table class="data-table ${cls}"><thead><tr>${headers.map((h) => `<th scope="col">${E(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}${filterable ? `<tr class="filter-empty" hidden><td colspan="${headers.length}">${empty("Nenhum resultado encontrado", "Experimente outro termo ou remova os filtros.", "search", "", true)}</td></tr>` : ""}</tbody></table></div>`;
  }
  function dataPanel(headers, rows, config = {}) {
    const total = rows.length;
    return `<section class="panel"><div class="toolbar"><div class="toolbar-left"><label class="local-search">${icon("search")}<input type="search" data-table-search placeholder="${E(config.placeholder || "Buscar registros…")}" aria-label="Buscar registros"></label>${config.filter || ""}</div><div class="toolbar-right"><span class="table-count" data-table-count${config.countDistinct ? ` data-count-distinct="${E(config.countDistinct)}"` : ""}>${fmt(total)} registro${total === 1 ? "" : "s"}</span>${config.extra || ""}</div></div>${total ? table(headers, rows, config.className || "") : empty(config.emptyTitle || "Tudo pronto para começar", config.emptyText || "Os registros da sua operação aparecerão aqui.", config.icon || "box", config.emptyAction || "")}<div class="table-footer"><span>${E(config.footer || "Dados atualizados da sua operação")}</span><span>${total ? "Deslize para ver mais colunas em telas menores" : "Nenhum registro"}</span></div></section>`;
  }
  function filterRow(text, status = "") {
    return `data-search="${E(String(text).toLowerCase())}" data-status="${E(status)}"`;
  }
  function applyFilters() {
    const local = $("[data-table-search]")?.value || "";
    const global = $("#global-search").value || "";
    const query = (local + " " + global).trim().toLocaleLowerCase("pt-BR");
    const terms = query.split(/\s+/).filter(Boolean);
    const status = $("[data-status-filter]")?.value || "";
    let total = 0;
    const visibleRows = [];
    $$("tr[data-search]").forEach((row) => {
      const show =
        terms.every((t) => row.dataset.search.includes(t)) &&
        (!status || row.dataset.status === status);
      row.hidden = !show;
      if (show) {
        total++;
        visibleRows.push(row);
      }
    });
    const count = $("[data-table-count]");
    if (count) {
      if (count.dataset.countDistinct) {
        const distinct = new Set(
          visibleRows.map((row) => row.dataset[count.dataset.countDistinct]),
        ).size;
        count.textContent = `${fmt(distinct)} ${distinct === 1 ? "material" : "materiais"}`;
      } else
        count.textContent = `${fmt(total)} registro${total === 1 ? "" : "s"}`;
    }
    const noResults = $(".filter-empty");
    if (noResults) noResults.hidden = total !== 0;
    $$("[data-card-search]").forEach((card) => {
      card.hidden = !terms.every((t) => card.dataset.cardSearch.includes(t));
    });
  }
  function statusFilter(values, label = "Todos os status") {
    return `<select data-status-filter aria-label="Filtrar por status"><option value="">${E(label)}</option>${enumOptions(values, "")}</select>`;
  }
  function setPage(html) {
    $("#page-content").innerHTML = html;
    applyFilters();
  }
  function errorPage(error) {
    setPage(
      `<div class="page-error">${icon("warning")}<h2>Não foi possível carregar esta página</h2><p>${E(error.message)}</p><button type="button" class="button primary" data-action="refresh">${icon("refresh")}Tentar novamente</button></div>`,
    );
  }
  function dialog(
    title,
    subtitle,
    body,
    submitLabel = "Salvar",
    onSubmit = null,
    wide = false,
  ) {
    closeSidebar();
    const d = $("#form-dialog");
    if (d.open) d.close();
    d.classList.toggle("wide", wide);
    $("#dialog-content").innerHTML =
      `<div class="dialog-header"><div><span class="eyebrow">COMPAC · SUA OPERAÇÃO</span><h2 id="dialog-title">${E(title)}</h2>${subtitle ? `<p>${E(subtitle)}</p>` : ""}</div><button type="button" class="icon-button" data-dialog-close aria-label="Fechar janela">${icon("close")}</button></div><form id="modal-form"><div class="dialog-body"><div id="modal-error" class="form-error" role="alert" hidden></div>${body}</div><div class="dialog-footer"><button type="button" class="button" data-dialog-close>${onSubmit ? "Cancelar" : "Fechar"}</button>${onSubmit ? `<button type="submit" class="button primary" id="modal-submit">${E(submitLabel)}</button>` : ""}</div></form>`;
    d.showModal();
    const intent = { key: crypto.randomUUID(), payload: null, pending: false };
    $("#modal-form").onsubmit = (e) => e.preventDefault();
    if (onSubmit)
      $("#modal-form").onsubmit = async (e) => {
        e.preventDefault();
        if (intent.pending) return;
        if (!e.currentTarget.reportValidity()) return;
        intent.pending = true;
        const submittedForm = e.currentTarget;
        const modalBody = $(".dialog-body", submittedForm);
        const b = $("#modal-submit");
        b.disabled = true;
        $("#modal-error").hidden = true;
        modalBody.inert = true;
        modalBody.setAttribute("aria-busy", "true");
        try {
          await onSubmit(submittedForm, intent);
          if (d.open && $("#modal-form") === submittedForm) d.close();
        } catch (err) {
          const box = $("#modal-error", submittedForm);
          if (box) {
            box.textContent = err.message;
            box.hidden = false;
            box.scrollIntoView({ block: "nearest" });
          }
        } finally {
          intent.pending = false;
          modalBody.inert = false;
          modalBody.removeAttribute("aria-busy");
          if (b.isConnected) b.disabled = false;
        }
      };
  }
  function formData(form) {
    return Object.fromEntries(new FormData(form).entries());
  }
  function field(
    name,
    label,
    type = "text",
    value = "",
    required = false,
    extra = "",
  ) {
    return `<div class="field${type === "textarea" ? " full" : ""}"><label for="field-${E(name)}">${E(label)}${required ? ' <span class="required-mark">*</span>' : ""}</label>${type === "textarea" ? `<textarea id="field-${E(name)}" name="${E(name)}" ${required ? "required" : ""} ${extra}>${E(value)}</textarea>` : `<input id="field-${E(name)}" name="${E(name)}" type="${E(type)}" value="${E(value)}" ${required ? "required" : ""} ${extra}>`}</div>`;
  }
  function selectField(name, label, opts, required = false, extra = "") {
    return `<div class="field"><label for="field-${E(name)}">${E(label)}${required ? ' <span class="required-mark">*</span>' : ""}</label><select id="field-${E(name)}" name="${E(name)}" ${required ? "required" : ""} ${extra}>${opts}</select></div>`;
  }
  function closeSidebar() {
    const sidebar = $("#sidebar");
    const wasOpen = sidebar.classList.contains("open");
    sidebar.classList.remove("open");
    sidebar.inert = sidebarMedia.matches;
    sidebar.removeAttribute("role");
    sidebar.removeAttribute("aria-modal");
    sidebar.removeAttribute("aria-label");
    $(".app-workspace").inert = false;
    $("#mobile-nav").inert = false;
    $("#sidebar-overlay").hidden = true;
    $$("#menu-toggle,[data-action=menu]").forEach(button => button.setAttribute("aria-expanded", "false"));
    if (wasOpen && sidebarReturnFocus?.isConnected) sidebarReturnFocus.focus();
  }
  function openSidebar() {
    if (!sidebarMedia.matches) return;
    sidebarReturnFocus = document.activeElement;
    const sidebar = $("#sidebar");
    sidebar.inert = false;
    sidebar.classList.add("open");
    sidebar.setAttribute("role", "dialog");
    sidebar.setAttribute("aria-modal", "true");
    sidebar.setAttribute("aria-label", "Navegação do COMPAC");
    $(".app-workspace").inert = true;
    $("#mobile-nav").inert = true;
    $("#sidebar-overlay").hidden = false;
    $$("#menu-toggle,[data-action=menu]").forEach(button => button.setAttribute("aria-expanded", "true"));
    $("#sidebar-close").focus();
  }
  const sidebarMedia = window.matchMedia("(max-width: 760px)");
  let sidebarReturnFocus = null;
  sidebarMedia.addEventListener("change", closeSidebar);
  closeSidebar();

  function refreshPage() {
    S.cache = {};
    return route();
  }

  function localInputDate() {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  }
  const navigation = [
    {
      group: "VISÃO DA OPERAÇÃO",
      items: [
        ["dashboard", "Visão geral", "grid"],
        ["estoque", "Estoque", "box"],
        ["movimentacoes", "Movimentações", "arrows"],
        ["requisicoes", "Requisições", "clipboard"],
        ["chamados", "Chamados", "ticket"],
        ["manutencao", "Manutenção", "wrench"],
      ],
    },
    {
      group: "GESTÃO E PLANEJAMENTO",
      items: [
        ["despesas", "Despesas", "wallet"],
        ["producao", "Produção", "chart"],
        ["previsao", "Previsão de consumo", "target"],
        ["cadastros", "Cadastros", "folder"],
        ["alertas", "Alertas da operação", "bell"],
      ],
    },
    {
      group: "ADMINISTRAÇÃO",
      admin: true,
      items: [
        ["usuarios", "Usuários e acessos", "users"],
        ["auditoria", "Histórico de auditoria", "shield"],
      ],
    },
  ];
  function renderNavigation() {
    const route = S.route.split("/")[0];
    $("#main-nav").innerHTML = navigation
      .filter((g) => !g.admin || isAdmin())
      .map(
        (g) =>
          `<div class="nav-group-label">${g.group}</div>${g.items.map(([id, label, ico]) => `<a href="#${id}" class="nav-link${route === id ? " active" : ""}"${route === id ? ' aria-current="page"' : ""}><span class="nav-icon">${icon(ico)}</span><span>${label}</span></a>`).join("")}`,
      )
      .join("");
    $("#mobile-nav").innerHTML =
      [
        ["dashboard", "Início", "grid"],
        ["estoque", "Estoque", "box"],
        ["requisicoes", "Requisições", "clipboard"],
        ["chamados", "Chamados", "ticket"],
      ]
        .map(
          ([id, label, ico]) =>
            `<a href="#${id}" class="mobile-link${route === id ? " active" : ""}"${route === id ? ' aria-current="page"' : ""}><span class="icon-wrap">${icon(ico)}</span><span>${label}</span></a>`,
        )
        .join("") +
      `<button type="button" class="mobile-link${!["dashboard", "estoque", "requisicoes", "chamados"].includes(route) ? " active" : ""}" data-action="menu"><span class="icon-wrap">${icon("menu")}</span><span>Mais</span></button>`;
  }
  function showAuth() {
    S.user = null;
    if ($("#form-dialog").open) $("#form-dialog").close();
    $("#boot-screen").hidden = true;
    $("#app-shell").hidden = true;
    $("#auth-screen").hidden = false;
    $("#auth-title").textContent = S.setup
      ? "Vamos começar."
      : "Bem-vindo de volta.";
    $("#auth-description").textContent = S.setup
      ? "Crie o primeiro administrador da sua operação."
      : "Entre com suas credenciais para continuar.";
    $("#setup-fields").hidden = !S.setup;
    $("#auth-name").required = S.setup;
    $("#setup-token-field").hidden = !(S.setup && S.setupToken);
    $("#auth-token").required = S.setup && S.setupToken;
    $("#auth-password").autocomplete = S.setup
      ? "new-password"
      : "current-password";
    $("#auth-password").minLength = S.setup ? 10 : 1;
    $("#auth-submit").innerHTML =
      (S.setup ? "Criar minha operação" : "Entrar no COMPAC") +
      ' <span aria-hidden="true">↗</span>';
    $("#auth-help").textContent = S.setup
      ? "O administrador poderá cadastrar a equipe após a configuração."
      : "Precisa de acesso? Fale com o administrador da sua equipe.";
  }
  async function enterApp() {
    S.user = await api("/auth/me");
    const schema = await api("/schema");
    S.schema = schema.ENTITIES || schema.entities || schema;
    S.cache = {};
    $("#boot-screen").hidden = true;
    $("#auth-screen").hidden = true;
    $("#app-shell").hidden = false;
    $("#user-name").textContent = S.user.name;
    $("#user-role").textContent = roleLabel(S.user.role);
    $("#user-avatar").textContent = initials(S.user.name);
    $("#topbar-avatar").textContent = initials(S.user.name);
    await route();
  }
  async function route() {
    if (!S.user) return;
    const routeString = decodeURIComponent(
      location.hash.slice(1) || "dashboard",
    );
    S.route = routeString.replace(/[^a-z0-9_/-]/gi, "");
    const [name, entity] = S.route.split("/");
    const version = ++S.version;
    $("#global-search").value = "";
    closeSidebar();
    renderNavigation();
    const titles = {
      dashboard: "Visão geral",
      estoque: "Estoque",
      movimentacoes: "Movimentações",
      requisicoes: "Requisições",
      chamados: "Chamados",
      manutencao: "Manutenção",
      cadastros: "Cadastros",
      despesas: "Despesas",
      producao: "Produção",
      previsao: "Previsão de consumo",
      alertas: "Alertas da operação",
      usuarios: "Usuários e acessos",
      auditoria: "Histórico de auditoria",
    };
    $("#breadcrumb-current").textContent =
      entityInfo[entity]?.title || titles[name] || "Página";
    document.title = `${$("#breadcrumb-current").textContent} · COMPAC`;
    setPage(
      '<div class="loading-state"><span class="spinner"></span>Organizando as informações…</div>',
    );
    try {
      const renderer = {
        dashboard: renderDashboard,
        estoque: renderStock,
        movimentacoes: renderMovements,
        requisicoes: renderRequisitions,
        chamados: renderTickets,
        manutencao: renderMaintenance,
        cadastros: () => (entity ? renderCatalog(entity) : renderCatalogHome()),
        despesas: () => renderCatalog("expenses"),
        producao: () => renderCatalog("production"),
        previsao: renderForecast,
        alertas: renderAlerts,
        usuarios: renderUsers,
        auditoria: renderAudit,
      }[name];
      if (!renderer) {
        setPage(
          pageHead(
            "Página não encontrada",
            "Escolha uma área no menu para continuar.",
          ) +
            empty(
              "Vamos voltar ao início?",
              "Sua operação está a um clique de distância.",
              "grid",
              '<a href="#dashboard" class="button primary">Ir para visão geral</a>',
            ),
        );
        return;
      }
      const html = await renderer();
      if (version === S.version && S.user) {
        setPage(html);
        if (name === "previsao") bindForecast();
      }
    } catch (e) {
      if (version === S.version && S.user) errorPage(e);
    }
  }
  async function renderDashboard() {
    const d = await api("/dashboard");
    const alerts = d.alerts || [];
    const recent = d.recent || [];
    const costs = d.expense_by_work || [];
    $("#notification-dot").hidden = !alerts.length;
    const today = new Date().toLocaleDateString("pt-BR", {
      day: "numeric",
      month: "long",
    });
    const h = new Date().getHours();
    const greeting = h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite";
    const first = S.user.name.split(" ")[0];
    const alertRows = alerts
      .slice(0, 3)
      .map(
        (a) =>
          `<div class="alert-item"><div class="alert-symbol ${a.priority === "URGENTE" || a.priority === "ALTA" ? "red" : ""}">${icon(a.type?.includes("ESTOQUE") ? "box" : "warning")}</div><div class="alert-copy"><strong>${E(a.message)}</strong><p>${E(human(a.type || "Alerta da operação"))}</p></div><a href="#${moduleRoute(a.module)}" aria-label="Abrir área do alerta">${icon("chevron")}</a></div>`,
      )
      .join("");
    const max = Math.max(
      ...costs.map((r) => Number(r.total || r.amount) || 0),
      1,
    );
    const recentRows = recent
      .slice(0, 5)
      .map(
        (r) =>
          `<tr><td class="primary-cell">${E(r.material || r.description || r.title || "Movimentação")}<span class="cell-subtitle">${E(r.origin || r.destination || r.author || "Almoxarifado")}</span></td><td>${badge(r.type || "ENTRADA")}</td><td><span class="quantity">${fmt(r.quantity)}</span><span class="unit">${E(r.unit || "")}</span></td><td>${date(r.created_at)}</td><td>${icon("arrowUpRight")}</td></tr>`,
      );
    return (
      pageHead(
        "Visão geral",
        "O que acontece na sua operação, em um só lugar.",
        `<div class="date-pill">${icon("calendar")}${E(today)}</div>`,
        "SEU DIA, SOB CONTROLE",
      ) +
      `<section class="welcome-banner"><div class="welcome-content"><span class="eyebrow light">PRONTO PARA MAIS UM DIA?</span><h2>${E(greeting)}, <span class="welcome-title">${E(first)}.</span></h2><p>Acompanhe os materiais, organize as demandas e mantenha a operação em movimento.</p></div>${canWrite() ? `<button type="button" class="button lime" data-action="new-movement">${icon("plus")}Nova movimentação ${icon("arrowUpRight")}</button>` : `<a class="button lime" href="#estoque">Consultar estoque ${icon("arrowUpRight")}</a>`}</section><div class="stats-grid">${statCard("Materiais cadastrados", d.materials, "box", "Base de materiais da operação", "estoque")}${statCard("Chamados em aberto", d.open_tickets, "ticket", "Acompanhe as demandas da equipe", "chamados")}${statCard("Requisições pendentes", d.pending_requisitions, "clipboard", "Solicitações aguardando andamento", "requisicoes")}${statCard("Despesas registradas", d.expenses, "wallet", "Total acumulado nas obras", "despesas", true)}</div><div class="dashboard-grid"><section class="panel table-panel"><div class="panel-header"><div><h2>Últimas movimentações</h2><p>O fluxo mais recente do seu almoxarifado</p></div><a href="#movimentacoes" class="text-link">Ver todas ${icon("arrowUpRight")}</a></div>${recentRows.length ? table(["Material", "Tipo", "Quantidade", "Data", ""], recentRows, "dashboard-table") : empty("Seu estoque começa por aqui", "Cadastre os materiais e registre a primeira movimentação para acompanhar seu fluxo.", "arrows", canWrite() ? '<button type="button" class="button small" data-action="new-movement">Registrar movimentação</button>' : "", true)}</section><section class="panel"><div class="panel-header"><div><h2>Fique de olho</h2><p>Pontos que merecem sua atenção</p></div><span class="badge ${alerts.length ? "amber" : "green"}">${alerts.length ? `${fmt(alerts.length)} alertas` : "Em dia"}</span></div>${alertRows ? `<div class="alerts-list">${alertRows}</div><div class="panel-body alert-panel-link"><a href="#alertas" class="text-link">Ver todos os alertas ${icon("arrowRight")}</a></div>` : empty("Tudo em ordem por aqui", "Os alertas de estoque, prazos e manutenção aparecerão neste espaço.", "checkCircle", "", true)}</section><section class="panel"><div class="panel-header"><div><h2>Despesas por obra</h2><p>Onde os recursos estão sendo aplicados</p></div><a href="#despesas" class="text-link">Detalhes ${icon("arrowUpRight")}</a></div><div class="panel-body">${
        costs.length
          ? `<div class="expense-chart">${costs
              .slice(0, 5)
              .map(
                (r) =>
                  `<div class="expense-bar-row"><div class="expense-bar-label"><span>${E(r.name || r.work || "Obra")}</span><strong>${money(r.total || r.amount)}</strong></div><progress class="expense-progress" value="${Number(r.total || r.amount) || 0}" max="${max}" aria-label="Despesa de ${E(r.name || r.work)}">${money(r.total || r.amount)}</progress></div>`,
              )
              .join(
                "",
              )}<div class="expense-chart-note"><i></i>Total de despesas registradas por obra</div></div>`
          : empty(
              "Custos à vista",
              "Registre as despesas das obras para acompanhar a distribuição dos recursos.",
              "chart",
              "",
              true,
            )
      }</div></section><section class="panel"><div class="panel-header"><div><h2>Atalhos para o seu dia</h2><p>Menos caminhos. Mais ação.</p></div><span class="panel-label">${icon("grid")}</span></div><div class="panel-body"><div class="quick-grid">${quickAction("Consultar estoque", "Saldos e disponibilidade", "box", "estoque")}${quickAction("Nova requisição", "Materiais para a obra", "clipboard", "requisicoes", canWrite() ? "new-requisition" : "")}${quickAction("Abrir chamado", "Conecte a sua equipe", "ticket", "chamados", canWrite() ? "new-ticket" : "")}${quickAction("Empréstimos", "Materiais com a equipe", "users", "movimentacoes", "show-loans")}</div></div><div class="table-footer"><span>${fmt(d.open_loans)} empréstimo${Number(d.open_loans) === 1 ? "" : "s"} em aberto</span><a href="#movimentacoes" class="text-link">Acompanhar ${icon("arrowRight")}</a></div></section></div>`
    );
  }
  function statCard(label, value, ico, foot, route, currency = false) {
    return `<a href="#${route}" class="stat-card"><div class="stat-top"><span>${E(label)}</span><span class="stat-icon">${icon(ico)}</span></div><div class="stat-value${currency ? " currency" : ""}">${currency ? money(value) : fmt(value)}</div><div class="stat-foot"><i></i><span>${E(foot)}</span></div></a>`;
  }
  function quickAction(title, description, ico, href, action = "") {
    return `<${action ? 'button type="button"' : "a"} class="quick-action" ${action ? `data-action="${action}"` : `href="#${href}"`}><span class="quick-icon">${icon(ico)}</span><span><strong>${E(title)}</strong><small>${E(description)}</small></span>${icon("arrowUpRight", "arrow")}</${action ? "button" : "a"}>`;
  }
  function moduleRoute(module) {
    return (
      {
        stock: "estoque",
        loans: "movimentacoes",
        maintenance: "manutencao",
        tickets: "chamados",
        requisitions: "requisicoes",
        materials: "cadastros/materials",
        equipment: "cadastros/equipment",
      }[module] ||
      module ||
      "alertas"
    );
  }
  async function renderStock() {
    const rows = await api("/stock");
    S.stock = rows;
    const totals = new Map();
    for (const row of rows) {
      const key = String(row.material_id);
      const material = totals.get(key) || {
        quantity: 0,
        minimum: Math.round(Number(row.minimum_stock) * 1000),
      };
      material.quantity += Math.round(Number(row.quantity) * 1000);
      totals.set(key, material);
    }
    const materials = [...totals.values()];
    const low = materials.filter(
      (material) => material.quantity < material.minimum,
    );
    const positive = materials.filter((material) => material.quantity > 0);
    const belowMinimum = (row) => {
      const material = totals.get(String(row.material_id));
      return material.quantity < material.minimum;
    };
    return (
      pageHead(
        "Estoque",
        "Disponibilidade de materiais, por local e em tempo real.",
        exportButton("stock") + addButton("Movimentar", "new-movement"),
      ) +
      `<div class="summary-strip">${summary("Materiais", materials.length, "box")}${summary("Com saldo global", positive.length, "checkCircle")}${summary("Abaixo do mínimo global", low.length, "warning")}</div><div class="page-note">${icon("info")}<p>O mínimo e a situação global consideram a soma de todos os locais de cada material. O saldo disponível é exibido por localização.</p></div>` +
      dataPanel(
        [
          "Material",
          "Local de estoque",
          "Saldo disponível",
          "Mínimo global",
          "Situação global",
        ],
        rows.map(
          (r) =>
            `<tr data-material-id="${E(r.material_id)}" ${filterRow(`${r.code} ${r.material} ${r.location} ${r.unit}`, belowMinimum(r) ? "low" : "ok")}><td class="primary-cell">${E(r.material)}<span class="cell-subtitle">${E(r.code || "Sem código")}</span></td><td>${E(r.location || "—")}</td><td><span class="quantity">${fmt(r.quantity)}</span><span class="unit">${E(r.unit)}</span></td><td>${fmt(r.minimum_stock)}<span class="unit">${E(r.unit)}</span></td><td>${belowMinimum(r) ? badge("Abaixo do mínimo", "amber") : badge("Estoque regular", "green")}<span class="cell-subtitle">Total: ${fmt(totals.get(String(r.material_id)).quantity / 1000)} ${E(r.unit)}</span></td></tr>`,
        ),
        {
          placeholder: "Material, código ou local…",
          countDistinct: "materialId",
          filter:
            '<select data-status-filter aria-label="Filtrar situação global"><option value="">Todos os materiais</option><option value="low">Abaixo do mínimo global</option><option value="ok">Estoque global regular</option></select>',
          emptyTitle: "Seu estoque está pronto para receber",
          emptyText:
            "Cadastre os materiais e os locais, depois registre uma entrada para iniciar o controle.",
          icon: "box",
          emptyAction: canWrite()
            ? '<a href="#cadastros/materials" class="button small">Cadastrar materiais</a>'
            : "",
          footer: "Saldo por material e local de armazenamento",
        },
      )
    );
  }
  function summary(label, value, ico, currency = false) {
    return `<div class="summary-card"><div><small>${E(label)}</small><strong>${currency ? money(value) : fmt(value)}</strong></div><span class="stat-icon">${icon(ico)}</span></div>`;
  }
  async function renderMovements() {
    const [movements, loans] = await Promise.all([
      api("/movements"),
      api("/loans"),
    ]);
    S.movements = movements;
    S.loans = loans;
    const tabs = `<div class="tabs" role="tablist" aria-label="Fluxos do estoque"><button type="button" role="tab" aria-selected="${S.tab === "movements"}" class="tab${S.tab === "movements" ? " active" : ""}" data-action="movements-tab" data-tab="movements">Histórico de movimentações</button><button type="button" role="tab" aria-selected="${S.tab === "loans"}" class="tab${S.tab === "loans" ? " active" : ""}" data-action="movements-tab" data-tab="loans">Empréstimos em aberto <span class="badge neutral">${loans.length}</span></button></div>`;
    const head = pageHead(
      "Movimentações",
      "Cada entrada, saída e transferência com seu registro completo.",
      exportButton("movements") +
        addButton("Nova movimentação", "new-movement"),
    );
    if (S.tab === "loans")
      return (
        head +
        tabs +
        dataPanel(
          [
            "Material",
            "Funcionário",
            "Local",
            "Quantidade",
            "Devolução prevista",
            "Ação",
          ],
          loans.map(
            (r) =>
              `<tr ${filterRow(`${r.material} ${r.employee} ${r.location}`)}><td class="primary-cell">${E(r.material)}</td><td>${E(r.employee)}</td><td>${E(r.location || "—")}</td><td><span class="quantity">${fmt(r.quantity)}</span><span class="unit">${E(r.unit)}</span></td><td>${r.due_date ? date(r.due_date) : '<span class="muted">Sem prazo definido</span>'}${r.due_date && new Date(r.due_date + "T23:59:59") < new Date() ? " " + badge("Atrasado", "red") : ""}</td><td>${canWrite() ? `<button type="button" class="table-action" data-action="return-loan" data-id="${r.id}">${icon("arrowDown")}Devolver</button>` : "—"}</td></tr>`,
          ),
          {
            placeholder: "Material ou funcionário…",
            emptyTitle: "Nenhum empréstimo em aberto",
            emptyText:
              "As saídas vinculadas a funcionários aparecerão aqui até a devolução.",
            icon: "users",
          },
        )
      );
    return (
      head +
      tabs +
      dataPanel(
        [
          "Data e hora",
          "Material",
          "Tipo",
          "Quantidade",
          "Origem → Destino",
          "Responsável",
          "Observações",
        ],
        movements.map(
          (r) =>
            `<tr ${filterRow(`${r.material} ${r.type} ${human(r.type)} ${r.employee} ${r.author} ${r.origin} ${r.destination} ${r.notes}`, r.type)}><td>${date(r.created_at, true)}<span class="cell-subtitle">#${r.id}</span></td><td class="primary-cell">${E(r.material)}</td><td>${badge(r.type)}</td><td><span class="quantity">${fmt(r.quantity)}</span><span class="unit">${E(r.unit)}</span></td><td>${E(r.origin || "Externo")} → ${E(r.destination || "Externo")}</td><td>${E(r.employee || r.author || "—")}<span class="cell-subtitle">Registrado por ${E(r.author || "—")}</span></td><td class="cell-wrap">${E(r.notes || "—")}</td></tr>`,
        ),
        {
          filter: statusFilter(
            ["ENTRADA", "SAIDA", "DEVOLUCAO", "TRANSFERENCIA", "AJUSTE"],
            "Todos os tipos",
          ),
          placeholder: "Material, local ou responsável…",
          emptyTitle: "O fluxo da sua operação aparece aqui",
          emptyText:
            "Registre entradas, saídas, devoluções e transferências de materiais.",
          icon: "arrows",
          emptyAction: canWrite()
            ? '<button type="button" class="button small" data-action="new-movement">Primeira movimentação</button>'
            : "",
        },
      )
    );
  }
  async function renderRequisitions() {
    const rows = await api("/requisitions");
    S.requisitions = rows;
    return (
      pageHead(
        "Requisições",
        "Do pedido da equipe ao material entregue na obra.",
        exportButton("requisitions") +
          addButton("Nova requisição", "new-requisition"),
      ) +
      dataPanel(
        [
          "Requisição",
          "Obra",
          "Solicitante",
          "Prioridade",
          "Status",
          "Itens",
          "Ação",
        ],
        rows.map(
          (r) =>
            `<tr ${filterRow(`${r.id} ${r.work} ${r.requester} ${human(r.status)} ${(r.items || []).map((i) => i.material).join(" ")}`, r.status)}><td class="primary-cell">REQ-${String(r.id).padStart(4, "0")}<span class="cell-subtitle">${date(r.created_at)}</span></td><td>${E(r.work)}</td><td>${E(r.requester)}</td><td>${badge(r.priority)}</td><td>${badge(r.status)}</td><td>${fmt((r.items || []).length)} ${(r.items || []).length === 1 ? "material" : "materiais"}</td><td><button type="button" class="table-action" data-action="view-requisition" data-id="${r.id}">${icon("eye")}Detalhes</button></td></tr>`,
        ),
        {
          placeholder: "Obra, solicitante ou material…",
          filter: statusFilter([
            "PENDENTE",
            "APROVADA",
            "ATENDIDA",
            "CANCELADA",
          ]),
          emptyTitle: "Organize o próximo pedido",
          emptyText:
            "Solicite os materiais necessários para a obra e acompanhe a aprovação e o atendimento.",
          icon: "clipboard",
          emptyAction: canWrite()
            ? '<button type="button" class="button small" data-action="new-requisition">Criar requisição</button>'
            : "",
        },
      )
    );
  }
  async function renderTickets() {
    const rows = await api("/tickets");
    S.tickets = rows;
    return (
      pageHead(
        "Chamados",
        "Demandas registradas. Equipe conectada. Trabalho em dia.",
        exportButton("tickets") + addButton("Abrir chamado", "new-ticket"),
      ) +
      `<div class="summary-strip">${summary("Abertos", rows.filter((r) => r.status === "ABERTO").length, "ticket")}${summary("Em andamento", rows.filter((r) => r.status === "EM_ANDAMENTO").length, "clock")}${summary("Resolvidos", rows.filter((r) => r.status === "RESOLVIDO").length, "checkCircle")}</div>` +
      dataPanel(
        [
          "Chamado",
          "Obra",
          "Responsável",
          "Prioridade",
          "Status",
          "Atualizado",
          "Ação",
        ],
        rows.map(
          (r) =>
            `<tr ${filterRow(`${r.id} ${r.title} ${r.work} ${r.assignee} ${r.creator} ${human(r.priority)} ${human(r.status)}`, r.status)}><td class="primary-cell cell-wrap">${E(r.title)}<span class="cell-subtitle">#${r.id} · ${E(r.creator)}</span></td><td>${E(r.work || "Geral")}</td><td>${E(r.assignee || "Não atribuído")}</td><td>${badge(r.priority)}</td><td>${badge(r.status)}</td><td>${date(r.updated_at)}</td><td><button type="button" class="table-action" data-action="view-ticket" data-id="${r.id}">${icon("eye")}Abrir</button></td></tr>`,
        ),
        {
          placeholder: "Título, obra ou responsável…",
          filter: statusFilter([
            "ABERTO",
            "EM_ANDAMENTO",
            "RESOLVIDO",
            "CANCELADO",
          ]),
          emptyTitle: "Um canal para resolver e avançar",
          emptyText:
            "Abra um chamado para acompanhar demandas, responsáveis e a solução de cada solicitação.",
          icon: "ticket",
          emptyAction: canWrite()
            ? '<button type="button" class="button small" data-action="new-ticket">Abrir primeiro chamado</button>'
            : "",
        },
      )
    );
  }
  async function renderMaintenance() {
    const rows = await api("/maintenance");
    S.maintenance = rows;
    return (
      pageHead(
        "Manutenção",
        "Cuide dos equipamentos para manter a operação em movimento.",
        addButton("Registrar manutenção", "new-maintenance"),
      ) +
      dataPanel(
        [
          "Equipamento",
          "Defeito relatado",
          "Status",
          "Abertura",
          "Conclusão",
          "Ação",
        ],
        rows.map(
          (r) =>
            `<tr ${filterRow(`${r.asset_tag} ${r.material} ${r.defect} ${r.resolution} ${human(r.status)}`, r.status)}><td class="primary-cell">${E(r.asset_tag)}<span class="cell-subtitle">${E(r.material || "Equipamento")}</span></td><td class="cell-wrap">${E(r.defect)}</td><td>${badge(r.status)}</td><td>${date(r.created_at)}</td><td>${date(r.closed_at)}</td><td>${!r.closed_at && canWrite() ? `<button type="button" class="table-action" data-action="close-maintenance" data-id="${r.id}">${icon("check")}Concluir</button>` : `<button type="button" class="table-action" data-action="view-maintenance" data-id="${r.id}">${icon("eye")}Detalhes</button>`}</td></tr>`,
        ),
        {
          placeholder: "Patrimônio, material ou defeito…",
          filter: statusFilter([...new Set(rows.map((r) => r.status))]),
          emptyTitle: "Equipamentos cuidados, operação contínua",
          emptyText:
            "Registre um defeito, acompanhe o reparo e documente a condição do equipamento na conclusão.",
          icon: "wrench",
          emptyAction: canWrite()
            ? '<button type="button" class="button small" data-action="new-maintenance">Registrar manutenção</button>'
            : "",
        },
      )
    );
  }
  function renderCatalogHome() {
    return (
      pageHead(
        "Cadastros",
        "A base organizada para uma operação que funciona.",
        "",
        "DADOS QUE CONECTAM A OPERAÇÃO",
      ) +
      `<div class="catalog-grid">${Object.entries(entityInfo)
        .filter(([key]) => S.schema[key])
        .map(
          ([key, m]) =>
            `<a href="#cadastros/${key}" class="catalog-card" data-card-search="${E((m.title + " " + m.description).toLowerCase())}"><div class="catalog-card-top"><span class="stat-icon">${icon(m.icon)}</span>${icon("arrowUpRight")}</div><div class="catalog-card-copy"><h2>${E(m.title)}</h2><p>${E(m.description)}</p></div></a>`,
        )
        .join("")}</div>`
    );
  }
  function catalogCell(value, f) {
    if (value === null || value === undefined || value === "")
      return '<span class="muted">—</span>';
    if (f.kind === "boolean")
      return badge(value ? "Sim" : "Não", value ? "green" : "neutral");
    if (f.kind === "relation") return E(lookup(f.relation, value));
    if (f.kind === "number")
      return f.label?.toLowerCase().match(/valor|custo|preço|preco/)
        ? money(value)
        : fmt(value);
    if (f.kind === "date") return date(value);
    if (f.kind === "select") return badge(value);
    return E(value);
  }
  async function renderCatalog(entity) {
    const m = entityInfo[entity];
    const schema = S.schema[entity];
    if (!m || !schema) throw new Error("Este cadastro não está disponível.");
    const [rows] = await Promise.all([
      catalog(entity, true),
      loadRelations(entity),
    ]);
    const fields = Object.entries(schema.fields);
    const columns = {
      materials: [
        "code",
        "description",
        "category_id",
        "unit",
        "minimum_stock",
        "status",
      ],
      expenses: [
        "supplier",
        "purchase_date",
        "material_id",
        "work_id",
        "quantity",
        "unit_cost",
        "total_cost",
      ],
    };
    const shown = (columns[entity] || fields.map(([key]) => key)).map((key) => [
      key,
      schema.fields[key] || { label: "Valor total (R$)", kind: "number" },
    ]);
    S.catalogEntity = entity;
    const isExpenses = entity === "expenses",
      isProduction = entity === "production";
    const total = isExpenses
      ? rows.reduce((v, r) => v + Number(r.total_cost || 0), 0)
      : 0;
    return (
      pageHead(
        m.title,
        m.description,
        (isExpenses || isProduction ? exportButton(entity) : "") +
          addButton("Novo cadastro", "new-catalog", `data-entity="${entity}"`),
        "BASE DA OPERAÇÃO",
      ) +
      (isExpenses
        ? `<div class="summary-strip">${summary("Total registrado", total, "wallet", true)}${summary("Despesas", rows.length, "clipboard")}${summary("Obras com despesas", new Set(rows.map((r) => r.work_id)).size, "building")}</div>`
        : "") +
      dataPanel(
        [...shown.map(([, f]) => f.label), "Ação"],
        rows.map(
          (r) =>
            `<tr ${filterRow(fields.map(([k, f]) => (f.kind === "relation" ? lookup(f.relation, r[k]) : r[k])).join(" "), r.status || (r.active === false ? "inactive" : "active"))}>${shown.map(([key, f], i) => `<td class="${i === 0 ? "primary-cell " : ""}${["text", "textarea"].includes(f.kind) ? "cell-wrap" : ""}">${catalogCell(r[key], f)}</td>`).join("")}<td><button type="button" class="table-action" data-action="${canWrite() ? "edit" : "view"}-catalog" data-entity="${entity}" data-id="${r.id}">${icon(canWrite() ? "edit" : "eye")}${canWrite() ? "Editar" : "Detalhes"}</button></td></tr>`,
        ),
        {
          placeholder: "Buscar em " + m.title.toLowerCase() + "…",
          filter: fields.some(([key]) => key === "active")
            ? '<select data-status-filter aria-label="Filtrar situação"><option value="">Todos os registros</option><option value="active">Ativos</option><option value="inactive">Inativos</option></select>'
            : schema.fields.status
              ? statusFilter(schema.fields.status.options || [])
              : "",
          emptyTitle: `Cadastre ${m.title.toLowerCase()}`,
          emptyText:
            m.description +
            " Os registros serão compartilhados com os demais módulos.",
          icon: m.icon,
          emptyAction: canWrite()
            ? `<button type="button" class="button small" data-action="new-catalog" data-entity="${entity}">Adicionar primeiro registro</button>`
            : "",
          footer: "Registros preservados para manter o histórico da operação",
        },
      )
    );
  }
  async function renderAlerts() {
    const rows = await api("/alerts");
    $("#notification-dot").hidden = !rows.length;
    return (
      pageHead(
        "Alertas da operação",
        "Estoque, prazos e equipamentos que precisam da sua atenção.",
      ) +
      (rows.length
        ? `<div class="alert-cards">${rows.map((r) => `<article class="alert-card" data-card-search="${E((r.message + " " + human(r.type)).toLowerCase())}"><div class="alert-symbol ${["ALTA", "URGENTE"].includes(r.priority) ? "red" : ""}">${icon(r.type?.includes("ESTOQUE") ? "box" : "warning")}</div><div class="alert-copy"><strong>${E(r.message)}</strong><p>${E(human(r.type))} · ${badge(r.priority)}</p></div><a href="#${moduleRoute(r.module)}" class="button small">Acompanhar ${icon("arrowUpRight")}</a></article>`).join("")}</div>`
        : `<div class="panel">${empty("Tudo em ordem", "Nenhum alerta ativo. Continue acompanhando sua operação por aqui.", "checkCircle")}</div>`)
    );
  }
  async function renderUsers() {
    if (!isAdmin())
      throw new Error(
        "A gestão de usuários está disponível apenas para administradores.",
      );
    const rows = await api("/users");
    S.cache.users = rows;
    return (
      pageHead(
        "Usuários e acessos",
        "A pessoa certa, com o acesso certo à operação.",
        addButton("Novo usuário", "new-user"),
        "ADMINISTRAÇÃO",
      ) +
      `<div class="page-note">${icon("shield")}<p>Administradores gerenciam toda a operação. Operadores registram as rotinas. O perfil Consulta acompanha as informações.</p></div>` +
      dataPanel(
        ["Pessoa", "Usuário", "Perfil de acesso", "Situação", "Ação"],
        rows.map(
          (r) =>
            `<tr ${filterRow(`${r.name} ${r.username} ${roleLabel(r.role)}`, r.active ? "active" : "inactive")}><td class="primary-cell">${E(r.name)}${r.id === S.user.id ? '<span class="cell-subtitle">Você</span>' : ""}</td><td>${E(r.username)}</td><td>${badge(roleLabel(r.role), r.role === "ADMIN" ? "blue" : "neutral")}</td><td>${badge(r.active ? "Ativo" : "Inativo", r.active ? "green" : "neutral")}</td><td><button type="button" class="table-action" data-action="edit-user" data-id="${r.id}">${icon("edit")}Gerenciar</button></td></tr>`,
        ),
        {
          placeholder: "Nome, usuário ou perfil…",
          filter:
            '<select data-status-filter aria-label="Filtrar situação"><option value="">Todos os usuários</option><option value="active">Ativos</option><option value="inactive">Inativos</option></select>',
          icon: "users",
        },
      )
    );
  }
  async function renderAudit() {
    if (!isAdmin())
      throw new Error(
        "O histórico de auditoria está disponível apenas para administradores.",
      );
    const rows = await api("/audit");
    return (
      pageHead(
        "Histórico de auditoria",
        "Rastreabilidade para acompanhar cada ação da equipe.",
        "",
        "ADMINISTRAÇÃO",
      ) +
      dataPanel(
        ["Data e hora", "Pessoa", "Ação", "Módulo / registro", "Detalhes"],
        rows.map(
          (r) =>
            `<tr ${filterRow(`${r.author} ${r.action} ${r.entity} ${r.details}`)}><td>${date(r.created_at, true)}</td><td class="primary-cell">${E(r.author)}</td><td>${E(human(r.action))}</td><td>${E(entityInfo[r.entity]?.title || human(r.entity))}<span class="cell-subtitle">Registro ${E(r.record_id ?? "—")}</span></td><td class="cell-wrap">${E(typeof r.details === "object" ? JSON.stringify(r.details) : r.details || "—")}</td></tr>`,
        ),
        {
          placeholder: "Pessoa, ação ou módulo…",
          emptyTitle: "O histórico começa com a operação",
          emptyText:
            "As ações realizadas no sistema serão registradas aqui para acompanhamento.",
          icon: "shield",
          footer:
            "Registros de auditoria preservam a rastreabilidade da operação",
        },
      )
    );
  }
  async function renderForecast() {
    await Promise.all([catalog("works"), catalog("consumption_profiles")]);
    const activities = [
      ...new Set(
        (S.cache.consumption_profiles || [])
          .map((r) => r.activity)
          .filter(Boolean),
      ),
    ];
    return (
      pageHead(
        "Previsão de consumo",
        "Planeje os materiais antes de começar a próxima atividade.",
        "",
        "PLANEJAMENTO COM DADOS",
      ) +
      `<div class="page-note">${icon("target")}<p>A previsão usa os perfis de consumo cadastrados e o estoque disponível. Escolha a obra, a atividade e a quantidade a produzir para calcular a necessidade de materiais.</p></div><section class="panel"><form id="forecast-form" class="forecast-form">${selectField("work_id", "Obra", options(S.cache.works, "", "Selecione a obra"), true)}<div class="field"><label for="forecast-activity">Atividade <span class="required-mark">*</span></label><input id="forecast-activity" name="activity" list="activities-list" placeholder="Atividade do perfil de consumo" required><datalist id="activities-list">${activities.map((a) => `<option value="${E(a)}"></option>`).join("")}</datalist></div>${field("quantity_produced", "Quantidade a produzir", "number", "", true, 'min="0.001" step="any" placeholder="0"')}<button class="button primary" type="submit">${icon("target")}Calcular previsão</button></form><div id="forecast-result">${empty("Antecipe o que sua obra precisa", "Preencha os dados acima para comparar o consumo previsto com os materiais disponíveis.", "target")}</div></section>`
    );
  }
  function bindForecast() {
    $("#forecast-form").onsubmit = async (e) => {
      e.preventDefault();
      const form = e.currentTarget;
      const result = $("#forecast-result");
      const version = S.version;
      if (!form.reportValidity()) return;
      const button = $("button[type=submit]", form);
      button.disabled = true;
      try {
        const q = new URLSearchParams(formData(form));
        const rows = await api("/forecast?" + q.toString());
        if (!result.isConnected || version !== S.version) return;
        const shortage = rows.filter((r) => Number(r.shortage) > 0);
        result.innerHTML =
          `<div class="forecast-summary">${rows.length ? `${fmt(rows.length)} materiais previstos · ${shortage.length ? `${fmt(shortage.length)} com necessidade de reposição` : "Estoque suficiente para esta previsão"}` : "Nenhum perfil de consumo encontrado para a atividade informada."}</div>` +
          (rows.length
            ? table(
                [
                  "Material",
                  "Consumo / unidade",
                  "Previsto",
                  "Disponível",
                  "Necessidade",
                ],
                rows.map(
                  (r) =>
                    `<tr><td class="primary-cell">${E(r.material)}<span class="cell-subtitle">${E(r.unit)}</span></td><td>${fmt(r.consumption_per_unit)}</td><td><span class="quantity">${fmt(r.expected)}</span><span class="unit">${E(r.unit)}</span></td><td>${fmt(r.available)}<span class="unit">${E(r.unit)}</span></td><td>${Number(r.shortage) > 0 ? `<span class="quantity low">${fmt(r.shortage)}</span><span class="unit">${E(r.unit)}</span>` : badge("Atendido", "green")}</td></tr>`,
                ),
              )
            : empty(
                "Defina um perfil de consumo",
                "Cadastre um perfil para esta atividade e tente calcular novamente.",
                "target",
                canWrite()
                  ? '<a href="#cadastros/consumption_profiles" class="button small">Cadastrar perfil</a>'
                  : "",
              ));
      } catch (err) {
        if (version === S.version) toast(err.message, "error");
      } finally {
        button.disabled = false;
      }
    };
  }
  function requireWrite() {
    if (!canWrite())
      throw new Error("Seu perfil permite apenas consultar as informações.");
  }
  async function openCatalog(entity, id = null, viewOnly = false) {
    if (!viewOnly) requireWrite();
    const schema = S.schema[entity];
    const m = entityInfo[entity];
    if (!schema || !m) throw new Error("Cadastro não disponível.");
    await Promise.all([catalog(entity), loadRelations(entity)]);
    const row = id
      ? (S.cache[entity] || []).find((r) => String(r.id) === String(id))
      : null;
    if (id && !row)
      throw new Error(
        "Registro não encontrado. Atualize a página e tente novamente.",
      );
    if (viewOnly) {
      dialog(
        m.title,
        "Informações do registro",
        `<div class="detail-grid">${Object.entries(schema.fields)
          .map(
            ([key, f]) =>
              `<div><span class="detail-label">${E(f.label)}</span><span class="detail-value">${catalogCell(row[key], f)}</span></div>`,
          )
          .join("")}</div>`,
      );
      return;
    }
    const fields = Object.entries(schema.fields)
      .map(([key, f]) => {
        let value = row ? row[key] : "";
        if (!row && f.kind === "date")
          value = localInputDate();
        if (!row && f.kind === "number" && f.minimum === 0) value = 0;
        if (f.kind === "relation")
          return selectField(
            key,
            f.label,
            options(
              S.cache[f.relation] || [],
              value,
              f.required ? "Selecione…" : "Não vinculado",
            ),
            f.required,
          );
        if (f.kind === "select")
          return selectField(
            key,
            f.label,
            enumOptions(f.options || [], value),
            f.required,
          );
        if (f.kind === "boolean")
          return `<div class="field"><span class="field-label">${E(f.label)}</span><label class="checkbox-label"><input type="checkbox" name="${E(key)}" ${value ? "checked" : ""}> ${key === "active" ? "Registro ativo" : "Sim, habilitar"}</label></div>`;
        return field(
          key,
          f.label,
          f.kind === "number"
            ? "number"
            : f.kind === "date"
              ? "date"
              : f.kind === "textarea"
                ? "textarea"
                : "text",
          value,
          f.required,
          `${f.kind === "number" ? `step="any"${f.minimum !== undefined ? ` min="${f.minimum}"` : ""}` : ""}${f.kind === "text" ? ' maxlength="500"' : ""}`,
        );
      })
      .join("");
    dialog(
      row ? "Editar " + m.singular : "Cadastrar " + m.singular,
      row
        ? "Mantenha as informações da sua operação atualizadas."
        : "Os campos com * são obrigatórios.",
      `<div class="form-grid">${fields}</div>${entity === "expenses" ? '<div class="dialog-notice notice-below">O valor total da despesa será calculado pela quantidade × custo unitário. Este cadastro não movimenta o estoque.</div>' : ""}`,
      row ? "Salvar alterações" : "Cadastrar",
      async (form) => {
        const body = formData(form);
        for (const [key, f] of Object.entries(schema.fields)) {
          if (f.kind === "boolean") body[key] = form.elements[key].checked;
          else if (body[key] === "" && !f.required) body[key] = null;
        }
        await api(`/catalog/${entity}${row ? "/" + row.id : ""}`, {
          method: row ? "PUT" : "POST",
          body,
        });
        S.cache = {};
        toast(row ? "Cadastro atualizado." : "Cadastro realizado.");
        await route();
      },
    );
  }
  async function openMovement(prefill = {}) {
    requireWrite();
    await Promise.all([
      catalog("materials"),
      catalog("locations"),
      catalog("employees"),
    ]);
    const types = [
      "ENTRADA",
      "SAIDA",
      "DEVOLUCAO",
      "TRANSFERENCIA",
      ...(isAdmin() ? ["AJUSTE"] : []),
    ];
    dialog(
      "Nova movimentação",
      "Registre o fluxo de materiais do almoxarifado.",
      `<div class="dialog-notice" id="movement-guidance">Cada movimentação atualiza os saldos e mantém o histórico da operação.</div><div class="form-grid">${selectField("type", "Tipo de movimentação", enumOptions(types, prefill.type || "ENTRADA"), true)}${selectField("material_id", "Material", options(S.cache.materials, prefill.material_id), true)}${field("quantity", "Quantidade", "number", prefill.quantity || "", true, 'step="any" min="0.001" placeholder="0"')}<div class="field" id="movement-origin">${selectField("origin_id", "Local de origem", options(S.cache.locations, prefill.origin_id), true).replace(/^<div class="field">|<\/div>$/g, "")}</div><div class="field" id="movement-destination">${selectField("destination_id", "Local de destino", options(S.cache.locations, prefill.destination_id), true).replace(/^<div class="field">|<\/div>$/g, "")}</div><div class="field" id="movement-employee">${selectField("employee_id", "Funcionário", options(S.cache.employees, prefill.employee_id, "Sem empréstimo vinculado"), false).replace(/^<div class="field">|<\/div>$/g, "")}</div><div class="field" id="movement-due">${field("due_date", "Previsão de devolução", "date", "").replace(/^<div class="field">|<\/div>$/g, "")}</div>${field("notes", "Observações", "textarea", "", false, 'maxlength="2000" placeholder="Informações que ajudam a acompanhar esta movimentação"')}</div>`,
      "Registrar movimentação",
      async (form, intent) => {
        const body = formData(form);
        const type = body.type;
        if (!["SAIDA", "TRANSFERENCIA"].includes(type)) delete body.origin_id;
        if (!["ENTRADA", "DEVOLUCAO", "TRANSFERENCIA", "AJUSTE"].includes(type))
          delete body.destination_id;
        if (!["SAIDA", "DEVOLUCAO"].includes(type)) delete body.employee_id;
        if (type !== "SAIDA") delete body.due_date;
        if (type === "TRANSFERENCIA" && body.origin_id === body.destination_id)
          throw new Error("Selecione locais diferentes para origem e destino.");
        const payload = JSON.stringify(body);
        if (intent.payload !== null && intent.payload !== payload)
          intent.key = crypto.randomUUID();
        intent.payload = payload;
        await api("/movements", {
          method: "POST", body,
          headers: { "Idempotency-Key": intent.key },
        });
        toast("Movimentação registrada. Os saldos foram atualizados.");
        await route();
      },
    );
    function updateMovementFields() {
      const form = $("#modal-form");
      const type = form.elements.type.value;
      for (const [id, shown, required] of [
        ["origin", ["SAIDA", "TRANSFERENCIA"].includes(type), true],
        [
          "destination",
          ["ENTRADA", "DEVOLUCAO", "TRANSFERENCIA", "AJUSTE"].includes(type),
          true,
        ],
        [
          "employee",
          ["SAIDA", "DEVOLUCAO"].includes(type),
          type === "DEVOLUCAO",
        ],
        ["due", type === "SAIDA", false],
      ]) {
        const wrap = $("#movement-" + id);
        wrap.hidden = !shown;
        const input = $("input,select", wrap);
        input.required = shown && required;
        input.disabled = !shown;
      }
      form.elements.quantity.min = type === "AJUSTE" ? "0" : "0.001";
      $('label[for="field-quantity"]').innerHTML =
        (type === "AJUSTE" ? "Saldo final no destino" : "Quantidade") +
        ' <span class="required-mark">*</span>';
      form.elements.notes.required = type === "AJUSTE";
      $("#movement-guidance").textContent = {
        ENTRADA:
          "Informe o material recebido e o local onde ele ficará armazenado.",
        SAIDA:
          "Vincule um funcionário para registrar um empréstimo e acompanhar a devolução.",
        DEVOLUCAO:
          "A devolução deve corresponder a um empréstimo em aberto do funcionário.",
        TRANSFERENCIA:
          "Os materiais serão transferidos entre os locais de origem e destino.",
        AJUSTE:
          "Informe o saldo final correto do local de destino e descreva a justificativa. O histórico preserva a diferença ajustada.",
      }[type];
    }
    $("#field-type").onchange = updateMovementFields;
    updateMovementFields();
  }
  function itemRow() {
    return `<div class="requisition-item"><div class="field"><label>Material <span class="required-mark">*</span></label><select name="item_material" required aria-label="Material da requisição">${options(S.cache.materials, "")}</select></div><div class="field"><label>Quantidade <span class="required-mark">*</span></label><input name="item_quantity" type="number" min="0.001" step="any" placeholder="0" required aria-label="Quantidade do material"></div><button type="button" class="icon-button" data-action="remove-item" aria-label="Remover material">${icon("trash")}</button></div>`;
  }
  async function openRequisition() {
    requireWrite();
    await Promise.all([catalog("works"), catalog("materials")]);
    dialog(
      "Nova requisição",
      "Solicite os materiais necessários para a sua obra.",
      `<div class="form-grid">${selectField("work_id", "Obra", options(S.cache.works, ""), true)}${selectField("priority", "Prioridade", enumOptions(["BAIXA", "NORMAL", "ALTA", "URGENTE"], "NORMAL"), true)}${field("notes", "Observações", "textarea", "", "", 'maxlength="2000" placeholder="Finalidade, local de aplicação ou detalhes da solicitação"')}</div><div class="items-header"><h3>Materiais solicitados</h3><button type="button" class="button small" data-action="add-item">${icon("plus")}Adicionar material</button></div><div id="requisition-items">${itemRow()}</div>`,
      "Criar requisição",
      async (form) => {
        const data = formData(form);
        const items = $$(".requisition-item", form).map((el) => ({
          material_id: $("select", el).value,
          quantity: $("input", el).value,
        }));
        if (!items.length) throw new Error("Adicione pelo menos um material.");
        if (new Set(items.map((i) => i.material_id)).size !== items.length)
          throw new Error(
            "Cada material deve aparecer apenas uma vez. Some as quantidades em um único item.",
          );
        await api("/requisitions", {
          method: "POST",
          body: {
            work_id: data.work_id,
            priority: data.priority,
            notes: data.notes,
            items,
          },
        });
        toast("Requisição criada e enviada para aprovação.");
        await route();
      },
    );
  }
  async function viewRequisition(id) {
    const row = (S.requisitions || (await api("/requisitions"))).find(
      (r) => String(r.id) === String(id),
    );
    if (!row) throw new Error("Requisição não encontrada.");
    let actions = "";
    if (canWrite() && ["PENDENTE", "APROVADA"].includes(row.status)) {
      actions = `<div class="detail-actions">${row.status === "PENDENTE" && isAdmin() ? `<button type="button" class="button primary" data-action="approve-requisition" data-id="${row.id}">${icon("check")}Aprovar requisição</button>` : ""}${row.status === "APROVADA" ? `<button type="button" class="button primary" data-action="fulfill-requisition" data-id="${row.id}">${icon("arrows")}Atender requisição</button>` : ""}<button type="button" class="button danger" data-action="cancel-requisition" data-id="${row.id}">Cancelar requisição</button></div>`;
    }
    dialog(
      `Requisição REQ-${String(row.id).padStart(4, "0")}`,
      "Acompanhe os materiais e o andamento da solicitação.",
      `<div class="detail-grid"><div><span class="detail-label">Obra</span><span class="detail-value">${E(row.work)}</span></div><div><span class="detail-label">Solicitante</span><span class="detail-value">${E(row.requester)}</span></div><div><span class="detail-label">Criada em</span><span class="detail-value">${date(row.created_at, true)}</span></div><div><span class="detail-label">Status</span>${badge(row.status)}</div><div><span class="detail-label">Prioridade</span>${badge(row.priority)}</div></div>${row.notes ? `<p class="detail-description">${E(row.notes)}</p>` : ""}${table(
        ["Material", "Quantidade"],
        (row.items || []).map(
          (i) =>
            `<tr><td class="primary-cell">${E(i.material)}</td><td><span class="quantity">${fmt(i.quantity)}</span><span class="unit">${E(i.unit)}</span></td></tr>`,
        ),
      )}${actions}${row.status === "PENDENTE" && !isAdmin() ? '<p class="muted approval-note">Esta requisição aguarda aprovação de um administrador.</p>' : ""}`,
      "",
      null,
      true,
    );
  }
  async function changeRequisition(id, action) {
    requireWrite();
    if (action === "APROVAR" && !isAdmin())
      throw new Error("A aprovação exige um administrador.");
    const row = (S.requisitions || []).find((r) => String(r.id) === String(id));
    if (action === "ATENDER") {
      await catalog("locations");
      const destinations = S.cache.locations.filter(
        (r) => String(r.work_id) === String(row.work_id),
      );
      dialog(
        "Atender requisição",
        `REQ-${String(id).padStart(4, "0")} · ${row.work}`,
        `<div class="dialog-notice">O atendimento é integral. Todos os materiais serão transferidos da origem para um local da obra. Se faltar estoque, a operação não será registrada.</div><div class="form-grid">${selectField("origin_id", "Retirar do local", options(S.cache.locations, ""), true)}${selectField("destination_id", "Entregar no local da obra", options(destinations, ""), true)}</div>${!destinations.length ? '<p class="inline-error">Cadastre um local de estoque vinculado a esta obra para atender a requisição.</p>' : ""}`,
        "Confirmar atendimento",
        async (form) => {
          const body = { action, ...formData(form) };
          if (body.origin_id === body.destination_id)
            throw new Error("Origem e destino devem ser diferentes.");
          await api(`/requisitions/${id}/action`, { method: "POST", body });
          toast("Requisição atendida. Os materiais foram transferidos.");
          await route();
        },
      );
      return;
    }
    dialog(
      action === "APROVAR" ? "Aprovar requisição" : "Cancelar requisição",
      `REQ-${String(id).padStart(4, "0")} · ${row?.work || ""}`,
      `<p class="detail-description flush-description">${action === "APROVAR" ? "A requisição ficará disponível para atendimento e transferência dos materiais para a obra." : "A solicitação será encerrada como cancelada, preservando seus itens e histórico."}</p>`,
      action === "APROVAR" ? "Confirmar aprovação" : "Confirmar cancelamento",
      async () => {
        await api(`/requisitions/${id}/action`, {
          method: "POST",
          body: { action },
        });
        toast(
          action === "APROVAR"
            ? "Requisição aprovada."
            : "Requisição cancelada.",
        );
        await route();
      },
    );
  }
  async function openTicket() {
    requireWrite();
    await Promise.all([catalog("works"), loadUsers()]);
    const users = S.cache.users.filter(
      (r) => r.active && r.role !== "CONSULTA",
    );
    dialog(
      "Abrir chamado",
      "Descreva a demanda e conecte quem pode resolver.",
      `<div class="form-grid"><div class="field full">${field("title", "Título do chamado", "text", "", true, 'maxlength="160" placeholder="Resuma o que precisa ser resolvido"').replace(/^<div class="field">|<\/div>$/g, "")}</div>${selectField("priority", "Prioridade", enumOptions(["BAIXA", "NORMAL", "ALTA", "URGENTE"], "NORMAL"), true)}${selectField("work_id", "Obra", options(S.cache.works, "", "Demanda geral"))}${selectField("assignee_id", "Responsável", options(users, "", "Definir depois"))}${field("description", "Descrição da demanda", "textarea", "", true, 'maxlength="5000" placeholder="Conte o que aconteceu, o local e as informações necessárias para o atendimento."')}</div>`,
      "Abrir chamado",
      async (form) => {
        const body = formData(form);
        await api("/tickets", { method: "POST", body });
        toast("Chamado aberto. A equipe já pode acompanhar.");
        await route();
      },
    );
  }
  async function viewTicket(id) {
    await Promise.all([catalog("works"), loadUsers()]);
    const d = await api("/tickets/" + id);
    const listed = (S.tickets || []).find((r) => String(r.id) === String(id));
    const users = S.cache.users.filter(
      (r) => r.active && r.role !== "CONSULTA",
    );
    const transitions = {
      ABERTO: ["EM_ANDAMENTO", "CANCELADO"],
      EM_ANDAMENTO: ["RESOLVIDO", "CANCELADO"],
      RESOLVIDO: ["ABERTO"],
      CANCELADO: ["ABERTO"],
    };
    const updater = canWrite()
      ? `<div class="detail-actions" id="ticket-update"><div class="field"><label for="ticket-status">Status</label><select id="ticket-status" name="status">${enumOptions([d.status, ...(transitions[d.status] || [])], d.status)}</select></div><div class="field"><label for="ticket-priority">Prioridade</label><select id="ticket-priority" name="priority">${enumOptions(["BAIXA", "NORMAL", "ALTA", "URGENTE"], d.priority)}</select></div><div class="field"><label for="ticket-assignee">Responsável</label><select id="ticket-assignee" name="assignee_id">${options(users, d.assignee_id, "Não atribuído")}</select></div><button type="button" class="button primary small" data-action="update-ticket" data-id="${id}">Salvar</button></div>`
      : "";
    dialog(
      `#${d.id} · ${d.title}`,
      "Uma linha do tempo para cada solução.",
      `<div class="detail-grid"><div><span class="detail-label">Obra</span><span class="detail-value">${E(d.work || lookup("works", d.work_id))}</span></div><div><span class="detail-label">Criado por</span><span class="detail-value">${E(d.creator || listed?.creator || lookup("users", d.creator_id))}</span></div><div><span class="detail-label">Última atualização</span><span class="detail-value">${date(d.updated_at, true)}</span></div><div><span class="detail-label">Status</span>${badge(d.status)}</div><div><span class="detail-label">Prioridade</span>${badge(d.priority)}</div><div><span class="detail-label">Responsável</span><span class="detail-value">${E(d.assignee || (d.assignee_id ? lookup("users", d.assignee_id) : "Não atribuído"))}</span></div></div><p class="detail-description">${E(d.description)}</p>${updater}<h3 class="detail-section-title">${icon("message")}Conversa <span class="badge neutral">${(d.comments || []).length}</span></h3>${(d.comments || []).length ? (d.comments || []).map((c) => `<article class="comment"><div class="comment-header"><strong>${E(c.author)}</strong><time>${date(c.created_at, true)}</time></div><p>${E(c.body)}</p></article>`).join("") : '<p class="muted comment-empty">Ainda não há comentários. As atualizações da equipe aparecerão aqui.</p>'}${canWrite() ? `<div class="comment-form"><textarea id="ticket-comment" aria-label="Novo comentário" placeholder="Compartilhe uma atualização…" maxlength="5000"></textarea><button type="button" class="button primary" data-action="comment-ticket" data-id="${id}">${icon("arrowUp")}<span>Enviar</span></button></div>` : ""}<h3 class="detail-section-title">${icon("history")}Histórico do chamado</h3>${(d.history || []).map((h) => `<div class="history-item"><strong>${E(human(h.action))} · ${E(h.author || "Sistema")}</strong><p>${date(h.created_at, true)}</p></div>`).join("")}`,
      "",
      null,
      true,
    );
  }
  async function updateTicket(id, button) {
    requireWrite();
    const parent = $("#ticket-update");
    const body = {
      status: $("[name=status]", parent).value,
      priority: $("[name=priority]", parent).value,
      assignee_id: $("[name=assignee_id]", parent).value || null,
    };
    const currentForm = $("#modal-form");
    const modalBody = $(".dialog-body", currentForm);
    const draft = $("#ticket-comment")?.value || "";
    button.disabled = true;
    modalBody.inert = true;
    modalBody.setAttribute("aria-busy", "true");
    try {
      await api("/tickets/" + id, { method: "PATCH", body });
      toast("Chamado atualizado.");
      await route();
      if ($("#modal-form") === currentForm && $("#form-dialog").open) {
        await viewTicket(id);
        if ($("#ticket-comment")) $("#ticket-comment").value = draft;
      }
    } finally {
      modalBody.inert = false;
      modalBody.removeAttribute("aria-busy");
      if (button.isConnected) button.disabled = false;
    }
  }
  async function commentTicket(id, button) {
    requireWrite();
    const input = $("#ticket-comment");
    const body = input.value.trim();
    if (!body) {
      input.focus();
      throw new Error("Escreva um comentário antes de enviar.");
    }
    const currentForm = $("#modal-form");
    const modalBody = $(".dialog-body", currentForm);
    button.disabled = true;
    modalBody.inert = true;
    modalBody.setAttribute("aria-busy", "true");
    try {
      await api(`/tickets/${id}/comments`, { method: "POST", body: { body } });
      toast("Comentário adicionado.");
      await route();
      if ($("#modal-form") === currentForm && $("#form-dialog").open)
        await viewTicket(id);
    } finally {
      modalBody.inert = false;
      modalBody.removeAttribute("aria-busy");
      if (button.isConnected) button.disabled = false;
    }
  }
  async function openMaintenance() {
    requireWrite();
    await catalog("equipment");
    const equipment = S.cache.equipment.filter(
      (r) => r.status !== "MANUTENCAO" && r.status !== "BAIXADO",
    );
    dialog(
      "Registrar manutenção",
      "Documente o defeito e acompanhe o reparo do equipamento.",
      `<div class="form-grid">${selectField("equipment_id", "Equipamento / patrimônio", options(equipment, ""), true)}${field("defect", "Defeito relatado", "textarea", "", true, 'maxlength="2000" placeholder="Descreva o problema observado no equipamento."')}</div><div class="dialog-notice notice-below">O equipamento ficará em manutenção até a conclusão do reparo.</div>`,
      "Registrar manutenção",
      async (form) => {
        await api("/maintenance", { method: "POST", body: formData(form) });
        delete S.cache.equipment;
        toast("Manutenção registrada.");
        await route();
      },
    );
  }
  async function closeMaintenance(id) {
    requireWrite();
    const row = (S.maintenance || []).find((r) => String(r.id) === String(id));
    dialog(
      "Concluir manutenção",
      `${row?.asset_tag || "Equipamento"} · Registre o reparo realizado.`,
      `<div class="dialog-notice">Defeito relatado: ${E(row?.defect || "—")}</div><div class="form-grid">${selectField("condition", "Condição após o reparo", enumOptions(["BOA", "REGULAR", "RUIM"], "BOA"), true)}${field("resolution", "Solução aplicada", "textarea", "", true, 'maxlength="2000" placeholder="Informe o serviço executado e as observações do reparo."')}</div>`,
      "Concluir manutenção",
      async (form) => {
        await api(`/maintenance/${id}/close`, {
          method: "POST",
          body: formData(form),
        });
        delete S.cache.equipment;
        toast("Manutenção concluída. O equipamento foi atualizado.");
        await route();
      },
    );
  }
  function viewMaintenance(id) {
    const row = (S.maintenance || []).find((r) => String(r.id) === String(id));
    if (!row) throw new Error("Manutenção não encontrada.");
    dialog(
      "Detalhes da manutenção",
      row.asset_tag,
      `<div class="detail-grid"><div><span class="detail-label">Material</span><span class="detail-value">${E(row.material)}</span></div><div><span class="detail-label">Status</span>${badge(row.status)}</div><div><span class="detail-label">Abertura</span><span class="detail-value">${date(row.created_at, true)}</span></div><div><span class="detail-label">Conclusão</span><span class="detail-value">${date(row.closed_at, true)}</span></div></div><h3 class="detail-section-title">Defeito relatado</h3><p class="detail-description">${E(row.defect)}</p><h3 class="detail-section-title">Solução aplicada</h3><p class="detail-description">${E(row.resolution || "Ainda não concluída.")}</p>`,
    );
  }
  function openUser(id = null) {
    if (!isAdmin()) throw new Error("Esta ação exige um administrador.");
    const row = id
      ? (S.cache.users || []).find((r) => String(r.id) === String(id))
      : null;
    dialog(
      row ? "Gerenciar acesso" : "Novo usuário",
      row ? row.name : "Cadastre uma pessoa e defina o perfil de acesso.",
      `<div class="form-grid">${!row ? field("name", "Nome completo", "text", "", true, 'maxlength="120" autocomplete="off"') + field("username", "Usuário", "text", "", true, 'maxlength="80" autocomplete="off"') : ""}${selectField(
        "role",
        "Perfil de acesso",
        enumOptions(
          [
            { value: "OPERADOR", label: "Operador" },
            { value: "CONSULTA", label: "Consulta" },
            { value: "ADMIN", label: "Administrador" },
          ],
          row?.role || "OPERADOR",
        ),
        true,
      )}${row ? `<div class="field"><span class="field-label">Situação do acesso</span><label class="checkbox-label"><input type="checkbox" name="active" ${row.active ? "checked" : ""}> Usuário ativo</label></div>` : ""}${field("password", row ? "Nova senha (opcional)" : "Senha inicial", "password", "", !row, 'minlength="10" autocomplete="new-password" placeholder="Pelo menos 10 caracteres"')}</div>${row ? '<div class="dialog-notice notice-below">Deixe a senha em branco para manter a atual. Desativar o acesso preserva o histórico da pessoa.</div>' : ""}`,
      "Salvar acesso",
      async (form) => {
        const body = formData(form);
        if (row) {
          body.active = form.elements.active.checked;
          if (!body.password) delete body.password;
        }
        await api("/users" + (row ? "/" + row.id : ""), {
          method: row ? "PATCH" : "POST",
          body,
        });
        delete S.cache.users;
        toast(row ? "Acesso atualizado." : "Usuário cadastrado.");
        if (row?.id === S.user.id) {
          S.user = await api("/auth/me");
          $("#user-role").textContent = roleLabel(S.user.role);
          renderNavigation();
          if (!isAdmin()) location.hash = "dashboard";
        }
        await route();
      },
    );
  }
  function openPassword() {
    dialog(
      "Trocar minha senha",
      "Após a alteração, entre novamente em seus dispositivos.",
      `<div class="form-grid">${field("current_password", "Senha atual", "password", "", true, 'autocomplete="current-password" maxlength="128"')}${field("new_password", "Nova senha", "password", "", true, 'autocomplete="new-password" minlength="10" maxlength="128"')}${field("confirm_password", "Confirmar nova senha", "password", "", true, 'autocomplete="new-password" minlength="10" maxlength="128"')}</div>`,
      "Alterar senha",
      async (form) => {
        const data = formData(form);
        if (data.new_password !== data.confirm_password)
          throw new Error("A confirmação deve ser igual à nova senha.");
        await api("/auth/password", {
          method: "POST",
          body: { current_password: data.current_password, new_password: data.new_password },
        });
        form.reset();
        S.user = null;
        S.cache = {};
        S.setup = false;
        showAuth();
        toast("Senha alterada. Entre novamente com a nova senha.");
      },
    );
  }
  const actions = {
    refresh: refreshPage,
    "change-password": openPassword,
    menu: () => openSidebar(),
    "new-movement": () => openMovement(),
    "show-loans": () => {
      S.tab = "loans";
      if (location.hash === "#movimentacoes") return route();
      location.hash = "movimentacoes";
    },
    "movements-tab": (el) => {
      S.tab = el.dataset.tab;
      return route();
    },
    "return-loan": (el) => {
      const r = (S.loans || []).find((r) => String(r.id) === el.dataset.id);
      if (!r) throw new Error("Empréstimo não encontrado.");
      return openMovement({
        type: "DEVOLUCAO",
        material_id: r.material_id,
        employee_id: r.employee_id,
        destination_id: r.location_id,
        quantity: r.quantity,
      });
    },
    "new-catalog": (el) => openCatalog(el.dataset.entity),
    "edit-catalog": (el) => openCatalog(el.dataset.entity, el.dataset.id),
    "view-catalog": (el) => openCatalog(el.dataset.entity, el.dataset.id, true),
    "new-requisition": () => openRequisition(),
    "view-requisition": (el) => viewRequisition(el.dataset.id),
    "approve-requisition": (el) => changeRequisition(el.dataset.id, "APROVAR"),
    "fulfill-requisition": (el) => changeRequisition(el.dataset.id, "ATENDER"),
    "cancel-requisition": (el) => changeRequisition(el.dataset.id, "CANCELAR"),
    "add-item": () => {
      $("#requisition-items").insertAdjacentHTML("beforeend", itemRow());
    },
    "remove-item": (el) => {
      const row = el.closest(".requisition-item");
      if ($$(".requisition-item").length === 1) {
        $("select", row).value = "";
        $("input", row).value = "";
      } else row.remove();
    },
    "new-ticket": () => openTicket(),
    "view-ticket": (el) => viewTicket(el.dataset.id),
    "update-ticket": (el) => updateTicket(el.dataset.id, el),
    "comment-ticket": (el) => commentTicket(el.dataset.id, el),
    "new-maintenance": () => openMaintenance(),
    "close-maintenance": (el) => closeMaintenance(el.dataset.id),
    "view-maintenance": (el) => viewMaintenance(el.dataset.id),
    "new-user": () => openUser(),
    "edit-user": (el) => openUser(el.dataset.id),
  };
  document.addEventListener("click", async (e) => {
    if (e.target.closest(".skip-link")) {
      e.preventDefault();
      (S.user ? $("#main-content") : $("#auth-username")).focus();
      return;
    }
    const close = e.target.closest("[data-dialog-close]");
    if (close) {
      $("#form-dialog").close();
      return;
    }
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const fn = actions[el.dataset.action];
    if (fn) {
      try {
        await fn(el);
      } catch (error) {
        toast(error.message, "error");
      }
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.matches("[data-table-search],#global-search")) applyFilters();
  });
  document.addEventListener("change", (e) => {
    if (e.target.matches("[data-status-filter]")) applyFilters();
  });
  $("#auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    if (!form.reportValidity()) return;
    const button = $("#auth-submit");
    button.disabled = true;
    $("#auth-error").hidden = true;
    try {
      const body = {
        username: form.elements.username.value.trim(),
        password: form.elements.password.value,
      };
      if (S.setup) {
        body.name = form.elements.name.value.trim();
        if (S.setupToken)
          body.setup_token = form.elements.setup_token.value.trim();
      }
      await api(S.setup ? "/auth/setup" : "/auth/login", {
        method: "POST",
        body,
      });
      form.reset();
      S.setup = false;
      await enterApp();
    } catch (error) {
      $("#auth-error").textContent = error.message;
      $("#auth-error").hidden = false;
    } finally {
      button.disabled = false;
    }
  });
  $("#password-toggle").innerHTML = icon("eye");
  $("#password-toggle").onclick = () => {
    const p = $("#auth-password");
    p.type = p.type === "password" ? "text" : "password";
    $("#password-toggle").setAttribute(
      "aria-label",
      p.type === "password" ? "Mostrar senha" : "Ocultar senha",
    );
  };
  $("#logout-button").onclick = async () => {
    try {
      await api("/auth/logout", { method: "POST" });
      S.user = null;
      S.cache = {};
      S.setup = false;
      showAuth();
      toast("Você saiu do COMPAC.");
    } catch (error) {
      toast(error.message, "error");
    }
  };
  $("#menu-toggle").onclick = openSidebar;
  $("#sidebar-close").onclick = closeSidebar;
  $("#sidebar-overlay").onclick = closeSidebar;
  $("#refresh-button").onclick = refreshPage;
  $("#form-dialog").addEventListener("click", (e) => {
    if (e.target === $("#form-dialog")) {
      const r = e.target.getBoundingClientRect();
      if (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      )
        e.target.close();
    }
  });
  window.addEventListener("hashchange", () => route());
  window.addEventListener("online", () => {
    $("#connection-text").textContent = "Conectado à operação";
  });
  window.addEventListener("offline", () => {
    $("#connection-text").textContent = "Sem conexão";
    toast(
      "Você está sem conexão. Reconecte para consultar e registrar informações.",
      "error",
    );
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && $("#sidebar").classList.contains("open") && sidebarMedia.matches) {
      const focusable = $$("a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex='-1'])", $("#sidebar"))
        .filter(el => el.getClientRects().length && !el.closest("[hidden]"));
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (!$("#sidebar").contains(document.activeElement) || (e.shiftKey && document.activeElement === first) || (!e.shiftKey && document.activeElement === last)) {
        e.preventDefault();
        (e.shiftKey ? last : first)?.focus();
      }
    }
    if (
      e.key === "/" &&
      !e.ctrlKey &&
      !e.metaKey &&
      !e.altKey &&
      !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) &&
      S.user &&
      !$("#form-dialog").open
    ) {
      e.preventDefault();
      $("#global-search").focus();
    }
    if (e.key === "Escape") closeSidebar();
  });
  $("#auth-lock").innerHTML = icon("lock");
  $(".workspace-icon").innerHTML = icon("building");
  $("#install-icon").innerHTML = icon("download");
  $("#password-settings-icon").innerHTML = icon("lock");
  $("#logout-button").innerHTML = icon("logout");
  $("#menu-toggle").innerHTML = icon("menu");
  $("#sidebar-close").innerHTML = icon("close");
  $("#search-icon").innerHTML = icon("search");
  $("#refresh-button").innerHTML = icon("refresh");
  $("#notification-icon").innerHTML = icon("bell");
  (async () => {
    try {
      const status = await api("/auth/status");
      S.setup = !!status.needs_setup;
      S.setupToken = !!status.setup_token_required;
      if (S.setup) {
        showAuth();
        return;
      }
      try {
        await enterApp();
      } catch (error) {
        showAuth();
        if (!/autentic|sessão|login|acesso|credencia/i.test(error.message)) {
          toast(error.message, "error");
        }
      }
    } catch (error) {
      showAuth();
      $("#auth-error").textContent = error.message;
      $("#auth-error").hidden = false;
    }
  })();
})();
