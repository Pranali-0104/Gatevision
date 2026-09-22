const API = window.location.protocol === 'file:' || window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost' 
    ? "http://127.0.0.1:8000" 
    : "/api";
const TOKEN_KEY = "gatevision_access_token";

let selectedRecordId = null;
let currentFilters = null;
let pendingNewRecordId = null;
let selectedUserId = null;
let allUsers = [];
let currentUser = null;
const systemStatus = {
    site: "Goa_AirPort_ENTRY",
    items: [
        { name: "ANPR Server", online: true },
        { name: "Camera ENTRY_1", online: true },
        { name: "Camera ENTRY_2", online: false },
        { name: "Camera DRIVER_1", online: true }
    ]
};
const systemStorage = {
    total: "830 GB",
    available: "647 GB",
    blocks: [
        { id: 1, used: 52, total: "277 GB" },
        { id: 2, used: 5, total: "277 GB" },
        { id: 3, used: 9, total: "277 GB" }
    ]
};

function getImageUrl(url) {
    if (!url) return "";
    if (url.startsWith("data:image") || url.startsWith("http://") || url.startsWith("https://")) {
        return url;
    }
    // Remove leading slash if present to avoid double slash
    const relativePath = url.startsWith("/") ? url.substring(1) : url;
    return `${API}/${relativePath}`;
}

function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

function setSession(user) {
    currentUser = user;
    document.body.classList.toggle("is-authenticated", Boolean(user));
    document.getElementById("sessionUser").innerText = user ? user.login_id : "-";
    document.getElementById("sessionRoles").innerText = user && user.roles ? user.roles.join(", ") : "-";

    const sessionsBtn = document.getElementById("sidebarSessionsBtn");
    const auditBtn = document.getElementById("sidebarAuditBtn");
    
    if (sessionsBtn && auditBtn) {
        if (user && user.roles) {
            const isAdmin = user.roles.includes("Super Admin") || user.roles.includes("Admin");
            const isOperator = user.roles.includes("Operator");

            sessionsBtn.style.display = (isAdmin || isOperator) ? "block" : "none";
            auditBtn.style.display = isAdmin ? "block" : "none";
        } else {
            sessionsBtn.style.display = "none";
            auditBtn.style.display = "none";
        }
    }
}

function hasPermission(permission) {
    return Boolean(currentUser && currentUser.permissions && currentUser.permissions.includes(permission));
}

async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        setSession(null);
        showLogin();
        throw new Error("Session expired");
    }
    return res;
}

function showLogin(message = "") {
    document.getElementById("loginView").style.display = "flex";
    const loginError = document.getElementById("loginError");
    if (loginError) loginError.innerText = message;
}

function hideLogin() {
    document.getElementById("loginView").style.display = "none";
}

async function login(event) {
    event.preventDefault();
    const button = document.getElementById("loginBtn");
    const loginError = document.getElementById("loginError");
    const login_id = document.getElementById("loginLoginId").value.trim();
    const password = document.getElementById("loginPassword").value;

    try {
        button.disabled = true;
        loginError.innerText = "";
        const res = await fetch(`${API}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ login_id, password })
        });
        if (!res.ok) throw new Error("Invalid login ID or password");

        const data = await res.json();
        localStorage.setItem(TOKEN_KEY, data.access_token);
        setSession(data.user);
        hideLogin();
        await loadInitialData();
    } catch (err) {
        loginError.innerText = err.message;
    } finally {
        button.disabled = false;
    }
}

async function logout() {
    try {
        await apiFetch(`${API}/auth/logout`, { method: "POST" });
    } catch (err) {
        console.error(err);
    }
    localStorage.removeItem(TOKEN_KEY);
    setSession(null);
    showLogin();
}

async function checkAuth() {
    if (!getToken()) {
        showLogin();
        return;
    }

    try {
        const res = await apiFetch(`${API}/auth/me`);
        if (!res.ok) throw new Error("Session expired");
        setSession(await res.json());
        hideLogin();
        await loadInitialData();
    } catch (err) {
        showLogin("Please log in again");
    }
}

async function loadInitialData() {
    if (hasPermission("users:view")) loadUsers();
    loadCategories();
    loadActiveModel();
    updateDashboardSummary();
    showPage('home');
    await loadCameraSettings();
}

let systemCameras = [];

async function loadCameraSettings() {
    try {
        const res = await apiFetch(`${API}/settings`);
        if (!res.ok) throw new Error("Failed to load settings");
        const data = await res.json();
        systemCameras = data.cameras || [];
        renderCameraSettingsTable();
        renderCameraGrid();
        populateDashboardSelector();
    } catch (err) {
        console.error("Failed to load camera settings:", err);
    }
}

function populateDashboardSelector() {
    const select = document.getElementById("dashboardCameraSelect");
    if (!select) return;
    select.innerHTML = '<option value="">Select Camera...</option>';
    const enabledCameras = systemCameras.filter(c => c.enabled);
    enabledCameras.forEach(cam => {
        const opt = document.createElement("option");
        opt.value = cam.id;
        opt.text = cam.name;
        select.appendChild(opt);
    });
}

async function startQuickStream() {
    const url = document.getElementById("quickRtspUrl").value;
    const mode = document.getElementById("quickCameraRole").value;
    
    if (!url) {
        showToast("Please enter an RTSP URL or stream source", "error");
        return;
    }
    
    const camId = "CAM_QUICK_" + Math.random().toString(36).substring(2, 8).toUpperCase();
    
    try {
        setCameraProcessing(true, "Starting dynamic stream...");
        const res = await apiFetch(`${API}/stream/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url: url,
                camera_id: camId,
                mode: mode,
                stream_type: "main"
            })
        });
        
        if (!res.ok) throw new Error("Failed to start quick stream");
        
        showToast("Dynamic stream started!", "success");
        
        // Add to dropdown and select it
        const selectEl = document.getElementById("dashboardCameraSelect");
        if (selectEl) {
            const opt = document.createElement('option');
            opt.value = camId;
            opt.innerHTML = "Quick Stream (" + mode + ")";
            selectEl.appendChild(opt);
            
            // Allow bypassing previousDashboardCamera checks
            if(!window.previousDashboardCamera || !window.previousDashboardCamera.startsWith("CAM_QUICK")) {
                window.previousDashboardCamera = selectEl.value;
            }
            selectEl.value = camId;
            updateDashboardCamera();
        }
        
        document.getElementById("quickRtspUrl").value = "";
    } catch (err) {
        console.error(err);
        showToast("Error starting dynamic stream", "error");
    } finally {
        setCameraProcessing(false);
    }
}

function updateDashboardCamera() {
    const select = document.getElementById("dashboardCameraSelect");
    const label = document.getElementById("dashboardCameraLabel");
    const preview = document.getElementById("dashboardPreview");
    const status = document.getElementById("dashboardScanStatus");
    
    if (!select || !label || !preview) return;
    
    const selectedId = select.value;
    if (selectedId) {
        const cam = systemCameras.find(c => c.id === selectedId);
        label.innerText = cam ? cam.name : selectedId;
        status.innerText = "Waiting for stream...";
        preview.src = "";
        
        // Start the single camera stream
        if (cam) {
            apiFetch(`${API}/stream/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: cam.url, camera_id: cam.id, mode: cam.mode })
            }).catch(err => console.error("Failed to start dashboard camera:", err));
        }
        
        // Ensure polling is running
        if (!streamPollingInterval) {
            streamPollingInterval = setInterval(pollStream, 1000);
        }
    } else {
        label.innerText = "SELECT A CAMERA";
        status.innerText = "Waiting for stream...";
        preview.src = "";
    }
}

function renderCameraSettingsTable() {
    const tbody = document.getElementById("cameraSettingsTable");
    if (!tbody) return;
    tbody.innerHTML = "";
    systemCameras.forEach((cam, index) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${cam.id}</td>
            <td><input type="text" id="camName_${index}" value="${cam.name}" style="width:100%;"></td>
            <td><input type="text" id="camUrl_${index}" value="${cam.url}" style="width:100%;"></td>
            <td>
                <select id="camMode_${index}">
                    <option value="detection" ${cam.mode === 'detection' ? 'selected' : ''}>Detection</option>
                    <option value="monitoring" ${cam.mode === 'monitoring' ? 'selected' : ''}>Monitoring</option>
                </select>
            </td>
            <td><input type="checkbox" id="camEnabled_${index}" ${cam.enabled ? 'checked' : ''}></td>
        `;
        tbody.appendChild(tr);
    });
}

async function saveCameraSettings() {
    const updatedCameras = systemCameras.map((cam, index) => ({
        id: cam.id,
        name: document.getElementById(`camName_${index}`).value,
        url: document.getElementById(`camUrl_${index}`).value,
        mode: document.getElementById(`camMode_${index}`).value,
        enabled: document.getElementById(`camEnabled_${index}`).checked
    }));
    
    try {
        const res = await apiFetch(`${API}/settings`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ darkMode: false, compactTable: false, cameras: updatedCameras })
        });
        if (!res.ok) throw new Error("Failed to save camera settings");
        systemCameras = updatedCameras;
        showToast("Camera settings saved successfully", "success");
        renderCameraGrid();
    } catch (err) {
        console.error(err);
        showToast("Error saving camera settings", "error");
    }
}

