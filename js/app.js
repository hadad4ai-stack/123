import { LocalLLM, MODELS, isWebGPUAvailable } from './llm.js';
import { SKILLS, getSkill, buildSystemPrompt } from './skills.js';
import { TOOLS, toolSpecs, runTool } from './tools.js';

// ---- persisted state -------------------------------------------------------
const LS = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

const state = {
  model: LS.get('model', MODELS[1].id),
  skillId: LS.get('skillId', 'general'),
  systemPrompt: LS.get('systemPrompt', ''),
  enabledTools: new Set(LS.get('enabledTools', Object.keys(TOOLS))),
  tts: LS.get('tts', false),
  messages: [], // chat history (without system message)
};

const llm = new LocalLLM();
let generating = false;
let abortCtl = null;

// ---- element refs ----------------------------------------------------------
const $ = (id) => document.getElementById(id);
const els = {
  menuBtn: $('menuBtn'), newChatBtn: $('newChatBtn'),
  drawer: $('drawer'), scrim: $('scrim'),
  modelSelect: $('modelSelect'), loadModelBtn: $('loadModelBtn'),
  loadProgress: $('loadProgress'), loadBar: $('loadBar'), loadText: $('loadText'),
  skillsList: $('skillsList'), toolsList: $('toolsList'),
  systemPrompt: $('systemPrompt'), saveSystemBtn: $('saveSystemBtn'),
  ttsToggle: $('ttsToggle'), clearChatBtn: $('clearChatBtn'),
  messages: $('messages'), composer: $('composer'),
  input: $('input'), sendBtn: $('sendBtn'),
  modelStatus: $('modelStatus'), activeSkillName: $('activeSkillName'),
};

// ---- drawer ----------------------------------------------------------------
function openDrawer() { els.drawer.hidden = false; els.scrim.hidden = false; }
function closeDrawer() { els.drawer.hidden = true; els.scrim.hidden = true; }
els.menuBtn.onclick = openDrawer;
els.scrim.onclick = closeDrawer;

// ---- settings UI -----------------------------------------------------------
function renderModelSelect() {
  els.modelSelect.innerHTML = MODELS
    .map((m) => `<option value="${m.id}">${m.label}</option>`)
    .join('');
  els.modelSelect.value = state.model;
}

function renderSkills() {
  els.skillsList.innerHTML = SKILLS.map((s) => `
    <button class="skill ${s.id === state.skillId ? 'active' : ''}" data-id="${s.id}">
      <span class="emoji">${s.emoji}</span>
      <span class="meta"><strong>${s.name}</strong><small>${s.desc}</small></span>
    </button>`).join('');
  els.skillsList.querySelectorAll('.skill').forEach((b) => {
    b.onclick = () => {
      state.skillId = b.dataset.id;
      // adopt the skill's default tools
      state.enabledTools = new Set(getSkill(state.skillId).tools);
      LS.set('skillId', state.skillId);
      LS.set('enabledTools', [...state.enabledTools]);
      renderSkills(); renderTools(); updateHeader();
    };
  });
}

function renderTools() {
  els.toolsList.innerHTML = Object.keys(TOOLS).map((name) => {
    const on = state.enabledTools.has(name);
    return `<span class="tool-chip ${on ? '' : 'off'}" data-name="${name}">
      ${on ? '✓' : '○'} ${name}</span>`;
  }).join('');
  els.toolsList.querySelectorAll('.tool-chip').forEach((c) => {
    c.onclick = () => {
      const n = c.dataset.name;
      state.enabledTools.has(n) ? state.enabledTools.delete(n) : state.enabledTools.add(n);
      LS.set('enabledTools', [...state.enabledTools]);
      renderTools();
    };
  });
}

function updateHeader() {
  els.activeSkillName.textContent = getSkill(state.skillId).name;
}

function setStatus(text, cls) {
  els.modelStatus.textContent = text;
  els.modelStatus.className = 'status' + (cls ? ' ' + cls : '');
}

