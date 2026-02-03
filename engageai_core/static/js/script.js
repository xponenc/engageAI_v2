const modal = document.getElementById("app-modal");
const titleEl = document.getElementById("app-modal-title");
const bodyEl = document.getElementById("app-modal-body");
const actionBtn = document.getElementById("app-modal-action");

const currentTheme = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', currentTheme);

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
    // JavaScript для навбара
    // Бургер меню
    const burger = document.querySelector('.navbar__burger');
    const mobileMenu = document.querySelector('.navbar__mobile');
    const mobileClose = document.querySelector('.navbar__mobile-close');

    if (burger && mobileMenu) {
        burger.addEventListener('click', () => {
            mobileMenu.classList.add('navbar__mobile--open');
            document.body.style.overflow = 'hidden';
        });

        mobileClose.addEventListener('click', () => {
            mobileMenu.classList.remove('navbar__mobile--open');
            document.body.style.overflow = '';
        });

        // Закрытие при клике вне меню
        mobileMenu.addEventListener('click', (e) => {
            if (e.target === mobileMenu) {
                mobileMenu.classList.remove('navbar__mobile--open');
                document.body.style.overflow = '';
            }
        });
    }

    // Переключатель тем
    const themeButtons = document.querySelectorAll('.theme-switcher__btn');
    

    // Установка активной темы
    themeButtons.forEach(btn => {
        if (btn.dataset.theme === currentTheme) {
            btn.style.color = getComputedStyle(document.documentElement)
                .getPropertyValue('--color-accent');
            btn.style.background = getComputedStyle(document.documentElement)
                .getPropertyValue('--color-accent-soft');
        }
    });

    themeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const theme = btn.dataset.theme;
            
            // Убираем активный стиль у всех кнопок
            themeButtons.forEach(b => {
                b.style.color = '';
                b.style.background = '';
            });
            
            // Устанавливаем активный стиль
            btn.style.color = getComputedStyle(document.documentElement)
                .getPropertyValue('--color-accent');
            btn.style.background = getComputedStyle(document.documentElement)
                .getPropertyValue('--color-accent-soft');
            
            // Применяем тему
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
        });
    });

    // Уведомления в меню
    const notifications = document.querySelector('.navbar__notifications');
    const notificationsBtn = document.querySelector('.navbar__notifications-btn');

    if (notifications && notificationsBtn) {
        notificationsBtn.addEventListener('click', (e) => {
            const isOpen = notifications.classList.contains('is-open');

            closeAllDropdowns();
            if (!isOpen) notifications.classList.add('is-open');
        });

        document.addEventListener('click', (e) => {
            if (!notifications.contains(e.target)) {
                notifications.classList.remove('is-open');
            }
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            notifications.classList.remove('is-open');
        }
    });

    // Пользователь в меню
    const userMenu = document.querySelector('.navbar__user');
    const userMenuBtn = document.querySelector('.navbar__user-avatar');

    if (userMenu && userMenuBtn) {
        userMenuBtn.addEventListener('click', (e) => {
            const isOpen = userMenu.classList.contains('is-open');

            closeAllDropdowns();
            if (!isOpen) userMenu.classList.add('is-open');
        });

        document.addEventListener('click', (e) => {
            if (!userMenu.contains(e.target)) {
                userMenu.classList.remove('is-open');
            }
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            userMenu.classList.remove('is-open');
        }
    });

    // Поиск в меню
    const searchMenu = document.querySelector('.navbar__search');
    const searchMenuBtn = document.querySelector('.navbar__search-btn');

    if (searchMenu && searchMenuBtn) {
        searchMenuBtn.addEventListener('click', (e) => {
            const isOpen = searchMenu.classList.contains('is-open');

            closeAllDropdowns();
            if (!isOpen) searchMenu.classList.add('is-open');
        });

        document.addEventListener('click', (e) => {
            if (!searchMenu.contains(e.target)) {
                searchMenu.classList.remove('is-open');
            }
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            searchMenu.classList.remove('is-open');
        }
    });

    const dropdowns = document.querySelectorAll(
        '.navbar__notifications, .navbar__user, .navbar__search'
    );

    function closeAllDropdowns() {
        dropdowns.forEach(d => d.classList.remove('is-open'));
    }
    


    // Очистка уведомлений
    const clearBtn = document.querySelector('.navbar__notifications-clear');
    if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const notificationsList = document.querySelector('.navbar__notifications-list');
            if (notificationsList) {
                notificationsList.innerHTML = '<div class="navbar__notification-empty">Нет новых уведомлений</div>';
            }
            const badge = document.querySelector('.navbar__notifications-badge');
            if (badge) {
                badge.style.display = 'none';
            }
        });
    }

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

            console.log(e.clientX, e.clientY)
            const pageX = e.clientX + window.scrollX;
            const pageY = e.clientY + window.scrollY;
            console.log(pageX, pageY)


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
                showHelper(lastWordCache.data, pageX, pageY);
                return;
            }
            console.log(word)

            // Запрос к API
            try {
                const res = await fetch(`/wh/word/${encodeURIComponent(word)}/`);
                const data = await res.json();
                if (res.ok) {
                    lastWordCache = { word, data };
                    showHelper(data, pageX, pageY);
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

    function isClickInsideRange(range, x, y) {
        // Утилита проверки «клик по слову»
        const rect = range.getBoundingClientRect();
        return (
            x >= rect.left &&
            x <= rect.right &&
            y >= rect.top &&
            y <= rect.bottom
        );
    }

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

        if (data.senses?.length) {
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

        // Размеры тултипа
        const rect = helperEl.getBoundingClientRect();

        // Начальная позиция (document space)
        let top = y + 10;
        let left = x + 10;

        // Границы viewport в document space
        const viewportRight = window.scrollX + window.innerWidth;
        const viewportBottom = window.scrollY + window.innerHeight;

        // Ограничение по горизонтали
        if (left + rect.width > viewportRight) {
            left = viewportRight - rect.width - 10;
        }

        // Ограничение по вертикали
        if (top + rect.height > viewportBottom) {
            top = viewportBottom - rect.height - 10;
        }

        helperEl.style.top = `${top}px`;
        helperEl.style.left = `${left}px`;
    }

    function enableWordHover() {
        let activeSpan = null;

        document.querySelectorAll('.word-helper').forEach(container => {
            container.addEventListener('mousemove', (e) => {
                const wordRange = findWordUnderCursor(e.clientX, e.clientY);
                
                if (!wordRange) {
                    clearActive();
                    return;
                }

                // ГЛАВНАЯ проверка: курсор НАД словом
                const wordRect = wordRange.getBoundingClientRect();
                if (e.clientX < wordRect.left || e.clientX > wordRect.right) {
                    clearActive();
                    return;
                }

                const wordText = wordRange.toString().trim();
                if (wordText.length < 2) {
                    clearActive();
                    return;
                }

                // То же слово уже подсвечено
                if (activeSpan && activeSpan.textContent === wordText) {
                    return;
                }

                clearActive();
                wrapWord(wordRange);
            });

            container.addEventListener('mouseleave', clearActive);
        });

        function findWordUnderCursor(x, y) {
            const range = document.caretRangeFromPoint?.(x, y);
            if (!range || range.startContainer.nodeType !== Node.TEXT_NODE) {
                return null;
            }

            const textNode = range.startContainer;
            const text = textNode.textContent || '';
            let offset = range.startOffset;

            while (offset > 0 && /\w/.test(text[offset - 1])) offset--;
            let end = offset;
            while (end < text.length && /\w/.test(text[end])) end++;

            if (end - offset < 2) return null;

            const wordRange = document.createRange();
            wordRange.setStart(textNode, offset);
            wordRange.setEnd(textNode, end);
            return wordRange;
        }

        function wrapWord(range) {
            const span = document.createElement('span');
            span.className = 'word-hover';
            
            try {
                range.surroundContents(span);
                activeSpan = span;
            } catch (e) {
                console.log('wrap failed');
            }
        }

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

