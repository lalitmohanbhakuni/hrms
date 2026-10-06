/* ═══════════════════════════════════════════════════════════════
   kiosk.js v2 — Button-triggered, fast, with sound feedback
   ═══════════════════════════════════════════════════════════════ */

(function() {
    'use strict';

    const data = JSON.parse(document.getElementById('kData').textContent);

    function getFingerprint() {
        try {
            return btoa(
                (screen.width + 'x' + screen.height) + '|' +
                new Date().getTimezoneOffset() + '|' +
                navigator.userAgent + '|' +
                navigator.language + '|' +
                (navigator.hardwareConcurrency || 0)
            );
        } catch (e) { return 'unknown'; }
    }


    // Screens
    const idleScreen   = document.getElementById('kIdleScreen');
    const cameraScreen = document.getElementById('kCameraScreen');
    const panel        = document.getElementById('kPanel');

    // Buttons
    const btnIn     = document.getElementById('kBtnIn');
    const btnOut    = document.getElementById('kBtnOut');
    const cancelBtn = document.getElementById('kCancelBtn');

    // Camera
    const video    = document.getElementById('kVideo');
    const canvas   = document.getElementById('kCanvas');
    const target   = document.getElementById('kTarget');
    const statusEl = document.getElementById('kStatus');

    // Liveness
    const livenessOverlay  = document.getElementById('kLiveness');
    const livenessProgress = document.getElementById('kLivenessProgress');

    // Panel
    const panelIcon = document.getElementById('kPanelIcon');
    const panelName = document.getElementById('kPanelName');
    const panelMsg  = document.getElementById('kPanelMsg');
    const panelTime = document.getElementById('kPanelTime');

    // Status
    const countEl       = document.getElementById('kCount');
    const clockStatusEl = document.getElementById('kClockStatus');
    const clockEl       = document.getElementById('kClock');

    // ── State ──
    let employees = [];
    let labeledDescriptors = [];
    let modelsLoaded = false;
    let currentStream = null;
    let detectionInterval = null;
    let activeAction = null;
    let actionInProgress = false;
    let livenessPassed = false;
    let eyesWereClosed = false;
    let eyesClosedSince = 0;
    let livenessStartTime = 0;
    let lastMatch = { id: null, count: 0, timestamp: 0 };
    let cameraStartTime = 0;

    const MATCH_INTERVAL_MS   = 300;    // faster loop
    const MIN_CONSECUTIVE_HITS = 1;     // 1 hit = enough (server verifies)
    const LIVENESS_TIMEOUT_MS = 20000;
    const MAX_CAMERA_TIME_MS  = 45000;
    const BLINK_MIN_MS        = 30;     // easier to detect
    const BLINK_MAX_MS        = 800;    // more lenient

    // ── Live clock ──
    setInterval(() => {
        const now = new Date();
        clockEl.textContent = now.toLocaleTimeString('en-IN', { hour12: false });
    }, 1000);

    function setStatus(msg) {
        statusEl.innerHTML = msg;
    }

    // ═══════════════════════════════════════════════════════
    // SOUND FEEDBACK
    // ═══════════════════════════════════════════════════════
    function beep(freq, duration) {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = freq;
            osc.type = 'sine';
            gain.gain.setValueAtTime(0.15, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            osc.start();
            osc.stop(ctx.currentTime + duration);
        } catch (e) { /* ignore */ }
    }

    function beepSuccess() {
        beep(800, 0.15);
        setTimeout(() => beep(1200, 0.25), 150);
    }

    function beepError() {
        beep(300, 0.4);
    }

    // ═══════════════════════════════════════════════════════
    // SCREEN SWITCHING
    // ═══════════════════════════════════════════════════════
    function showIdle() {
        idleScreen.classList.add('active');
        cameraScreen.classList.remove('active');
        panel.classList.remove('active');
    }

    function showCamera() {
        idleScreen.classList.remove('active');
        panel.classList.remove('active');
        cameraScreen.classList.add('active');
    }

    function showPanel(state, icon, name, msg, time) {
        idleScreen.classList.remove('active');
        cameraScreen.classList.remove('active');
        panel.className = 'k-panel state-' + state + ' active';
        panelIcon.innerHTML = '<i class="las ' + icon + '"></i>';
        panelName.textContent = name || '';
        panelMsg.textContent = msg || '';
        panelTime.textContent = time || '';
        panelTime.style.display = time ? 'inline-block' : 'none';
    }

    // ═══════════════════════════════════════════════════════
    // LOAD MODELS & EMPLOYEES
    // ═══════════════════════════════════════════════════════
    async function loadModels() {
        const base = data.static_base + '/models';
        try {
            await faceapi.nets.tinyFaceDetector.loadFromUri(base);
            await faceapi.nets.faceLandmark68Net.loadFromUri(base);
            await faceapi.nets.faceRecognitionNet.loadFromUri(base);
            modelsLoaded = true;
            clockStatusEl.textContent = 'Ready';
            console.log('[kiosk] Models loaded');
        } catch (e) {
            console.error('[kiosk] Model load failed:', e);
            clockStatusEl.textContent = 'Model load failed';
        }
    }

    async function loadVectors() {
        clockStatusEl.textContent = 'Loading employees...';
        try {
            const res = await fetch(data.vectors_url + '?token=' + encodeURIComponent(data.token));
            const json = await res.json();
            if (!res.ok) throw new Error(json.error || 'Failed');
            employees = json.employees || [];
            countEl.textContent = employees.length;

            labeledDescriptors = employees.map(emp => {
                const descriptors = emp.vectors.map(v => new Float32Array(v));
                return new faceapi.LabeledFaceDescriptors(
                    JSON.stringify({
                        id: emp.employee_id,
                        code: emp.employee_code,
                        name: emp.full_name,
                    }),
                    descriptors
                );
            });
            clockStatusEl.textContent = `${employees.length} employees ready`;
        } catch (e) {
            console.error('[kiosk] Load vectors failed:', e);
            clockStatusEl.textContent = 'Load failed';
        }
    }

    // ═══════════════════════════════════════════════════════
    // CAMERA
    // ═══════════════════════════════════════════════════════
    async function startCamera() {
        try {
            if (currentStream) {
                currentStream.getTracks().forEach(t => t.stop());
            }
            currentStream = await navigator.mediaDevices.getUserMedia({
                video: { width: 960, height: 720, facingMode: 'user' }
            });
            video.srcObject = currentStream;
            return true;
        } catch (e) {
            console.error('[kiosk] Camera error:', e);
            return false;
        }
    }

    function stopCamera() {
        if (currentStream) {
            currentStream.getTracks().forEach(t => t.stop());
            currentStream = null;
        }
        if (video) video.srcObject = null;
    }

    // ═══════════════════════════════════════════════════════
    // BLINK DETECTION (easier)
    // ═══════════════════════════════════════════════════════
    function distance(p1, p2) {
        return Math.hypot(p1.x - p2.x, p1.y - p2.y);
    }
    function eyeAspectRatio(eyePoints) {
        const v1 = distance(eyePoints[1], eyePoints[5]);
        const v2 = distance(eyePoints[2], eyePoints[4]);
        const h  = distance(eyePoints[0], eyePoints[3]);
        if (h === 0) return 0;
        return (v1 + v2) / (2 * h);
    }
    function avgEAR(landmarks) {
        return (eyeAspectRatio(landmarks.getLeftEye()) +
                eyeAspectRatio(landmarks.getRightEye())) / 2;
    }
    function checkBlink(landmarks) {
        const ear = avgEAR(landmarks);
        // More lenient thresholds
        const CLOSED = 0.24;   // was 0.21
        const OPEN   = 0.26;   // was 0.28

        if (ear < CLOSED) {
            if (!eyesWereClosed) {
                eyesWereClosed = true;
                eyesClosedSince = Date.now();
            }
        } else if (ear > OPEN) {
            if (eyesWereClosed) {
                const closedMs = Date.now() - eyesClosedSince;
                eyesWereClosed = false;
                if (closedMs >= BLINK_MIN_MS && closedMs <= BLINK_MAX_MS) {
                    return true;
                }
            }
        }
        return false;
    }

    // ═══════════════════════════════════════════════════════
    // DETECTION LOOP
    // ═══════════════════════════════════════════════════════
    function startDetection() {
        detectionInterval = setInterval(async () => {
            if (!modelsLoaded || !labeledDescriptors.length) return;
            if (actionInProgress) return;
            if (video.readyState < 2) return;

            if (Date.now() - cameraStartTime > MAX_CAMERA_TIME_MS) {
                setStatus('⏰ Timeout — please try again');
                cancelAction();
                return;
            }

            try {
                const detection = await faceapi
                    .detectSingleFace(video, new faceapi.TinyFaceDetectorOptions({
                        inputSize: 416, scoreThreshold: 0.5,
                    }))
                    .withFaceLandmarks()
                    .withFaceDescriptor();

                if (!detection) {
                    target.classList.remove('detected');
                    setStatus('👤 Please look at the camera');
                    return;
                }

                target.classList.add('detected');

                // ── Liveness ──
                if (!livenessPassed) {
                    const blinked = checkBlink(detection.landmarks);
                    const elapsed = Date.now() - livenessStartTime;
                    const pct = Math.min(100, (elapsed / LIVENESS_TIMEOUT_MS) * 100);
                    if (livenessProgress) livenessProgress.style.width = pct + '%';

                    if (blinked) {
                        livenessPassed = true;
                        livenessOverlay.classList.add('hidden');
                        setStatus('✅ Verified — hold still');
                        console.log('[kiosk] Blink detected');
                    } else {
                        setStatus('👁 Please blink to verify');
                    }
                    return;
                }

                // ── Match ──
                setStatus('👤 Hold still...');
                const matcher = new faceapi.FaceMatcher(labeledDescriptors, 0.6);
                const best = matcher.findBestMatch(detection.descriptor);

                if (best.label === 'unknown') {
                    setStatus('👤 Face not recognized');
                    lastMatch = { id: null, count: 0, timestamp: 0 };
                    return;
                }

                const info = JSON.parse(best.label);
                lastMatch = { id: info.id, count: lastMatch.count + 1, timestamp: Date.now() };
                setStatus(`👤 ${info.name}`);

                if (lastMatch.count >= MIN_CONSECUTIVE_HITS) {
                    target.classList.add('matched');
                    await sendAttendance(info, best.distance, detection.descriptor);
                }
            } catch (e) {
                console.error('[kiosk] Detection error:', e);
            }
        }, MATCH_INTERVAL_MS);
    }

    function stopDetection() {
        if (detectionInterval) {
            clearInterval(detectionInterval);
            detectionInterval = null;
        }
    }

    // ═══════════════════════════════════════════════════════
    // API CALL
    // ═══════════════════════════════════════════════════════
    async function sendAttendance(info, distance, descriptor) {
        if (actionInProgress) return;
        actionInProgress = true;
        stopDetection();

        setStatus('<i class="las la-spinner la-spin"></i> Saving...');

        try {
            const res = await fetch(data.clock_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Kiosk-Client': 'nitohr-kiosk-v1',
                },
                body: JSON.stringify({
                    token:             data.token,
                    employee_id:       info.id,
                    action:            activeAction,
                    confidence:        distance,
                    descriptor:        Array.from(descriptor),
                    liveness_verified: true,
                    fingerprint:       getFingerprint(),
                }),
            });

            const json = await res.json();

            if (!res.ok) {
                beepError();
                showResult('danger', 'la-exclamation-triangle',
                           info.name, json.error || 'Failed', '');
                scheduleReset(8000);
                return;
            }

            // Pick state
            let state = 'info', icon = 'la-check-circle';
            switch (json.action) {
                case 'in':           state='success'; icon='la-check-circle'; beepSuccess(); break;
                case 'out':          state='success'; icon='la-hand-peace';   beepSuccess(); break;
                case 'already_in':   state='info';    icon='la-info-circle';  beep(500,0.2); break;
                case 'already_out':  state='info';    icon='la-info-circle';  beep(500,0.2); break;
                case 'already_done': state='info';    icon='la-check-circle'; beep(500,0.2); break;
                case 'cooldown':     state='info';    icon='la-clock';        beep(500,0.2); break;
                case 'too_soon':     state='warning'; icon='la-hourglass-half'; beepError(); break;
                case 'not_in':       state='warning'; icon='la-exclamation-circle'; beepError(); break;
                default:             state='info';
            }

            showResult(state, icon, json.full_name, json.message, json.time);
            scheduleReset(10000);   // 10 seconds

        } catch (e) {
            console.error('[kiosk] API error:', e);
            beepError();
            showResult('danger', 'la-exclamation-triangle',
                       info.name, 'Server error', '');
            scheduleReset(8000);
        }
    }

    function showResult(state, icon, name, msg, time) {
        stopCamera();
        showPanel(state, icon, name, msg, time);
    }

    function scheduleReset(ms) {
        setTimeout(() => {
            actionInProgress = false;
            activeAction = null;
            resetLiveness();
            lastMatch = { id: null, count: 0, timestamp: 0 };
            showIdle();
        }, ms);
    }

    function resetLiveness() {
        livenessPassed = false;
        eyesWereClosed = false;
        eyesClosedSince = 0;
        livenessStartTime = 0;
        livenessOverlay.classList.remove('hidden');
        livenessProgress.style.width = '0%';
        target.classList.remove('detected', 'matched');
    }

    // ═══════════════════════════════════════════════════════
    // ACTION HANDLERS
    // ═══════════════════════════════════════════════════════
    async function startAction(action) {
        if (actionInProgress) return;
        if (!modelsLoaded || !labeledDescriptors.length) {
            alert('Kiosk not ready. Please wait.');
            return;
        }

        console.log('[kiosk] Action:', action);
        activeAction = action;
        actionInProgress = false;
        cameraStartTime = Date.now();
        resetLiveness();
        livenessStartTime = Date.now();

        showCamera();
        setStatus('<i class="las la-spinner la-spin"></i> Starting camera...');
        beep(600, 0.1);

        const ok = await startCamera();
        if (!ok) {
            beepError();
            showResult('danger', 'la-exclamation-triangle', '',
                       'Camera access denied', '');
            scheduleReset(5000);
            return;
        }

        setStatus('👁 Please blink to verify');
        startDetection();
    }

    function cancelAction() {
        stopDetection();
        stopCamera();
        actionInProgress = false;
        activeAction = null;
        resetLiveness();
        lastMatch = { id: null, count: 0, timestamp: 0 };
        beep(400, 0.1);
        showIdle();
    }

    // ═══════════════════════════════════════════════════════
    // EVENTS
    // ═══════════════════════════════════════════════════════
    // Check In / Check Out / Cancel buttons  ← इन्हें बाहर रखो
    btnIn.addEventListener('click',  () => startAction('in'));
    btnOut.addEventListener('click', () => startAction('out'));
    cancelBtn.addEventListener('click', cancelAction);
    
    
    // OK button on result panel
    document.getElementById('kOkBtn').addEventListener('click', () => {
        
        actionInProgress = false;
        activeAction = null;
        resetLiveness();
        lastMatch = { id: null, count: 0, timestamp: 0 };
        showIdle();
    });

    // ═══════════════════════════════════════════════════════
    // INIT
    // ═══════════════════════════════════════════════════════
    (async function init() {
        console.log('[kiosk] Init');
        clockStatusEl.textContent = 'Loading...';
        await loadModels();
        await loadVectors();
        showIdle();
    })();

})();