from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from html import escape, unescape
from pathlib import Path

import markdown


REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
OUTPUT_DIR = REPO_ROOT / "site"
ASSETS_DIR = OUTPUT_DIR / "assets"
REPO_URL = "https://github.com/korolevpavel/xbsl-ai-skills"
SITE_TITLE = "XBSL Skills"
SITE_SUBTITLE = "AI-инструменты для 1С:Элемент"

STYLE_CSS = """
:root {
  --bg: #f5f0e7;
  --bg-accent: radial-gradient(circle at top left, rgba(16, 134, 121, 0.16), transparent 34%),
    radial-gradient(circle at top right, rgba(220, 131, 72, 0.16), transparent 28%),
    linear-gradient(180deg, #fbf7ef 0%, #f1eadf 100%);
  --surface: rgba(255, 251, 245, 0.82);
  --surface-strong: #fffaf4;
  --surface-alt: rgba(243, 236, 224, 0.92);
  --line: rgba(97, 87, 69, 0.16);
  --line-strong: rgba(16, 134, 121, 0.28);
  --text: #1f2421;
  --muted: #5d645d;
  --accent: #108679;
  --accent-strong: #075f57;
  --accent-soft: rgba(16, 134, 121, 0.12);
  --warm: #d68048;
  --warm-soft: rgba(214, 128, 72, 0.13);
  --code-bg: #142325;
  --code-text: #dffcf4;
  --shadow: 0 18px 46px rgba(43, 39, 32, 0.08);
  --radius-lg: 24px;
  --radius-md: 18px;
  --radius-sm: 12px;
  --font-sans: "IBM Plex Sans", "Segoe UI Variable", "Segoe UI", "SF Pro Display", system-ui, sans-serif;
  --font-headings: "Avenir Next", "Segoe UI Variable Display", "Trebuchet MS", sans-serif;
  --font-mono: "JetBrains Mono", "SFMono-Regular", "Cascadia Code", "Menlo", monospace;
}

body[data-theme="dark"] {
  --bg: #101818;
  --bg-accent: radial-gradient(circle at top left, rgba(31, 181, 161, 0.18), transparent 32%),
    radial-gradient(circle at top right, rgba(230, 139, 81, 0.18), transparent 24%),
    linear-gradient(180deg, #0f1716 0%, #101919 100%);
  --surface: rgba(21, 30, 30, 0.8);
  --surface-strong: #172120;
  --surface-alt: rgba(16, 24, 24, 0.92);
  --line: rgba(225, 236, 232, 0.12);
  --line-strong: rgba(69, 208, 189, 0.28);
  --text: #edf4f0;
  --muted: #9db0a8;
  --accent: #34c8b4;
  --accent-strong: #91f2e4;
  --accent-soft: rgba(52, 200, 180, 0.12);
  --warm: #f0a26c;
  --warm-soft: rgba(240, 162, 108, 0.14);
  --code-bg: #0a1010;
  --code-text: #d9fff5;
  --shadow: 0 24px 56px rgba(0, 0, 0, 0.28);
}

* {
  box-sizing: border-box;
}

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  background: var(--bg-accent);
  font-family: var(--font-sans);
}

body::before,
body::after {
  content: "";
  position: fixed;
  z-index: 0;
  border-radius: 50%;
  pointer-events: none;
  filter: blur(10px);
}

body::before {
  top: 72px;
  right: 8vw;
  width: 190px;
  height: 190px;
  background: var(--warm-soft);
}

body::after {
  bottom: 8vh;
  left: 5vw;
  width: 220px;
  height: 220px;
  background: var(--accent-soft);
}

a {
  color: var(--accent);
  text-decoration: none;
}

a:hover {
  color: var(--accent-strong);
}

button,
input {
  font: inherit;
}

.site-shell {
  position: relative;
  z-index: 1;
  width: min(1500px, calc(100% - 28px));
  margin: 16px auto 22px;
}

.panel {
  background: color-mix(in srgb, var(--surface) 94%, transparent);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
}

.topbar {
  position: sticky;
  top: 16px;
  z-index: 50;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px;
  margin-bottom: 18px;
}

.menu-btn {
  display: none;
}

.toolbar-btn,
.hero-link,
.repo-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.toolbar-btn {
  height: 48px;
  min-width: 48px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface-alt);
  color: var(--text);
  cursor: pointer;
  transition: transform 120ms ease, border-color 120ms ease;
}

.toolbar-btn:hover,
.hero-link:hover,
.repo-link:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  margin-right: auto;
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 15px;
  background:
    linear-gradient(135deg, rgba(16, 134, 121, 0.92), rgba(16, 134, 121, 0.34)),
    linear-gradient(315deg, rgba(214, 128, 72, 0.78), rgba(214, 128, 72, 0.24));
  position: relative;
  flex: 0 0 auto;
}

.brand-mark::after {
  content: "";
  position: absolute;
  inset: 10px;
  border: 2px solid rgba(255, 255, 255, 0.94);
  border-radius: 11px 11px 5px 11px;
}

.brand-copy {
  min-width: 0;
}

.brand-title {
  display: block;
  font-family: var(--font-headings);
  font-size: 1rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.brand-subtitle {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-size: 0.9rem;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 1 620px;
}

.search-wrap {
  position: relative;
  flex: 1 1 auto;
}

.search-input {
  width: 100%;
  height: 48px;
  padding: 0 16px 0 46px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface-alt);
  color: var(--text);
  outline: none;
}

.search-input:focus {
  border-color: var(--line-strong);
  box-shadow: 0 0 0 4px var(--accent-soft);
}

.search-icon {
  position: absolute;
  top: 50%;
  left: 16px;
  width: 18px;
  height: 18px;
  transform: translateY(-50%);
  color: var(--muted);
}

.toolbar-btn-label {
  display: none;
}

.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 260px;
  gap: 18px;
  align-items: start;
}

.sidebar {
  position: sticky;
  top: 100px;
  padding: 22px;
}

.sidebar-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 0.84rem;
  font-weight: 700;
}

.sidebar-title {
  margin: 16px 0 8px;
  font-family: var(--font-headings);
  font-size: 1.7rem;
  line-height: 1.02;
}

.sidebar-text {
  margin: 0;
  color: var(--muted);
  line-height: 1.55;
}

.nav-list {
  list-style: none;
  padding: 0;
  margin: 20px 0 0;
  display: grid;
  gap: 10px;
}

.nav-link {
  display: block;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: color-mix(in srgb, var(--surface-alt) 90%, transparent);
  transition: transform 120ms ease, border-color 120ms ease;
}

.nav-link:hover {
  transform: translateY(-1px);
}

.nav-link.active {
  border-color: var(--line-strong);
  background: linear-gradient(180deg, var(--accent-soft), color-mix(in srgb, var(--surface-strong) 92%, transparent));
}

.nav-label {
  display: block;
  color: var(--text);
  font-weight: 700;
}

.nav-description {
  margin-top: 8px;
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.5;
}

.repo-link {
  width: 100%;
  margin-top: 18px;
  height: 46px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--surface-alt);
  color: var(--text);
  font-weight: 600;
}

.content {
  min-width: 0;
}

.page {
  padding: 28px;
}

.hero {
  position: relative;
  overflow: hidden;
  padding: 28px;
  margin-bottom: 18px;
  border-radius: 26px;
  border: 1px solid var(--line);
  background:
    radial-gradient(circle at top right, rgba(214, 128, 72, 0.14), transparent 30%),
    radial-gradient(circle at left center, rgba(16, 134, 121, 0.12), transparent 34%),
    color-mix(in srgb, var(--surface-strong) 96%, transparent);
}

.hero::after {
  content: "";
  position: absolute;
  top: 18px;
  right: -8px;
  width: 150px;
  height: 150px;
  border-radius: 28px;
  transform: rotate(12deg);
  border: 1px solid rgba(16, 134, 121, 0.16);
  background: linear-gradient(180deg, rgba(16, 134, 121, 0.08), transparent);
}

.hero-meta {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 11px;
  border-radius: 999px;
  background: var(--surface-alt);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.84rem;
  font-weight: 600;
}

.hero-title {
  position: relative;
  z-index: 1;
  margin: 0;
  max-width: 760px;
  font-family: var(--font-headings);
  font-size: clamp(2.1rem, 3.1vw, 3.3rem);
  line-height: 0.96;
  letter-spacing: -0.02em;
}

.hero-description {
  position: relative;
  z-index: 1;
  max-width: 760px;
  margin: 16px 0 0;
  color: var(--muted);
  font-size: 1.03rem;
  line-height: 1.72;
}

.hero-actions {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 18px;
}

.hero-link {
  height: 42px;
  padding: 0 14px;
  border-radius: 12px;
  background: var(--surface-alt);
  border: 1px solid var(--line);
  color: var(--text);
  font-weight: 600;
}

.hero-link.primary {
  color: white;
  border-color: transparent;
  background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 86%, white), color-mix(in srgb, var(--accent) 92%, black));
}

.doc-body h1 {
  display: none;
}

.doc-body h2,
.doc-body h3,
.doc-body h4 {
  scroll-margin-top: 105px;
  font-family: var(--font-headings);
  line-height: 1.08;
  letter-spacing: -0.02em;
}

.doc-body h2 {
  margin: 34px 0 14px;
  font-size: 1.7rem;
}

.doc-body h3 {
  margin: 24px 0 12px;
  font-size: 1.22rem;
}

.doc-body h4 {
  margin: 18px 0 10px;
  font-size: 1rem;
}

.doc-body p,
.doc-body li,
.doc-body td,
.doc-body th,
.doc-body blockquote {
  line-height: 1.72;
}

.doc-body p,
.doc-body ul,
.doc-body ol,
.doc-body table,
.doc-body pre,
.doc-body blockquote {
  margin: 0 0 18px;
}

.doc-body ul,
.doc-body ol {
  padding-left: 1.45rem;
}

.doc-body li + li {
  margin-top: 8px;
}

.doc-body code {
  padding: 0.14rem 0.38rem;
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent-soft) 72%, transparent);
  color: color-mix(in srgb, var(--accent-strong) 82%, var(--text));
  font-family: var(--font-mono);
  font-size: 0.92em;
}

.doc-body pre {
  padding: 18px 20px;
  overflow: auto;
  border-radius: 18px;
  background: var(--code-bg);
  color: var(--code-text);
}

.doc-body pre code {
  padding: 0;
  background: none;
  color: inherit;
  font-size: 0.92rem;
}

.doc-body table {
  width: 100%;
  border-collapse: collapse;
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
  background: color-mix(in srgb, var(--surface-alt) 92%, transparent);
}

.doc-body th,
.doc-body td {
  padding: 12px 14px;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--line);
}

.doc-body tr:last-child td {
  border-bottom: none;
}

.doc-body th {
  color: var(--muted);
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.doc-body blockquote {
  padding: 14px 18px;
  border-left: 4px solid var(--accent);
  border-radius: 0 14px 14px 0;
  background: var(--accent-soft);
}

.stats-grid,
.skills-grid {
  display: grid;
  gap: 14px;
}

.stats-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 24px 0 10px;
}

.skills-grid {
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  margin: 0;
}

.stat-card,
.skill-card {
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: color-mix(in srgb, var(--surface-alt) 94%, transparent);
}

.stat-value {
  font-family: var(--font-headings);
  font-size: 1.8rem;
  line-height: 1;
}

.stat-label {
  margin-top: 8px;
  color: var(--muted);
  line-height: 1.5;
}

.catalog {
  margin: 26px 0 6px;
}

.catalog-title {
  margin: 0 0 8px;
  font-family: var(--font-headings);
  font-size: 1.8rem;
}

.catalog-copy {
  margin: 0 0 16px;
  color: var(--muted);
  line-height: 1.6;
}

.skill-card {
  display: block;
  transition: transform 120ms ease, border-color 120ms ease;
}

.skill-card:hover {
  transform: translateY(-2px);
  border-color: var(--line-strong);
}

.skill-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.skill-card-title {
  color: var(--text);
  font-weight: 700;
}

.skill-card-runtime {
  flex: 0 0 auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--warm-soft);
  color: color-mix(in srgb, var(--warm) 74%, var(--text));
  font-size: 0.72rem;
}

.skill-card-copy {
  margin-top: 10px;
  color: var(--muted);
  line-height: 1.55;
}

.skill-card-arrow {
  margin-top: 14px;
  color: var(--accent);
  font-weight: 700;
}

.toc {
  position: sticky;
  top: 100px;
  padding: 22px;
}

.toc-title {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 0.92rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.toc-list,
.toc-list ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.toc-list ul {
  margin-top: 8px;
  padding-left: 14px;
  border-left: 1px solid var(--line);
}

.toc-item + .toc-item {
  margin-top: 10px;
}

.toc-link {
  color: var(--muted);
  line-height: 1.45;
}

.toc-empty {
  color: var(--muted);
  line-height: 1.5;
}

.search-panel {
  position: absolute;
  top: calc(100% + 10px);
  left: 0;
  right: 0;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: color-mix(in srgb, var(--surface-strong) 96%, transparent);
  box-shadow: var(--shadow);
  display: none;
}

.search-panel.visible {
  display: block;
}

.search-results {
  display: grid;
  gap: 8px;
}

.search-result {
  display: block;
  padding: 14px 16px;
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface-alt) 92%, transparent);
  border: 1px solid transparent;
}

.search-result:hover {
  border-color: var(--line-strong);
}

.search-result-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
  color: var(--text);
  font-weight: 700;
}

.search-result-page {
  color: var(--accent);
  font-size: 0.82rem;
}

.search-result-copy,
.search-hint {
  color: var(--muted);
  line-height: 1.5;
}

.search-hint {
  padding: 14px 16px;
}

.page-footer {
  margin-top: 28px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 0.9rem;
}

.overlay {
  display: none;
}

@media (max-width: 1180px) {
  .layout {
    grid-template-columns: 300px minmax(0, 1fr);
  }

  .toc {
    display: none;
  }
}

@media (max-width: 920px) {
  .site-shell {
    width: min(100%, calc(100% - 18px));
    margin-top: 10px;
  }

  .topbar {
    top: 10px;
    flex-wrap: wrap;
  }

  .menu-btn {
    display: inline-flex;
  }

  .toolbar {
    flex: 1 0 100%;
  }

  .layout {
    display: block;
  }

  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 80;
    width: min(360px, calc(100vw - 28px));
    border-radius: 0 24px 24px 0;
    transform: translateX(-105%);
    transition: transform 180ms ease;
    overflow: auto;
  }

  body.nav-open .sidebar {
    transform: translateX(0);
  }

  .overlay {
    position: fixed;
    inset: 0;
    z-index: 70;
    background: rgba(0, 0, 0, 0.28);
  }

  body.nav-open .overlay {
    display: block;
  }

  .page {
    padding: 20px;
  }

  .hero {
    padding: 22px;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .toolbar-btn-label {
    display: inline;
  }
}

@media (max-width: 620px) {
  .brand {
    width: 100%;
  }

  .toolbar {
    gap: 8px;
  }

  .hero-title {
    font-size: 1.95rem;
  }

  .doc-body table {
    display: block;
    overflow-x: auto;
  }
}
"""

