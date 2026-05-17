/**
 * QR Display — no batch, no DB, pure signed tokens.
 * Polls /instructor/session/qr-token every 90s.
 * Requires qrcode.min.js loaded before this script.
 */

const LIFETIME_MS = 90_000;

let countdownInterval = null;
let currentSessionId  = null;

async function fetchAndRender() {
    try {
        const url = currentSessionId
            ? `/instructor/session/qr-token?session_id=${currentSessionId}`
            : `/instructor/session/qr-token`;

        const res  = await fetch(url, {
            headers: { 'X-CSRFToken': window.getCsrfToken?.() || '' }
        });
        const data = await res.json();

        if (!data.success) {
            showStatus(data.message || 'Session error.', 'error');
            return;
        }

        currentSessionId = data.session_id || currentSessionId;
        renderQR(data.token);
        startCountdown(LIFETIME_MS);

        // Schedule next refresh just before expiry
        setTimeout(fetchAndRender, LIFETIME_MS - 2000);

    } catch (err) {
        showStatus('Connection lost. Retrying…', 'error');
        setTimeout(fetchAndRender, 5000);
    }
}

function renderQR(token) {
    const el = document.getElementById('qr-canvas');
    el.innerHTML = '';

    new QRCode(el, {
        text        : token,
        width       : 300,
        height      : 300,
        colorDark   : '#1e1b4b',
        colorLight  : '#ffffff',
        correctLevel: QRCode.CorrectLevel.H,
    });

    showStatus('Active', 'active');
}

function startCountdown(ms) {
    clearInterval(countdownInterval);
    let remaining = Math.floor(ms / 1000);
    const el      = document.getElementById('qr-countdown');

    countdownInterval = setInterval(() => {
        remaining--;
        el.textContent = `Refreshes in ${remaining}s`;
        el.className   = remaining <= 10 ? 'countdown-urgent' : '';
        if (remaining <= 0) {
            clearInterval(countdownInterval);
            el.textContent = 'Refreshing…';
        }
    }, 1000);
}

function showStatus(msg, type) {
    const el  = document.getElementById('qr-status');
    el.textContent = msg;
    el.className   = type === 'active' ? 'status-active' : 'status-error';
}

// Start on load
window.addEventListener('DOMContentLoaded', fetchAndRender);