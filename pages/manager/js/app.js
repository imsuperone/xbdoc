// Document Memory Assistant - app module
(function (App) {
  "use strict";
  const { state } = App;

function initTabs() {
  const tabs = document.querySelectorAll(".cat-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      App.switchTab(tab.dataset.tab);
    });
  });
}

async function startApp() {
  console.log("[DocMemory] Starting Android 16 UI application...");

  // 1. Synchronous UI initialization (never blocks)
  App.initTheme();
  App.initAccentPicker();
  App.initAccentPopover();
  initTabs();
  App.initDocGridEvents();
  App.initDocSearch();
  App.initDropzone();
  App.initDocChipsEvents();
  App.initGroupSuggest();
  App.initDocMode();
  App.initShieldChoice();
  App.initForceChoice();
  App.initShieldFilter();
  App.initBindingForm();
  App.initBindingListEvents();
  App.initReaderEvents();
  App.initBackupButtons();
  App.initSettings();
  App.initRefreshButton();
  App.updatePromptCount();
  App.fetchAndApplyVersion();

  // 2. Load critical first-screen data first, then prefetch secondary tabs
  try {
    await Promise.all([App.loadSettings(), App.loadDocs()]);
    console.log("[DocMemory] Initial data loaded successfully.");
  } catch (e) {
    console.warn("[DocMemory] Initial data load partial failure:", e);
  }
  App.ensureBindingsLoaded();

  // 更新检查不阻塞首屏，延后让路
  setTimeout(() => {
    App.checkForUpdate();
  }, 2500);
}

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startApp);
  } else {
    startApp();
  }
})(window.DocMemoryApp = window.DocMemoryApp || {});
