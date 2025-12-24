document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('task-response-form');
    if (!form) return;
    
    // Кэш URL для быстрого доступа
    const urlCache = {};
    
    form.addEventListener('submit', function(e) {
        if (!supportsFetch() || !form.checkValidity()) {
            return;
        }
        
        e.preventDefault();
        
        const formData = new FormData(form);
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn.innerHTML;
        
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Отправка...';
        
        fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(handleResponse)
        .then(data => handleSuccess(data, form, submitBtn, originalBtnText))
        .catch(error => handleError(error, submitBtn, originalBtnText));
    });
    
    function supportsFetch() {
        return window.fetch && window.FormData;
    }
    
    function handleResponse(response) {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `Ошибка ${response.status}: ${response.statusText}`);
            });
        }
        return response.json();
    }
    
    function handleSuccess(data, form, submitBtn, originalBtnText) {
        if (data.error) {
            throw new Error(data.error);
        }
        
        // Кэшируем URL для быстрого доступа
        if (data.redirect_urls) {
            Object.assign(urlCache, data.redirect_urls);
        }
        
        showFeedbackModal(data, form);
        resetSubmitButton(submitBtn, originalBtnText);
    }
    
    function handleError(error, button, originalText) {
        console.error('Error:', error);
        showErrorAlert(error.message || 'Произошла ошибка при отправке ответа');
        resetSubmitButton(button, originalText);
    }
    
    function resetSubmitButton(button, originalText) {
        button.disabled = false;
        button.innerHTML = originalText;
    }
    
    function showErrorAlert(message) {
        // Ищем контейнер для ошибок или создаем его
        let errorContainer = document.getElementById('error-container');
        if (!errorContainer) {
            errorContainer = document.createElement('div');
            errorContainer.id = 'error-container';
            errorContainer.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x p-3 m-3 shadow';
            errorContainer.style.zIndex = '9999';
            document.body.appendChild(errorContainer);
            
            // Автоматическое закрытие через 5 секунд
            setTimeout(() => {
                errorContainer.remove();
            }, 5000);
        }
        
        errorContainer.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="fas fa-exclamation-circle me-2"></i>
                <div>${message}</div>
                <button type="button" class="btn-close ms-auto" data-bs-dismiss="alert"></button>
            </div>
        `;
    }
    
    function showFeedbackModal(data, form) {
        const modalHtml = `
        <div class="modal fade show" id="feedbackModal" tabindex="-1" style="display: block;">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header bg-${data.success ? 'success' : 'warning'}">
                        <h5 class="modal-title text-white">${data.success ? 'Отлично!' : 'Попробуйте еще раз'}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <p class="lead">${data.feedback.message || 'Отличная работа!'}</p>
                        ${data.explanation ? `
                            <div class="mt-3 p-2 bg-light rounded border">
                                <h6 class="mb-2"><i class="fas fa-lightbulb me-1 text-warning"></i> Совет:</h6>
                                <p class="mb-0">${data.explanation}</p>
                            </div>
                        ` : ''}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-${data.success ? 'success' : 'warning'} w-100 py-2" 
                                onclick="handleModalClose('${data.next_action}', '${data.redirect_url}')">
                            <i class="fas fa-arrow-right me-2"></i>Продолжить
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <div class="modal-backdrop fade show"></div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    
        
        // Закрытие модалки по клику на backdrop
        document.querySelector('.modal-backdrop').addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal();
            }
        });
        
        // Обработка клавиатуры
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && document.getElementById('feedbackModal')) {
                closeModal();
            }
        });
        
        // Автоматическое закрытие через 3 секунды для успешных ответов
        if (data.success) {
            setTimeout(() => {
                if (document.getElementById('feedbackModal')) {
                    closeModal();
                    handleModalClose(data.next_action, data.next_task_id, data.enrollment_id);
                }
            }, 3000);
        }
    }
    
    function closeModal() {
        const modal = document.getElementById('feedbackModal');
        const backdrop = document.querySelector('.modal-backdrop');
        
        if (modal) {
            modal.classList.remove('show');
            modal.style.display = 'none';
            setTimeout(() => modal.remove(), 300);
        }
        
        if (backdrop) {
            backdrop.classList.remove('show');
            setTimeout(() => backdrop.remove(), 300);
        }
        
        // Восстанавливаем кнопку отправки
        const form = document.getElementById('task-response-form');
        if (form) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-check me-2"></i>Отправить ответ';
            }
        }
    }
    
    function handleModalClose(nextAction, redirectUrl) {
        closeModal();

        
        
        // Автоматическое закрытие через 3 секунды для успешных ответов
        if (nextAction !== 'REPEAT_TASK' && redirectUrl) {
            setTimeout(() => {
                window.location.href = redirectUrl;
            }, 3000);
        } else if (redirectUrl && redirectUrl !== 'undefined') {
            window.location.href = redirectUrl;
        } else {
            // Резервный вариант - перезагрузка страницы
            window.location.reload();
        }
    }
    
    // Обработчик для кнопок закрытия модалки
    document.addEventListener('click', function(e) {
        if (e.target && e.target.dataset.bsDismiss === 'modal') {
            closeModal();
        }
    });

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
});