APP_JS = """
(() => {
  const body = document.body;
  const themeKey = "xbsl-skills-theme";
  const searchInput = document.querySelector("[data-search-input]");
  const searchPanel = document.querySelector("[data-search-panel]");
  const searchResults = document.querySelector("[data-search-results]");
  const themeToggle = document.querySelector("[data-theme-toggle]");
  const themeLabel = document.querySelector("[data-theme-label]");
  const navToggles = document.querySelectorAll("[data-sidebar-toggle]");
  const sidebar = document.querySelector("[data-sidebar]");
  const overlay = document.querySelector("[data-overlay]");

  const applyTheme = (theme) => {
    body.dataset.theme = theme;
    localStorage.setItem(themeKey, theme);
    if (themeLabel) {
      themeLabel.textContent = theme === "dark" ? "Светлая тема" : "Тёмная тема";
    }
  };

  applyTheme(localStorage.getItem(themeKey) || body.dataset.theme || "light");

  themeToggle?.addEventListener("click", () => {
    applyTheme(body.dataset.theme === "dark" ? "light" : "dark");
  });

  const setNavState = (isOpen) => {
    body.classList.toggle("nav-open", isOpen);
  };

  navToggles.forEach((button) => {
    button.addEventListener("click", () => {
      setNavState(!body.classList.contains("nav-open"));
    });
  });

  overlay?.addEventListener("click", () => setNavState(false));
  sidebar?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => setNavState(false));
  });

  const index = (window.SEARCH_INDEX || []).map((item) => {
    const text = [item.title, item.summary, item.text, ...(item.headings || [])]
      .join(" ")
      .toLowerCase();
    return { ...item, searchText: text };
  });

  const tokenize = (value) =>
    value
      .trim()
      .toLowerCase()
      .split(/\\s+/)
      .filter(Boolean);

  const scoreItem = (item, tokens) => {
    let score = 0;
    const title = item.title.toLowerCase();
    const summary = item.summary.toLowerCase();
    const headings = (item.headings || []).join(" ").toLowerCase();
    for (const token of tokens) {
      if (!item.searchText.includes(token)) {
        return -1;
      }
      if (title.includes(token)) score += 7;
      if (summary.includes(token)) score += 3;
      if (headings.includes(token)) score += 2;
      score += Math.max(1, 4 - item.searchText.indexOf(token) / 200);
    }
    return score;
  };

  const createSnippet = (item, query) => {
    if (!query) {
      return item.summary;
    }
    const text = item.text.replace(/\\s+/g, " ");
    const lower = text.toLowerCase();
    const firstToken = tokenize(query)[0];
    const index = lower.indexOf(firstToken);
    if (index === -1) {
      return item.summary;
    }
    const start = Math.max(0, index - 70);
    const end = Math.min(text.length, index + 170);
    const prefix = start > 0 ? "..." : "";
    const suffix = end < text.length ? "..." : "";
    return prefix + text.slice(start, end).trim() + suffix;
  };

  const renderResults = (query) => {
    if (!searchPanel || !searchResults) {
      return;
    }

    const trimmed = query.trim();
    const tokens = tokenize(trimmed);
    searchPanel.classList.add("visible");

    if (!trimmed) {
      searchResults.innerHTML = index
        .slice(0, 6)
        .map((item) => `
          <a class="search-result" href="${item.url}">
            <div class="search-result-title">
              <span>${item.title}</span>
              <span class="search-result-page">${item.pageLabel}</span>
            </div>
            <div class="search-result-copy">${item.summary}</div>
          </a>
        `)
        .join("");
      return;
    }

    const results = index
      .map((item) => ({ item, score: scoreItem(item, tokens) }))
      .filter((entry) => entry.score >= 0)
      .sort((left, right) => right.score - left.score)
      .slice(0, 8);

    if (!results.length) {
      searchResults.innerHTML = `
        <div class="search-hint">
          Ничего не найдено. Попробуйте имя скилла, команду из описания или термин из секций.
        </div>
      `;
      return;
    }

    searchResults.innerHTML = results
      .map(({ item }) => `
        <a class="search-result" href="${item.url}">
          <div class="search-result-title">
            <span>${item.title}</span>
            <span class="search-result-page">${item.pageLabel}</span>
          </div>
          <div class="search-result-copy">${createSnippet(item, trimmed)}</div>
        </a>
      `)
      .join("");
  };

  searchInput?.addEventListener("input", (event) => {
    renderResults(event.target.value);
  });

  searchInput?.addEventListener("focus", (event) => {
    renderResults(event.target.value);
  });

  document.addEventListener("click", (event) => {
    if (
      searchPanel &&
      searchInput &&
      !searchPanel.contains(event.target) &&
      event.target !== searchInput
    ) {
      searchPanel.classList.remove("visible");
    }
  });

  document.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName;
    const isTypingTarget =
      tag === "INPUT" || tag === "TEXTAREA" || document.activeElement?.isContentEditable;

    if (event.key === "/" && !isTypingTarget) {
      event.preventDefault();
      searchInput?.focus();
    }

    if (event.key === "Escape") {
      setNavState(false);
      searchPanel?.classList.remove("visible");
      if (document.activeElement === searchInput) {
        searchInput.blur();
      }
    }
  });
})();
"""


