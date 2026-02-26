document.addEventListener('DOMContentLoaded', function () {
    // ================= STATE =================
    let activeSection = 'overview';
    let activeCameraId = null;
    let currentStream = null;

    // ================= ELEMENTS =================
    const totalScansEl = document.getElementById('total-scans');
    const passCountEl = document.getElementById('pass-count');
    const failCountEl = document.getElementById('fail-count');
    const recentHistoryList = document.getElementById('recent-history-list');
    const feedImg = document.getElementById('main-inspection-feed');
    const cameraSelect = document.getElementById('inspection-camera-select');
    const cameraStatusIndicator = document.getElementById('camera-status-indicator');
    const mainUploadBtn = document.getElementById('main-upload-btn');
    const mainFileInput = document.getElementById('main-file-upload');
    const mainScanResultBox = document.getElementById('main-scan-result');
    const btnStartInspection = document.getElementById('btn-start-inspection');

    // ================= NAVIGATION =================
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const target = item.getAttribute('data-target');
            switchSection(target);

            // Close sidebar on mobile after click
            if (window.innerWidth <= 992) {
                sidebar.classList.remove('open');
            }
        });
    });

    async function switchSection(sectionId) {
        document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));

        const targetSection = document.getElementById(`${sectionId}-section`);
        if (targetSection) {
            targetSection.classList.add('active');
            const activeNav = document.querySelector(`.nav-item[data-target="${sectionId}"]`);
            if (activeNav) activeNav.classList.add('active');
            document.getElementById('current-page').textContent =
                sectionId.charAt(0).toUpperCase() + sectionId.slice(1);
            activeSection = sectionId;

            // Section-specific data loading
            if (sectionId === 'overview') updateStats();
            if (sectionId === 'templates') loadTemplates();
            if (sectionId === 'camera') loadCameras();
            if (sectionId === 'history') loadHistory();

            // Camera feed management
            if (sectionId === 'inspection') {
                // Check which tab is active within inspection
                const activeTab = document.querySelector('.tech-tab.active');
                if (activeTab && activeTab.getAttribute('data-tab') === 'webcam-main') {
                    await loadCameras(); // Load and start feed
                }
            } else {
                stopFeed();
            }
        }
    }

    // ================= CAMERA LOGIC =================

    async function loadCameras() {
        if (!cameraSelect) return;

        try {
            cameraSelect.innerHTML = '<option value="">Searching...</option>';

            // Explicitly request permissions first to get device labels
            try {
                const tempStream = await navigator.mediaDevices.getUserMedia({ video: true });
                tempStream.getTracks().forEach(track => track.stop());
            } catch (e) {
                console.warn("Permission denied or no camera found:", e);
            }

            const devices = await navigator.mediaDevices.enumerateDevices();
            const videoDevices = devices.filter(device => device.kind === 'videoinput');

            cameraSelect.innerHTML = '';

            if (videoDevices.length === 0) {
                cameraSelect.innerHTML = '<option value="">No cameras found</option>';
                return;
            }

            videoDevices.forEach((device, index) => {
                const option = document.createElement('option');
                option.value = device.deviceId;
                option.textContent = device.label || `Camera ${index + 1}`;
                cameraSelect.appendChild(option);
            });

            // Set active camera or default to first
            if (activeCameraId === null && videoDevices.length > 0) {
                activeCameraId = videoDevices[0].deviceId;
            }

            cameraSelect.value = activeCameraId;
            startFeed(activeCameraId);

        } catch (error) {
            console.error('Error loading cameras:', error);
            cameraSelect.innerHTML = '<option value="">Error accessing camera</option>';
        }
    }

    async function startFeed(deviceId) {
        if (!feedImg) return;

        stopFeed(); // Clean up existing stream

        activeCameraId = deviceId;
        const constraints = {
            video: {
                deviceId: deviceId ? { exact: deviceId } : undefined,
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        };

        try {
            currentStream = await navigator.mediaDevices.getUserMedia(constraints);
            feedImg.srcObject = currentStream;

            if (cameraStatusIndicator) {
                cameraStatusIndicator.innerHTML = '<i class="fa-solid fa-circle fa-beat" style="color: var(--success-color);"></i> LIVE';
                cameraStatusIndicator.style.borderColor = 'var(--success-color)';
                cameraStatusIndicator.style.color = 'var(--success-color)';
            }
        } catch (error) {
            console.error('Error starting video stream:', error);
            if (cameraStatusIndicator) {
                cameraStatusIndicator.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i> ERROR';
                cameraStatusIndicator.style.borderColor = 'var(--danger-color)';
                cameraStatusIndicator.style.color = 'var(--danger-color)';
            }
        }
    }

    function stopFeed() {
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
        if (feedImg) {
            feedImg.srcObject = null;
        }
        if (cameraStatusIndicator) {
            cameraStatusIndicator.innerHTML = '<i class="fa-solid fa-power-off"></i> OFFLINE';
            cameraStatusIndicator.style.borderColor = '#6c757d';
            cameraStatusIndicator.style.color = '#6c757d';
        }
    }

    // Handle Camera Selection Change
    if (cameraSelect) {
        cameraSelect.addEventListener('change', (e) => {
            const newId = e.target.value;
            if (newId !== "") {
                startFeed(newId);
            }
        });
    }

    // Capture & Scan Function
    window.captureAndScan = async function () {
        if (!btnStartInspection || !feedImg) return;

        const canvas = document.getElementById('capture-canvas');
        if (!canvas) return;

        const originalText = btnStartInspection.innerHTML;
        btnStartInspection.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Analyzing...';
        btnStartInspection.disabled = true;

        // Show loading state in result box
        mainScanResultBox.classList.remove('hidden');
        mainScanResultBox.innerHTML = '<div class="loading-spinner-tech"><i class="fa-solid fa-circle-notch fa-spin"></i> Analyzing captured frame...</div>';

        try {
            // Setup canvas dimensions to match video
            canvas.width = feedImg.videoWidth;
            canvas.height = feedImg.videoHeight;

            // Draw current video frame to canvas
            const ctx = canvas.getContext('2d');
            ctx.drawImage(feedImg, 0, 0, canvas.width, canvas.height);

            // Convert canvas to Blob
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.95));

            // Prepare FormData
            const formData = new FormData();
            formData.append('file', blob, 'capture.jpg');

            // Send to existing /api/scan endpoint
            const response = await fetch('/api/scan', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            showScanResult(result);

        } catch (error) {
            console.error('Capture/Analysis error:', error);
            mainScanResultBox.innerHTML = '<div class="error-msg"><i class="fa-solid fa-circle-exclamation"></i> Analysis failed. Check camera and try again.</div>';
        } finally {
            btnStartInspection.innerHTML = originalText;
            btnStartInspection.disabled = false;
        }
    };

    // ================= STATS & OVERVIEW =================
    async function updateStats() {
        try {
            const response = await fetch('/api/stats');
            const data = await response.json();
            totalScansEl.textContent = data.total_scans;
            if (passCountEl) passCountEl.textContent = data.pass_count;
            if (failCountEl) failCountEl.textContent = data.fail_count;
            loadRecentHistory();
        } catch (error) {
            console.error('Error updating stats:', error);
        }
    }

    async function loadRecentHistory() {
        try {
            const response = await fetch('/api/history/recent');
            const data = await response.json();

            if (data.length === 0) {
                recentHistoryList.innerHTML = '<div class="empty-state-tech">No recent detections.</div>';
                return;
            }

            recentHistoryList.innerHTML = data.map(scan => {
                const status = scan.status === 'PASS' || scan.status === 'PERFECT' ? 'PASS'
                    : (scan.status === 'UNKNOWN' || scan.matched_part === 'UNKNOWN') ? 'UNKNOWN'
                        : 'FAIL';
                const colorMap = { PASS: 'var(--success-color)', FAIL: 'var(--danger-color)', UNKNOWN: '#f59f00' };
                const iconMap = { PASS: 'fa-check-circle', FAIL: 'fa-triangle-exclamation', UNKNOWN: 'fa-question-circle' };

                return `
                <div class="tech-list-item">
                    <div class="tech-item-info">
                        <div class="tech-item-main">
                            <i class="fa-solid ${iconMap[status]}" style="color: ${colorMap[status]}"></i>
                            <span style="color: ${colorMap[status]}; font-weight: 700;">${status}</span>
                        </div>
                        <div class="tech-item-time">${new Date(scan.timestamp).toLocaleTimeString()}</div>
                    </div>
                </div>
            `}).join('');
        } catch (error) {
            console.error('Error loading recent history:', error);
        }
    }

    // Initial load
    updateStats();

    // Auto-start if landed on inspection
    const currentActiveNav = document.querySelector('.nav-item.active');
    if (currentActiveNav && currentActiveNav.getAttribute('data-target') === 'inspection') {
        switchSection('inspection');
    }



    // ================= INSPECTION: UPLOAD & SCAN =================
    if (mainFileInput) {
        mainFileInput.onchange = (e) => {
            const file = e.target.files[0];
            document.getElementById('main-file-name').textContent = file ? file.name : 'No file selected';
            mainUploadBtn.disabled = !file;
        };
    }

    if (mainUploadBtn) {
        mainUploadBtn.onclick = async () => {
            const file = mainFileInput.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            mainScanResultBox.classList.remove('hidden');
            mainScanResultBox.innerHTML = '<div class="loading-spinner-tech"><i class="fa-solid fa-circle-notch fa-spin"></i> Analyzing image...</div>';
            mainUploadBtn.disabled = true;

            try {
                const response = await fetch('/api/scan', {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();
                showScanResult(result);
            } catch (error) {
                mainScanResultBox.innerHTML = '<div class="error-msg"><i class="fa-solid fa-circle-exclamation"></i> Analysis failed.</div>';
            } finally {
                mainUploadBtn.disabled = false;
            }
        };
    }

    // ================= SCAN RESULT DISPLAY =================
    function showScanResult(result) {
        if (result.error || result.detail) {
            mainScanResultBox.innerHTML = `<div class="error-msg"><i class="fa-solid fa-circle-exclamation"></i> ${result.error || result.detail}</div>`;
            return;
        }

        const status = result.status === 'PASS' || result.status === 'PERFECT' ? 'PASS'
            : result.status === 'UNKNOWN' || (result.matched_part === 'UNKNOWN') ? 'UNKNOWN'
                : 'FAIL';
        const colorMap = { PASS: '#0ca678', FAIL: '#fa5252', UNKNOWN: '#f59f00' };
        const iconMap = { PASS: 'fa-check-circle', FAIL: 'fa-triangle-exclamation', UNKNOWN: 'fa-question-circle' };
        const bgMap = { PASS: 'rgba(12,166,120,0.08)', FAIL: 'rgba(250,82,82,0.08)', UNKNOWN: 'rgba(245,159,0,0.08)' };

        const confidence = result.confidence != null ? (result.confidence * 100).toFixed(1) : null;
        const matchedPart = result.matched_part || '—';

        let visHtml = '';
        if (result.visualization) {
            visHtml = `
                <div style="margin-top: 12px; border-radius: 8px; overflow: hidden; border: 1px solid rgba(255,255,255,0.06);">
                    <img src="data:image/png;base64,${result.visualization}" 
                         style="width: 100%; display: block;" alt="AI Visualization">
                </div>`;
        }

        mainScanResultBox.innerHTML = `
            <div style="background: ${bgMap[status]}; border: 1px solid ${colorMap[status]}30; border-radius: 12px; padding: 20px;">
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 14px;">
                    <i class="fa-solid ${iconMap[status]}" style="font-size: 28px; color: ${colorMap[status]};"></i>
                    <span style="color: ${colorMap[status]}; font-weight: 800; font-size: 22px;">${status}</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                    ${confidence !== null ? `
                    <div style="background: rgba(0,0,0,0.15); border-radius: 8px; padding: 12px;">
                        <div style="font-size: 11px; text-transform: uppercase; opacity: 0.6; margin-bottom: 4px;">Confidence</div>
                        <div style="font-size: 20px; font-weight: 700; color: ${colorMap[status]};">${confidence}%</div>
                        <div style="height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; margin-top: 6px;">
                            <div style="height: 100%; width: ${Math.min(confidence, 100)}%; background: ${colorMap[status]}; border-radius: 2px;"></div>
                        </div>
                    </div>` : ''}
                    <div style="background: rgba(0,0,0,0.15); border-radius: 8px; padding: 12px;">
                        <div style="font-size: 11px; text-transform: uppercase; opacity: 0.6; margin-bottom: 4px;">Matched Class</div>
                        <div style="font-size: 18px; font-weight: 600;">${matchedPart}</div>
                    </div>
                </div>
                ${visHtml}
            </div>
        `;
        updateStats();
    }

    // ================= TAB SWITCHING =================
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('tech-tab')) {
            const btn = e.target;
            const parent = btn.parentElement;
            const tabId = btn.getAttribute('data-tab');

            parent.querySelectorAll('.tech-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const section = btn.closest('.content-section, .cv-panel');
            section.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(`tab-${tabId}`).classList.add('active');

            // Handle Camera Feed on Tab Switch
            if (tabId === 'webcam-main') {
                loadCameras();
            } else {
                stopFeed();
            }
        }
    });

    // ================= TEMPLATE MANAGEMENT =================
    window.openTemplateWizard = function () {
        document.getElementById('template-list-view').classList.add('hidden');
        document.getElementById('template-wizard-view').classList.remove('hidden');
    };

    window.closeTemplateWizard = function () {
        document.getElementById('template-list-view').classList.remove('hidden');
        document.getElementById('template-wizard-view').classList.add('hidden');
        resetTemplateWizard();
    };

    // Toggle Custom Class Input
    const classRadios = document.querySelectorAll('input[name="template-class"]');
    const customClassWrapper = document.getElementById('custom-class-input-wrapper');
    const customClassInput = document.getElementById('custom-class-name');

    classRadios.forEach(radio => {
        radio.addEventListener('change', () => {
            customClassWrapper.classList.toggle('hidden', radio.value !== 'Custom');
            if (radio.value === 'Custom') customClassInput.focus();
        });
    });

    const templateUploadZone = document.getElementById('template-upload-zone');
    const templateFileInput = document.getElementById('template-files');
    const templatePreviewList = document.getElementById('template-preview-list');
    const saveTemplateBtn = document.getElementById('save-template-btn');
    let selectedTemplateFiles = [];

    if (templateUploadZone) templateUploadZone.addEventListener('click', () => templateFileInput.click());
    if (templateFileInput) templateFileInput.addEventListener('change', handleTemplateFiles);

    function handleTemplateFiles(e) {
        const files = Array.from(e.target.files);
        selectedTemplateFiles = [...selectedTemplateFiles, ...files].slice(0, 10);
        updateTemplatePreview();
    }

    function updateTemplatePreview() {
        templatePreviewList.innerHTML = selectedTemplateFiles.map((file, idx) => `
            <div class="preview-card">
                <img src="${URL.createObjectURL(file)}">
                <button onclick="removeTemplateFile(${idx})">&times;</button>
            </div>
        `).join('');
        saveTemplateBtn.classList.toggle('hidden', selectedTemplateFiles.length < 1);
    }

    window.removeTemplateFile = function (idx) {
        selectedTemplateFiles.splice(idx, 1);
        updateTemplatePreview();
    };

    if (saveTemplateBtn) {
        saveTemplateBtn.addEventListener('click', async () => {
            const selectedRadio = document.querySelector('input[name="template-class"]:checked');
            let name = selectedRadio.value;

            if (name === 'Custom') {
                name = customClassInput.value.trim();
                if (!name) {
                    alert("Please enter a custom class name.");
                    customClassInput.focus();
                    return;
                }
            }

            if (!name) return;

            const formData = new FormData();
            selectedTemplateFiles.forEach(file => formData.append('files', file));

            saveTemplateBtn.disabled = true;
            saveTemplateBtn.textContent = 'Saving...';

            try {
                const response = await fetch(`/api/templates?name=${encodeURIComponent(name)}`, {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();
                if (result.id) {
                    alert('Template saved successfully!');
                    closeTemplateWizard();
                    loadTemplates();
                } else {
                    alert('Error: ' + (result.detail || 'Unknown error'));
                }
            } catch (error) {
                alert('Upload failed.');
                console.error(error);
            } finally {
                saveTemplateBtn.disabled = false;
                saveTemplateBtn.innerHTML = '<i class="fa-solid fa-database"></i> Commit Model';
            }
        });
    }

    function resetTemplateWizard() {
        selectedTemplateFiles = [];
        updateTemplatePreview();
        if (templateFileInput) templateFileInput.value = '';
    }

    async function loadTemplates() {
        try {
            const container = document.getElementById('registered-templates-container');
            container.innerHTML = '<div class="loading-tech"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading...</div>';
            const response = await fetch('/api/templates');
            const data = await response.json();

            if (data.length === 0) {
                container.innerHTML = '<div class="empty-state-tech">No templates registered yet.</div>';
                return;
            }

            container.innerHTML = data.map(t => `
                <div class="template-card">
                    <div class="template-icon"><i class="fa-solid fa-layer-group"></i></div>
                    <div class="template-details">
                        <h4>${t.name}</h4>
                        <p>${t.image_count} reference images</p>
                        <small>Created: ${new Date(t.created_at).toLocaleDateString()}</small>
                    </div>
                    <button class="btn-icon delete" onclick="deleteTemplate(${t.id})">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            `).join('');
        } catch (error) {
            console.error('Error loading templates:', error);
        }
    }

    window.deleteTemplate = async function (id) {
        if (!confirm('Delete this template?')) return;
        try {
            await fetch(`/api/templates/${id}`, { method: 'DELETE' });
            loadTemplates();
        } catch (error) {
            console.error('Error deleting template:', error);
        }
    };



    // ================= HISTORY =================
    async function loadHistory() {
        try {
            const tbody = document.getElementById('history-table-body');
            const response = await fetch('/api/history');
            const data = await response.json();

            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:#6c757d;">No inspection records found.</td></tr>';
                return;
            }

            tbody.innerHTML = data.map(h => {
                const status = (h.status === 'PASS' || h.status === 'PERFECT') ? 'PASS' : 'FAIL';
                const statusClass = status.toLowerCase();
                return `
                <tr>
                    <td class="mono-text">#${h.id.toString().padStart(4, '0')}</td>
                    <td>${new Date(h.timestamp).toLocaleString(undefined, {
                    year: 'numeric', month: 'short', day: 'numeric',
                    hour: '2-digit', minute: '2-digit'
                })}</td>
                    <td><span class="status-badge-tech ${statusClass}">${status}</span></td>
                </tr>
            `;
            }).join('');
        } catch (error) {
            console.error(error);
        }
    }

    window.exportHistory = function () {
        window.location.href = '/api/export/history';
    };

    // ================= MOBILE MENU =================
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const sidebar = document.getElementById('sidebar');
    if (mobileMenuBtn && sidebar) {
        mobileMenuBtn.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }
});
