/**
 * Read-only extraction helpers for $ceratops-task-lifecycle import-from-chatgpt.
 *
 * Import this module inside the node_repl browser session, then pass the
 * exported script strings to tab.playwright.evaluate(...). The snippets read
 * rendered DOM content only; they intentionally avoid cookies, storage,
 * credentials, browser profiles, and network internals.
 */

export const LIST_CHATS_SCRIPT = `(() => {
  const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
  const out = [];
  const seen = new Set();

  for (const link of Array.from(document.querySelectorAll("a[href]"))) {
    const href = new URL(link.getAttribute("href"), location.href).href;
    const isChat = /^https:\\/\\/chatgpt\\.com\\/(?:g\\/[^/]+(?:\\/[^/]+)?\\/)?c\\/[0-9a-f-]+/i.test(href);
    if (!isChat || seen.has(href)) continue;

    const title = clean(link.innerText || link.textContent);
    if (!title) continue;

    seen.add(href);
    out.push({ title, url: href });
  }

  return {
    extractedAt: new Date().toISOString(),
    url: location.href,
    title: document.title || "",
    chats: out
  };
})()`;

export const EXTRACT_CONVERSATION_SCRIPT = `(() => {
  const clean = (value) => String(value || "")
    .replace(/\\u00a0/g, " ")
    .replace(/[ \\t]+\\n/g, "\\n")
    .replace(/\\n{3,}/g, "\\n\\n")
    .trim();

  const removeControls = (node) => {
    for (const selector of [
      "button",
      "nav",
      "menu",
      "[role='button']",
      "[aria-hidden='true']",
      "[data-testid*='copy']",
      "[data-testid*='feedback']",
      "[data-testid*='composer']",
      "[contenteditable='true']"
    ]) {
      for (const child of Array.from(node.querySelectorAll(selector))) child.remove();
    }
  };

  const roleNodes = Array.from(document.querySelectorAll("[data-message-author-role]"));
  const messageRoots = roleNodes.length
    ? roleNodes.map((node) => ({ node, role: node.getAttribute("data-message-author-role") || "unknown" }))
    : Array.from(document.querySelectorAll("article")).map((node) => {
        const label = clean(node.getAttribute("aria-label") || node.innerText).toLowerCase();
        const role = label.includes("you said") || label.includes("user") ? "user"
          : label.includes("chatgpt") || label.includes("assistant") ? "assistant"
          : "unknown";
        return { node, role };
      });

  const messages = [];
  const seen = new Set();

  for (const item of messageRoots) {
    const clone = item.node.cloneNode(true);
    removeControls(clone);

    const text = clean(clone.innerText || clone.textContent);
    if (!text) continue;

    const root = item.node.closest("article") || item.node;
    const id = item.node.getAttribute("data-message-id")
      || root.getAttribute("data-testid")
      || root.id
      || "";
    const key = item.role + "\\n" + text;
    if (seen.has(key)) continue;
    seen.add(key);

    messages.push({
      role: clean(item.role || "unknown").toLowerCase(),
      id,
      text
    });
  }

  const activeLink = document.querySelector("a[aria-current='page'][href*='/c/']");
  const chatTitle = clean(activeLink?.innerText || document.title || "");
  const scrollElement = document.scrollingElement || document.documentElement;

  return {
    extractedAt: new Date().toISOString(),
    url: location.href,
    pageTitle: document.title || "",
    chatTitle,
    scroll: {
      y: scrollElement.scrollTop,
      height: scrollElement.scrollHeight,
      viewport: window.innerHeight
    },
    messages
  };
})()`;

export function mergeMessages(chunks) {
  const messages = [];
  const seen = new Set();

  for (const chunk of chunks || []) {
    for (const message of chunk?.messages || []) {
      const role = normalizeRole(message.role);
      const text = String(message.text || "").trim();
      if (!text) continue;

      const key = `${role}\n${text.replace(/\s+/g, " ")}`;
      if (seen.has(key)) continue;
      seen.add(key);
      messages.push({ ...message, role, text });
    }
  }

  return messages;
}

export function formatTranscript(payload) {
  const title = payload?.chatTitle || payload?.pageTitle || "ChatGPT chat";
  const url = payload?.url || "";
  const extractedAt = payload?.extractedAt || new Date().toISOString();
  const messages = payload?.messages || [];
  const lines = [
    "# Imported ChatGPT Chat",
    "",
    `Title: ${title}`,
    `Source: ${url}`,
    `Extracted: ${extractedAt}`,
    `Messages: ${messages.length}`,
    "",
    "Use this transcript as a handoff only. Do not assume access to hidden ChatGPT state, attachments, tools, or future sync.",
    ""
  ];

  messages.forEach((message, index) => {
    lines.push(`## ${index + 1}. ${formatRole(message.role)}`);
    lines.push("");
    lines.push(String(message.text || "").trim());
    lines.push("");
  });

  return lines.join("\n").trim() + "\n";
}

function normalizeRole(role) {
  const normalized = String(role || "unknown").toLowerCase();
  if (normalized.includes("user")) return "user";
  if (normalized.includes("assistant") || normalized.includes("chatgpt")) return "assistant";
  if (normalized.includes("tool")) return "tool";
  if (normalized.includes("system")) return "system";
  return normalized || "unknown";
}

function formatRole(role) {
  const normalized = normalizeRole(role);
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}
