Код скрипта для страницы

```commandline
// Единый кэш: только последнее слово
let lastWordCache = null;

// Создаём один раз — переиспользуем
const helperEl = document.createElement('div');
helperEl.style.cssText = `
  position: absolute;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  font-size: 14px;
  z-index: 10000;
  max-width: 300px;
  display: none;
  pointer-events: auto;
`;
document.body.appendChild(helperEl);

// Закрытие при клике вне хелпера
document.addEventListener('click', (e) => {
  if (!helperEl.contains(e.target) && !e.target.closest('.word-helper')) {
    helperEl.style.display = 'none';
  }
});

// Обработка кликов по словам в .word-helper
document.querySelectorAll('.word-helper').forEach(paragraph => {
  paragraph.addEventListener('click', async (e) => {
    // Игнорируем клики не по тексту (например, по пробелам или краям)
    if (e.target !== paragraph) return;

    // Получаем слово под курсором
    const range = document.caretRangeFromPoint?.(e.clientX, e.clientY) ||
                  document.caretPositionFromPoint?.(e.clientX, e.clientY);
    if (!range) return;

    let node = range.startContainer;
    let offset = range.startOffset;

    // Если кликнули между словами — выходим
    if (node.nodeType !== Node.TEXT_NODE) return;

    const text = node.textContent;
    if (!text) return;

    // Находим границы слова
    let start = offset;
    let end = offset;

    while (start > 0 && /\w/.test(text[start - 1])) start--;
    while (end < text.length && /\w/.test(text[end])) end++;

    const word = text.slice(start, end).toLowerCase();
    if (!word || word.length < 2) return;

    // Кэширование: если это то же слово — просто покажем
    if (lastWordCache && lastWordCache.word === word) {
      showHelper(lastWordCache.data, e.clientX, e.clientY);
      return;
    }

    // Запрос к API
    try {
      const res = await fetch(`/api/word/${encodeURIComponent(word)}/`);
      const data = await res.json();
      if (res.ok) {
        lastWordCache = { word, data };
        showHelper(data, e.clientX, e.clientY);
      } else {
        // Можно показать "Not found", но для минимализма — тихо игнорируем
        helperEl.style.display = 'none';
      }
    } catch (err) {
      console.error('Word helper error:', err);
      helperEl.style.display = 'none';
    }
  });
});

function showHelper(data, x, y) {
  // Выбираем первое доступное произношение
  const audioUrl = data.pronunciations?.[0]?.audio_url || null;

  let html = `
    <div style="margin-bottom: 8px;">
      <strong>${data.word}</strong> 
      ${data.pos ? `<small>(${data.pos})</small>` : ''}
      ${data.ipa ? `<br><span style="color:#555; font-family:monospace;">${data.ipa}</span>` : ''}
    </div>
  `;

  if (data.senses && data.senses.length) {
    html += `<ul style="padding-left:16px; margin:4px 0;">`;
    data.senses.slice(0, 2).forEach(s => {
      html += `<li style="margin:2px 0;">${s.gloss}</li>`;
    });
    html += `</ul>`;
  }

  if (audioUrl) {
    html += `
      <div style="margin-top:6px;">
        <audio controls style="width:100%; height:28px; outline:none;">
          <source src="${audioUrl}" type="audio/mpeg">
        </audio>
      </div>
    `;
  }

  helperEl.innerHTML = html;
  helperEl.style.display = 'block';

  // Позиционирование рядом с курсором
  const rect = helperEl.getBoundingClientRect();
  let top = y + 10;
  let left = x + 10;

  // Не уходить за край экрана
  if (left + rect.width > window.innerWidth) {
    left = window.innerWidth - rect.width - 10;
  }
  if (top + rect.height > window.innerHeight) {
    top = window.innerHeight - rect.height - 10;
  }

  helperEl.style.top = `${top}px`;
  helperEl.style.left = `${left}px`;
}
```