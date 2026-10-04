/* Native-messaging bridge for Jev's task-tab memory and restore command. */
const api = globalThis.browser || globalThis.chrome;
const BROWSER = globalThis.browser ? "firefox" : "chrome";
const HOST = "com.crankyclippy.bridge";
const RECONNECT_ALARM = "cranky-clippy-native-reconnect";
let nativePort = null;
let retryDelay = 1000;

function invoke(object, method, ...args) {
  return new Promise((resolve, reject) => {
    object[method](...args, result => {
      const error = api.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve(result);
    });
  });
}

function connectNative() {
  if (nativePort) return;
  try {
    nativePort = api.runtime.connectNative(HOST);
  } catch (_error) {
    scheduleReconnect();
    return;
  }
  nativePort.onMessage.addListener(message => {
    if (message.action === "remember") {
      rememberTab(message.target);
    } else if (message.action === "restore") {
      restoreTab(message.target);
    } else if (message.action === "shutdown") {
      const port = nativePort;
      nativePort = null;
      try { port.disconnect(); } catch (_error) {}
      scheduleReconnect();
    }
  });
  nativePort.onDisconnect.addListener(() => {
    nativePort = null;
    scheduleReconnect();
  });
  retryDelay = 1000;
}

function scheduleReconnect() {
  setTimeout(connectNative, retryDelay);
  retryDelay = Math.min(retryDelay * 2, 30000);
}

async function rememberTab(target) {
  try {
    const tabs = await invoke(api.tabs, "query", {});
    const expectedUrl = normalizedUrl(target.site_url || "");
    const expectedTitle = (target.tab_title || "").trim().toLocaleLowerCase();
    const titleMatches = candidate => {
      const actual = (candidate.title || "").trim().toLocaleLowerCase();
      return Boolean(expectedTitle && actual && (actual === expectedTitle ||
        actual.includes(expectedTitle) || expectedTitle.includes(actual)));
    };
    const urlCandidates = expectedUrl
      ? tabs.filter(candidate => normalizedUrl(candidate.url) === expectedUrl)
      : [];
    // Search all windows, not just lastFocusedWindow: the browser's active
    // tab may already be the distraction while Jev is processing its verdict.
    const tab = (urlCandidates.find(titleMatches) || urlCandidates[0]) ||
      tabs.find(titleMatches);
    if (!tab) {
      nativePort?.postMessage({type: "remember_mismatch", expected: target.tab_title || target.site_url});
      return;
    }
    const record = {
      tabId: tab.id,
      windowId: tab.windowId,
      url: tab.url || target.site_url || "",
      title: tab.title || target.tab_title || target.window_title || "",
      target: target,
      savedAt: Date.now(),
    };
    await invoke(api.storage.local, "set", {lastOnTaskTab: record});
    nativePort?.postMessage({type: "remembered", title: record.title});
  } catch (error) {
    nativePort?.postMessage({type: "error", action: "remember", message: String(error)});
  }
}

function normalizedUrl(url) {
  try {
    const parsed = new URL(url);
    parsed.hash = "";
    return parsed.href;
  } catch (_error) {
    return url || "";
  }
}

async function restoreTab(target) {
  try {
    const stored = await invoke(api.storage.local, "get", "lastOnTaskTab");
    const saved = stored && stored.lastOnTaskTab;
    const tabs = await invoke(api.tabs, "query", {});
    const desiredUrl = (saved && saved.url) || target.site_url || "";
    const desiredNormalized = normalizedUrl(desiredUrl);
    let tab = saved && tabs.find(candidate =>
      candidate.id === saved.tabId &&
      desiredNormalized && normalizedUrl(candidate.url) === desiredNormalized
    );
    if (!tab && desiredNormalized) {
      tab = tabs.find(candidate => normalizedUrl(candidate.url) === desiredNormalized);
    }
    if (!tab && target.tab_title) {
      const title = target.tab_title.trim().toLocaleLowerCase();
      tab = tabs.find(candidate => (candidate.title || "").trim().toLocaleLowerCase() === title);
    }

    if (!tab) {
      if (!desiredUrl || !/^https?:\/\//i.test(desiredUrl)) {
        throw new Error("The saved tab is gone and has no restorable web URL.");
      }
      tab = await invoke(api.tabs, "create", {url: desiredUrl, active: true});
    } else {
      await invoke(api.tabs, "update", tab.id, {active: true});
    }
    if (tab.windowId !== undefined) {
      await invoke(api.windows, "update", tab.windowId, {focused: true});
    }
    nativePort?.postMessage({
      type: "restored",
      reusedExistingTab: Boolean(saved && tab.id === saved.tabId),
      title: tab.title || target.tab_title || "",
      url: tab.url || desiredUrl,
    });
  } catch (error) {
    nativePort?.postMessage({type: "error", action: "restore", message: String(error)});
  }
}

api.runtime.onInstalled.addListener(() => {
  api.alarms.create(RECONNECT_ALARM, {periodInMinutes: 1});
  connectNative();
});
api.runtime.onStartup.addListener(() => {
  api.alarms.create(RECONNECT_ALARM, {periodInMinutes: 1});
  connectNative();
});
api.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === RECONNECT_ALARM && !nativePort) connectNative();
});
connectNative();
