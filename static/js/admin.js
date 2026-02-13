document.addEventListener('DOMContentLoaded', function () {
    // ================= STATE =================
    let activeSection = 'overview';
    let activeCameraId = 0;

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

    // ================= NAVIGATION =================
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const target = item.getAttribute('data-target');
            switchSection(target);
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
            /*
            if (sectionId === 'inspection') {
                await populateCameraSelector();
                startFeed(activeCameraId);
            } else {
                stopFeed();
            }
            */
        }
    }

    // Camera Feed and Selector Logic Disabled
    /*
    function startFeed(cameraId) { ... }
    function stopFeed() { ... }
    async function populateCameraSelector() { ... }
    if (cameraSelect) { ... }
    */

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
                const isPass = scan.status === 'PASS' || scan.status === 'PERFECT';
                const statusColor = isPass ? 'var(--success-color)' : 'var(--danger-color)';
                const icon = isPass ? 'fa-check-circle' : 'fa-triangle-exclamation';

                return `
                <div class="tech-list-item">
                    <div class="tech-item-info">
                        <div class="tech-item-main">
                            <i class="fa-solid ${icon}" style="color: ${statusColor}"></i>
                            <span style="color: ${statusColor}; font-weight: 700;">${isPass ? 'PASS' : 'FAIL'}</span>
                        </div>
                        <div class="tech-item-time">
                            ${new Date(scan.timestamp).toLocaleTimeString()} | ${scan.matched_part || 'UNIDENTIFIED'}
                        </div>
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

    // Capture and Scan Logic Disabled
    /*
    window.captureAndScan = async function () { ... };
    */

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
        if (result.error) {
            mainScanResultBox.innerHTML = `<div class="error-msg"><i class="fa-solid fa-circle-exclamation"></i> ${result.error}</div>`;
            return;
        }

        const isPass = result.status === 'PASS' || result.status === 'PERFECT';
        const timing = result.timing ? `${result.timing.total_ms}ms` : '';

        mainScanResultBox.innerHTML = `
            <div class="tech-result-header ${isPass ? 'pass' : 'fail'}">
                <i class="fa-solid ${isPass ? 'fa-check-circle' : 'fa-triangle-exclamation'}"></i>
                <span style="color: ${isPass ? '#0ca678' : '#fa5252'}; font-weight: 800;">${isPass ? 'PASS' : 'FAIL'}</span>
                ${timing ? `<span style="font-size: 0.7rem; color: #adb5bd; margin-left: auto;">${timing}</span>` : ''}
            </div>
            <div class="tech-result-grid">
                <div>
                    <span class="tech-metric-label">IDENTIFIED OBJECT</span>
                    <span class="tech-metric-value">${result.matched_part || 'UNKNOWN'}</span>
                </div>
            </div>
        `;
        updateStats();
    }

    // ================= TAB SWITCHING =================
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('tech-tab')) {
            const btn = e.target;
            const parent = btn.parentElement;
            parent.querySelectorAll('.tech-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const section = btn.closest('.content-section, .cv-panel');
            section.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(`tab-${btn.getAttribute('data-tab')}`).classList.add('active');
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
        saveTemplateBtn.classList.toggle('hidden', selectedTemplateFiles.length < 3);
    }

    window.removeTemplateFile = function (idx) {
        selectedTemplateFiles.splice(idx, 1);
        updateTemplatePreview();
    };

    if (saveTemplateBtn) {
        saveTemplateBtn.addEventListener('click', async () => {
            const name = prompt("Enter template name (e.g., 'Crankshaft V8'):");
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

    // Camera Management Logic Disabled
    /*
    window.openAddCameraModal = function () { ... }
    window.closeAddCameraModal = function () { ... }
    window.testNewCameraConnection = async function () { ... }
    window.saveNewCamera = async function () { ... }
    async function loadCameras() { ... }
    window.toggleCamera = async function (id, activate) { ... }
    window.deleteCamera = async function (id) { ... }
    */

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