@dataclass
class SkillPage:
    slug: str
    title: str
    description: str
    runtime: list[str]
    source_path: Path
    output_path: str
    html_content: str
    toc_tokens: list[dict[str, object]]
    summary: str


@dataclass
class Page:
    page_type: str
    title: str
    description: str
    output_path: str
    github_url: str
    html_content: str
    toc_html: str
    summary: str
    plain_text: str
    headings: list[str]
    primary_anchor: str | None
    nav_label: str


def detect_source_branch() -> str:
    env_branch = os.getenv("GITHUB_REF_NAME")
    if env_branch:
        return env_branch

    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "master"

    branch = result.stdout.strip()
    return branch or "master"


SOURCE_BRANCH = detect_source_branch()


def slugify(value: str, separator: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[-\s]+", separator, normalized, flags=re.UNICODE)
    return normalized.strip(separator) or "section"


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text

    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return None, text

    _, remainder = parts
    frontmatter = parts[0][4:]
    return frontmatter, remainder


def parse_frontmatter(frontmatter: str | None) -> dict[str, object]:
    if not frontmatter:
        return {}

    result: dict[str, object] = {}
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if not re.match(r"^[A-Za-z0-9_-]+:", line):
            index += 1
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        if key == "description" and value in {"", ">", "|"}:
            description_lines: list[str] = []
            index += 1
            while index < len(lines):
                nested = lines[index]
                if re.match(r"^[A-Za-z0-9_-]+:", nested):
                    break
                if nested.strip():
                    description_lines.append(nested.strip())
                index += 1
            result[key] = " ".join(description_lines).strip()
            continue

        if key == "compatibility" and value:
            if "python3" in value.lower():
                result["runtime"] = ["python3"]
            else:
                result["runtime"] = [value]
            index += 1
            continue

        if key == "compatibility":
            runtime: list[str] = []
            index += 1
            while index < len(lines):
                nested = lines[index]
                if re.match(r"^[A-Za-z0-9_-]+:", nested):
                    break
                runtime_match = re.match(r"^\s*-\s+(.+)$", nested)
                if runtime_match:
                    runtime.append(runtime_match.group(1).strip())
                index += 1
            if runtime:
                result["runtime"] = runtime
            continue

        result[key] = value.strip('"').strip("'")
        index += 1

    return result


def extract_skill_order(readme_text: str) -> list[str]:
    return re.findall(r"\(\.claude/skills/([^/]+)/SKILL\.md\)", readme_text)


def build_page_map(skill_paths: list[Path]) -> dict[Path, str]:
    page_map = {Path("README.md"): "index.html"}
    for skill_path in skill_paths:
        slug = skill_path.parent.name
        page_map[skill_path.relative_to(REPO_ROOT)] = f"skills/{slug}.html"
    return page_map


def split_link_target(target: str) -> tuple[str, str]:
    if "#" in target:
        path, anchor = target.split("#", 1)
        return path, "#" + anchor
    return target, ""


def build_repo_url(relative_path: Path) -> str:
    return f"{REPO_URL}/blob/{SOURCE_BRANCH}/{relative_path.as_posix()}"


def build_repo_tree_url(relative_path: Path) -> str:
    return f"{REPO_URL}/tree/{SOURCE_BRANCH}/{relative_path.as_posix()}"


def rewrite_links(html: str, source_relative: Path, page_map: dict[Path, str]) -> str:
    source_dir = source_relative.parent

    def replace(match: re.Match[str]) -> str:
        href = match.group(1)
        if href.startswith(("http://", "https://", "mailto:", "#")):
            return match.group(0)

        path_part, anchor = split_link_target(href)
        candidate = (source_dir / path_part).resolve()
        try:
            relative_path = candidate.relative_to(REPO_ROOT)
        except ValueError:
            return match.group(0)

        if relative_path in page_map:
            return f'href="{page_map[relative_path]}{anchor}"'

        github_target = build_repo_tree_url(relative_path) if candidate.is_dir() else build_repo_url(relative_path)
        return f'href="{github_target}{anchor}"'

    return re.sub(r'href="([^"]+)"', replace, html)


def markdown_to_html(md_text: str, source_relative: Path, page_map: dict[Path, str]) -> tuple[str, list[dict[str, object]]]:
    renderer = markdown.Markdown(
        extensions=["extra", "toc", "sane_lists", "smarty"],
        extension_configs={"toc": {"slugify": slugify, "permalink": False}},
        output_format="html5",
    )
    html = renderer.convert(md_text)
    return rewrite_links(html, source_relative, page_map), renderer.toc_tokens


def render_toc(tokens: list[dict[str, object]]) -> str:
    visible_tokens = tokens[0].get("children", []) if tokens else []
    if not visible_tokens:
        return '<p class="toc-empty">На этой странице нет вложенных разделов. Используйте левое меню или поиск.</p>'

    def render_items(items: list[dict[str, object]]) -> str:
        parts = ['<ul class="toc-list">']
        for item in items:
            children = item.get("children", [])
            parts.append('<li class="toc-item">')
            parts.append(
                f'<a class="toc-link" href="#{escape(str(item["id"]))}">{escape(str(item["name"]))}</a>'
            )
            if children:
                parts.append(render_items(children))
            parts.append("</li>")
        parts.append("</ul>")
        return "".join(parts)

    return render_items(visible_tokens)


def flatten_tokens(tokens: list[dict[str, object]]) -> list[dict[str, object]]:
    flat: list[dict[str, object]] = []

    def visit(items: list[dict[str, object]]) -> None:
        for item in items:
            flat.append(item)
            children = item.get("children", [])
            if children:
                visit(children)

    visible_tokens = tokens[0].get("children", []) if tokens else []
    visit(visible_tokens)
    return flat


def extract_primary_anchor(tokens: list[dict[str, object]]) -> str | None:
    visible_tokens = tokens[0].get("children", []) if tokens else []
    if not visible_tokens:
        return None
    return str(visible_tokens[0]["id"])


def extract_title(md_text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", md_text, flags=re.MULTILINE)
    return match.group(1).strip() if match else fallback


def extract_summary(html: str, fallback: str) -> str:
    paragraphs = [strip_tags(item) for item in re.findall(r"<p>(.*?)</p>", html, flags=re.S)]
    for paragraph in paragraphs:
        if len(paragraph) >= 40:
            return paragraph
    return fallback


def collect_skills(readme_text: str, page_map: dict[Path, str]) -> list[SkillPage]:
    ordered_slugs = extract_skill_order(readme_text)
    skill_paths = {path.parent.name: path for path in SKILLS_ROOT.glob("*/SKILL.md")}
    slugs = ordered_slugs + sorted(slug for slug in skill_paths if slug not in ordered_slugs)

    skills: list[SkillPage] = []
    for slug in slugs:
        path = skill_paths[slug]
        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
        meta = parse_frontmatter(frontmatter)
        html_content, toc_tokens = markdown_to_html(body, path.relative_to(REPO_ROOT), page_map)
        description = str(meta.get("description") or "").strip() or extract_summary(html_content, slug)
        title = str(meta.get("name") or slug).strip()
        runtime = list(meta.get("runtime") or [])
        if not runtime and ((path.parent / "scripts").exists() or "python3" in body):
            runtime = ["python3"]
        skills.append(
            SkillPage(
                slug=slug,
                title=title,
                description=description,
                runtime=runtime,
                source_path=path,
                output_path=f"skills/{slug}.html",
                html_content=html_content,
                toc_tokens=toc_tokens,
                summary=description,
            )
        )
    return skills


def skill_cards(skills: list[SkillPage]) -> str:
    cards = []
    for skill in skills:
        runtime = ", ".join(skill.runtime) if skill.runtime else "Без требований"
        cards.append(
            f"""
            <a class="skill-card" href="{skill.output_path}">
              <div class="skill-card-top">
                <span class="skill-card-title">{escape(skill.title)}</span>
                <span class="skill-card-runtime">{escape(runtime)}</span>
              </div>
              <div class="skill-card-copy">{escape(skill.description)}</div>
              <div class="skill-card-arrow">Открыть скилл →</div>
            </a>
            """
        )
    return "".join(cards)


def build_home_content(readme_html: str, skills: list[SkillPage]) -> str:
    tests_count = len(list((REPO_ROOT / "tests").rglob("test_*.py")))
    stats_html = f"""
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value">{len(skills)}</div>
        <div class="stat-label">Скиллов в каталоге</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{tests_count}</div>
        <div class="stat-label">Тестовых модулей в репозитории</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">MIT</div>
        <div class="stat-label">Лицензия и открытый исходный код</div>
      </div>
    </div>
    """
    catalog_html = f"""
    <section class="catalog" id="skills-catalog">
      <h2 class="catalog-title">Каталог скиллов</h2>
      <p class="catalog-copy">Отдельные страницы собираются прямо из файлов `SKILL.md`, поэтому сайт остаётся синхронным с исходниками репозитория.</p>
      <div class="skills-grid">
        {skill_cards(skills)}
      </div>
    </section>
    """
    return stats_html + catalog_html + readme_html


def build_nav(skills: list[SkillPage], active_output_path: str) -> str:
    items = [
        {
            "label": "Обзор",
            "description": "Главная страница, установка, примеры и структура репозитория.",
            "path": "index.html",
        }
    ]
    items.extend(
        {
            "label": skill.title,
            "description": skill.description,
            "path": skill.output_path,
        }
        for skill in skills
    )

    html_parts = []
    for item in items:
        active_class = " active" if item["path"] == active_output_path else ""
        html_parts.append(
            f"""
            <li>
              <a class="nav-link{active_class}" href="{item["path"]}">
                <span class="nav-label">{escape(item["label"])}</span>
                <span class="nav-description">{escape(item["description"])}</span>
              </a>
            </li>
            """
        )
    return "".join(html_parts)


def render_page(page: Page, skills: list[SkillPage]) -> str:
    primary_href = f"#{page.primary_anchor}" if page.primary_anchor else "#top"
    page_kind = "Каталог" if page.page_type == "home" else "Скилл"
    chips = [f"<span class=\"chip\">{page_kind}</span>"]
    if page.page_type == "home":
        chips.append(f"<span class=\"chip\">{len(skills)} навыков</span>")
        chips.append("<span class=\"chip\">GitHub Pages ready</span>")
    else:
        skill = next(skill for skill in skills if skill.output_path == page.output_path)
        for runtime in skill.runtime:
            chips.append(f"<span class=\"chip\">{escape(runtime)}</span>")

    base_href = page_base_href(page.output_path)

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(page.title)} · {SITE_TITLE}</title>
  <meta name="description" content="{escape(page.summary)}">
  <base href="{base_href}">
  <link rel="stylesheet" href="assets/style.css">
</head>
<body data-theme="light">
  <div class="site-shell">
    <header class="topbar panel">
      <button class="toolbar-btn menu-btn" type="button" data-sidebar-toggle aria-label="Открыть меню">☰</button>
      <a class="brand" href="index.html">
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-copy">
          <span class="brand-title">{SITE_TITLE}</span>
          <span class="brand-subtitle">{SITE_SUBTITLE}</span>
        </span>
      </a>
      <div class="toolbar">
        <div class="search-wrap">
          <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7"></circle>
            <path d="m20 20-3.5-3.5"></path>
          </svg>
          <input class="search-input" type="search" placeholder="Поиск по скиллам и README" data-search-input aria-label="Поиск">
          <div class="search-panel" data-search-panel>
            <div class="search-results" data-search-results></div>
          </div>
        </div>
        <button class="toolbar-btn" type="button" data-theme-toggle>
          <span>◐</span>
          <span class="toolbar-btn-label" data-theme-label>Тёмная тема</span>
        </button>
      </div>
    </header>

    <div class="layout">
      <aside class="sidebar panel" data-sidebar>
        <div class="sidebar-badge">GitHub Pages</div>
        <h2 class="sidebar-title">Публичный каталог XBSL Skills</h2>
        <p class="sidebar-text">Сайт собирается из реальных markdown-файлов репозитория и ведёт на исходники там, где это уместно.</p>
        <ul class="nav-list">
          {build_nav(skills, page.output_path)}
        </ul>
        <a class="repo-link" href="{REPO_URL}" target="_blank" rel="noreferrer">Открыть репозиторий</a>
      </aside>

      <main class="content">
        <div class="page panel">
          <section class="hero">
            <div class="hero-meta">
              {''.join(chips)}
            </div>
            <h1 class="hero-title">{escape(page.title)}</h1>
            <p class="hero-description">{escape(page.description)}</p>
            <div class="hero-actions">
              <a class="hero-link primary" href="{primary_href}">Читать</a>
              <a class="hero-link" href="{page.github_url}" target="_blank" rel="noreferrer">Исходник на GitHub</a>
            </div>
          </section>

          <article class="doc-body" id="top">
            {page.html_content}
          </article>

          <div class="page-footer">
            <span>Поиск доступен по клавише <code>/</code>.</span>
            <span>Source branch: <code>{escape(SOURCE_BRANCH)}</code></span>
          </div>
        </div>
      </main>

      <aside class="toc panel">
        <h2 class="toc-title">На странице</h2>
        {page.toc_html}
      </aside>
    </div>
  </div>

  <div class="overlay" data-overlay></div>

  <script src="assets/search-index.js"></script>
  <script src="assets/app.js"></script>
</body>
</html>
"""


def build_pages(skills: list[SkillPage], readme_text: str, page_map: dict[Path, str]) -> list[Page]:
    readme_html, readme_toc = markdown_to_html(readme_text, Path("README.md"), page_map)
    home_content = build_home_content(readme_html, skills)
    home_page = Page(
        page_type="home",
        title=extract_title(readme_text, SITE_TITLE),
        description="Набор скиллов для работы с проектами 1С:Элемент, с удобным каталогом и живыми страницами по каждому навыку.",
        output_path="index.html",
        github_url=build_repo_url(Path("README.md")),
        html_content=home_content,
        toc_html=render_toc(readme_toc),
        summary=extract_summary(readme_html, SITE_SUBTITLE),
        plain_text=strip_tags(home_content),
        headings=[strip_tags(item["name"]) for item in flatten_tokens(readme_toc)],
        primary_anchor="skills-catalog",
        nav_label="Обзор",
    )

    pages = [home_page]
    for skill in skills:
        toc_html = render_toc(skill.toc_tokens)
        headings = [strip_tags(item["name"]) for item in flatten_tokens(skill.toc_tokens)]
        pages.append(
            Page(
                page_type="skill",
                title=skill.title,
                description=skill.description,
                output_path=skill.output_path,
                github_url=build_repo_url(skill.source_path.relative_to(REPO_ROOT)),
                html_content=skill.html_content,
                toc_html=toc_html,
                summary=skill.summary,
                plain_text=strip_tags(skill.html_content),
                headings=headings,
                primary_anchor=extract_primary_anchor(skill.toc_tokens),
                nav_label=skill.title,
            )
        )
    return pages


def write_assets(pages: list[Page]) -> None:
    (ASSETS_DIR / "style.css").write_text(STYLE_CSS.strip() + "\n", encoding="utf-8")
    (ASSETS_DIR / "app.js").write_text(APP_JS.strip() + "\n", encoding="utf-8")

    search_index = [
        {
            "title": page.title,
            "url": page.output_path,
            "summary": page.summary,
            "text": page.plain_text,
            "headings": page.headings,
            "pageLabel": page.nav_label,
        }
        for page in pages
    ]
    (ASSETS_DIR / "search-index.js").write_text(
        "window.SEARCH_INDEX = " + json.dumps(search_index, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def page_base_href(output_path: str) -> str:
    parts = Path(output_path).parts[:-1]
    if not parts:
        return "./"
    return "../" * len(parts)


def ensure_output_dirs() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    (OUTPUT_DIR / "skills").mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def build_site() -> None:
    ensure_output_dirs()

    readme_text = README_PATH.read_text(encoding="utf-8")
    skill_paths = list(SKILLS_ROOT.glob("*/SKILL.md"))
    page_map = build_page_map(skill_paths)
    skills = collect_skills(readme_text, page_map)
    pages = build_pages(skills, readme_text, page_map)

    write_assets(pages)

    for page in pages:
        output_file = OUTPUT_DIR / page.output_path
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(render_page(page, skills), encoding="utf-8")

    print(f"Site built at {OUTPUT_DIR}")


if __name__ == "__main__":
    build_site()