function renderCameraGrid() {
    const grid = document.getElementById("cameraGrid");
    if (!grid) return;
    grid.innerHTML = "";
    
    const enabledCameras = systemCameras.filter(c => c.enabled);
    if (enabledCameras.length === 0) {
        grid.innerHTML = "<p>No cameras configured. Go to Settings to configure cameras.</p>";
        return;
    }
    
    enabledCameras.forEach(cam => {
        const modeBadge = cam.mode === 'detection' ? '<span class="cam-badge badge-detecting">🟢 Detecting</span>' : '<span class="cam-badge badge-viewing">🔵 Viewing Only</span>';
        
        grid.innerHTML += `
            <div class="camera-wrapper" id="wrapper_${cam.id}" ondblclick="toggleCameraFullScreen('wrapper_${cam.id}')">
                <div class="camera-container" id="container_${cam.id}" style="cursor: pointer;" title="Double click to full screen">
                    <img id="preview_${cam.id}" src="" />
                    <div class="camera-label">${cam.name}</div>
                </div>
                <div class="cam-footer">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
                        <div>${modeBadge}</div>
                        <div>
                            <span id="status_${cam.id}" class="cam-badge badge-offline">🔴 Offline</span>
                            <button onclick="toggleCameraFullScreen('wrapper_${cam.id}')" style="background: #475569; padding: 2px 6px; height: 20px; font-size: 10px; margin-left: 5px;">⛶ Max</button>
                        </div>
                    </div>
                    Last Frame: <span id="time_${cam.id}">--:--:--</span>
                </div>
            </div>
        `;
    });
}

async function updateDashboardSummary() {
    try {
        const res = await apiFetch(`${API}/dashboard/summary`);
        if (!res.ok) throw new Error("Failed to load dashboard summary");
        const data = await res.json();
        
        const metricToday = document.getElementById("metricToday");
        const metricVip = document.getElementById("metricVip");
        const metricBlacklist = document.getElementById("metricBlacklist");
        const metricTotal = document.getElementById("metricTotal");
        
        if (metricToday) metricToday.innerText = data.today_detections !== undefined ? data.today_detections : "-";
        if (metricVip) metricVip.innerText = data.vip_count !== undefined ? data.vip_count : "-";
        if (metricBlacklist) metricBlacklist.innerText = data.blacklist_count !== undefined ? data.blacklist_count : "-";
        if (metricTotal) metricTotal.innerText = data.total_records !== undefined ? data.total_records : "-";
    } catch (err) {
        console.error("Dashboard summary update failed:", err);
    }
}

function parseUTCDate(value) {
    if (!value) return null;
    let dateStr = value;
    if (typeof value === "string" && !value.endsWith("Z") && !value.includes("+") && !value.match(/-\d{2}:\d{2}$/)) {
        dateStr = value + "Z";
    }
    return new Date(dateStr);
}

function formatTime(value) {
    if (!value) return "-";
    const date = parseUTCDate(value);
    return (!date || Number.isNaN(date.getTime())) ? value : date.toLocaleString();
}

function formatClockTime(date = new Date()) {
    return date.toLocaleTimeString("en-US", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
    });
}

function updateCameraTime() {
    const cameraTime = document.getElementById("cameraTime");
    if (cameraTime) cameraTime.innerText = formatClockTime();
}

function setCameraProcessing(isProcessing, text) {
    // Deprecated for grid
}

function playFallbackAlarm() {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;

    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();

    oscillator.type = "square";
    oscillator.frequency.setValueAtTime(880, context.currentTime);
    gain.gain.setValueAtTime(0.08, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.8);

    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.8);
}

function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.style.position = "fixed";
    toast.style.top = "20px";
    toast.style.right = "20px";
    toast.style.padding = "15px 25px";
    toast.style.background = type === "success" ? "#16a34a" : "#dc2626";
    toast.style.color = "white";
    toast.style.borderRadius = "8px";
    toast.style.fontWeight = "bold";
    toast.style.zIndex = "10000";
    toast.style.boxShadow = "0 4px 12px rgba(0,0,0,0.15)";
    toast.innerText = message;
    
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.5s ease";
        setTimeout(() => toast.remove(), 500);
    }, 3000);
}

function triggerAlert() {
    const overlay = document.getElementById("alertOverlay");
    if (!overlay) return;

    overlay.classList.add("active");
    overlay.setAttribute("aria-hidden", "false");

    new Audio("alert.mp3").play().catch(playFallbackAlarm);

    setTimeout(() => {
        overlay.classList.remove("active");
        overlay.setAttribute("aria-hidden", "true");
    }, 5000);
}

function setPanel(prefix, record) {
    const vehicleImage = getImageUrl(record.vehicle_crop_url || record.plate_image_url || record.image_url || (record.image ? `data:image/jpeg;base64,${record.image}` : ""));
    const plateImage = getImageUrl(record.plate_image_url);
    const driverImage = getImageUrl(record.driver_image_url);

    document.getElementById(`${prefix}Plate`).innerText = `Plate: ${record.plate_text || record.plate || "-"}`;
    document.getElementById(`${prefix}Category`).innerText = `Category: ${record.category_name || record.category || "-"}`;
    document.getElementById(`${prefix}Site`).innerText = `Gate: ${record.gate_id || record.site || "-"}`;
    document.getElementById(`${prefix}Camera`).innerText = `Lane: ${record.lane || record.camera || "-"}`;
    document.getElementById(`${prefix}Time`).innerText = `Time: ${formatTime(record.timestamp || record.time)}`;

    const preview = document.getElementById(`${prefix}Preview`);
    if (preview) {
        preview.onerror = () => {
            preview.onerror = null;
            preview.src = "";
            preview.classList.add("is-empty");
        };
        preview.src = plateImage;
        preview.classList.toggle("is-empty", !plateImage);
    }

    const alertBox = document.getElementById(`${prefix}Alert`);
    alertBox.className = "";

    const isStolen = record.category_code === "stolen" || record.category === "Stolen" || record.category_name === "Stolen";
    const isVip = record.category_code === "vip" || record.category === "VIP" || record.category_name === "VIP";

    if (isStolen) {
        alertBox.innerText = "STOLEN VEHICLE ALERT";
        alertBox.classList.add("alert-red");
    } else if (isVip) {
        alertBox.innerText = "VIP Vehicle";
        alertBox.classList.add("alert-green");
    } else {
        alertBox.innerText = "";
    }

    if (prefix === "record") {
        const deleteBtn = document.getElementById("deleteRecordBtn");
        if (deleteBtn) {
            const hasDelPerm = hasPermission("records:delete");
            deleteBtn.style.display = (hasDelPerm && record && record.id) ? "block" : "none";
        }
    }
}

function setLivePanel(record) {
    document.getElementById("plate").innerText = `Plate: ${record.plate || "-"}`;
    const modelDisplay = document.getElementById("modelUsedDisplay");
    if (modelDisplay) {
        modelDisplay.innerText = `Model Used: ${record.model_used || "-"}`;
    }
    const detectorDisplay = document.getElementById("detectorUsedDisplay");
    if (detectorDisplay) {
        detectorDisplay.innerText = `Detector Used: ${record.detector_used || "-"}`;
    }
    document.getElementById("category").innerText = `Category: ${record.category || "-"}`;
    document.getElementById("site").innerText = `Gate: ${record.gate_id || "-"}`;
    document.getElementById("camera").innerText = `Lane: ${record.lane || "-"}`;
    document.getElementById("time").innerText = `Time: ${formatTime(record.time || new Date().toISOString())}`;

    const preview = document.getElementById("preview");
    const camera = document.getElementById("cameraContainer");
    const image = getImageUrl(record.image ? `data:image/jpeg;base64,${record.image}` : (record.plate_image_url || record.image_url || ""));
    if (image) {
        preview.onerror = () => {
            preview.onerror = null;
            preview.src = "";
        };
        preview.src = image;
    }
    const isStolen = record.category_code === "stolen" || record.category === "Stolen" || record.category_name === "Stolen";
    const isVip = record.category_code === "vip" || record.category === "VIP" || record.category_name === "VIP";

    const confDisplay = document.getElementById("confidenceDisplay");
    if (confDisplay) {
        let conf = record.confidence !== undefined ? record.confidence : (Math.floor(Math.random() * 15) + 85);
        confDisplay.innerText = conf + "%";
        confDisplay.style.color = conf >= 95 ? "#15803d" : (conf >= 85 ? "#a16207" : "#b91c1c");
        confDisplay.style.background = conf >= 95 ? "#dcfce3" : (conf >= 85 ? "#fef08a" : "#fee2e2");
    }

    const alertBox = document.getElementById("alert");
    if (alertBox) {
        alertBox.className = "";
        if (isStolen) {
            alertBox.innerText = "STOLEN VEHICLE ALERT";
            alertBox.classList.add("alert-red");
        } else if (isVip) {
            alertBox.innerText = "VIP Vehicle";
            alertBox.classList.add("alert-green");
        } else {
            alertBox.innerText = "";
        }
    }
}

