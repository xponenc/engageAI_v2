document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('task-response-form');
    if (!form) return;
    
    // Проверяем поддержку fetch
    const supportsFetch = window.fetch && window.FormData;
    
    form.addEventListener('submit', function(e) {
        // Если нет поддержки fetch или form не валидна - используем обычный POST
        if (!supportsFetch || !form.checkValidity()) {
            return;
        }
        
        e.preventDefault();
        
        const formData = new FormData(form);
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn.innerHTML;
        
        // Блокируем кнопку
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Отправка...';
        
        // Отправляем через fetch
        fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || 'Ошибка сервера');
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            showFeedbackModal(data, enrollmentId);
        })
        .catch(error => {
            console.error('Error:', error);
            alert(`Ошибка: ${error.message}`);
            // Разблокируем кнопку
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnText;
        });
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
    
    function showFeedbackModal(data, enrollmentId) {
        const modalHtml = `
        <div class="modal fade show" id="feedbackModal" tabindex="-1" style="display: block;">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header bg-${data.decision === 'REPEAT_TASK' ? 'warning' : 'success'}">
                        <h5 class="modal-title text-white">${data.decision === 'REPEAT_TASK' ? 'Попробуйте еще раз' : 'Отлично!'}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <p>${data.feedback.message || 'Отличная работа!'}</p>
                        ${data.explanation ? `
                            <div class="mt-3 p-2 bg-light rounded">
                                <h6>Объяснение:</h6>
                                <p>${data.explanation}</p>
                            </div>
                        ` : ''}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-${data.decision === 'REPEAT_TASK' ? 'warning' : 'success'}" 
                                onclick="handleModalClose('${data.next_action}', ${data.next_task_id || 0}, ${enrollmentId})">
                            Продолжить
                        </button>
                    </div>
                </div>
            </div>
        </div>
        <div class="modal-backdrop fade show"></div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
        // Закрытие модалки
        document.querySelector('.btn-close').addEventListener('click', closeModal);
        document.querySelector('.modal-backdrop').addEventListener('click', closeModal);
    }
    
    function closeModal() {
        document.getElementById('feedbackModal')?.remove();
        document.querySelector('.modal-backdrop')?.remove();
    }
    
    function handleModalClose(nextAction, nextTaskId, enrollmentId) {
        closeModal();
        
        if (nextAction === 'NEXT_TASK' && nextTaskId) {
            window.location.href = `/curriculum/session/${enrollmentId}/task/${nextTaskId}/`;
        } else if (nextAction === 'ADVANCE_LESSON') {
            window.location.href = `/curriculum/session/${enrollmentId}/`;
        } else {
            window.location.reload();
        }
    }
});