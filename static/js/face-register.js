/* ═══════════════════════════════════════════════════════════════
   face-register.js — Guided face registration
   Works on desktop AND mobile (no Spacebar needed)
   ═══════════════════════════════════════════════════════════════ */

(function() {
    'use strict';

    const data = JSON.parse(document.getElementById('frData').textContent);
    const video = document.getElementById('frVideo');
    const canvas = document.getElementById('frCanvas');
    const oval = document.getElementById('frOval');
    const camWrap = document.getElementById('frCamWrap');
    const instructionEl = document.getElementById('frInstruction');
    const captureBtn = document.getElementById('frCaptureBtn');
    const saveBtn = document.getElementById('frSaveBtn');
    const consent = document.getElementById('frConsent');
    const consentName = document.getElementById('frConsentName');
    const camSwitch = document.getElementById('frCamSwitch');
    const steps = document.querySelectorAll('.fr-step');

    const REQUIRED_SAMPLES = 5;
    const STEPS = [
        { label: 'Look straight at the camera', icon: 'la-user' },
        { label: 'Turn head slightly LEFT', icon: 'la-arrow-left' },
        { label: 'Turn head slightly RIGHT', icon: 'la-arrow-right' },
        { label: 'Smile 🙂', icon: 'la-smile' },
        { label: 'Neutral expression', icon: 'la-meh' },
    ];

    const vectors = [];
    let modelsLoaded = false;
    let capturing = false;
    let currentStream = null;
    let cameraFacing = 'user';   // 'user' (front) or 'environment' (back)

    // ─── Instruction setter ───
    function setInstruction(msg, type, icon) {
        const i = icon ? `<i class="las ${icon}"></i> ` : '';
        instructionEl.innerHTML = i + msg;
        instructionEl.className = 'fr-instruction' + (type ? ' ' + type : '');
    }

    // ─── Steps indicator ───
    function updateSteps() {
        steps.forEach((el, i) => {
            el.classList.remove('active', 'done');
            if (i < vectors.length) el.classList.add('done');
            else if (i === vectors.length) el.classList.add('active');
        });
    }

    // ─── Load face models ───
    async function loadModels() {
        const base = data.static_base + '/models';
        try {
            await faceapi.nets.tinyFaceDetector.loadFromUri(base);
            await faceapi.nets.faceLandmark68Net.loadFromUri(base);
            await faceapi.nets.faceRecognitionNet.loadFromUri(base);
            modelsLoaded = true;
            captureBtn.disabled = false;
            updateSteps();
            setInstruction(STEPS[0].label, 'success', STEPS[0].icon);
            console.log('[fr] Models loaded');
        } catch (e) {
            console.error('[fr] Model load failed:', e);
            setInstruction('Failed to load models. Please refresh.', 'error', 'la-exclamation-triangle');
        }
    }

    // ─── Start camera (with facing option) ───
    async function startCamera(facing) {
        if (currentStream) {
            currentStream.getTracks().forEach(t => t.stop());
        }
        try {
            currentStream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 720 },
                    height: { ideal: 960 },
                    facingMode: facing || cameraFacing,
                }
            });
            video.srcObject = currentStream;

            // Mirror only front camera
            if ((facing || cameraFacing) === 'user') {
                camWrap.classList.add('mirror');
            } else {
                camWrap.classList.remove('mirror');
            }

            // Show camera switch if device has multiple cameras
            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                const videoInputs = devices.filter(d => d.kind === 'videoinput');
                if (videoInputs.length > 1) {
                    camSwitch.style.display = 'flex';
                }
            } catch (err) { /* ignore */ }

            console.log('[fr] Camera started:', facing || cameraFacing);
        } catch (e) {
            console.error('[fr] Camera error:', e);
            setInstruction('Camera access denied', 'error', 'la-exclamation-triangle');
        }
    }

    // ─── Switch camera ───
    camSwitch.addEventListener('click', async () => {
        cameraFacing = cameraFacing === 'user' ? 'environment' : 'user';
        await startCamera(cameraFacing);
    });

    // ─── Continuous detection for oval color feedback ───
    function startDetectionLoop() {
        setInterval(async () => {
            if (!modelsLoaded || video.readyState < 2) return;
            if (capturing) return;

            try {
                const detection = await faceapi
                    .detectSingleFace(video, new faceapi.TinyFaceDetectorOptions())
                    .withFaceLandmarks()
                    .withFaceDescriptor();

                if (detection) {
                    oval.classList.add('detected');
                } else {
                    oval.classList.remove('detected');
                }
            } catch (e) {
                /* ignore */
            }
        }, 400);
    }

    // ─── Capture sample (button click) ───
    async function captureSample() {
        if (capturing) return;
        if (vectors.length >= REQUIRED_SAMPLES) {
            setInstruction('All samples captured. Please review and save.', 'success', 'la-check');
            return;
        }

        capturing = true;
        captureBtn.disabled = true;
        setInstruction('Capturing...', null, 'la-spinner');

        try {
            const detection = await faceapi
                .detectSingleFace(video, new faceapi.TinyFaceDetectorOptions({
                    inputSize: 416,
                    scoreThreshold: 0.4,
                }))
                .withFaceLandmarks()
                .withFaceDescriptor();

            if (!detection) {
                setInstruction('No face detected. Please look at the camera.', 'error', 'la-exclamation-triangle');
                setTimeout(() => {
                    setInstruction(STEPS[vectors.length]?.label || 'Please look at camera', 'success', STEPS[vectors.length]?.icon);
                    captureBtn.disabled = false;
                    capturing = false;
                }, 1500);
                return;
            }

            vectors.push(Array.from(detection.descriptor));
            const idx = vectors.length;

            oval.classList.add('captured');
            setTimeout(() => oval.classList.remove('captured'), 400);

            updateSteps();
            console.log(`[fr] Sample ${idx}/5 captured`);

            if (vectors.length < REQUIRED_SAMPLES) {
                const nextStep = STEPS[vectors.length];
                setInstruction(`Sample ${idx}/5 captured ✓  →  ${nextStep.label}`, 'success', nextStep.icon);
                captureBtn.disabled = false;
            } else {
                setInstruction('All 5 samples captured ✓  Please save.', 'success', 'la-check-circle');
            }

            updateSaveState();
        } catch (e) {
            console.error('[fr] Capture error:', e);
            setInstruction('Error capturing. Please try again.', 'error');
            captureBtn.disabled = false;
        } finally {
            capturing = false;
        }
    }

    captureBtn.addEventListener('click', captureSample);

    // ─── Save button state ───
    function updateSaveState() {
        const ready = vectors.length === REQUIRED_SAMPLES
                   && consent.checked
                   && consentName.value.trim().length > 2;
        saveBtn.disabled = !ready;
    }
    consent.addEventListener('change', updateSaveState);
    consentName.addEventListener('input', updateSaveState);
    setInterval(updateSaveState, 400);

    // ─── Save to server ───
    saveBtn.addEventListener('click', async () => {
        saveBtn.disabled = true;
        setInstruction('Saving...', null, 'la-spinner');

        try {
            const res = await fetch(data.save_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': data.csrf_token,
                },
                body: JSON.stringify({
                    employee_id:    data.employee_id,
                    vectors:        vectors,
                    consent_name:   consentName.value.trim(),
                    model_version:  'face-api-1.0',
                }),
            });

            const json = await res.json();

            if (res.ok && json.success) {
                setInstruction('✓ ' + json.message, 'success', 'la-check-circle');
                setTimeout(() => {
                    window.location.href = '/employees/' + data.user_id + '/';
                }, 1500);
            } else {
                setInstruction('Error: ' + (json.error || 'Save failed'), 'error');
                saveBtn.disabled = false;
            }
        } catch (e) {
            console.error('[fr] Save error:', e);
            setInstruction('Network error. Please try again.', 'error');
            saveBtn.disabled = false;
        }
    });

    // ─── Init ───
    (async function init() {
        console.log('[fr] Init');
        await loadModels();
        await startCamera('user');
        startDetectionLoop();
    })();

})();