// ---- model loading ---------------------------------------------------------
els.modelSelect.onchange = () => { state.model = els.modelSelect.value; LS.set('model', state.model); };

els.loadModelBtn.onclick = async () => {
  if (!isWebGPUAvailable()) {
    setStatus('WebGPU غير مدعوم على هذا المتصفح', 'error');
    alert('متصفحك لا يدعم WebGPU.\nعلى الآيفون: استخدم Safari مع iOS 17 أو أحدث، أو فعّل WebGPU من الإعدادات.');
    return;
  }
  els.loadModelBtn.disabled = true;
  els.loadProgress.hidden = false;
  setStatus('جارٍ التحميل…', 'loading');
  try {
    await llm.load(state.model, ({ progress, text }) => {
      els.loadBar.style.width = Math.round(progress * 100) + '%';
      els.loadText.textContent = text || `${Math.round(progress * 100)}%`;
    });
    setStatus('جاهز ✓', 'ready');
    els.loadText.textContent = 'اكتمل التحميل';
    updateSendEnabled();
    setTimeout(closeDrawer, 600);
  } catch (err) {
    console.error(err);
    setStatus('فشل التحميل', 'error');
    els.loadText.textContent = String(err.message || err);
  } finally {
    els.loadModelBtn.disabled = false;
  }
};

// ---- system prompt ---------------------------------------------------------
els.systemPrompt.value = state.systemPrompt;
els.saveSystemBtn.onclick = () => {
  state.systemPrompt = els.systemPrompt.value;
  LS.set('systemPrompt', state.systemPrompt);
  els.saveSystemBtn.textContent = 'تم الحفظ ✓';
  setTimeout(() => (els.saveSystemBtn.textContent = 'حفظ التعليمات'), 1200);
};

els.ttsToggle.checked = state.tts;
els.ttsToggle.onchange = () => { state.tts = els.ttsToggle.checked; LS.set('tts', state.tts); };

els.clearChatBtn.onclick = () => { state.messages = []; renderMessages(); closeDrawer(); };
els.newChatBtn.onclick = () => { state.messages = []; renderMessages(); };

// ---- rendering messages ----------------------------------------------------
function escapeHtml(s) {
  return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}
