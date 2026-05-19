async function collectDeviceFingerprint() {
    const c = {};

    c.screen     = `${screen.width}x${screen.height}x${screen.colorDepth}`;
    c.pixelRatio = window.devicePixelRatio;
    c.userAgent  = navigator.userAgent;
    c.platform   = navigator.platform;
    c.language   = navigator.language;
    c.timezone   = Intl.DateTimeFormat().resolvedOptions().timeZone;
    c.cores      = navigator.hardwareConcurrency;
    c.memory     = navigator.deviceMemory;
    c.touch      = navigator.maxTouchPoints;

    try {
        const canvas = document.createElement('canvas');
        const ctx    = canvas.getContext('2d');
        ctx.font     = '14px Arial';
        ctx.fillText('QRAttend🎓', 2, 14);
        c.canvas = canvas.toDataURL().slice(-50);
    } catch (_) {}

    try {
        const gl  = document.createElement('canvas').getContext('webgl');
        const dbg = gl?.getExtension('WEBGL_debug_renderer_info');
        if (dbg) {
            c.gpu = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);
        }
    } catch (_) {}

    const raw  = JSON.stringify(c);
    const buf  = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
    const hash = Array.from(new Uint8Array(buf))
                      .map(b => b.toString(16).padStart(2, '0')).join('');

    return hash;
}

// Run once on load — store in BOTH localStorage (persistent) and sessionStorage (fast access)
// localStorage survives browser close; sessionStorage is faster to read during the session.
// If localStorage already has a value from a previous session, reuse it so the fingerprint
// stays consistent even if minor browser characteristics drift between visits.
window.addEventListener('DOMContentLoaded', async () => {
    try {
        // Prefer the stored value — recomputing can produce a slightly different hash
        // if the browser has updated since last visit.
        const stored = localStorage.getItem('device_fp') || sessionStorage.getItem('device_fp');

        let hash;
        if (stored) {
            hash = stored;
        } else {
            hash = await collectDeviceFingerprint();
        }

        // Keep both storages in sync
        localStorage.setItem('device_fp', hash);
        sessionStorage.setItem('device_fp', hash);

        // If there's a hidden input on this page (login / register), fill it
        const input = document.getElementById('device_fingerprint');
        if (input) input.value = hash;

    } catch (e) {
        console.warn('Fingerprint collection failed:', e);
    }
});