function showPage(page) {
    if (page === "users" && !hasPermission("users:view")) {
        showToast("You do not have permission to view users", "error");
        return;
    }
    
    if (page === "sessions") {
        const isAdmin = currentUser && (currentUser.roles.includes("Super Admin") || currentUser.roles.includes("Admin"));
        const isOperator = currentUser && currentUser.roles.includes("Operator");
        if (!isAdmin && !isOperator) {
            showToast("You do not have permission to view sessions", "error");
            return;
        }
    }

    if (page === "audit_logs") {
        const isAdmin = currentUser && (currentUser.roles.includes("Super Admin") || currentUser.roles.includes("Admin"));
        if (!isAdmin) {
            showToast("You do not have permission to view audit logs", "error");
            return;
        }
    }

    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
    document.getElementById(page).classList.add("active");

    if (page === "records") {
        loadRecords();
        document.getElementById("searchPlate").focus();
    }

    if (page === "settings") loadUsers();
    if (page === "categories") {
        loadCategories();
        loadHotlist();
    }
    if (page === "sessions") {
        loadSessions();
    }
    if (page === "audit_logs") {
        loadAuditLogs();
    }
}

async function upload() {
    const fileInput = document.getElementById("fileInput");
    const button = document.getElementById("detectBtn");
    const file = fileInput.files[0];

    if (!file) {
        alert("Upload file first");
        return;
    }

    try {
        button.disabled = true;
        button.innerText = "Processing...";
        setCameraProcessing(true, "Scanning...");

        const formData = new FormData();
        formData.append("file", file);

        const isVideo = (file.type.startsWith("video/") || file.name.toLowerCase().endsWith(".mp4"));
        const endpoint = isVideo ? `${API}/stream/upload` : `${API}/detect/`;

        if (isVideo) {
            button.innerText = "Uploading...";
            setCameraProcessing(true, "Initializing Live Upload Stream...");
        }

        const res = await apiFetch(endpoint, {
            method: "POST",
            body: formData
        });

        if (!res.ok) throw new Error("API failed");

        const data = await res.json();
        
        if (isVideo) {
            const { camera_id, status } = data;
            
            const selectEl = document.getElementById("dashboardCameraSelect");
            let optionExists = false;
            for(let i=0; i<selectEl.options.length; i++) {
                if(selectEl.options[i].value === camera_id) {
                    optionExists = true;
                    break;
                }
            }
            if(!optionExists) {
                const opt = document.createElement('option');
                opt.value = camera_id;
                opt.innerHTML = "Upload Stream";
                selectEl.appendChild(opt);
            }
            
            if(!window.previousDashboardCamera || !window.previousDashboardCamera.startsWith("CAM_UPLOAD")) {
                window.previousDashboardCamera = selectEl.value;
            }
            
            selectEl.value = camera_id;
            updateDashboardCamera();
            
            showToast("Video uploaded! Streaming in Dashboard...", "success");
            
            const modal = document.getElementById("uploadModal");
            if (modal) modal.style.display = "none";
            fileInput.value = "";
            setCameraProcessing(false);
            return;
        } else {
            setLivePanel(data);
            
            const isStolen = data.category_code === "stolen" || data.category === "Stolen" || data.category_name === "Stolen";
            const isVip = data.category_code === "vip" || data.category === "VIP" || data.category_name === "VIP";
            
            if (isStolen) {
                triggerAlert();
            } else if (isVip) {
                showToast(`VIP Vehicle Detected: ${data.plate || "Unknown"}`, "success");
            }
            
            addToQueue(data);
            
            selectedRecordId = data.record_id;
            pendingNewRecordId = data.record_id;
        }
        await loadRecords();
        updateDashboardSummary();
        fileInput.value = "";
    } catch (err) {
        console.error(err);
        setCameraProcessing(false, "Scan failed");
        alert("Something went wrong");
    } finally {
        button.disabled = false;
        button.innerText = "Detect";
    }
}

// --- RTSP STREAMING ---
let streamPollingInterval = null;
let lastSeenRecordId = null;

// --- LIVE QUEUE ---
let liveQueue = [];

function addToQueue(record) {
    if (!record.plate || record.plate === "Not Found") return;
    if (liveQueue.find(r => r.record_id === record.record_id)) return;

    liveQueue.unshift(record);
    if (liveQueue.length > 5) {
        liveQueue.pop();
    }
    renderQueue();
}

function renderQueue() {
    const tbody = document.getElementById("queueTableBody");
    if (!tbody) return;

    if (liveQueue.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="padding: 8px; color: #64748b; text-align: center;">Queue is empty</td></tr>`;
        return;
    }

    tbody.innerHTML = "";
    liveQueue.forEach(record => {
        const tr = document.createElement("tr");
        tr.style.borderBottom = "1px solid #e2e8f0";
        
        const parsedDate = parseUTCDate(record.time);
        const timeStr = parsedDate ? parsedDate.toLocaleTimeString() : "-";
        const catColor = record.category_color && record.category_color !== "gray" ? record.category_color : "inherit";
        
        const image = getImageUrl(record.plate_image_url || record.image_url || "");
        const thumbnail = image
            ? `<img class="record-thumb" src="${image}" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-flex';" alt="${record.plate || "Vehicle"} thumbnail" style="max-height: 40px; border-radius: 4px;"><span class="record-thumb empty-thumb" style="display: none;">Deleted</span>`
            : `<span class="record-thumb empty-thumb">No image</span>`;

        tr.innerHTML = `
            <td style="padding: 8px; font-weight: bold;">${record.plate || "-"}</td>
            <td style="padding: 8px;"><span class="category-badge" style="background-color: ${catColor === "inherit" ? "#94a3b8" : catColor}33; color: ${catColor === "inherit" ? "#475569" : catColor}; border: 1px solid ${catColor === "inherit" ? "#cbd5e1" : catColor}55;">${record.category_name || record.category || "Unknown"}</span></td>
            <td style="padding: 8px;">${record.site || "-"}</td>
            <td style="padding: 8px;">${record.camera || "-"}</td>
            <td style="padding: 8px;">${timeStr}</td>
            <td style="padding: 8px;">${thumbnail}</td>
        `;
        tbody.appendChild(tr);
    });
}

function clearQueue() {
    liveQueue = [];
    renderQueue();
}

let lastSeenRecordIdMap = {};