// very small markdown: code fences, inline code, bold
function formatContent(text) {
  let html = escapeHtml(text);
  html = html.replace(/```([\s\S]*?)```/g, (_, c) => `<pre><code>${c.replace(/^\n/, '')}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  return html;
}

function renderMessages() {
  if (!state.messages.length) {
    els.messages.innerHTML = `
      <div class="welcome">
        <div class="logo">✦</div>
        <h1>نموذج محلي على جهازك</h1>
        <p>يعمل الذكاء الاصطناعي بالكامل داخل المتصفح دون إرسال بياناتك لأي خادم.
        افتح ☰ لاختيار النموذج وكتابة تعليمات النظام ثم اضغط «تحميل النموذج».</p>
      </div>`;
    return;
  }
  els.messages.innerHTML = '';
  for (const m of state.messages) {
    if (m.role === 'tool' || m._tool) {
      const div = document.createElement('div');
      div.className = 'msg tool';
      div.innerHTML = `<div class="role">🔧 أداة: ${escapeHtml(m._name || '')}</div>${escapeHtml(m.content)}`;
      els.messages.appendChild(div);
      continue;
    }
    if (m.role === 'user' || m.role === 'assistant') {
      const div = document.createElement('div');
      div.className = 'msg ' + m.role;
      div.innerHTML = `<div class="role">${m.role === 'user' ? 'أنت' : 'المساعد'}</div>${formatContent(m.content || '')}`;
      els.messages.appendChild(div);
    }
  }
  scrollDown();
}

function scrollDown() { els.messages.scrollTop = els.messages.scrollHeight; }

// streaming bubble helper
function newAssistantBubble() {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="role">المساعد</div><span class="body"><span class="typing"><span></span><span></span><span></span></span></span>`;
  els.messages.appendChild(div);
  scrollDown();
  const body = div.querySelector('.body');
  return {
    set(text) { body.innerHTML = formatContent(text); scrollDown(); },
  };
}

function addToolBubble(name, content) {
  const div = document.createElement('div');
  div.className = 'msg tool';
  div.innerHTML = `<div class="role">🔧 أداة: ${escapeHtml(name)}</div>${escapeHtml(content)}`;
  els.messages.appendChild(div);
  scrollDown();
}

// ---- TTS -------------------------------------------------------------------
function speak(text) {
  if (!state.tts || !('speechSynthesis' in window)) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ar-SA';
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

// ---- the chat loop (with tool calling) ------------------------------------
async function send() {
  const text = els.input.value.trim();
  if (!text || generating) return;
  if (!llm.ready) { openDrawer(); setStatus('حمّل النموذج أولاً', 'error'); return; }

  els.input.value = '';
  autoGrow();
  state.messages.push({ role: 'user', content: text });
  renderMessages();

  generating = true;
  updateSendEnabled();
  abortCtl = new AbortController();

  const skill = getSkill(state.skillId);
  const enabledNames = [...state.enabledTools];
  const system = buildSystemPrompt(skill, state.systemPrompt, enabledNames);
  const specs = toolSpecs(state.enabledTools);

  // working message array sent to the model
  const work = [{ role: 'system', content: system }, ...state.messages.map(stripMeta)];

  try {
    // allow a few tool-call rounds
    for (let round = 0; round < 5; round++) {
      const bubble = newAssistantBubble();
      let streamed = '';
      const assistantMsg = await llm.chat(work, {
        tools: specs.length ? specs : undefined,
        signal: abortCtl.signal,
        onDelta: (d) => { streamed += d; bubble.set(streamed); },
      });

      work.push(assistantMsg);

      if (assistantMsg.tool_calls && assistantMsg.tool_calls.length) {
        // if the model produced no visible text, drop the empty bubble
        if (!streamed.trim()) bubble.set('⋯ يستدعي الأدوات');
        for (const call of assistantMsg.tool_calls) {
          let args = {};
          try { args = JSON.parse(call.function.arguments || '{}'); } catch {}
          const result = await runTool(call.function.name, args);
          addToolBubble(call.function.name, result);
          work.push({ role: 'tool', tool_call_id: call.id, content: result });
        }
        // loop again so the model can use the tool results
        continue;
      }

      // final answer
      if (assistantMsg.content != null) {
        state.messages.push({ role: 'assistant', content: assistantMsg.content });
        bubble.set(assistantMsg.content);
        speak(assistantMsg.content);
      }
      break;
    }
  } catch (err) {
    console.error(err);
    addToolBubble('error', String(err.message || err));
  } finally {
    generating = false;
    abortCtl = null;
    updateSendEnabled();
  }
}

// strip our UI-only fields before sending to the model
function stripMeta(m) {
  const { _name, _tool, ...rest } = m;
  return rest;
}

// ---- composer behaviour ----------------------------------------------------
function autoGrow() {
  els.input.style.height = 'auto';
  els.input.style.height = Math.min(els.input.scrollHeight, 140) + 'px';
}
function updateSendEnabled() {
  els.sendBtn.disabled = generating || !els.input.value.trim();
  els.sendBtn.textContent = generating ? '■' : '↑';
}
els.input.addEventListener('input', () => { autoGrow(); updateSendEnabled(); });
els.input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
});
els.composer.addEventListener('submit', (e) => { e.preventDefault(); submit(); });

function submit() {
  if (generating) { abortCtl?.abort(); llm.interrupt(); return; }
  send();
}

// ---- boot ------------------------------------------------------------------
function boot() {
  renderModelSelect();
  renderSkills();
  renderTools();
  updateHeader();
  renderMessages();
  updateSendEnabled();
  if (!isWebGPUAvailable()) {
    setStatus('WebGPU غير متاح', 'error');
  }
}
boot();
