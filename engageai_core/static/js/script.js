// theme-switcher.js
class ThemeSwitcher {
    constructor() {
        this.themes = ['light', 'dark', 'solarized', ];
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



document.addEventListener('DOMContentLoaded', function() {
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
        init: function() {
            if (!this.burger || !this.mobileMenu) return;
            
            // Обработчики событий
            this.burger.addEventListener('click', this.toggleMenu.bind(this));
            
            // Закрытие при клике вне меню
            document.addEventListener('click', this.handleOutsideClick.bind(this));
            
            // Закрытие при нажатии Escape
            document.addEventListener('keydown', this.handleEscape.bind(this));
            
            // Предотвращение закрытия при клике внутри меню
            this.mobileMenu.addEventListener('click', function(e) {
                e.stopPropagation();
            });
            
            // Закрытие при изменении размера окна (на десктоп)
            window.addEventListener('resize', this.handleResize.bind(this));
        },
        
        // Переключение меню
        toggleMenu: function() {
            this.isOpen = !this.isOpen;
            
            if (this.isOpen) {
                this.openMenu();
            } else {
                this.closeMenu();
            }
        },
        
        // Открытие меню
        openMenu: function() {
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
        closeMenu: function() {
            this.mobileMenu.classList.remove('nav__mobile_open');
            this.burger.classList.remove('nav__burger--active');
            this.body.style.overflow = ''; // Разблокируем скролл
            
            // Возвращаем бургер в исходное состояние
            this.animateBurger(false);
            
            // Возвращаем фокус на бургер-кнопку
            this.burger.focus();
        },
        
        // Анимация бургер-кнопки
        animateBurger: function(isOpen) {
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
        handleOutsideClick: function(e) {
            if (this.isOpen && 
                !this.mobileMenu.contains(e.target) && 
                !this.burger.contains(e.target)) {
                this.closeMenu();
            }
        },
        
        // Закрытие при нажатии Escape
        handleEscape: function(e) {
            if (this.isOpen && e.key === 'Escape') {
                this.closeMenu();
            }
        },
        
        // Обработка изменения размера окна
        handleResize: function() {
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
        link.addEventListener('keydown', function(e) {
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
});