/* kiosk.js — face recognition kiosk with smart UX */

(function() {
    'use strict';

    const data = JSON.parse(document.getElementById('kData').textContent);
    const video = document.getElementById('kVideo');
    const canvas = document.getElementById('kCanvas');
    const target = document.getElementById('kTarget');
    const statusEl = document.getElementById('kStatus');
    const panel = document.getElementById('kPanel');
    const panelIcon = document.getElementById('kPanelIcon');
    const panelName = document.getElementById('kPanelName');
    const panelMsg = document.getElementById('kPanelMsg');
    const panelTime = document.getElementById('kPanelTime');
    const countEl = document.getElementById('kCount');
    const clockStatusEl = document.getElementById('kClockStatus');
    const clockEl = document.getElementById('kClock');
    const livenessOverlay = document.getElementById('kLiveness');
    const livenessProgress = document.getElementById('kLivenessProgress');

    let employees = [];
    let labeledDescriptors = [];
    let modelsLoaded = false;
    let busy = false;

    // ── Liveness state ──
    let livenessPassed = false;
    let eyesWereClosed = false;
    let eyesClosedSince = 0;
    let livenessStartTime = Date.now();
    const LIVENESS_TIMEOUT_MS = 15000;   // reset if no blink in 15s
    const LIVENESS_MAX_WAIT_MS = 20000;  // give up after 20s total
    const BLINK_MIN_MS = 50;             // eyes must be closed at least 50ms
    const BLINK_MAX_MS = 600;            // but not longer than 600ms

    const MATCH_INTERVAL_MS = 500;
    const COOLDOWN_AFTER_MATCH_MS = 4000;
    const MIN_CONSECUTIVE_HITS = 2;
    let lastMatch = { id: null, count: 0, timestamp: 0 };

    // Live clock
    setInterval(() => {
        const now = new Date();
        clockEl.textContent = now.toLocaleTimeString('en-IN', { hour12: false });
    }, 1000);

    function setStatus(msg, type) {
        statusEl.innerHTML = msg;
        statusEl.className = 'k-status';
    }

    function showPanel(state, icon, name, msg, time) {
        panel.className = 'k-panel state-' + state + ' show';
        panelIcon.innerHTML = '<i class="las ' + icon + '"></i>';
        panelName.textContent = name || '';
        panelMsg.textContent = msg || '';
        if (time) {
            panelTime.textContent = time;
            panelTime.style.display = 'inline-block';
        } else {
            panelTime.style.display = 'none';
        }

        // Remove dark backdrop during success/info (show clean full-color panel)
        if (state === 'success' || state === 'info') {
            document.querySelector('.k-video-wrap').classList.add('cleared');
        }
    }

    function hidePanel() {
        panel.classList.remove('show');
        // Bring back dark backdrop for next scan
        document.querySelector('.k-video-wrap').classList.remove('cleared');
    }

    async function loadModels() {
        const base = data.static_base + '/models';
        try {
            await faceapi.nets.tinyFaceDetector.loadFromUri(base);
            await faceapi.nets.faceLandmark68Net.loadFromUri(base);
            await faceapi.nets.faceRecognitionNet.loadFromUri(base);
            modelsLoaded = true;
            clockStatusEl.textContent = 'Models ready';
        } catch (e) {
            console.error('Model load failed:', e);
            setStatus('❌ Model load failed');
        }
    }

    async function startCamera() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { width: 1280, height: 720, facingMode: 'user' }
            });
            video.srcObject = stream;
        } catch (e) {
            console.error('Camera error:', e);
            setStatus('❌ Camera denied');
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

            clockStatusEl.textContent = `${employees.length} employee${employees.length === 1 ? '' : 's'}`;
        } catch (e) {
            console.error('Load vectors failed:', e);
            clockStatusEl.textContent = 'Load failed';
        }
    }

    function startDetection() {
        setInterval(async () => {
            if (!modelsLoaded || !labeledDescriptors.length || busy) return;
            if (video.readyState < 2) return;

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
                    lastMatch = { id: null, count: 0, timestamp: 0 };
                    return;
                }

                target.classList.add('detected');

                const matcher = new faceapi.FaceMatcher(labeledDescriptors, 0.6);
                const best = matcher.findBestMatch(detection.descriptor);

                if (best.label === 'unknown') {
                    setStatus('👤 Face not recognized');
                    lastMatch = { id: null, count: 0, timestamp: 0 };
                    return;
                }

                const info = JSON.parse(best.label);
                const same = lastMatch.id === info.id;
                lastMatch = {
                    id: info.id,
                    count: same ? lastMatch.count + 1 : 1,
                    timestamp: Date.now(),
                };

                setStatus(`👤 ${info.name} — hold still`);

                if (lastMatch.count >= MIN_CONSECUTIVE_HITS) {
                    target.classList.add('matched');
                    await handleMatch(info, best.distance, detection.descriptor);
                }
            } catch (e) {
                console.error('Detection error:', e);
            }
        }, MATCH_INTERVAL_MS);
    }

    async function handleMatch(info, distance, descriptor) {
        if (busy) return;
        busy = true;

        try {
            const res = await fetch(data.clock_url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    token:       data.token,
                    employee_id: info.id,
                    action:      'auto',
                    confidence:  distance,
                    descriptor:  Array.from(descriptor),
                    liveness_verified: true,
                }),
            });

            const json = await res.json();

            if (!res.ok) {
                showPanel('warning', '⚠', info.name, json.error || 'Failed', '');
                setTimeout(() => { hidePanel(); reset(); }, 3000);
                return;
            }

            // Determine panel style based on response
            let type = 'info';
            let icon = '✓';
            let msg = json.message;

            switch (json.action) {
                case 'in':
                    type = 'success'; icon = '✓';
                    break;
                case 'out':
                    type = 'info'; icon = '👋';
                    break;
                case 'already_done':
                    type = 'info'; icon = '✓';
                    break;
                case 'cooldown':
                    type = 'info'; icon = '✓';
                    break;
                case 'too_soon':
                    type = 'warning'; icon = '⏳';
                    break;
                default:
                    type = 'info';
            }

            showPanel(type, icon, json.full_name, msg, json.time);

            setTimeout(() => {
                hidePanel();
                reset();
            }, COOLDOWN_AFTER_MATCH_MS);

        } catch (e) {
            console.error('Clock API error:', e);
            showPanel('warning', '⚠', info.name, 'Server error', '');
            setTimeout(() => { hidePanel(); reset(); }, 3000);
        }
    }


    // ─── Eye Aspect Ratio (EAR) — higher = open, lower = closed ───
    function distance(p1, p2) {
        return Math.hypot(p1.x - p2.x, p1.y - p2.y);
    }

    function eyeAspectRatio(eyePoints) {
        // eyePoints = array of 6 {x, y}
        const v1 = distance(eyePoints[1], eyePoints[5]);
        const v2 = distance(eyePoints[2], eyePoints[4]);
        const h  = distance(eyePoints[0], eyePoints[3]);
        if (h === 0) return 0;
        return (v1 + v2) / (2 * h);
    }

    function avgEAR(landmarks) {
        const leftEye  = landmarks.getLeftEye();
        const rightEye = landmarks.getRightEye();
        return (eyeAspectRatio(leftEye) + eyeAspectRatio(rightEye)) / 2;
    }

    // ─── Blink detection ───
    function checkBlink(landmarks) {
        const ear = avgEAR(landmarks);

        // Thresholds — tune if needed
        const CLOSED_THRESHOLD = 0.21;
        const OPEN_THRESHOLD   = 0.28;

        if (ear < CLOSED_THRESHOLD) {
            if (!eyesWereClosed) {
                eyesWereClosed = true;
                eyesClosedSince = Date.now();
            }
        } else if (ear > OPEN_THRESHOLD) {
            if (eyesWereClosed) {
                const closedMs = Date.now() - eyesClosedSince;
                eyesWereClosed = false;
                if (closedMs >= BLINK_MIN_MS && closedMs <= BLINK_MAX_MS) {
                    return true;   // valid blink!
                }
            }
        }
        return false;
    }


    function reset() {
        target.classList.remove('matched');
        lastMatch = { id: null, count: 0, timestamp: 0 };
        busy = false;
        document.querySelector('.k-video-wrap').classList.remove('cleared');

        // Reset liveness for the next employee
        livenessPassed = false;
        eyesWereClosed = false;
        eyesClosedSince = 0;
        livenessStartTime = Date.now();
        if (livenessOverlay) livenessOverlay.classList.remove('hidden');
        if (livenessProgress) livenessProgress.style.width = '0%';

        setStatus('👁 Please blink to verify');
    }

    (async function init() {
        await loadModels();
        await startCamera();
        await loadVectors();
        startDetection();
        livenessStartTime = Date.now();
        setStatus('👁 Please blink to verify');
    })();

})();