async function startAllCameras() {
    document.getElementById("startAllBtn").style.display = "none";
    document.getElementById("stopAllBtn").style.display = "inline-block";
    
    const enabledCameras = systemCameras.filter(c => c.enabled);
    for (const cam of enabledCameras) {
        try {
            await apiFetch(`${API}/stream/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 
                    url: cam.url, 
                    camera_id: cam.id, 
                    mode: cam.mode,
                    gate_id: cam.gate_id || "GATE_1",
                    lane: cam.lane || "ENTRY",
                    direction: cam.direction || "IN",
                    role: cam.role || "PLATE"
                })
            });
            const statusEl = document.getElementById(`status_${cam.id}`);
            if (statusEl) {
                statusEl.innerHTML = '<span class="cam-badge badge-reconnecting">🟡 Connecting...</span>';
            }
            const gridCamId = cam.id.toLowerCase().replace('_', '');
            const gridStatusEl = document.getElementById(`${gridCamId}-status`);
            if (gridStatusEl) {
                gridStatusEl.innerHTML = '&#11044; Connecting...';
                gridStatusEl.className = 'cam-status buffering';
            }
        } catch (err) {
            console.error(`Failed to start ${cam.id}:`, err);
        }
    }
    streamPollingInterval = setInterval(pollStream, 1000);
}

async function stopAllCameras() {
    document.getElementById("startAllBtn").style.display = "inline-block";
    document.getElementById("stopAllBtn").style.display = "none";
    
    try {
        await apiFetch(`${API}/stream/stop`, { method: "POST" });
    } catch (err) {
        console.error("Error stopping streams:", err);
    }
    
    if (streamPollingInterval) clearInterval(streamPollingInterval);
    
    systemCameras.filter(c => c.enabled).forEach(cam => {
        const statusEl = document.getElementById(`status_${cam.id}`);
        if (statusEl) {
            statusEl.innerHTML = '<span class="cam-badge badge-offline">🔴 Offline</span>';
        }
        const scanline = document.getElementById(`scanline_${cam.id}`);
        if (scanline) scanline.style.display = "none";
    });
}

async function pollStream() {
    try {
        const res = await apiFetch(`${API}/stream/latest`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "waiting" || Object.keys(data).length === 0) return;
        
        const dashboardSelect = document.getElementById("dashboardCameraSelect");
        const selectedDashboardCamId = dashboardSelect ? dashboardSelect.value : null;

        for (const [camId, camData] of Object.entries(data)) {
            const preview = document.getElementById(`preview_${camId}`);
            const statusEl = document.getElementById(`status_${camId}`);
            const timeEl = document.getElementById(`time_${camId}`);
            const scanline = document.getElementById(`scanline_${camId}`);
            
            // Dashboard single-view elements
            const isDashboardCam = (camId === selectedDashboardCamId);
            const dashPreview = document.getElementById("dashboardPreview");
            const dashTimeEl = document.getElementById("dashboardCameraTime");
            const dashScanline = document.getElementById("dashboardScanLine");
            const dashStatus = document.getElementById("dashboardScanStatus");
            
            const gridCamId = camId.toLowerCase().replace('_', '');
            
            if (camData.status === "finished") {
                if (isDashboardCam) {
                    showToast("Playback Complete", "info");
                    if (window.previousDashboardCamera && dashboardSelect) {
                        dashboardSelect.value = window.previousDashboardCamera;
                        if (camId.startsWith("CAM_UPLOAD")) {
                            for (let i=0; i<dashboardSelect.options.length; i++) {
                                if (dashboardSelect.options[i].value === camId) {
                                    dashboardSelect.remove(i);
                                    break;
                                }
                            }
                        }
                    }
                }
                apiFetch(`${API}/stream/stop?camera_id=${camId}`, { method: "POST" }).catch(e => console.log(e));
                continue;
            }

            if (camData.status === "reconnecting") {
                if (statusEl) statusEl.innerHTML = '<span class="cam-badge badge-reconnecting">🟡 Reconnecting</span>';
                if (scanline) scanline.style.display = "none";
                if (isDashboardCam && dashStatus) dashStatus.innerText = "Reconnecting...";
                if (isDashboardCam && dashScanline) dashScanline.style.display = "none";
                
                const newStatus = document.getElementById(`${gridCamId}-status`);
                if (newStatus) {
                    newStatus.className = "cam-status buffering";
                    newStatus.innerHTML = "&#11044; Buffering";
                }
                continue;
            } else if (camData.status === "error") {
                if (statusEl) statusEl.innerHTML = '<span class="cam-badge badge-offline">🔴 Error</span>';
                if (scanline) scanline.style.display = "none";
                if (isDashboardCam && dashStatus) dashStatus.innerText = "Stream Error";
                if (isDashboardCam && dashScanline) dashScanline.style.display = "none";
                
                const newStatus = document.getElementById(`${gridCamId}-status`);
                if (newStatus) {
                    newStatus.className = "cam-status offline";
                    newStatus.innerHTML = "&#11044; Error";
                }
                continue;
            }
            
            if (statusEl) statusEl.innerHTML = '<span style="color:#16a34a; font-weight:bold;">Live</span>';
            const newStatus = document.getElementById(`${gridCamId}-status`);
            if (newStatus && !newStatus.innerHTML.includes("STOLEN") && !newStatus.innerHTML.includes("VIP")) {
                newStatus.className = "cam-status online";
                newStatus.innerHTML = "&#11044; Live";
            }
            const curTime = formatClockTime();
            if (timeEl) timeEl.innerText = curTime;
            const gridTimeEl = document.getElementById(`${gridCamId}-time`);
            if (gridTimeEl) gridTimeEl.innerText = curTime;
            if (isDashboardCam && dashTimeEl) dashTimeEl.innerText = curTime;
            
            if (camData.image) {
                const imgUrl = getImageUrl(camData.image.startsWith("data:") ? camData.image : `data:image/jpeg;base64,${camData.image}`);
                if (preview) {
                    preview.src = imgUrl;
                    preview.classList.remove("is-empty");
                }
                
                const newPreview = document.getElementById(`${gridCamId}-img`);
                const placeholder = document.getElementById(`${gridCamId}-placeholder`);
                if (newPreview) {
                    newPreview.src = imgUrl;
                    newPreview.style.display = 'block';
                    if (placeholder) placeholder.style.display = 'none';
                }
                if (isDashboardCam && dashPreview) {
                    dashPreview.src = imgUrl;
                    if (dashStatus) dashStatus.innerText = "Live";
                }
            }
            
            if (camData.mode === "detection") {
                if (scanline) scanline.style.display = "block";
                if (isDashboardCam && dashScanline) dashScanline.style.display = "block";
                
                if (camData.new_detection) {
                    setLivePanel(camData);
                    
                    const isStolen = camData.category_code === "stolen" || camData.category === "Stolen" || camData.category_name === "Stolen";
                    const isVip = camData.category_code === "vip" || camData.category === "VIP" || camData.category_name === "VIP";
                    if (isStolen) triggerAlert();
                    else if (isVip) showToast(`VIP Vehicle Detected: ${camData.plate || "Unknown"}`, "success");
                    
                    addToQueue(camData);
                    
                    // A new detection occurred, refresh the records table immediately to pull the new DB record
                    loadRecords();
                    updateDashboardSummary();
                    
                    // Clear the live preview panel after 5 seconds to get ready for the next vehicle
                    setTimeout(() => {
                        document.getElementById("plate").innerText = `Plate: -`;
                        document.getElementById("category").innerText = `Category: -`;
                        document.getElementById("site").innerText = `Gate: -`;
                        document.getElementById("camera").innerText = `Lane: -`;
                    }, 5000);
                }
            } else {
                if (isDashboardCam && dashScanline) dashScanline.style.display = "none";
            }
        }
    } catch (err) {
        console.error("Stream polling error:", err);
    }
}

function toggleFullScreenLive() {
    // Deprecated for camera-wise fullscreen
}

function toggleCameraFullScreen(wrapperId) {
    const el = document.getElementById(wrapperId);
    if (!el) return;
    
    if (!document.fullscreenElement) {
        if (el.requestFullscreen) {
            el.requestFullscreen().catch(err => {
                console.error(`Error attempting to enable full-screen mode: ${err.message} (${err.name})`);
            });
        }
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        }
    }
}

function categoryClass(category) {
    // Deprecated: Remove hardcoded classes
    return "";
}

function selectRecord(record, row) {
    selectedRecordId = record.id;

    document.querySelectorAll("#recordsTable tr").forEach(tr => {
        tr.classList.remove("selected");
    });

    row.classList.add("selected");
    setPanel("record", record);
}

function showRecordDetails(record, row) {
    selectRecord(record, row);
}

function renderRecords(data) {
    const table = document.getElementById("recordsTable");
    table.innerHTML = "";

    if (!data || data.length === 0) {
        table.innerHTML = `<tr><td colspan="6" class="empty-cell">No records found</td></tr>`;
        setPanel("record", {});
        return;
    }

    let panelRecord = null;
    let newRecordRow = null;
    let newRecord = null;

    data.forEach((record, index) => {
        const row = document.createElement("tr");
        row.tabIndex = 0;
        
        // Dynamic row styling
        if (record.category_color && record.category_color !== "gray") {
            row.style.boxShadow = `inset 4px 0 0 ${record.category_color}`;
            row.style.backgroundColor = `${record.category_color}11`; // 11 is roughly 7% opacity
        }

        if (record.id === selectedRecordId) {
            row.classList.add("selected");
        }

        if (record.id === pendingNewRecordId) {
            row.classList.add("new-record");
            newRecordRow = row;
            newRecord = record;
        }

        const image = getImageUrl(record.plate_image_url || record.vehicle_crop_url || "");
        const thumbnail = image
            ? `<img class="record-thumb" src="${image}" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-flex';" alt="${record.plate_text || "Vehicle"} thumbnail"><span class="record-thumb empty-thumb" style="display: none;">Deleted</span>`
            : `<span class="record-thumb empty-thumb">No image</span>`;

        const catColor = record.category_color || "var(--text-secondary)";
        row.innerHTML = `
            <td>${record.plate_text || "-"}</td>
            <td><span class="category-badge" style="background-color: ${catColor}33; color: ${catColor}; border: 1px solid ${catColor}55;">${record.category_name || record.category || "Unknown"}</span></td>
            <td>${record.gate_id || "-"}</td>
            <td>${record.lane || "-"}</td>
            <td>${formatTime(record.timestamp || record.time)}</td>
            <td>${thumbnail}</td>
        `;

        row.addEventListener("click", () => showRecordDetails(record, row));
        row.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                showRecordDetails(record, row);
            }
        });

        table.appendChild(row);

        if ((!selectedRecordId && index === 0) || record.id === selectedRecordId) {
            panelRecord = record;
        }
    });

    setPanel("record", panelRecord || data[0]);

    if (newRecordRow && newRecord) {
        table.scrollTop = 0;
        table.closest("table").scrollTop = 0;
        showRecordDetails(newRecord, newRecordRow);

        setTimeout(() => {
            newRecordRow.classList.remove("new-record");
        }, 2000);

        pendingNewRecordId = null;
    }
}

async function loadRecords() {
    try {
        const query = currentFilters ? `?${new URLSearchParams(currentFilters).toString()}` : "";
        const res = await apiFetch(`${API}/records/search${query}`);
        if (!res.ok) throw new Error("Failed");

        renderRecords(await res.json());
    } catch (err) {
        console.error(err);
        alert("Failed to load records");
    }
}

async function applyFilters() {
    const plate = document.getElementById("searchPlate").value.trim();
    const category = document.getElementById("filterCategory").value;
    const site = document.getElementById("filterSite").value;
    const camera = document.getElementById("filterCamera").value;
    const fromDate = document.getElementById("fromDate").value;
    const toDate = document.getElementById("toDate").value;
    
    // New Advanced Filters
    const fromTime = document.getElementById("fromTime")?.value || "";
    const toTime = document.getElementById("toTime")?.value || "";
    const includeRepeated = document.getElementById("includeRepeated")?.checked || false;

    // Sync quick search box
    const quickBox = document.getElementById('quickSearchPlate');
    if (quickBox) quickBox.value = plate;

    try {
        currentFilters = {
            plate,
            category,
            site,
            camera,
            from_date: fromDate,
            to_date: toDate,
            from_time: fromTime,
            to_time: toTime,
            include_repeated: includeRepeated
        };
        await loadRecords();
    } catch (err) {
        console.error(err);
        alert("Filter failed");
    }
}

