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
                recentHistoryList.innerHTML = '<div class="empty-state">No recent scans</div>';
                return;
            }

            recentHistoryList.innerHTML = data.map(scan => `
                <div class="history-item ${scan.status.toLowerCase()}">
                    <div class="history-info">
                        <strong>${scan.status}</strong> - ${scan.matched_part || 'Unknown'}
                        <span>${new Date(scan.timestamp).toLocaleString()}</span>
                    </div>
                    <div class="history-confidence">
                        ${Math.round(scan.confidence * 100)}%
                    </div>
                </div>
            `).join('');
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
                <div class="camera-card ${c.is_active ? 'active' : 'inactive'}">
                    <div class="camera-preview">
                        <img src="/api/video_feed?camera_id=${c.id}" alt="Preview">
                        <span class="status-badge">${c.is_active ? 'Online' : 'Offline'}</span>
                    </div>
                    <div class="camera-info">
                        <h4>${c.name}</h4>
                        <p>${c.camera_type.toUpperCase()} - ${c.url}</p>
                    </div>
                    <div class="camera-actions">
                        <button onclick="toggleCamera(${c.id}, ${!c.is_active})">${c.is_active ? 'Disable' : 'Enable'}</button>
                        <button class="btn-danger" onclick="deleteCamera(${c.id})">Remove</button>
                    </div>
                </div>
            `).join('');
        } catch (error) {
            console.error('Error loading cameras:', error);
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
    const scanModal = document.getElementById('scan-modal');
    const openScanBtn = document.getElementById('open-scan-modal');
    const closeScanBtn = document.querySelector('#scan-modal .close-modal');
    const uploadBtn = document.getElementById('modal-upload-btn');
    const fileInput = document.getElementById('modal-file-upload');
    const scanResultBox = document.getElementById('scan-result');

    openScanBtn.onclick = () => scanModal.style.display = 'block';
    closeScanBtn.onclick = () => {
        scanModal.style.display = 'none';
        scanResultBox.classList.add('hidden');
    };

    // Tabs in Scan Modal
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.getAttribute('data-tab')}`).classList.add('active');
        };
    });

    fileInput.onchange = (e) => {
        document.getElementById('file-name').textContent = e.target.files[0]?.name || 'No file chosen';
        uploadBtn.disabled = !e.target.files[0];
    };

    window.captureAndScan = async function () {
        scanResultBox.classList.remove('hidden');
        scanResultBox.innerHTML = '<div class="loading-spinner">Analyzing Frame...</div>';

        try {
            const response = await fetch('/api/capture_and_scan', { method: 'POST' });
            const result = await response.json();
            showScanResult(result);
        } catch (error) {
            scanResultBox.innerHTML = '<div class="error">Failed to capture frame.</div>';
        }
    };

    uploadBtn.onclick = async () => {
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        scanResultBox.classList.remove('hidden');
        scanResultBox.innerHTML = '<div class="loading-spinner">Analyzing Uploaded Image...</div>';

        try {
            const response = await fetch('/api/scan', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            showScanResult(result);
        } catch (error) {
            scanResultBox.innerHTML = '<div class="error">Analysis failed.</div>';
        }
    };

    function showScanResult(result) {
        const isPerfect = result.status === 'PERFECT';
        scanResultBox.innerHTML = `
            <div class="result-header ${result.status.toLowerCase()}">
                <i class="fa-solid ${isPerfect ? 'fa-check-circle' : 'fa-circle-exclamation'}"></i>
                <span>Status: ${result.status}</span>
            </div>
            <div class="result-body">
                <p><strong>Part Match:</strong> ${result.matched_part || 'None'}</p>
                <div class="confidence-bar">
                    <div class="fill" style="width: ${result.confidence * 100}%"></div>
                </div>
                <p class="confidence-text">Confidence: ${Math.round(result.confidence * 100)}%</p>
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

            tbody.innerHTML = data.map(h => `
                <tr>
                    <td>#${h.id}</td>
                    <td>${new Date(h.timestamp).toLocaleString()}</td>
                    <td><span class="status-tag ${h.status.toLowerCase()}">${h.status}</span></td>
                    <td><button class="btn-text">View Details</button></td>
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