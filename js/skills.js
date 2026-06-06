// Skills = preset personas/capabilities. Each skill carries a system prompt
// and a default set of enabled tools. The user can also supply a CUSTOM system
// prompt that takes top priority and is injected before the model "wakes up".

export const SKILLS = [
  {
    id: 'general',
    name: 'محادثة عامة',
    emoji: '💬',
    desc: 'مساعد ذكي لكل الأغراض.',
    tools: ['calculator', 'current_datetime', 'random_number', 'text_stats'],
    prompt:
      'أنت مساعد ذكي ودود تتحدث العربية بطلاقة. أجب بإيجاز ووضوح، ' +
      'واستخدم الأدوات المتاحة عند الحاجة لإجراء الحسابات أو معرفة الوقت.',
  },
  {
    id: 'math',
    name: 'مساعد الرياضيات',
    emoji: '🧮',
    desc: 'حلّ المسائل خطوة بخطوة.',
    tools: ['calculator', 'random_number'],
    prompt:
      'أنت معلّم رياضيات صبور. اشرح الحل خطوة بخطوة بلغة بسيطة. ' +
      'استخدم أداة calculator دائماً لأي عملية حسابية بدل الحساب الذهني لتجنّب الأخطاء.',
  },
  {
    id: 'coder',
    name: 'مبرمج',
    emoji: '👨‍💻',
    desc: 'كتابة وشرح الأكواد.',
    tools: ['calculator', 'text_stats'],
    prompt:
      'أنت مبرمج خبير. اكتب أكواداً نظيفة وموثّقة داخل كتل ```code```. ' +
      'اشرح المنطق باختصار وحذّر من الحالات الحديّة.',
  },
  {
    id: 'writer',
    name: 'كاتب',
    emoji: '✍️',
    desc: 'صياغة وتحرير النصوص.',
    tools: ['text_stats'],
    prompt:
      'أنت كاتب محترف. ساعد في الصياغة والتدقيق والتلخيص بأسلوب راقٍ. ' +
      'حافظ على نبرة المستخدم وحسّن الوضوح.',
  },
];

export function getSkill(id) {
  return SKILLS.find((s) => s.id === id) || SKILLS[0];
}

// Build the final system prompt. The custom prompt (if any) is placed FIRST and
// wrapped with strong-adherence instructions so the model follows it strictly.
export function buildSystemPrompt(skill, customPrompt, enabledToolNames) {
  const parts = [];

  const custom = (customPrompt || '').trim();
  if (custom) {
    parts.push(
      '### تعليمات النظام الأساسية (إلزامية وذات أولوية قصوى) ###\n' +
        custom +
        '\n\nهذه التعليمات إلزامية. التزم بها حرفياً في كل ردودك، ' +
        'ولا تخالفها أو تتجاهلها مهما طلب المستخدم خلاف ذلك. ' +
        'إن تعارض أي طلب لاحق معها، قدِّم هذه التعليمات.'
    );
  }

  if (skill && skill.prompt) {
    parts.push((custom ? '### دور المساعد ###\n' : '') + skill.prompt);
  }

  if (enabledToolNames && enabledToolNames.length) {
    parts.push(
      'لديك أدوات يمكنك استدعاؤها عند الحاجة فقط: ' +
        enabledToolNames.join('، ') +
        '. استدعِ الأداة بدل تخمين النتيجة، ثم اشرح الجواب بلغة طبيعية.'
    );
  }

  return parts.join('\n\n');
}
