const statusEl = document.getElementById("adminStatus");
const tokenInput = document.getElementById("adminToken");
const loadBtn = document.getElementById("loadContent");
const loadLocalBtn = document.getElementById("loadLocal");
const saveBtn = document.getElementById("saveContent");
const addNewsBtn = document.getElementById("addNews");
const addGroupBtn = document.getElementById("addGroup");
const newsList = document.getElementById("newsList");
const groupList = document.getElementById("groupList");

const newsTpl = document.getElementById("newsItemTpl");
const groupTpl = document.getElementById("groupTpl");
const roleTpl = document.getElementById("roleTpl");

let contentState = { news: [], jobs: [] };

const setStatus = (message, isError = false) => {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "#b91c1c" : "#6b7280";
};

const readField = (obj, path, fallback = "") => {
  return path.split(".").reduce((acc, key) => (acc ? acc[key] : undefined), obj) ?? fallback;
};

const setField = (obj, path, value) => {
  const keys = path.split(".");
  let current = obj;
  keys.forEach((key, index) => {
    if (index === keys.length - 1) {
      current[key] = value;
    } else {
      if (!current[key] || typeof current[key] !== "object") {
        current[key] = {};
      }
      current = current[key];
    }
  });
};

const createEmptyLang = () => ({ zh: "", ja: "", en: "" });

const createNewsItem = () => ({
  id: `news-${Date.now()}`,
  title: createEmptyLang(),
  body: createEmptyLang(),
});

const createRole = () => ({
  id: `role-${Date.now()}`,
  title: createEmptyLang(),
  location: createEmptyLang(),
  desc: createEmptyLang(),
});

const createGroup = () => ({
  id: `group-${Date.now()}`,
  title: createEmptyLang(),
  desc: createEmptyLang(),
  roles: [],
});

const bindInputs = (root, target) => {
  root.querySelectorAll("[data-field]").forEach((input) => {
    const path = input.dataset.field;
    input.value = readField(target, path, "");
    input.addEventListener("input", (event) => {
      setField(target, path, event.target.value);
    });
  });
};

const renderNews = () => {
  newsList.innerHTML = "";
  contentState.news.forEach((item, index) => {
    const node = newsTpl.content.cloneNode(true);
    const card = node.querySelector(".admin-card");
    bindInputs(card, item);
    card.querySelector("[data-remove]").addEventListener("click", () => {
      contentState.news.splice(index, 1);
      renderNews();
    });
    newsList.appendChild(node);
  });
};

const renderRoles = (roleListEl, roles) => {
  roleListEl.innerHTML = "";
  roles.forEach((role, index) => {
    const node = roleTpl.content.cloneNode(true);
    const card = node.querySelector(".admin-card");
    bindInputs(card, role);
    card.querySelector("[data-remove]").addEventListener("click", () => {
      roles.splice(index, 1);
      renderRoles(roleListEl, roles);
    });
    roleListEl.appendChild(node);
  });
};

const renderGroups = () => {
  groupList.innerHTML = "";
  contentState.jobs.forEach((group, index) => {
    const node = groupTpl.content.cloneNode(true);
    const card = node.querySelector(".admin-card");
    bindInputs(card, group);
    const roleListEl = card.querySelector("[data-role-list]");
    renderRoles(roleListEl, group.roles || []);
    card.querySelector("[data-add-role]").addEventListener("click", () => {
      group.roles = group.roles || [];
      group.roles.push(createRole());
      renderRoles(roleListEl, group.roles);
    });
    card.querySelector("[data-remove]").addEventListener("click", () => {
      contentState.jobs.splice(index, 1);
      renderGroups();
    });
    groupList.appendChild(node);
  });
};

const renderAll = () => {
  renderNews();
  renderGroups();
};

const loadContent = async (url) => {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`加载失败：${response.status}`);
  return response.json();
};

const applyContent = (data) => {
  contentState = {
    news: Array.isArray(data.news) ? data.news : [],
    jobs: Array.isArray(data.jobs) ? data.jobs : [],
  };
  renderAll();
};

loadBtn.addEventListener("click", async () => {
  try {
    const data = await loadContent("/api/content");
    applyContent(data);
    setStatus("已从后台加载内容。");
  } catch (error) {
    setStatus("无法从后台加载，请确认后台服务已启动。", true);
  }
});

loadLocalBtn.addEventListener("click", async () => {
  try {
    const data = await loadContent("./content.json");
    applyContent(data);
    setStatus("已加载本地 content.json。");
  } catch (error) {
    setStatus("无法加载本地 content.json。", true);
  }
});

saveBtn.addEventListener("click", async () => {
  try {
    const response = await fetch("/api/content", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "x-admin-token": tokenInput.value.trim(),
      },
      body: JSON.stringify(contentState, null, 2),
    });
    if (!response.ok) throw new Error(`保存失败：${response.status}`);
    setStatus("内容已保存到后台。");
  } catch (error) {
    setStatus("保存失败，请确认令牌和后台服务。", true);
  }
});

addNewsBtn.addEventListener("click", () => {
  contentState.news.push(createNewsItem());
  renderNews();
});

addGroupBtn.addEventListener("click", () => {
  contentState.jobs.push(createGroup());
  renderGroups();
});

tokenInput.value = localStorage.getItem("kizuna-admin-token") || "";
tokenInput.addEventListener("input", () => {
  localStorage.setItem("kizuna-admin-token", tokenInput.value);
});

loadLocalBtn.click();
