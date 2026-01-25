// theme-switcher.js
class ThemeSwitcher {
    constructor() {
        this.themes = ['light', 'dark', 'solarized',];
        this.themeNames = {
            'light': 'Светлая',
            'dark': 'Темная',
            'solarized': 'Solarized',
        };
        this.nextThemeNames = {
            'light': 'Включить темную тему',
            'dark': 'Включить Solarized тему',
            'solarized': 'Включить светлую тему'
        };
        this.currentTheme = this.getSavedTheme() || 'light';
        this.init();
    }

    init() {
        this.applyTheme(this.currentTheme);
        this.bindEvents();
        this.setupKeyboardShortcut();
    }

    // Получить сохраненную тему из localStorage
    getSavedTheme() {
        return localStorage.getItem('theme');
    }

    // Сохранить тему в localStorage
    saveTheme(theme) {
        localStorage.setItem('theme', theme);
    }

    // Применить тему
    applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        this.currentTheme = theme;
        this.saveTheme(theme);
        this.updateButtonTitle();
    }

    // Переключить на следующую тему
    nextTheme() {
        const currentIndex = this.themes.indexOf(this.currentTheme);
        const nextIndex = (currentIndex + 1) % this.themes.length;
        const nextTheme = this.themes[nextIndex];
        this.applyTheme(nextTheme);

        // Показать уведомление о смене темы
        this.showThemeNotification();
    }

    // Обновить title кнопки
    updateButtonTitle() {
        const button = document.querySelector('.theme-toggle');
        if (button) {
            button.title = this.nextThemeNames[this.currentTheme] + ' (Ctrl+/)';
        }
    }

    // Привязать события
    bindEvents() {
        // Переключатель тем
        const themeToggle = document.querySelector('.theme-toggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => this.nextTheme());
        }

        // Слушатель изменения системной темы
        this.watchSystemTheme();
    }

    // Отслеживание системной темы
    watchSystemTheme() {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        const handleSystemThemeChange = (e) => {
            // Автоматически переключаемся только если тема не была явно выбрана пользователем
            const savedTheme = this.getSavedTheme();
            if (!savedTheme) {
                const systemTheme = e.matches ? 'dark' : 'light';
                this.applyTheme(systemTheme);
            }
        };

        mediaQuery.addEventListener('change', handleSystemThemeChange);

        // Инициализация при загрузке, если тема не сохранена
        if (!this.getSavedTheme()) {
            const systemTheme = mediaQuery.matches ? 'dark' : 'light';
            this.applyTheme(systemTheme);
        }
    }

    // Горячая клавиша для переключения тем
    setupKeyboardShortcut() {
        document.addEventListener('keydown', (e) => {
            // Ctrl + / для переключения темы
            if (e.ctrlKey && e.key === '/') {
                e.preventDefault();
                this.nextTheme();
            }
        });
    }

    // Показать уведомление о смене темы
    showThemeNotification() {
        // Создаем временное уведомление
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 70px;
            right: 20px;
            background: var(--color-surface);
            color: var(--color-text);
            padding: 8px 12px;
            border-radius: var(--radius-md);
            border: 1px solid var(--color-border);
            box-shadow: var(--shadow-md);
            z-index: 10000;
            font-size: 0.8rem;
            transition: all 0.3s ease;
            pointer-events: none;
        `;
        notification.textContent = `Тема: ${this.themeNames[this.currentTheme]}`;

        document.body.appendChild(notification);

        // Автоматически скрываем через 1.5 секунды
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transform = 'translateY(-10px)';
            setTimeout(() => notification.remove(), 300);
        }, 1500);
    }
}


const modal = document.getElementById("app-modal");
const titleEl = document.getElementById("app-modal-title");
const bodyEl = document.getElementById("app-modal-body");
const actionBtn = document.getElementById("app-modal-action");

let modalAction = null;

function lockScroll() {
    const scrollBarWidth =
        window.innerWidth - document.documentElement.clientWidth;

    document.body.style.overflow = "hidden";
    document.body.style.paddingRight = `${scrollBarWidth}px`;
}

function unlockScroll() {
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
}

function openModal({ title, body, type = "success", onAction }) {
    lockScroll();
    modal.classList.remove("modal--success", "modal--warning");
    modal.classList.add("modal--open", `modal--${type}`);
    modal.setAttribute("aria-hidden", "false");

    titleEl.textContent = title;
    bodyEl.innerHTML = body;

    modalAction = onAction;
    actionBtn.focus();
}

function closeModal() {
    modal.classList.remove("modal--open");
    modal.setAttribute("aria-hidden", "true");
    modalAction = null;
    unlockScroll();
}

actionBtn.addEventListener("click", () => {
    if (typeof modalAction === "function") {
        modalAction();
    }
    closeModal();
});

modal.addEventListener("click", (e) => {
    if (e.target.hasAttribute("data-modal-close")) {
        closeModal();
    }
});

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("modal--open")) {
        closeModal();
    }
});


let helperEl = null;
// Единый кэш: только последнее слово
let lastWordCache = null;

document.addEventListener('DOMContentLoaded', function () {

    click_handler();

    
    

    // Создаём один раз — переиспользуем
    helperEl = document.createElement('div');
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
    world_helper();

    new ThemeSwitcher();

    // Убираем класс initial-load после загрузки
    setTimeout(() => {
        document.body.classList.remove('initial-load');
    }, 100);


    const nav = {
        // Элементы
        burger: document.querySelector('.nav__burger'),
        mobileMenu: document.querySelector('.nav__mobile'),
        body: document.body,

        // Состояние
        isOpen: false,

        // Инициализация
        init: function () {
            if (!this.burger || !this.mobileMenu) return;

            // Обработчики событий
            this.burger.addEventListener('click', this.toggleMenu.bind(this));

            // Закрытие при клике вне меню
            document.addEventListener('click', this.handleOutsideClick.bind(this));

            // Закрытие при нажатии Escape
            document.addEventListener('keydown', this.handleEscape.bind(this));

            // Предотвращение закрытия при клике внутри меню
            this.mobileMenu.addEventListener('click', function (e) {
                e.stopPropagation();
            });

            // Закрытие при изменении размера окна (на десктоп)
            window.addEventListener('resize', this.handleResize.bind(this));
        },

        // Переключение меню
        toggleMenu: function () {
            this.isOpen = !this.isOpen;

            if (this.isOpen) {
                this.openMenu();
            } else {
                this.closeMenu();
            }
        },

        // Открытие меню
        openMenu: function () {
            this.mobileMenu.classList.add('nav__mobile_open');
            this.burger.classList.add('nav__burger--active');
            this.body.style.overflow = 'hidden'; // Блокируем скролл страницы

            // Анимация бургер-кнопки
            this.animateBurger(true);

            // Фокус на первом элементе меню для доступности
            const firstLink = this.mobileMenu.querySelector('.nav__mobile-link');
            if (firstLink) {
                setTimeout(() => firstLink.focus(), 100);
            }
        },

        // Закрытие меню
        closeMenu: function () {
            this.mobileMenu.classList.remove('nav__mobile_open');
            this.burger.classList.remove('nav__burger--active');
            this.body.style.overflow = ''; // Разблокируем скролл

            // Возвращаем бургер в исходное состояние
            this.animateBurger(false);

            // Возвращаем фокус на бургер-кнопку
            this.burger.focus();
        },

        // Анимация бургер-кнопки
        animateBurger: function (isOpen) {
            const lines = this.burger.querySelectorAll('.nav__burger-line');

            if (isOpen) {
                // Превращаем в крестик
                lines[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
                lines[1].style.opacity = '0';
                lines[2].style.transform = 'rotate(-45deg) translate(7px, -6px)';
            } else {
                // Возвращаем в исходное состояние
                lines[0].style.transform = 'none';
                lines[1].style.opacity = '1';
                lines[2].style.transform = 'none';
            }
        },

        // Закрытие при клике вне меню
        handleOutsideClick: function (e) {
            if (this.isOpen &&
                !this.mobileMenu.contains(e.target) &&
                !this.burger.contains(e.target)) {
                this.closeMenu();
            }
        },

        // Закрытие при нажатии Escape
        handleEscape: function (e) {
            if (this.isOpen && e.key === 'Escape') {
                this.closeMenu();
            }
        },

        // Обработка изменения размера окна
        handleResize: function () {
            // Закрываем меню при переходе на десктоп
            if (window.innerWidth > 900 && this.isOpen) {
                this.closeMenu();
            }
        }
    };

    // Инициализация навигации
    nav.init();

    // Дополнительные улучшения для доступности
    const mobileLinks = document.querySelectorAll('.nav__mobile-link');
    mobileLinks.forEach(link => {
        link.addEventListener('keydown', function (e) {
            // Закрытие меню при нажатии Enter или Space на ссылке
            if (e.key === 'Enter' || e.key === ' ') {
                setTimeout(() => {
                    if (nav.isOpen) {
                        nav.closeMenu();
                    }
                }, 100);
            }
        });
    });

    // отображение сообщений Django

    const messageContainer = document.getElementById('django-messages');
    if (!messageContainer) return;

    const AUTO_CLOSE_MS = 5000;

    messageContainer.querySelectorAll('.message').forEach((msg, index) => {
        // staggered appearance
        msg.style.opacity = '0';
        msg.style.transform = 'translateY(-8px)';
        msg.style.transition = 'opacity .25s ease, transform .25s ease';

        requestAnimationFrame(() => {
            msg.style.opacity = '1';
            msg.style.transform = 'translateY(0)';
        });

        let timeout = setTimeout(() => closeMessage(msg), AUTO_CLOSE_MS);

        // pause on hover
        msg.addEventListener('mouseenter', () => clearTimeout(timeout));
        msg.addEventListener('mouseleave', () => {
            timeout = setTimeout(() => closeMessage(msg), 1500);
        });
    });

    function closeMessage(msg) {
        msg.style.opacity = '0';
        msg.style.transform = 'translateY(-6px)';
        setTimeout(() => msg.remove(), 250);
    }

});

function click_handler() {
    document.addEventListener('click', (e) => {
        if (!helperEl.contains(e.target) && !e.target.closest('.word-helper')) {
            helperEl.style.display = 'none';
        }
    });
}


function world_helper() {
    // Обработка кликов по словам в .word-helper
    document.querySelectorAll('.word-helper').forEach(paragraph => {
        paragraph.addEventListener('click', async (e) => {
            // Игнорируем клики не по тексту (например, по пробелам или краям)
            if (!e.target.closest('.word-helper')) return;

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
                const res = await fetch(`/wh/word/${encodeURIComponent(word)}/`);
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

    function enableWordHover() {
        let activeSpan = null;

        document.querySelectorAll('.word-helper').forEach(container => {

            container.addEventListener('mousemove', (e) => {
                const range =
                    document.caretRangeFromPoint?.(e.clientX, e.clientY) ||
                    document.caretPositionFromPoint?.(e.clientX, e.clientY);

                if (!range || !range.startContainer) return;
                if (range.startContainer.nodeType !== Node.TEXT_NODE) return;

                const textNode = range.startContainer;
                const text = textNode.textContent;
                const offset = range.startOffset;

                if (!text || !/\w/.test(text[offset])) {
                    clearActive();
                    return;
                }

                // находим границы слова
                let start = offset;
                let end = offset;

                while (start > 0 && /\w/.test(text[start - 1])) start--;
                while (end < text.length && /\w/.test(text[end])) end++;

                // если уже подсвечено это же слово — ничего не делаем
                if (
                    activeSpan &&
                    activeSpan.textContent === text.slice(start, end)
                ) return;

                clearActive();

                const wordRange = document.createRange();
                wordRange.setStart(textNode, start);
                wordRange.setEnd(textNode, end);

                const span = document.createElement('span');
                span.className = 'word-hover';

                wordRange.surroundContents(span);
                activeSpan = span;
            });

            container.addEventListener('mouseleave', clearActive);
        });

        function clearActive() {
            if (!activeSpan) return;

            const parent = activeSpan.parentNode;
            while (activeSpan.firstChild) {
                parent.insertBefore(activeSpan.firstChild, activeSpan);
            }
            parent.removeChild(activeSpan);
            activeSpan = null;
        }

        
    }

    enableWordHover();
}

