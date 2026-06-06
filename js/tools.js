// Tool definitions + executors for local function calling.
// Each tool exposes an OpenAI-style `spec` (passed to the model) and a `run`
// function that actually executes locally in the browser.

// --- safe arithmetic evaluator (no eval) -----------------------------------
function evalMath(expr) {
  const tokens = expr.match(/(\d+\.?\d*|\.\d+|[()+\-*/%^])/g);
  if (!tokens || tokens.join('') !== expr.replace(/\s+/g, '')) {
    throw new Error('تعبير غير صالح');
  }
  let pos = 0;
  const peek = () => tokens[pos];
  const next = () => tokens[pos++];

  function parseExpr() {
    let v = parseTerm();
    while (peek() === '+' || peek() === '-') {
      const op = next();
      const r = parseTerm();
      v = op === '+' ? v + r : v - r;
    }
    return v;
  }
  function parseTerm() {
    let v = parsePow();
    while (peek() === '*' || peek() === '/' || peek() === '%') {
      const op = next();
      const r = parsePow();
      if (op === '*') v *= r;
      else if (op === '/') v /= r;
      else v %= r;
    }
    return v;
  }
  function parsePow() {
    const v = parseFactor();
    if (peek() === '^') { next(); return Math.pow(v, parsePow()); }
    return v;
  }
  function parseFactor() {
    if (peek() === '(') { next(); const v = parseExpr(); if (next() !== ')') throw new Error('قوس ناقص'); return v; }
    if (peek() === '-') { next(); return -parseFactor(); }
    if (peek() === '+') { next(); return parseFactor(); }
    const t = next();
    if (t === undefined || isNaN(Number(t))) throw new Error('رقم متوقع');
    return Number(t);
  }
  const result = parseExpr();
  if (pos !== tokens.length) throw new Error('تعبير غير مكتمل');
  return result;
}

export const TOOLS = {
  calculator: {
    spec: {
      type: 'function',
      function: {
        name: 'calculator',
        description: 'يحسب نتيجة تعبير رياضي. يدعم + - * / % ^ والأقواس. استخدمه لأي عملية حسابية.',
        parameters: {
          type: 'object',
          properties: {
            expression: { type: 'string', description: 'التعبير الرياضي، مثل "2 * (3 + 4) ^ 2"' },
          },
          required: ['expression'],
        },
      },
    },
    run: async ({ expression }) => {
      const value = evalMath(String(expression));
      return { expression, result: value };
    },
  },

  current_datetime: {
    spec: {
      type: 'function',
      function: {
        name: 'current_datetime',
        description: 'يعيد التاريخ والوقت الحاليين على جهاز المستخدم. استخدمه عندما يُسأل عن اليوم أو الساعة.',
        parameters: { type: 'object', properties: {}, required: [] },
      },
    },
    run: async () => {
      const now = new Date();
      return {
        iso: now.toISOString(),
        local: now.toLocaleString('ar', { dateStyle: 'full', timeStyle: 'short' }),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        weekday: now.toLocaleDateString('ar', { weekday: 'long' }),
      };
    },
  },

  random_number: {
    spec: {
      type: 'function',
      function: {
        name: 'random_number',
        description: 'يولّد عدداً صحيحاً عشوائياً ضمن نطاق [min, max] شاملاً الطرفين.',
        parameters: {
          type: 'object',
          properties: {
            min: { type: 'number', description: 'أصغر قيمة' },
            max: { type: 'number', description: 'أكبر قيمة' },
          },
          required: ['min', 'max'],
        },
      },
    },
    run: async ({ min, max }) => {
      min = Math.ceil(Number(min)); max = Math.floor(Number(max));
      if (max < min) [min, max] = [max, min];
      return { value: Math.floor(Math.random() * (max - min + 1)) + min, min, max };
    },
  },

  text_stats: {
    spec: {
      type: 'function',
      function: {
        name: 'text_stats',
        description: 'يحسب إحصائيات نص: عدد الأحرف والكلمات والأسطر.',
        parameters: {
          type: 'object',
          properties: { text: { type: 'string', description: 'النص المطلوب تحليله' } },
          required: ['text'],
        },
      },
    },
    run: async ({ text }) => {
      const s = String(text);
      const words = s.trim() ? s.trim().split(/\s+/).length : 0;
      return { characters: s.length, words, lines: s.split('\n').length };
    },
  },
};

// list of specs to send to the model, filtered by enabled set
export function toolSpecs(enabled) {
  return Object.entries(TOOLS)
    .filter(([name]) => enabled.has(name))
    .map(([, t]) => t.spec);
}

// execute a tool call by name; always resolves to a string result
export async function runTool(name, args) {
  const tool = TOOLS[name];
  if (!tool) return JSON.stringify({ error: `أداة غير معروفة: ${name}` });
  try {
    const out = await tool.run(args || {});
    return JSON.stringify(out);
  } catch (err) {
    return JSON.stringify({ error: String(err.message || err) });
  }
}