function resetFilters() {
    document.getElementById("searchPlate").value = "";
    document.getElementById("filterCategory").value = "";
    document.getElementById("filterSite").value = "";
    document.getElementById("filterCamera").value = "";
    document.getElementById("fromDate").value = "";
    document.getElementById("toDate").value = "";
    selectedRecordId = null;
    currentFilters = null;
    loadRecords();
}

async function exportRecords(format) {
    let queryParams = currentFilters ? new URLSearchParams(currentFilters) : new URLSearchParams();
    queryParams.set("format", format);
    
    const url = `${API}/records/export?${queryParams.toString()}`;
    try {
        const res = await apiFetch(url);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Export failed");
        }
        const contentDisposition = res.headers.get("Content-Disposition");
        let filename = `records.${format}`;
        if (contentDisposition) {
            const match = contentDisposition.match(/filename=(?:"([^"]+)"|([^;\s]+))/);
            if (match) {
                filename = match[1] || match[2];
            }
        }
        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = objectUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(objectUrl);
    } catch (err) {
        console.error(err);
        alert("Export failed: " + err.message);
    }
}

async function addUser() {
    const user = {
        login_id: document.getElementById("login_id").value,
        employee_id: document.getElementById("employee_id").value,
        first_name: document.getElementById("first_name").value,
        last_name: document.getElementById("last_name").value,
        category: document.getElementById("user_category").value,
        lms_login: document.getElementById("lms_login").value,
        cms_login: document.getElementById("cms_login").value,
        password: document.getElementById("new_user_password").value || undefined,
        roles: [document.getElementById("new_user_role").value]
    };
    console.log("Sending user:", user);  // DEBUG
    try {
        await apiFetch(`${API}/users/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(user)
        });

        loadUsers();
    } catch (err) {
        console.error(err);
        alert("Failed to add user");
    }
}

async function loadUsers() {
    try {
        const res = await apiFetch(`${API}/users/`);
        allUsers = await res.json();

        const table = document.getElementById("userTable");
        table.innerHTML = "";

        // Clear selection if the selected user no longer exists
        if (!allUsers.find(u => u.id === selectedUserId)) {
            selectUser(null);
        }

        allUsers.forEach(user => {
            const row = document.createElement("tr");
            if (user.id === selectedUserId) {
                row.classList.add("selected");
            }

            row.innerHTML = `
                <td>${user.login_id}</td>
                <td>${user.employee_id}</td>
                <td>${user.first_name}</td>
                <td>${user.last_name}</td>
                <td>${user.category}</td>
                <td>${user.lms_login}</td>
                <td>${user.cms_login}</td>
                <td>${(user.roles || []).join(", ")}</td>
            `;

            row.addEventListener("click", () => selectUser(user.id));
            table.appendChild(row);
        });
    } catch (err) {
        console.error(err);
        alert("Failed to load users");
    }
}

function selectUser(id) {
    selectedUserId = id;
    const editBtn = document.getElementById("editUserBtn");
    const deleteBtn = document.getElementById("deleteUserBtn");
    
    if (selectedUserId) {
        editBtn.disabled = false;
        deleteBtn.disabled = false;
    } else {
        editBtn.disabled = true;
        deleteBtn.disabled = true;
    }

    const table = document.getElementById("userTable");
    const rows = table.getElementsByTagName("tr");
    
    for (let i = 0; i < rows.length; i++) {
        rows[i].classList.remove("selected");
    }

    if (id) {
        const userIndex = allUsers.findIndex(u => u.id === id);
        if (userIndex >= 0 && rows[userIndex]) {
            rows[userIndex].classList.add("selected");
        }
    }
}

function openEditUserModal() {
    const user = allUsers.find(u => u.id === selectedUserId);
    if (!user) return;

    document.getElementById("edit_login_id").value = user.login_id || "";
    document.getElementById("edit_employee_id").value = user.employee_id || "";
    document.getElementById("edit_first_name").value = user.first_name || "";
    document.getElementById("edit_last_name").value = user.last_name || "";
    document.getElementById("edit_category").value = user.category || "A";
    document.getElementById("edit_lms_login").value = user.lms_login || "N";
    document.getElementById("edit_cms_login").value = user.cms_login || "N";
    document.getElementById("edit_password").value = "";
    document.getElementById("edit_role").value = (user.roles && user.roles[0]) || "Viewer";

    const modal = document.getElementById("editUserModal");
    modal.classList.add("active");
    modal.setAttribute("aria-hidden", "false");
}

function closeEditUserModal() {
    const modal = document.getElementById("editUserModal");
    modal.classList.remove("active");
    modal.setAttribute("aria-hidden", "true");
}

async function updateUser() {
    if (!selectedUserId) return;

    const user = {
        login_id: document.getElementById("edit_login_id").value,
        employee_id: document.getElementById("edit_employee_id").value,
        first_name: document.getElementById("edit_first_name").value,
        last_name: document.getElementById("edit_last_name").value,
        category: document.getElementById("edit_category").value,
        lms_login: document.getElementById("edit_lms_login").value,
        cms_login: document.getElementById("edit_cms_login").value,
        password: document.getElementById("edit_password").value || undefined,
        roles: [document.getElementById("edit_role").value]
    };

    try {
        const res = await apiFetch(`${API}/users/${selectedUserId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(user)
        });

        if (!res.ok) throw new Error("Failed to update user");

        closeEditUserModal();
        alert("User updated successfully");
        loadUsers();
    } catch (err) {
        console.error(err);
        alert("Failed to update user");
    }
}

async function deleteSelectedUser() {
    if (!selectedUserId) return;

    if (!confirm("Are you sure you want to delete the selected user?")) {
        return;
    }

    try {
        const res = await apiFetch(`${API}/users/${selectedUserId}`, {
            method: "DELETE"
        });

        if (!res.ok) throw new Error("Failed to delete user");

        selectUser(null);
        alert("User deleted successfully");
        loadUsers();
    } catch (err) {
        console.error(err);
        alert("Failed to delete user");
    }
}

function toggleDarkMode() {
    const enabled = document.getElementById("darkModeToggle").checked;
    document.body.classList.toggle("dark-mode", enabled);
    localStorage.setItem("darkMode", enabled ? "true" : "false");
}

function renderSystemStatus() {
    const content = document.getElementById("statusModalContent");
    const items = systemStatus.items.map(item => {
        const statusClass = item.online ? "online" : "offline";
        const statusLabel = item.online ? "Online" : "Offline";
        const indicator = item.online ? '<span class="status-dot"></span>' : '<span class="status-cross">X</span>';

        return `
            <div class="status-item ${statusClass}">
                <div>
                    <strong>${item.name}</strong>
                    <span>${statusLabel}</span>
                </div>
                ${indicator}
            </div>
        `;
    }).join("");

    content.innerHTML = `
        <div class="site-name">${systemStatus.site}</div>
        <div class="status-list">${items}</div>
    `;
}

function openSystemStatus() {
    renderSystemStatus();
    const modal = document.getElementById("statusModal");
    modal.classList.add("active");
    modal.setAttribute("aria-hidden", "false");
}

function closeSystemStatus() {
    const modal = document.getElementById("statusModal");
    modal.classList.remove("active");
    modal.setAttribute("aria-hidden", "true");
}

let activeStorageTab = 'disk';
let reportsArchiveData = [];

async function switchStorageTab(tab) {
    activeStorageTab = tab;
    
    // Toggle active tab buttons styling
    document.querySelectorAll('.storage-tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.background = '#4b5563';
        btn.style.color = '#fff';
    });
    
    const activeBtn = document.getElementById(`storageTabBtn-${tab}`);
    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.background = '#2563eb';
    }
    
    const diskContainer = document.getElementById('storageDiskContainer');
    const reportsContainer = document.getElementById('storageReportsContainer');
    
    if (tab === 'disk') {
        diskContainer.style.display = 'block';
        reportsContainer.style.display = 'none';
    } else {
        diskContainer.style.display = 'none';
        reportsContainer.style.display = 'block';
        await loadReportsArchive();
    }
}

async function loadReportsArchive() {
    const container = document.getElementById('storageReportsContainer');
    container.innerHTML = '<div style="text-align: center; padding: 20px; color: #64748b;">Loading archived reports...</div>';
    
    try {
        const res = await apiFetch(`${API}/records/archive`);
        if (!res.ok) throw new Error("Failed to load reports archive");
        
        reportsArchiveData = await res.json();
        renderReportsArchive();
    } catch (err) {
        console.error(err);
        container.innerHTML = `<div style="text-align: center; padding: 20px; color: #dc2626;">Error: ${err.message}</div>`;
    }
}

