document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('task-response-form');
    if (!form) return;

    form.addEventListener('submit', onSubmit);

    /* ==========================
       Form submit
    ========================== */

    function onSubmit(event) {
        if (!supportsFetch() || !form.checkValidity()) {
            return;
        }

        event.preventDefault();

        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnHtml = submitBtn.innerHTML;

        setSubmitLoading(submitBtn);

        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
            .then(handleResponse)
            .then(data => handleSuccess(data))
            .catch(error => handleError(error))
            .finally(() => restoreSubmitButton(submitBtn, originalBtnHtml));
    }

    /* ==========================
       Handlers
    ========================== */

    function handleResponse(response) {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `Ошибка ${response.status}`);
            });
        }
        return response.json();
    }

    function handleSuccess(data) {
        if (data.error) {
            throw new Error(data.error);
        }

        showFeedbackModal(data);
    }

    function handleError(error) {
        console.error(error);

        openModal({
            title: 'Ошибка',
            type: 'error',
            body: `
                <p class="modal__text">
                    ${error.message || 'Произошла ошибка при отправке ответа'}
                </p>
            `,
            actionText: 'Закрыть'
        });
    }

    /* ==========================
       UI helpers
    ========================== */

     function setSubmitLoading(button, loadingText = 'Отправка…') {
        if (!button) return;

        // сохраняем состояние
        button.dataset.originalHtml = button.innerHTML;

        // очищаем кнопку
        button.innerHTML = '';
        button.disabled = true;

        // спиннер
        const spinner = document.createElement('span');
        spinner.className = 'button-spinner';

        // текст
        const text = document.createElement('span');
        text.textContent = loadingText;

        button.append(spinner, text);
    }

    function restoreSubmitButton(button) {
        if (!button || !button.dataset.originalHtml) return;

        button.innerHTML = button.dataset.originalHtml;
        button.disabled = false;

        delete button.dataset.originalHtml;
    }

    /* ==========================
       Feedback modal
    ========================== */

    function showFeedbackModal(data) {
        openModal({
            title: data.success ? 'Отлично!' : 'Попробуйте ещё раз',
            type: data.success ? 'success' : 'warning',

            body: `
                <p class="modal__text">
                    ${data.feedback?.message || 'Отличная работа!'}
                </p>

                ${data.explanation ? `
                    <div class="modal__hint">
                        <strong class="modal__hint-title">Совет</strong>
                        <p class="modal__hint-text">${data.explanation}</p>
                    </div>
                ` : ''}
            `,

            actionText: 'Продолжить',

            onAction: () => {
                handleNextStep(data.next_action, data.redirect_url);
            },

            autoCloseMs: data.success ? 3000 : null
        });
    }

    /* ==========================
       Navigation logic
    ========================== */

    function handleNextStep(nextAction, redirectUrl) {
        if (nextAction !== 'REPEAT_TASK' && redirectUrl) {
            window.location.href = redirectUrl;
            return;
        }

        if (redirectUrl && redirectUrl !== 'undefined') {
            window.location.href = redirectUrl;
            return;
        }

        window.location.reload();
    }

    /* ==========================
       Utils
    ========================== */

    function supportsFetch() {
        return 'fetch' in window && 'FormData' in window;
    }

    function getCookie(name) {
        let value = null;
        if (!document.cookie) return value;

        document.cookie.split(';').forEach(cookie => {
            const c = cookie.trim();
            if (c.startsWith(name + '=')) {
                value = decodeURIComponent(c.slice(name.length + 1));
            }
        });

        return value;
    }

   

 
});
