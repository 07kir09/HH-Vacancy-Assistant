from __future__ import annotations

import contextlib
import io
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from hh_api import HHApiError
from main import load_context, make_api, scan
from storage import Storage
from users import (
    create_user,
    list_users,
    load_user_config,
    load_user_profile,
    runtime_config_for_user,
    save_credentials,
    save_uploaded_resume,
    save_user_config,
    save_user_profile,
    user_dir,
)
from profile_builder import build_profile_from_text
from resume_parser import ResumeParseError, extract_text


HTML = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>HH Apply Assistant</title>
  <style>
    :root {
      --bg: #f5f7fa;
      --panel: #ffffff;
      --line: #d9e0e8;
      --text: #202833;
      --muted: #637083;
      --accent: #1f6feb;
      --accent-2: #0f8b6f;
      --danger: #c2410c;
      --danger-bg: #fff3ed;
      --ok-bg: #ecfdf3;
      --info-bg: #eff6ff;
      --shadow: 0 1px 2px rgba(15, 23, 42, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
    }
    button, input, textarea, select { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      padding: 8px 10px;
      cursor: pointer;
      min-height: 36px;
    }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    button.good { background: var(--accent-2); border-color: var(--accent-2); color: #fff; }
    button.warn { color: var(--danger); }
    button:disabled { opacity: .55; cursor: not-allowed; }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fff;
      color: var(--text);
    }
    textarea {
      min-height: 260px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      line-height: 1.45;
      resize: vertical;
    }
    .app {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: 100vh;
    }
    aside {
      border-right: 1px solid var(--line);
      background: #edf2f7;
      padding: 18px;
    }
    main { padding: 18px; }
    h1 { font-size: 20px; margin: 0 0 18px; }
    h2 { font-size: 15px; margin: 0 0 12px; }
    h3 { font-size: 13px; margin: 0 0 8px; color: var(--muted); }
    label { display: block; color: var(--muted); font-size: 12px; margin: 0 0 6px; }
    .stack { display: grid; gap: 12px; }
    .row { display: flex; gap: 8px; align-items: center; }
    .row > * { min-width: 0; }
    .user-create input { flex: 1 1 auto; }
    .user-create button { flex: 0 0 88px; }
    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
      min-width: 0;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(340px, 1fr) minmax(420px, 1.35fr);
      gap: 14px;
      align-items: start;
    }
    .tabs { display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
    .tab.active { background: #dbeafe; border-color: #93c5fd; color: #0f3d8a; }
    .users { display: grid; gap: 6px; }
    .user-item { text-align: left; }
    .user-item.active { border-color: var(--accent); background: #dbeafe; }
    .muted { color: var(--muted); }
    .small { font-size: 12px; }
    .help { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 6px; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 10px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .notice {
      border: 1px solid #bfdbfe;
      background: var(--info-bg);
      color: #16407a;
      border-radius: 8px;
      padding: 10px 12px;
      min-height: 40px;
      margin-bottom: 14px;
    }
    .notice.ok { border-color: #bbf7d0; background: var(--ok-bg); color: #166534; }
    .notice.error { border-color: #fed7aa; background: var(--danger-bg); color: #9a3412; }
    .summary {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #f8fafc;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .empty {
      border: 1px dashed #b7c3d0;
      border-radius: 8px;
      padding: 18px;
      color: var(--muted);
      background: #f8fafc;
    }
    .log {
      white-space: pre-wrap;
      background: #101828;
      color: #d1e7ff;
      border-radius: 6px;
      padding: 12px;
      min-height: 120px;
      max-height: 280px;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 9px 6px; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; font-size: 12px; }
    .draft-title { font-weight: 650; }
    .letter {
      white-space: pre-wrap;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      min-height: 220px;
    }
    .section { display: none; }
    .section.active { display: block; }
    .required::after { content: " *"; color: var(--danger); }
    body.busy { cursor: progress; }
    @media (max-width: 900px) {
      .app { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h1>HH Apply Assistant</h1>
      <div class="stack">
        <div>
          <label class="required">Новый пользователь</label>
          <div class="row user-create">
            <input id="newUser" placeholder="например: kirill" />
            <button class="primary" onclick="createUser()">Создать</button>
          </div>
          <div class="help">ID нужен для отдельной папки профиля: латиница, цифры, точка, тире или underscore.</div>
        </div>
        <div>
          <label>Пользователи</label>
          <div id="users" class="users"></div>
        </div>
        <div class="small muted">
          Отклик отправляется вручную на hh.ru. Система ищет вакансии, пишет письмо и открывает страницу отклика.
        </div>
      </div>
    </aside>
    <main>
      <div class="topbar">
        <div id="status" class="notice" style="flex: 1">Создай пользователя или выбери существующего слева.</div>
        <div id="currentUser" class="badge">Пользователь не выбран</div>
      </div>
      <div class="tabs">
        <button class="tab active" data-tab="setup" onclick="showTab('setup')">1. Настройка</button>
        <button class="tab" data-tab="profile" onclick="showTab('profile')">2. Профиль</button>
        <button class="tab" data-tab="config" onclick="showTab('config')">3. Поиск</button>
        <button class="tab" data-tab="drafts" onclick="showTab('drafts')">4. Черновики</button>
      </div>

      <section id="setup" class="section active">
        <div class="grid">
          <div class="panel stack">
            <h2>Резюме кандидата</h2>
            <div>
              <label class="required">Файл резюме</label>
              <input id="resumeFile" type="file" accept=".pdf,.docx,.txt,.md" />
              <div class="help">Поддерживаются PDF, DOCX, TXT и MD. После загрузки профиль и ключевые слова поиска заполнятся автоматически.</div>
            </div>
            <button class="primary" onclick="uploadResume()">Загрузить резюме</button>
            <div id="resumeSummary" class="summary">Резюме еще не загружено для выбранного пользователя.</div>
          </div>
          <div class="panel stack">
            <h2>Доступ к HH API</h2>
            <div>
              <label class="required">HH_CLIENT_ID</label>
              <input id="clientId" autocomplete="off" placeholder="client_id из приложения на dev.hh.ru" />
              <div class="help">Это ID зарегистрированного приложения HH, не email от аккаунта.</div>
            </div>
            <div>
              <label class="required">HH_CLIENT_SECRET</label>
              <input id="clientSecret" type="password" autocomplete="off" placeholder="client_secret из dev.hh.ru" />
              <div class="help">Секрет хранится только локально в папке пользователя и не попадает в git.</div>
            </div>
            <div class="row">
              <button onclick="saveCredentials()">Сохранить ключи</button>
              <button class="primary" onclick="getAppToken()">Проверить доступ</button>
            </div>
            <div id="tokenSummary" class="summary">Сначала сохрани оба ключа, потом получи application token.</div>
          </div>
        </div>
      </section>

      <section id="profile" class="section">
        <div class="panel stack">
          <div class="row">
            <div style="flex: 1">
              <h2>Профиль из резюме</h2>
              <div class="help">Здесь можно поправить роли, зарплату, навыки и факты для сопроводительных писем.</div>
            </div>
            <button class="primary" onclick="saveProfile()">Сохранить профиль</button>
          </div>
          <textarea id="profileText" placeholder="После загрузки резюме здесь появится JSON-профиль кандидата."></textarea>
        </div>
      </section>

      <section id="config" class="section">
        <div class="panel stack">
          <div class="row">
            <div style="flex: 1">
              <h2>Параметры поиска</h2>
              <div class="help">Главные поля: search.keywords, search.desired_salary, filters.min_score, filters.positive_keywords и filters.negative_keywords.</div>
            </div>
            <button class="primary" onclick="saveConfig()">Сохранить поиск</button>
            <button class="good" onclick="scan()">Найти вакансии</button>
          </div>
          <textarea id="configText" placeholder="Здесь будет YAML-конфиг поиска."></textarea>
        </div>
      </section>

      <section id="drafts" class="section">
        <div class="grid">
          <div class="panel stack">
            <div class="row">
              <div style="flex: 1">
                <h2>Черновики откликов</h2>
                <div class="help">Выбери вакансию, скопируй письмо и открой официальный отклик на hh.ru.</div>
              </div>
              <button onclick="loadDrafts()">Обновить</button>
            </div>
            <div id="draftsTable"></div>
          </div>
          <div class="panel stack">
            <h2>Сопроводительное письмо</h2>
            <div id="letter" class="letter muted">Выбери вакансию слева.</div>
            <div class="row">
              <button onclick="copyLetter()">Копировать письмо</button>
              <button class="primary" onclick="openSelected()">Открыть отклик</button>
              <button class="good" onclick="markSelected('sent')">Отметить отправленным</button>
              <button class="warn" onclick="markSelected('skipped')">Пропустить</button>
            </div>
          </div>
        </div>
      </section>

      <div style="height: 14px"></div>
      <div class="panel">
        <h2>События и ошибки</h2>
        <div id="log" class="log"></div>
      </div>
    </main>
  </div>
  <script>
    let currentUser = null;
    let selectedDraft = null;
    let drafts = [];
    const logEl = document.getElementById('log');
    const statusEl = document.getElementById('status');
    const currentUserEl = document.getElementById('currentUser');
    const resumeSummaryEl = document.getElementById('resumeSummary');
    const tokenSummaryEl = document.getElementById('tokenSummary');

    function log(message) {
      logEl.textContent = `${new Date().toLocaleTimeString()} ${message}\n` + logEl.textContent;
    }
    function setStatus(message, kind = 'info') {
      statusEl.textContent = message;
      statusEl.className = `notice ${kind === 'error' ? 'error' : kind === 'ok' ? 'ok' : ''}`.trim();
    }
    function setBusy(isBusy) {
      document.body.classList.toggle('busy', isBusy);
      document.querySelectorAll('button').forEach(button => {
        button.disabled = isBusy;
      });
    }
    function errorMessage(error) {
      if (!error) return 'Неизвестная ошибка';
      if (error instanceof SyntaxError) return 'Ошибка формата JSON: проверь скобки, кавычки и запятые.';
      return error.message || String(error);
    }
    async function runAction(progress, work) {
      if (document.body.classList.contains('busy')) return;
      setBusy(true);
      setStatus(progress);
      try {
        return await work();
      } catch (error) {
        const message = errorMessage(error);
        setStatus(message, 'error');
        log(`Ошибка: ${message}`);
      } finally {
        setBusy(false);
      }
    }
    async function api(path, options = {}) {
      const request = {...options};
      if (typeof request.body === 'string') {
        request.headers = {'Content-Type': 'application/json', ...(request.headers || {})};
      }
      const res = await fetch(path, request);
      const text = await res.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = {text}; }
      if (!res.ok) throw new Error(data.error || text || res.statusText);
      return data;
    }
    function showTab(id) {
      document.querySelectorAll('.tab').forEach(el => el.classList.toggle('active', el.dataset.tab === id));
      document.querySelectorAll('.section').forEach(el => el.classList.toggle('active', el.id === id));
      if (id === 'drafts') loadDrafts().catch(error => {
        const message = errorMessage(error);
        setStatus(message, 'error');
        log(`Ошибка: ${message}`);
      });
    }
    async function loadUsers() {
      const data = await api('/api/users');
      const box = document.getElementById('users');
      box.innerHTML = '';
      if (!data.users.length) {
        box.innerHTML = '<div class="empty">Пока нет пользователей.</div>';
      }
      data.users.forEach(user => {
        const btn = document.createElement('button');
        btn.className = 'user-item' + (user === currentUser ? ' active' : '');
        btn.textContent = user;
        btn.onclick = () => selectUser(user);
        box.appendChild(btn);
      });
      if (!currentUser && data.users.length) await selectUser(data.users[0]);
    }
    async function createUser() {
      await runAction('Создаю пользователя...', async () => {
        const user = document.getElementById('newUser').value.trim();
        if (!user) throw new Error('Введи ID пользователя, например kirill.');
        const data = await api('/api/users', {method: 'POST', body: JSON.stringify({user})});
        document.getElementById('newUser').value = '';
        currentUser = data.user;
        await loadUsers();
        await loadUserData();
        setStatus(`Пользователь ${currentUser} готов. Загрузи резюме или проверь профиль.`, 'ok');
        log(`Пользователь ${currentUser} создан`);
      });
    }
    async function selectUser(user) {
      await runAction(`Загружаю профиль ${user}...`, async () => {
        currentUser = user;
        selectedDraft = null;
        clearSelectedDraft();
        await loadUsers();
        await loadUserData();
        setStatus(`Выбран пользователь ${user}.`, 'ok');
        log(`Выбран пользователь ${user}`);
      });
    }
    function requireUser() {
      if (!currentUser) throw new Error('Сначала выбери пользователя');
    }
    async function loadUserData() {
      requireUser();
      const profile = await api(`/api/users/${currentUser}/profile`);
      const config = await api(`/api/users/${currentUser}/config`);
      document.getElementById('profileText').value = JSON.stringify(profile.profile, null, 2);
      document.getElementById('configText').value = config.config;
      currentUserEl.textContent = `Пользователь: ${currentUser}`;
      updateResumeSummary(profile.profile);
      await loadDrafts();
    }
    async function uploadResume() {
      await runAction('Загружаю и разбираю резюме...', async () => {
        requireUser();
        const file = document.getElementById('resumeFile').files[0];
        if (!file) throw new Error('Выбери файл резюме: PDF, DOCX, TXT или MD.');
        const fd = new FormData();
        fd.append('resume', file);
        const data = await api(`/api/users/${currentUser}/resume`, {method: 'POST', body: fd});
        document.getElementById('profileText').value = JSON.stringify(data.profile, null, 2);
        const config = await api(`/api/users/${currentUser}/config`);
        document.getElementById('configText').value = config.config;
        updateResumeSummary(data.profile);
        setStatus(`Резюме загружено. Найдено навыков: ${data.skills.length}.`, 'ok');
        log(`Резюме распарсено: ${data.skills.join(', ') || 'навыки не найдены'}`);
      });
    }
    async function saveProfile() {
      await runAction('Сохраняю профиль...', async () => {
        requireUser();
        const profile = JSON.parse(document.getElementById('profileText').value);
        await api(`/api/users/${currentUser}/profile`, {method: 'POST', body: JSON.stringify({profile})});
        updateResumeSummary(profile);
        setStatus('Профиль сохранен.', 'ok');
        log('Профиль сохранен');
      });
    }
    async function saveConfig() {
      await runAction('Сохраняю параметры поиска...', async () => {
        requireUser();
        await api(`/api/users/${currentUser}/config`, {method: 'POST', body: JSON.stringify({config: document.getElementById('configText').value})});
        setStatus('Параметры поиска сохранены.', 'ok');
        log('Конфиг поиска сохранен');
      });
    }
    async function saveCredentials() {
      await runAction('Сохраняю HH credentials...', async () => {
        requireUser();
        await api(`/api/users/${currentUser}/credentials`, {
          method: 'POST',
          body: JSON.stringify({
            client_id: document.getElementById('clientId').value,
            client_secret: document.getElementById('clientSecret').value
          })
        });
        document.getElementById('clientSecret').value = '';
        tokenSummaryEl.textContent = 'Ключи сохранены. Теперь нажми "Проверить доступ".';
        setStatus('HH credentials сохранены локально.', 'ok');
        log('HH credentials сохранены локально');
      });
    }
    async function getAppToken() {
      await runAction('Проверяю доступ к HH API...', async () => {
        requireUser();
        const data = await api(`/api/users/${currentUser}/app-token`, {method: 'POST'});
        tokenSummaryEl.textContent = data.message;
        setStatus('Доступ к HH API работает.', 'ok');
        log(data.message);
      });
    }
    async function scan() {
      await runAction('Ищу вакансии и генерирую письма...', async () => {
        requireUser();
        log('Поиск запущен...');
        const data = await api(`/api/users/${currentUser}/scan`, {method: 'POST'});
        log(data.output || 'Поиск завершен');
        await loadDrafts();
        showTab('drafts');
        setStatus('Поиск завершен. Проверь черновики.', 'ok');
      });
    }
    async function loadDrafts() {
      if (!currentUser) return;
      const data = await api(`/api/users/${currentUser}/drafts`);
      drafts = data.drafts;
      const box = document.getElementById('draftsTable');
      if (!drafts.length) {
        box.innerHTML = '<div class="empty">Черновиков пока нет. Проверь параметры поиска и нажми "Найти вакансии".</div>';
        return;
      }
      const rows = drafts.map((d, i) => `<tr>
        <td>${i + 1}</td>
        <td><div class="draft-title">${escapeHtml(d.title)}</div><div class="small muted">${escapeHtml(d.company || '')}</div></td>
        <td>${d.score}</td>
        <td><button onclick="selectDraftByIndex(${i})">Выбрать</button></td>
      </tr>`).join('');
      box.innerHTML = `<table><thead><tr><th>#</th><th>Вакансия</th><th>Score</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
    }
    function selectDraftByIndex(index) {
      selectDraft(drafts[index]);
    }
    function selectDraft(draft) {
      if (!draft) return;
      selectedDraft = draft;
      document.getElementById('letter').classList.remove('muted');
      document.getElementById('letter').textContent = draft.letter || '';
      setStatus(`Выбрана вакансия: ${draft.title}.`, 'ok');
      log(`Выбрана вакансия: ${draft.title}`);
    }
    async function copyLetter() {
      await runAction('Копирую письмо...', async () => {
        if (!selectedDraft) throw new Error('Сначала выбери вакансию из списка черновиков.');
        if (!navigator.clipboard) throw new Error('Браузер не дал доступ к clipboard. Выдели письмо вручную и скопируй.');
        await navigator.clipboard.writeText(selectedDraft.letter || '');
        setStatus('Письмо скопировано.', 'ok');
        log('Письмо скопировано');
      });
    }
    async function openSelected() {
      await runAction('Открываю отклик...', async () => {
        if (!selectedDraft) throw new Error('Сначала выбери вакансию из списка черновиков.');
        if (navigator.clipboard) {
          await navigator.clipboard.writeText(selectedDraft.letter || '');
        }
        const url = selectedDraft.apply_url || selectedDraft.alternate_url;
        if (!url) throw new Error('У вакансии нет ссылки для отклика.');
        window.open(url, '_blank', 'noopener');
        setStatus('Страница отклика открыта. Вставь письмо на hh.ru и отправь вручную.', 'ok');
      });
    }
    async function markSelected(status) {
      await runAction('Обновляю статус черновика...', async () => {
        if (!selectedDraft) throw new Error('Сначала выбери вакансию из списка черновиков.');
        await api(`/api/users/${currentUser}/drafts/${selectedDraft.vacancy_id}/status`, {method: 'POST', body: JSON.stringify({status})});
        log(status === 'sent' ? 'Отмечено отправленным' : 'Вакансия пропущена');
        clearSelectedDraft();
        await loadDrafts();
        setStatus(status === 'sent' ? 'Вакансия отмечена отправленной.' : 'Вакансия пропущена.', 'ok');
      });
    }
    function clearSelectedDraft() {
      selectedDraft = null;
      const letter = document.getElementById('letter');
      letter.textContent = 'Выбери вакансию слева.';
      letter.classList.add('muted');
    }
    function updateResumeSummary(profile) {
      const name = profile.name || 'имя не найдено';
      const roles = (profile.target_roles || []).slice(0, 3).join(', ') || 'роли не указаны';
      const skills = (profile.skills || []).slice(0, 8).join(', ') || 'навыки не найдены';
      resumeSummaryEl.textContent = `Кандидат: ${name}. Роли: ${roles}. Навыки: ${skills}.`;
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    loadUsers().catch(error => {
      const message = errorMessage(error);
      setStatus(message, 'error');
      log(`Ошибка: ${message}`);
    });
  </script>
</body>
</html>
"""


class WebError(RuntimeError):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "JobApplyBot/0.1"

    def do_GET(self) -> None:
        self._handle("GET")

    def do_HEAD(self) -> None:
        if urlparse(self.path).path == "/":
            payload = HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            if method == "GET" and parsed.path == "/":
                self._send_html(HTML)
                return
            if parsed.path.startswith("/api/"):
                self._handle_api(method, parsed.path)
                return
            raise WebError(HTTPStatus.NOT_FOUND, "Not found")
        except WebError as exc:
            self._send_json({"error": str(exc)}, exc.status)
        except json.JSONDecodeError:
            self._send_json({"error": "Некорректный JSON в запросе."}, HTTPStatus.BAD_REQUEST)
        except ResumeParseError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except HHApiError as exc:
            status = _http_status(exc.status_code)
            message = str(exc)
            self._send_json({"error": message, "details": exc.payload}, status)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_api(self, method: str, path: str) -> None:
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if parts == ["api", "users"] and method == "GET":
            self._send_json({"users": list_users()})
            return
        if parts == ["api", "users"] and method == "POST":
            user = str(self._read_json().get("user", ""))
            path = create_user(user)
            self._send_json({"user": path.name})
            return
        if len(parts) < 3 or parts[0] != "api" or parts[1] != "users":
            raise WebError(HTTPStatus.NOT_FOUND, "Unknown API route")

        user = parts[2]
        if len(parts) == 4 and parts[3] == "profile":
            if method == "GET":
                self._send_json({"profile": load_user_profile(user)})
                return
            if method == "POST":
                profile = self._read_json().get("profile")
                if not isinstance(profile, dict):
                    raise WebError(HTTPStatus.BAD_REQUEST, "profile must be an object")
                save_user_profile(user, profile)
                self._send_json({"ok": True})
                return
        if len(parts) == 4 and parts[3] == "config":
            create_user(user)
            path = user_dir(user) / "config.yaml"
            if method == "GET":
                self._send_json({"config": path.read_text(encoding="utf-8")})
                return
            if method == "POST":
                import yaml

                text = str(self._read_json().get("config", ""))
                try:
                    data = yaml.safe_load(text) or {}
                except yaml.YAMLError as exc:
                    raise WebError(HTTPStatus.BAD_REQUEST, f"Ошибка YAML: {exc}") from exc
                if not isinstance(data, dict):
                    raise WebError(HTTPStatus.BAD_REQUEST, "config.yaml должен быть YAML-объектом.")
                save_user_config(user, data)
                self._send_json({"ok": True})
                return
        if len(parts) == 4 and parts[3] == "resume" and method == "POST":
            filename, content = self._read_multipart_file("resume")
            saved = save_uploaded_resume(user, filename, content)
            text = extract_text(saved)
            if not text.strip():
                raise WebError(
                    HTTPStatus.BAD_REQUEST,
                    "Из файла не удалось извлечь текст. Попробуй DOCX/TXT или PDF с текстовым слоем.",
                )
            profile = build_profile_from_text(text)
            save_user_profile(user, profile)
            config = _configure_search(load_user_config(user), profile)
            save_user_config(user, config)
            self._send_json({"profile": profile, "skills": profile.get("skills", [])})
            return
        if len(parts) == 4 and parts[3] == "credentials" and method == "POST":
            data = self._read_json()
            client_id = str(data.get("client_id", "")).strip()
            client_secret = str(data.get("client_secret", "")).strip()
            if not client_id or not client_secret:
                raise WebError(HTTPStatus.BAD_REQUEST, "Заполни HH_CLIENT_ID и HH_CLIENT_SECRET.")
            save_credentials(user, client_id, client_secret)
            self._send_json({"ok": True})
            return
        if len(parts) == 4 and parts[3] == "app-token" and method == "POST":
            config, _profile, storage = _context(user)
            _validate_hh_credentials(config)
            api = make_api(config, storage, "hh_app")
            token = api.get_application_token()
            self._send_json({"message": f"Application token saved. expires_in={token.get('expires_in')}"})
            return
        if len(parts) == 4 and parts[3] == "scan" and method == "POST":
            config, profile, storage = _context(user)
            _validate_hh_credentials(config)
            _validate_search_config(config)
            api = make_api(config, storage, "hh_app")
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                scan(config, profile, api, storage)
            self._send_json({"output": output.getvalue()})
            return
        if len(parts) == 4 and parts[3] == "drafts" and method == "GET":
            create_user(user)
            storage = Storage(user_dir(user) / "job_apply_bot.db")
            self._send_json({"drafts": [_row_to_dict(row) for row in storage.list_drafts(limit=100)]})
            return
        if len(parts) == 6 and parts[3] == "drafts" and parts[5] == "status" and method == "POST":
            vacancy_id = parts[4]
            status = str(self._read_json().get("status", ""))
            create_user(user)
            storage = Storage(user_dir(user) / "job_apply_bot.db")
            if status == "sent":
                storage.mark_sent(vacancy_id)
            elif status in {"skipped", "draft"}:
                storage.mark_status(vacancy_id, status)
            else:
                raise WebError(HTTPStatus.BAD_REQUEST, "Unsupported status")
            self._send_json({"ok": True})
            return
        raise WebError(HTTPStatus.NOT_FOUND, "Unknown API route")

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise WebError(HTTPStatus.BAD_REQUEST, "JSON-запрос должен быть объектом.")
        return data

    def _read_multipart_file(self, field_name: str) -> tuple[str, bytes]:
        content_type = self.headers.get("Content-Type", "")
        marker = "boundary="
        if marker not in content_type:
            raise WebError(HTTPStatus.BAD_REQUEST, "Expected multipart/form-data")
        boundary = content_type.split(marker, 1)[1].strip().strip('"')
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        delimiter = b"--" + boundary.encode()
        for part in body.split(delimiter):
            if not part or part in {b"--\r\n", b"--"}:
                continue
            header_blob, _, content = part.partition(b"\r\n\r\n")
            headers = header_blob.decode("utf-8", errors="ignore")
            if f'name="{field_name}"' not in headers:
                continue
            filename = "resume"
            match = __import__("re").search(r'filename="([^"]*)"', headers)
            if match:
                filename = match.group(1) or filename
            payload = content.rstrip(b"\r\n")
            if not payload:
                raise WebError(HTTPStatus.BAD_REQUEST, "Файл резюме пустой.")
            return filename, payload
        raise WebError(HTTPStatus.BAD_REQUEST, f"Missing file field: {field_name}")

    def _send_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _context(user: str):
    return load_context("config.yaml", "resume_profile.json", user)


def _configure_search(config: dict, profile: dict) -> dict:
    from main import configure_search_from_profile

    return configure_search_from_profile(config, profile)


def _validate_hh_credentials(config: dict) -> None:
    hh = config.get("hh", {})
    if not str(hh.get("client_id", "")).strip() or not str(hh.get("client_secret", "")).strip():
        raise WebError(HTTPStatus.BAD_REQUEST, "Сначала сохрани HH_CLIENT_ID и HH_CLIENT_SECRET.")


def _validate_search_config(config: dict) -> None:
    keywords = config.get("search", {}).get("keywords", [])
    if not isinstance(keywords, list) or not any(str(item).strip() for item in keywords):
        raise WebError(HTTPStatus.BAD_REQUEST, "В параметрах поиска нет search.keywords.")


def _http_status(status_code: int) -> HTTPStatus:
    if status_code < 400 or status_code > 599:
        return HTTPStatus.BAD_GATEWAY
    try:
        return HTTPStatus(status_code)
    except ValueError:
        return HTTPStatus.BAD_GATEWAY


def _row_to_dict(row) -> dict:
    return {
        "vacancy_id": row["vacancy_id"],
        "title": row["title"],
        "company": row["company"],
        "score": row["score"],
        "status": row["status"],
        "alternate_url": row["alternate_url"],
        "apply_url": row["apply_url"],
        "letter": row["letter"],
        "error_text": row["error_text"],
    }


def run_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Web dashboard: http://{host}:{port}")
    httpd.serve_forever()