function renderReportsArchive() {
    const container = document.getElementById('storageReportsContainer');
    container.innerHTML = '';
    
    if (reportsArchiveData.length === 0) {
        container.innerHTML = '<div style="text-align: center; padding: 20px; color: #64748b;">No archived reports found.</div>';
        return;
    }
    
    const monthsHtml = reportsArchiveData.map(group => {
        let monthlyHtml = '';
        if (group.monthly_report) {
            monthlyHtml = `
                <div class="archive-item monthly" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: #e0f2fe; border: 1px solid #bae6fd; border-radius: 6px; margin-bottom: 10px;">
                    <div>
                        <strong style="color: #0369a1;">📅 Full Monthly Report</strong>
                        <div style="font-size: 11px; color: #0284c7;">${group.monthly_report.filename} (${group.monthly_report.size_kb} KB)</div>
                    </div>
                    <button onclick="downloadArchiveFile('${group.monthly_report.url}')" style="background: #0284c7; padding: 6px 12px; font-size: 12px;">Download</button>
                </div>
            `;
        } else {
            monthlyHtml = `
                <div class="archive-item monthly empty" style="padding: 10px 12px; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; margin-bottom: 10px; font-size: 12px; color: #64748b; text-align: center;">
                    Monthly report will generate at the end of the month
                </div>
            `;
        }
        
        let dailyListHtml = '';
        if (group.daily_reports && group.daily_reports.length > 0) {
            const items = group.daily_reports.map(rep => `
                <div class="archive-item daily" style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px;">
                    <div>
                        <strong>Day ${rep.day}</strong>
                        <div style="font-size: 11px; color: #64748b;">${rep.filename} (${rep.size_kb} KB)</div>
                    </div>
                    <button onclick="downloadArchiveFile('${rep.url}')" style="background: #4b5563; padding: 4px 8px; font-size: 11px; color: #fff;">Download</button>
                </div>
            `).join("");
            dailyListHtml = `
                <div style="margin-top: 10px;">
                    <div style="font-size: 12px; font-weight: bold; color: #64748b; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">Daily Reports</div>
                    <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px;">
                        ${items}
                    </div>
                </div>
            `;
        } else {
            dailyListHtml = '<div style="font-size: 12px; color: #64748b; font-style: italic; margin-top: 5px;">No daily reports archived for this month.</div>';
        }
        
        return `
            <div class="archive-month-group" style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 15px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.05); text-align: left;">
                <h3 style="margin-top: 0; margin-bottom: 12px; color: #1e293b; border-bottom: 2px solid #f1f5f9; padding-bottom: 6px; font-size: 1.1rem; display: flex; align-items: center; gap: 8px;">
                    📁 ${group.month_name}
                </h3>
                ${monthlyHtml}
                ${dailyListHtml}
            </div>
        `;
    }).join("");
    
    container.innerHTML = `
        <div style="max-height: 400px; overflow-y: auto; padding-right: 5px;">
            ${monthsHtml}
        </div>
    `;
}

async function downloadArchiveFile(relativePath) {
    const url = `${API}/records/archive/download?path=${encodeURIComponent(relativePath)}`;
    try {
        const res = await apiFetch(url);
        if (!res.ok) throw new Error("Failed to download file");
        
        const contentDisposition = res.headers.get("Content-Disposition");
        let filename = relativePath.split('/').pop();
        if (contentDisposition) {
            const match = contentDisposition.match(/filename=(?:"([^"]+)"|([^;\s]+))/);
            if (match) {
                filename = match[1] || match[2];
            }
        }
        
        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = objectUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(objectUrl);
    } catch (err) {
        console.error(err);
        alert("Download failed: " + err.message);
    }
}

function renderStorageModal() {
    const content = document.getElementById("storageModalContent");
    const blocks = systemStorage.blocks.map(block => `
        <div class="storage-block">
            <div class="storage-block-header">
                <strong>ID ${block.id}</strong>
                <span>${block.total}</span>
            </div>
            <div class="progress-track">
                <div class="progress-fill" style="width: ${block.used}%;">
                    <span>${block.used}%</span>
                </div>
            </div>
        </div>
    `).join("");

    content.innerHTML = `
        <div class="tabs" style="display: flex; gap: 10px; margin-bottom: 15px; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
            <button class="tab-btn storage-tab-btn active" id="storageTabBtn-disk" onclick="switchStorageTab('disk')" style="background: #2563eb; padding: 6px 12px; font-size: 13px; color: #fff;">Disk Storage</button>
            <button class="tab-btn storage-tab-btn" id="storageTabBtn-reports" onclick="switchStorageTab('reports')" style="background: #4b5563; padding: 6px 12px; font-size: 13px; color: #fff;">Report Archives</button>
        </div>
        
        <div id="storageDiskContainer">
            <div class="storage-summary" style="margin-bottom: 15px;">
                <div>
                    <span>Total space</span>
                    <strong>${systemStorage.total}</strong>
                </div>
                <div>
                    <span>Available</span>
                    <strong>${systemStorage.available}</strong>
                </div>
            </div>
            <div class="storage-list">${blocks}</div>
        </div>
        
        <div id="storageReportsContainer" style="display: none;"></div>
    `;
    
    activeStorageTab = 'disk';
}

function openStorageModal() {
    renderStorageModal();
    const modal = document.getElementById("storageModal");
    modal.classList.add("active");
    modal.setAttribute("aria-hidden", "false");
}

function closeStorageModal() {
    const modal = document.getElementById("storageModal");
    modal.classList.remove("active");
    modal.setAttribute("aria-hidden", "true");
}

document.getElementById("searchPlate").addEventListener("keypress", event => {
    if (event.key === "Enter") applyFilters();
});

window.onload = () => {
    const darkModeEnabled = localStorage.getItem("darkMode") === "true";
    document.body.classList.toggle("dark-mode", darkModeEnabled);
    document.getElementById("darkModeToggle").checked = darkModeEnabled;
    updateCameraTime();
    setInterval(updateCameraTime, 1000);
    checkAuth();
};

// --- CATEGORY MANAGEMENT ---
async function loadCategories() {
    try {
        const res = await apiFetch(`${API}/categories/`);
        const categories = await res.json();
        
        // Populate category list UI
        const list = document.getElementById("categoryList");
        if (list) {
            list.innerHTML = categories.map(c => `
                <li style="background: var(--bg-tertiary); padding: 8px 12px; border-radius: 6px; display: flex; align-items: center; gap: 10px; border-left: 4px solid ${c.color}">
                    <span>${c.icon || ''}</span>
                    <strong>${c.name}</strong> 
                    <span style="font-size: 11px; opacity: 0.7;">(${c.code})</span>
                    <button onclick="deleteCategory(${c.id})" style="padding: 2px 6px; font-size: 12px; background: #dc2626; margin-left: auto;">X</button>
                </li>
            `).join("");
        }

        // Populate hotlist dropdown
        const hotlistSelect = document.getElementById("hotlist_category");
        if (hotlistSelect) {
            hotlistSelect.innerHTML = `<option value="">Select Category</option>` + 
                categories.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
        }

        // Populate filter dropdown in records
        const filterSelect = document.getElementById("filterCategory");
        if (filterSelect) {
            const currentVal = filterSelect.value;
            filterSelect.innerHTML = `<option value="">All Categories</option>` + 
                categories.map(c => `<option value="${c.name}">${c.name}</option>`).join("");
            filterSelect.value = currentVal; // preserve selection
        }
    } catch (err) {
        console.error("Failed to load categories", err);
    }
}

async function addCategory() {
    const name = document.getElementById("new_category_name").value.trim();
    const code = document.getElementById("new_category_code").value.trim();
    const icon = document.getElementById("new_category_icon").value.trim();
    const color = document.getElementById("new_category_color").value;
    const description = document.getElementById("new_category_description").value.trim();
    
    if (!name || !code) {
        alert("Name and Code are required");
        return;
    }
    
    try {
        await apiFetch(`${API}/categories/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, code, icon, color, description })
        });
        document.getElementById("new_category_name").value = "";
        document.getElementById("new_category_code").value = "";
        document.getElementById("new_category_description").value = "";
        loadCategories();
    } catch (err) {
        console.error("Failed to add category", err);
    }
}

async function deleteCategory(id) {
    if (!confirm("Delete category?")) return;
    try {
        await apiFetch(`${API}/categories/${id}`, { method: "DELETE" });
        loadCategories();
    } catch (err) {
        console.error("Failed to delete category", err);
    }
}

// --- HOTLIST MANAGEMENT ---
async function loadHotlist() {
    try {
        const res = await apiFetch(`${API}/hotlist/`);
        const hotlist = await res.json();
        
        const table = document.getElementById("hotlistTable");
        if (table) {
            table.innerHTML = hotlist.map(h => `
                <tr>
                    <td>${h.plate_number}</td>
                    <td><span class="category-badge" style="background-color: ${h.category_color}33; color: ${h.category_color}; border: 1px solid ${h.category_color}55;">${h.category_icon || ''} ${h.category_name || "Unknown"}</span></td>
                    <td><button onclick="deleteHotlistEntry(${h.id})" style="padding: 4px 8px; font-size: 12px; background: #dc2626;">Remove</button></td>
                </tr>
            `).join("");
        }
    } catch (err) {
        console.error("Failed to load hotlist", err);
    }
}

async function addHotlistEntry() {
    const plate_number = document.getElementById("hotlist_plate").value.trim().toUpperCase();
    const category_id = document.getElementById("hotlist_category").value;
    
    if (!plate_number || !category_id) {
        alert("Please enter plate and select category");
        return;
    }
    
    try {
        const res = await apiFetch(`${API}/hotlist/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ plate_number, category_id: parseInt(category_id) })
        });
        if (!res.ok) throw new Error(await res.text());
        
        document.getElementById("hotlist_plate").value = "";
        loadHotlist();
    } catch (err) {
        console.error("Failed to add to hotlist", err);
        alert("Failed to add: " + err.message);
    }
}

