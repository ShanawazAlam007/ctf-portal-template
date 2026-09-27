// KIIT CYBER CTF Portal Scripts

document.addEventListener('DOMContentLoaded', () => {
    // 1. Mobile Menu Toggle
    const navToggle = document.getElementById('navToggle');
    const navMenu = document.getElementById('navMenu');

    if (navToggle && navMenu) {
        navToggle.addEventListener('click', () => {
            navMenu.classList.toggle('show');
        });
    }

    // 2. Auto-dismiss alerts after 8 seconds (except persistent ones)
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            if (alert && alert.parentElement) {
                alert.style.transition = 'opacity 0.5s ease';
                alert.style.opacity = '0';
                setTimeout(() => alert.remove(), 500);
            }
        }, 8000);
    });

    // 3. Prevent double submit on forms
    const forms = document.querySelectorAll('.cyber-form');
    forms.forEach(form => {
        form.addEventListener('submit', (e) => {
            const btn = form.querySelector('button[type="submit"]');
            if (btn && !btn.disabled) {
                // If it's valid, show working state
                setTimeout(() => {
                    btn.disabled = true;
                    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
                }, 50);
            }
        });
    });

    // 4. Copy to Clipboard for target info
    document.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const textToCopy = btn.getAttribute('data-copy');
            if (navigator.clipboard && textToCopy) {
                navigator.clipboard.writeText(textToCopy).then(() => {
                    const original = btn.innerHTML;
                    btn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    setTimeout(() => { btn.innerHTML = original; }, 2000);
                });
            }
        });
    });
});
