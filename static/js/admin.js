document.addEventListener('DOMContentLoaded', function () {
    // Current Active Section
    let activeSection = 'overview';

    // Stats elements
    const totalScansEl = document.getElementById('total-scans');
    const perfectCountEl = document.getElementById('perfect-count');
    const defectedCountEl = document.getElementById('defected-count');
    const recentHistoryList = document.getElementById('recent-history-list');

    // Navigation
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const target = item.getAttribute('data-target');
            switchSection(target);
        });
    });

    function switchSection(sectionId) {
        document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));

        const targetSection = document.getElementById(`${sectionId}-section`);
        if (targetSection) {
            targetSection.classList.add('active');
            const activeNav = document.querySelector(`.nav-item[data-target="${sectionId}"]`);
            if (activeNav) activeNav.classList.add('active');
            document.getElementById('current-page').textContent = sectionId.charAt(0).toUpperCase() + sectionId.slice(1);
            activeSection = sectionId;

            // Trigger data refresh based on section
            if (sectionId === 'overview') updateStats();
            if (sectionId === 'templates') loadTemplates();
            if (sectionId === 'camera') loadCameras();
            if (sectionId === 'history') loadHistory();
        }
    }

    // Initial load
    updateStats();

    // ================= STATS & OVERVIEW =================
    async function updateStats() {
        try {
            const response = await fetch('/api/stats');
            const data = await response.json();
            totalScansEl.textContent = data.total_scans;
            perfectCountEl.textContent = data.perfect_count;
            defectedCountEl.textContent = data.defected_count;

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
                recentHistoryList.innerHTML = '<div class="empty-state-tech">System IDLE. No recent detections.</div>';
                return;
            }

            recentHistoryList.innerHTML = data.map(scan => {
                const statusColor = scan.status === 'PERFECT' ? 'var(--success-color)' : 'var(--danger-color)';
                const icon = scan.status === 'PERFECT' ? 'fa-check-circle' : 'fa-triangle-exclamation';

                return `
                <div class="tech-list-item">
                    <div class="tech-item-info">
                        <div class="tech-item-main">
                            <i class="fa-solid ${icon}" style="color: ${statusColor}"></i>
                            ${scan.status}
                        </div>
                        <div class="tech-item-time">
                            ${new Date(scan.timestamp).toLocaleTimeString()} | ID: #${scan.matched_part || 'UNIDENTIFIED'}
                        </div>
                    </div>
                    <div class="tech-item-meta">
                        <span class="tech-conf">${Math.round(scan.confidence * 100)}%</span>
                        <span class="tech-conf-label">CONFIDENCE</span>
                    </div>
                </div>
            `}).join('');
        } catch (error) {
            console.error('Error loading recent history:', error);
        }
    }

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

    templateUploadZone.addEventListener('click', () => templateFileInput.click());
    templateFileInput.addEventListener('change', handleTemplateFiles);

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

    saveTemplateBtn.addEventListener('click', async () => {
        const name = prompt("Enter template name (e.g., 'Crankshaft V8'):");
        if (!name) return;

        const formData = new FormData();
        selectedTemplateFiles.forEach(file => formData.append('files', file));

        saveTemplateBtn.disabled = true;
        saveTemplateBtn.textContent = "Saving...";

        try {
            const response = await fetch(`/api/templates?name=${encodeURIComponent(name)}`, {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            if (result.id) {
                alert("Template saved successfully!");
                closeTemplateWizard();
                loadTemplates();
            } else {
                alert("Error saving template: " + (result.detail || "Unknown error"));
            }
        } catch (error) {
            alert("Upload failed. Check console for details.");
            console.error(error);
        } finally {
            saveTemplateBtn.disabled = false;
            saveTemplateBtn.textContent = "Save Reference Model";
        }
    });

    function resetTemplateWizard() {
        selectedTemplateFiles = [];
        updateTemplatePreview();
        templateFileInput.value = '';
    }

    async function loadTemplates() {
        try {
            const container = document.getElementById('registered-templates-container');
            container.innerHTML = 'Loading...';
            const response = await fetch('/api/templates');
            const data = await response.json();

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
        if (!confirm("Delete this template?")) return;
        try {
            await fetch(`/api/templates/${id}`, { method: 'DELETE' });
            loadTemplates();
        } catch (error) {
            console.error('Error deleting template:', error);
        }
    };

    // ================= CAMERA MANAGEMENT =================
    window.openAddCameraModal = function () {
        document.getElementById('add-camera-modal').style.display = 'block';
    };

    window.closeAddCameraModal = function () {
        document.getElementById('add-camera-modal').style.display = 'none';
    };

    window.testNewCameraConnection = async function () {
        const url = document.getElementById('new-camera-url').value;
        if (!url) return alert("Enter URL first");

        try {
            const response = await fetch(`/api/cameras/test?url=${encodeURIComponent(url)}`, { method: 'POST' });
            const result = await response.json();
            alert(result.success ? "Connection Successful!" : "Connection Failed: " + result.error);
        } catch (error) {
            alert("Test request failed.");
        }
    };

    window.saveNewCamera = async function () {
        const name = document.getElementById('new-camera-name').value;
        const type = document.getElementById('new-camera-type').value;
        const url = document.getElementById('new-camera-url').value;

        try {
            const response = await fetch('/api/cameras', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, camera_type: type, url })
            });
            const data = await response.json();
            if (data.id) {
                closeAddCameraModal();
                loadCameras();
            }
        } catch (error) {
            console.error(error);
        }
    };

    async function loadCameras() {
        try {
            const container = document.getElementById('camera-list-container');
            const response = await fetch('/api/cameras');
            const data = await response.json();

            container.innerHTML = data.map(c => `
                <div class="camera-card-tech ${c.is_active ? 'active' : 'inactive'}">
                    <div class="cam-header">
                        <span class="cam-id">CAM-${c.id.toString().padStart(2, '0')}</span>
                        <span class="cam-status ${c.is_active ? 'on' : 'off'}">
                             <i class="fa-solid fa-circle"></i> ${c.is_active ? 'ONLINE' : 'OFFLINE'}
                        </span>
                    </div>
                    <div class="camera-preview-tech">
                        <div class="scan-overlay"></div>
                        <img src="/api/video_feed?camera_id=${c.id}" alt="Preview" onerror="this.style.display='none'">
                        <div class="no-signal">NO SIGNAL</div>
                    </div>
                    <div class="cam-info-tech">
                        <h4>${c.name}</h4>
                        <div class="cam-meta">${c.camera_type.toUpperCase()} :: ${c.url}</div>
                    </div>
                    <div class="cam-actions-tech">
                        <button class="btn-tech-sm" onclick="toggleCamera(${c.id}, ${!c.is_active})">
                           ${c.is_active ? '<i class="fa-solid fa-power-off"></i> DEACTIVATE' : '<i class="fa-solid fa-power-off"></i> ACTIVATE'}
                        </button>
                        <button class="btn-tech-sm danger" onclick="deleteCamera(${c.id})">
                             <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (error) {
            console.error('Error loading cameras:', error);
            document.getElementById('camera-list-container').innerHTML = '<div class="error-msg">Failed to load camera feeds</div>';
        }
    }

    window.deleteCamera = async function (id) {
        if (!confirm("Remove this camera?")) return;
        try {
            await fetch(`/api/cameras/${id}`, { method: 'DELETE' });
            loadCameras();
        } catch (error) {
            console.error(error);
        }
    };

    // ================= QUICK SCAN MODAL =================
    // ================= SCAN MODAL TECH =================
    const scanModal = document.getElementById('scan-modal');
    const openScanBtn = document.getElementById('open-scan-modal');
    // Updated selector for the new close button class
    const closeScanBtn = document.querySelector('.close-modal-tech');
    const uploadBtn = document.getElementById('modal-upload-btn');
    const fileInput = document.getElementById('modal-file-upload');
    const scanResultBox = document.getElementById('scan-result');

    openScanBtn.onclick = (e) => {
        e.preventDefault(); // Prevent default anchor behavior
        scanModal.style.display = 'block';
    };

    closeScanBtn.onclick = () => {
        scanModal.style.display = 'none';
        scanResultBox.classList.add('hidden');
    };

    // Close on click outside
    scanModal.onclick = (e) => {
        if (e.target === scanModal) {
            scanModal.style.display = 'none';
            scanResultBox.classList.add('hidden');
        }
    };

    // Tabs in Scan Modal (Logic updated for .tech-tab)
    document.querySelectorAll('.tech-tab').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tech-tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.getAttribute('data-tab')}`).classList.add('active');
        };
    });

    fileInput.onchange = (e) => {
        document.getElementById('file-name').textContent = e.target.files[0]?.name || 'No file selected';
        uploadBtn.disabled = !e.target.files[0];
    };

    window.captureAndScan = async function () {
        scanResultBox.classList.remove('hidden');
        scanResultBox.innerHTML = '<div class="loading-spinner-tech"><i class="fa-solid fa-circle-notch fa-spin"></i> ACQUIRING TARGET...</div>';

        try {
            const response = await fetch('/api/capture_and_scan', { method: 'POST' });
            const result = await response.json();
            showScanResult(result);
        } catch (error) {
            scanResultBox.innerHTML = '<div class="error-msg">Signal Lost. Capture failed.</div>';
        }
    };

    uploadBtn.onclick = async () => {
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        scanResultBox.classList.remove('hidden');
        scanResultBox.innerHTML = '<div class="loading-spinner-tech"><i class="fa-solid fa-microchip fa-bounce"></i> PROCESSING DATA STREAM...</div>';

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            showScanResult(result);
        } catch (error) {
            scanResultBox.innerHTML = '<div class="error-msg">Analysis protocol failed.</div>';
        }
    };

    function showScanResult(result) {
        const isPerfect = result.status === 'PERFECT';

        scanResultBox.innerHTML = `
            <div class="tech-result-header ${result.status.toLowerCase()}">
                <i class="fa-solid ${isPerfect ? 'fa-check-circle' : 'fa-triangle-exclamation'}"></i>
                <span>${result.status}</span>
            </div>
            <div class="tech-result-grid">
                <div>
                    <span class="tech-metric-label">IDENTIFIED OBJECT</span>
                    <span class="tech-metric-value">${result.matched_part || 'UNKNOWN_ENTITY'}</span>
                </div>
                <div>
                    <span class="tech-metric-label">CONFIDENCE SCORE</span>
                    <span class="tech-metric-value">${Math.round(result.confidence * 100)}%</span>
                    <div class="tech-progress">
                        <div class="tech-progress-bar" style="width: ${result.confidence * 100}%"></div>
                    </div>
                </div>
            </div>
        `;
        updateStats(); // Refresh dashboard
    }

    // ================= HISTORY =================
    async function loadHistory() {
        try {
            const tbody = document.getElementById('history-table-body');
            const response = await fetch('/api/history');
            const data = await response.json();

            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#6c757d;">No inspection records found.</td></tr>';
                return;
            }

            tbody.innerHTML = data.map(h => `
                <tr>
                    <td class="mono-text">#${h.id.toString().padStart(4, '0')}</td>
                    <td>${new Date(h.timestamp).toLocaleString(undefined, {
                year: 'numeric', month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit'
            })}</td>
                    <td><span class="status-badge-tech ${h.status.toLowerCase()}">${h.status}</span></td>
                    <td>
                        <div class="confidence-bar-mini" style="width: 100px; height: 4px; background: #333; border-radius: 2px; overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 8px;">
                            <div style="width: ${h.confidence * 100}%; background: var(--tech-accent); height: 100%;"></div>
                        </div>
                        <span style="font-size: 0.8rem;">${Math.round(h.confidence * 100)}%</span>
                    </td>
                    <td>
                        <button class="btn-tech-icon" title="View Details">
                            <i class="fa-solid fa-eye"></i>
                        </button>
                    </td>
                </tr>
            `).join('');
        } catch (error) {
            console.error(error);
        }
    }

    window.exportHistory = function () {
        window.location.href = '/api/export/history';
    };
});