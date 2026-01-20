document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.querySelector('#refresh-status');
    const enrollmentId = document.querySelector('[data-enrollment-id]')?.dataset.enrollmentId;
    if (!enrollmentId) return;

    let pollingInterval = null;
    let isRequestInFlight = false;

    function fetchStatus(button = null) {
        if (isRequestInFlight) return;
        isRequestInFlight = true;

        let restoreButton = null;

        if (button) {
            restoreButton = startButtonSpinner(button, 'Проверка...');
        }

        fetch(`/curriculum/session/${enrollmentId}/assessment-status/`, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'REDIRECT' && data.redirect_url) {
                    stopPolling();
                    window.location.href = data.redirect_url;
                    return;
                }

                if (data.status === 'ERROR') {
                    showErrorMessage(data.error_message);
                    stopPolling();
                    return;
                }

                if (typeof data.progress === 'number') {
                    updateProgress(data);
                }
            })
            .catch(err => {
                console.error('Assessment status error:', err);
            })
            .finally(() => {
                isRequestInFlight = false;
                if (restoreButton) restoreButton();
            });
    }

    

    // Кнопка "Проверить статус"
    refreshBtn.addEventListener('click', e => {
        fetchStatus(button);
    });

    // Автообновление
    pollingInterval = setInterval(() => fetchStatus(), 15000);
    setTimeout(() => fetchStatus(), 1000);

    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    function startButtonSpinner(button, loadingText = 'Загрузка...') {
        const originalText = button.textContent;

        // Создаём спиннер
        const spinner = document.createElement('span');
        spinner.className = 'button-spinner';

        // Очищаем кнопку
        button.textContent = '';
        button.appendChild(spinner);
        button.appendChild(document.createTextNode(` ${loadingText}`));
        button.disabled = true;

        // Возврат кнопки в исходное состояние
        return () => {
            button.disabled = false;
            button.textContent = originalText;
        };
    }

});