async function deleteHotlistEntry(id) {
    if (!confirm("Remove plate from hotlist?")) return;
    try {
        await apiFetch(`${API}/hotlist/${id}`, { method: "DELETE" });
        loadHotlist();
    } catch (err) {
        console.error("Failed to delete hotlist entry", err);
    }
}

// --- SESSIONS & AUDIT LOGS FUNCTIONALITY ---

let currentSessionTab = 'login';
let sessionPage = 1;
const sessionLimit = 15;

async function switchSessionTab(tab) {
    currentSessionTab = tab;
    
    // Toggle active classes on tab buttons
    document.querySelectorAll('#sessions .tabs .tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.background = '#4b5563';
    });
    
    // Using explicit target to set active styling
    const activeBtn = event.currentTarget;
    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.background = '#2563eb';
    }
    
    // Toggle tables display
    const loginContainer = document.getElementById('loginDetailsTableContainer');
    const sessionContainer = document.getElementById('sessionDetailsTableContainer');
    
    if (tab === 'login') {
        loginContainer.style.display = 'block';
        sessionContainer.style.display = 'none';
    } else {
        loginContainer.style.display = 'none';
        sessionContainer.style.display = 'block';
    }
    
    sessionPage = 1;
    await loadSessions();
}

async function loadSessions() {
    const searchVal = document.getElementById('sessionSearch').value.trim();
    const fromDate = document.getElementById('sessionFromDate').value;
    const toDate = document.getElementById('sessionToDate').value;
    
    const params = new URLSearchParams({
        page: sessionPage,
        limit: sessionLimit
    });
    
    if (searchVal) params.set('search', searchVal);
    if (fromDate) params.set('from_date', fromDate);
    if (toDate) params.set('to_date', toDate);
    
    try {
        const res = await apiFetch(`${API}/sessions/?${params.toString()}`);
        if (!res.ok) throw new Error(await res.text());
        
        const data = await res.json();
        renderSessions(data.results, data.total);
    } catch (err) {
        console.error(err);
        showToast("Failed to load sessions: " + err.message, "error");
    }
}

function calculateDuration(loginTime, logoutTime) {
    const start = parseUTCDate(loginTime);
    const end = logoutTime ? parseUTCDate(logoutTime) : new Date();
    
    const diffMs = end - start;
    if (diffMs < 0) return "-";
    
    const diffSecs = Math.floor(diffMs / 1000);
    const hours = Math.floor(diffSecs / 3600);
    const minutes = Math.floor((diffSecs % 3600) / 60);
    const seconds = diffSecs % 60;
    
    let parts = [];
    if (hours > 0) parts.push(`${hours}h`);
    if (minutes > 0 || hours > 0) parts.push(`${minutes}m`);
    parts.push(`${seconds}s`);
    
    return parts.join(' ');
}

function renderSessions(results, total) {
    const loginBody = document.getElementById('loginDetailsTableBody');
    const sessionBody = document.getElementById('sessionDetailsTableBody');
    
    if (currentSessionTab === 'login') {
        loginBody.innerHTML = '';
        if (results.length === 0) {
            loginBody.innerHTML = `<tr><td colspan="6" class="empty-cell">No sessions found</td></tr>`;
        } else {
            results.forEach(s => {
                const tr = document.createElement('tr');
                const isFailed = s.access_status === 'Failed';
                const statusBadge = `<span class="category-badge" style="background-color: ${isFailed ? '#fecaca' : '#bbf7d0'}; color: ${isFailed ? '#b91c1c' : '#15803d'};">${s.access_status}</span>`;
                
                tr.innerHTML = `
                    <td>${formatTime(s.login_time)}</td>
                    <td><strong>${s.user_login_id}</strong></td>
                    <td>${formatTime(s.logout_time)}</td>
                    <td>${statusBadge}</td>
                    <td>${s.ip_address || '-'}</td>
                    <td style="font-size: 11px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${s.user_agent || ''}">${s.user_agent || '-'}</td>
                `;
                loginBody.appendChild(tr);
            });
        }
    } else {
        sessionBody.innerHTML = '';
        if (results.length === 0) {
            sessionBody.innerHTML = `<tr><td colspan="7" class="empty-cell">No sessions found</td></tr>`;
        } else {
            results.forEach(s => {
                const tr = document.createElement('tr');
                const durationStr = calculateDuration(s.login_time, s.logout_time);
                const activeBadge = `<span class="category-badge" style="background-color: ${s.is_active ? '#bbf7d0' : '#e5e7eb'}; color: ${s.is_active ? '#15803d' : '#374151'};">${s.is_active ? 'Active' : 'Inactive'}</span>`;
                
                tr.innerHTML = `
                    <td style="font-family: monospace; font-size: 12px;">${s.id}</td>
                    <td><strong>${s.user_login_id}</strong></td>
                    <td>${activeBadge}</td>
                    <td>${formatTime(s.login_time)}</td>
                    <td>${formatTime(s.logout_time)}</td>
                    <td>${durationStr}</td>
                    <td>${s.ip_address || '-'}</td>
                `;
                sessionBody.appendChild(tr);
            });
        }
    }
    
    // Pagination UI
    const startIdx = results.length > 0 ? (sessionPage - 1) * sessionLimit + 1 : 0;
    const endIdx = (sessionPage - 1) * sessionLimit + results.length;
    document.getElementById('sessionPaginationInfo').innerText = `Showing ${startIdx}-${endIdx} of ${total}`;
    
    document.getElementById('prevSessionPageBtn').disabled = sessionPage === 1;
    document.getElementById('nextSessionPageBtn').disabled = endIdx >= total;
}

function applySessionFilters() {
    sessionPage = 1;
    loadSessions();
}

function resetSessionFilters() {
    document.getElementById('sessionSearch').value = '';
    document.getElementById('sessionFromDate').value = '';
    document.getElementById('sessionToDate').value = '';
    sessionPage = 1;
    loadSessions();
}

function changeSessionPage(delta) {
    sessionPage += delta;
    loadSessions();
}

// --- AUDIT LOGS FUNCTIONALITY ---

let auditPage = 1;
const auditLimit = 15;

async function loadAuditLogs() {
    const searchVal = document.getElementById('auditSearch').value.trim();
    const entityType = document.getElementById('auditFilterEntity').value;
    const fromDate = document.getElementById('auditFromDate').value;
    const toDate = document.getElementById('auditToDate').value;
    
    const params = new URLSearchParams({
        page: auditPage,
        limit: auditLimit
    });
    
    if (searchVal) params.set('search', searchVal);
    if (entityType) params.set('entity_type', entityType);
    if (fromDate) params.set('from_date', fromDate);
    if (toDate) params.set('to_date', toDate);
    
    try {
        const res = await apiFetch(`${API}/audit-logs/?${params.toString()}`);
        if (!res.ok) throw new Error(await res.text());
        
        const data = await res.json();
        renderAuditLogs(data.results, data.total);
    } catch (err) {
        console.error(err);
        showToast("Failed to load audit logs: " + err.message, "error");
    }
}

function renderAuditLogs(results, total) {
    const body = document.getElementById('auditLogsTableBody');
    body.innerHTML = '';
    
    if (results.length === 0) {
        body.innerHTML = `<tr><td colspan="6" class="empty-cell">No audit logs found</td></tr>`;
    } else {
        results.forEach(log => {
            const tr = document.createElement('tr');
            tr.style.cursor = 'pointer';
            
            tr.innerHTML = `
                <td>${formatTime(log.timestamp)}</td>
                <td><strong>${log.user_login_id}</strong></td>
                <td><span class="category-badge" style="background-color: #e8f1ff; color: #2563eb; font-size: 11px;">${log.action}</span></td>
                <td>${log.entity_type || '-'}</td>
                <td>${log.entity_id || '-'}</td>
                <td>${log.ip_address || '-'}</td>
            `;
            
            tr.onclick = () => openAuditDetailModal(log);
            body.appendChild(tr);
        });
    }
    
    // Pagination UI
    const startIdx = results.length > 0 ? (auditPage - 1) * auditLimit + 1 : 0;
    const endIdx = (auditPage - 1) * auditLimit + results.length;
    document.getElementById('auditPaginationInfo').innerText = `Showing ${startIdx}-${endIdx} of ${total}`;
    
    document.getElementById('prevAuditPageBtn').disabled = auditPage === 1;
    document.getElementById('nextAuditPageBtn').disabled = endIdx >= total;
}

function applyAuditFilters() {
    auditPage = 1;
    loadAuditLogs();
}

function resetAuditFilters() {
    document.getElementById('auditSearch').value = '';
    document.getElementById('auditFilterEntity').value = '';
    document.getElementById('auditFromDate').value = '';
    document.getElementById('auditToDate').value = '';
    auditPage = 1;
    loadAuditLogs();
}

function changeAuditPage(delta) {
    auditPage += delta;
    loadAuditLogs();
}

function formatValueForDiff(val) {
    if (!val) return "None / Empty";
    try {
        const parsed = JSON.parse(val);
        return JSON.stringify(parsed, null, 2);
    } catch (e) {
        return val;
    }
}

function openAuditDetailModal(log) {
    document.getElementById('auditDetAction').innerText = log.action;
    document.getElementById('auditDetUser').innerText = log.user_login_id;
    document.getElementById('auditDetEntity').innerText = log.entity_type ? `${log.entity_type} (ID: ${log.entity_id || '-'})` : '-';
    document.getElementById('auditDetTime').innerText = formatTime(log.timestamp);
    
    document.getElementById('auditDetOld').innerText = formatValueForDiff(log.old_value);
    document.getElementById('auditDetNew').innerText = formatValueForDiff(log.new_value);
    
    const modal = document.getElementById('auditDetailModal');
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
}

function closeAuditDetailModal() {
    const modal = document.getElementById('auditDetailModal');
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
}

// --- DELETE RECORD FUNCTIONALITY ---
async function deleteSelectedRecord() {
    if (!selectedRecordId) return;
    
    if (!confirm("Are you sure you want to delete this vehicle record? This action cannot be undone and will be audited.")) {
        return;
    }
    
    try {
        const res = await apiFetch(`${API}/records/${selectedRecordId}`, {
            method: 'DELETE'
        });
        
        if (!res.ok) throw new Error(await res.text());
        
        showToast("Record deleted successfully", "success");
        selectedRecordId = null;
        setPanel("record", {});
        await loadRecords();
        updateDashboardSummary();
    } catch (err) {
        console.error(err);
        showToast("Failed to delete record: " + err.message, "error");
    }
}

async function loadActiveModel() {
    try {
        const res = await apiFetch(`${API}/models/`);
        if (!res.ok) return;
        const data = await res.json();
        const selector = document.getElementById("modelSelector");
        if (selector) selector.value = data.active;
        const display = document.getElementById("activeModelDisplay");
        if (display) display.innerText = data.active;
    } catch (err) {
        console.error("Failed to load active model:", err);
    }
}

async function selectModel() {
    const selector = document.getElementById("modelSelector");
    if (!selector) return;
    const selected = selector.value;
    
    try {
        const res = await apiFetch(`${API}/models/select`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model: selected })
        });
        
        if (!res.ok) throw new Error(await res.text());
        
        const display = document.getElementById("activeModelDisplay");
        if (display) display.innerText = selected;
        showToast(`Model ${selected} selected successfully`, "success");
    } catch (err) {
        console.error("Failed to select model:", err);
        showToast("Failed to select model: " + err.message, "error");
    }
}



/* ==========================================================
   ADVANCED SEARCH LOGIC
   ========================================================== */
function openAdvancedSearch() {
    document.getElementById('advancedSearchModal').classList.add('open');
}

function closeAdvancedSearch() {
    document.getElementById('advancedSearchModal').classList.remove('open');
}

function applyQuickSearch() {
    const quickPlate = document.getElementById('quickSearchPlate').value;
    document.getElementById('searchPlate').value = quickPlate;
    applyFilters();
}

// Add Escape key listener for advanced search modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('advancedSearchModal')?.classList.contains('open')) {
        closeAdvancedSearch();
    }
});


/* ==========================================================
   CAMERA GRID LOGIC
   ========================================================== */
const cameras = [
    { id: 'cam1', name: 'Main Entrance' },
    { id: 'cam2', name: 'Exit Gate' },
    { id: 'cam3', name: 'Visitor Lane' },
    { id: 'cam4', name: 'Parking A' },
    { id: 'cam5', name: 'Parking B' },
    { id: 'cam6', name: 'Loading Dock' },
    { id: 'cam7', name: 'Perimeter North' },
    { id: 'cam8', name: 'Perimeter South' }
];

let activeModalCameraId = null;

function renderCameraGrid() {
    const grid = document.getElementById('cameraGrid');
    if (!grid) return;
    
    grid.innerHTML = cameras.map((cam, index) => {
        const title = `CAM 0${index + 1}`;
        const isCam1 = cam.id === 'cam1';
        const initialStatusClass = isCam1 ? 'buffering' : 'offline';
        const initialStatusText = isCam1 ? '&#11044; Buffering' : '&#11044; No Signal';
        
        return `
            <div class="camera-tile" onclick="openCameraModal({
                cameraId: '${cam.id}',
                cameraName: '${title}',
                cameraSubtitle: '${cam.name}',
                statusClass: document.getElementById('${cam.id}-status').className,
                statusText: document.getElementById('${cam.id}-status').innerHTML,
                timestamp: document.getElementById('${cam.id}-time').innerText,
                imageSrc: document.getElementById('${cam.id}-img').src
            })">
                <div class="camera-tile-header">
                    <div>
                        <h4 class="camera-tile-title">${title}</h4>
                        <div class="camera-tile-subtitle">${cam.name}</div>
                    </div>
                    <div style="text-align: right;">
                        <div id="${cam.id}-status" class="cam-status ${initialStatusClass}">${initialStatusText}</div>
                        <div id="${cam.id}-time" style="font-size: 10px; color: #64748b; margin-top: 2px;">-</div>
                    </div>
                </div>
                <div class="camera-tile-body">
                    <img id="${cam.id}-img" src="" style="display: none; width: 100%; height: 100%; object-fit: cover;">
                    <div id="${cam.id}-placeholder" style="color: #475569; font-size: 12px;">${isCam1 ? 'Waiting for stream...' : 'No Signal'}</div>
                    <div class="camera-tile-hover-icon">&#9974;</div>
                </div>
            </div>
        `;
    }).join('');
}

function openCameraModal(data) {
    activeModalCameraId = data.cameraId;
    
    document.getElementById('modalCamTitle').innerText = data.cameraName;
    document.getElementById('modalCamSubtitle').innerText = data.cameraSubtitle;
    
    const modalStatus = document.getElementById('modalCamStatus');
    modalStatus.className = "cam-status " + data.statusClass;
    modalStatus.innerHTML = data.statusText;
    
    document.getElementById('modalCamTime').innerText = data.timestamp;
    
    const feed = document.getElementById('modalCamFeed');
    const spinner = document.getElementById('modalSpinner');
    
    if (data.imageSrc && data.imageSrc !== window.location.href) {
        feed.src = data.imageSrc;
        feed.style.display = 'block';
        spinner.style.display = 'none';
    } else {
        feed.style.display = 'none';
        spinner.style.display = 'flex';
    }
    
    document.getElementById('cameraModal').classList.add('open');
}

function closeCameraModal() {
    activeModalCameraId = null;
    document.getElementById('cameraModal').classList.remove('open');
    if (document.fullscreenElement) {
        document.exitFullscreen().catch(err => console.error(err));
    }
}

function toggleFullscreen() {
    const container = document.getElementById('modalVideoContainer');
    if (!document.fullscreenElement) {
        container.requestFullscreen().catch(err => {
            console.error(`Error attempting to enable full-screen mode: ${err.message} (${err.name})`);
        });
    } else {
        document.exitFullscreen();
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('cameraModal')?.classList.contains('open')) {
        closeCameraModal();
    }
});


function updateCameraGridStatus(record) {
    // Map random camera or use record.camera if it maps to cam1-cam8
    const camIndex = Math.floor(Math.random() * 8) + 1;
    const camId = `cam${camIndex}`;
    
    const isStolen = record.category_code === "stolen" || record.category === "Stolen" || record.category_name === "Stolen";
    const isVip = record.category_code === "vip" || record.category === "VIP" || record.category_name === "VIP";
    
    let statusClass = "online";
    let statusText = "&#11044; Online";
    if (isStolen) {
        statusClass = "alert";
        statusText = "&#9888; STOLEN";
    } else if (isVip) {
        statusClass = "vip";
        statusText = "&#11044; VIP";
    }
    
    const statusEl = document.getElementById(`${camId}-status`);
    if (statusEl) {
        statusEl.className = `cam-status ${statusClass}`;
        statusEl.innerHTML = statusText;
    }
    
    const timeEl = document.getElementById(`${camId}-time`);
    if (timeEl) {
        timeEl.innerText = formatTime(record.time);
    }
    
    const imgEl = document.getElementById(`${camId}-img`);
    const placeholder = document.getElementById(`${camId}-placeholder`);
    if (imgEl && placeholder) {
        const imageSrc = getImageUrl(record.plate_image_url || record.image_url || (record.image ? `data:image/jpeg;base64,${record.image}` : ""));
        if (imageSrc) {
            imgEl.src = imageSrc;
            imgEl.style.display = 'block';
            placeholder.style.display = 'none';
        }
    }
    
    // Update modal if it's currently open for this camera
    if (activeModalCameraId === camId) {
        const modalStatus = document.getElementById('modalCamStatus');
        if (modalStatus) {
            modalStatus.className = `cam-status ${statusClass}`;
            modalStatus.innerHTML = statusText;
        }
        const modalTime = document.getElementById('modalCamTime');
        if (modalTime) {
            modalTime.innerText = formatTime(record.time);
        }
        const modalFeed = document.getElementById('modalCamFeed');
        const spinner = document.getElementById('modalSpinner');
        if (modalFeed && spinner) {
            modalFeed.src = imgEl.src;
            modalFeed.style.display = 'block';
            spinner.style.display = 'none';
        }
    }
}
