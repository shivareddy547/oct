// /media/shivareddy/E/oct-2025/15_evg/oct/my-blue-app/public/dev-click-assistant.js
(function() {
    'use strict';

    // Only run on localhost
    if (!["localhost", "127.0.0.1", "0.0.0.0"].includes(window.location.hostname)) {
        return;
    }

    console.log("🧠 Dev Assistant Loading...");

    // ===== Persistent state =====
    let selections = JSON.parse(localStorage.getItem("dev_requirements") || "[]");
    let referenceComponents = JSON.parse(localStorage.getItem("dev_reference_components") || "{}");
    let activeInputBox = null;
    let toolbar = null;

    // ===== Utilities =====
    const saveSelections = () => {
        localStorage.setItem("dev_requirements", JSON.stringify(selections));
    };

    const saveReferenceComponents = () => {
        localStorage.setItem("dev_reference_components", JSON.stringify(referenceComponents));
    };

    const clearSelections = () => {
        selections = [];
        saveSelections();
        updateCount();
    };

    function getReactComponentName(node) {
        if (!node) return "Unknown";

        // Try React fiber detection
        for (const k in node) {
            if (k.startsWith("__reactFiber$") || k.startsWith("__reactInternalInstance$")) {
                let fiber = node[k];
                while (fiber) {
                    if (fiber.type && fiber.type.name) return fiber.type.name;
                    if (fiber.elementType && fiber.elementType.name) return fiber.elementType.name;
                    fiber = fiber.return;
                }
            }
        }

        // Fallback: climb up DOM tree
        let current = node;
        let depth = 0;
        while (current && depth < 5) {
            // Check for data attributes
            const dataComponent = current.getAttribute("data-component");
            if (dataComponent) return dataComponent;

            // Check for meaningful class names
            const className = current.className;
            if (className && typeof className === 'string') {
                const componentClass = className.split(' ').find(cls =>
                    cls.includes('component') || cls.includes('Component') ||
                    cls.includes('container') || cls.includes('Container') ||
                    cls.includes('page') || cls.includes('Page') ||
                    cls.includes('section') || cls.includes('Section') ||
                    cls.includes('header') || cls.includes('Header') ||
                    cls.includes('footer') || cls.includes('Footer') ||
                    cls.includes('nav') || cls.includes('Nav')
                );
                if (componentClass) return componentClass;
            }

            // Check for ID
            const id = current.id;
            if (id) return id;

            // Check for meaningful tag names with content
            const tagName = current.tagName?.toLowerCase();
            const textContent = current.textContent?.trim();
            if (tagName && textContent && textContent.length > 0) {
                if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'button', 'a', 'form', 'input', 'textarea'].includes(tagName)) {
                    return `${tagName}-${textContent.substring(0, 15).replace(/\s+/g, '-')}`;
                }
            }

            current = current.parentElement;
            depth++;
        }

        // Final fallback
        return node.tagName?.toLowerCase() || "element";
    }

    function getEnhancedDomPath(el) {
        if (!el) return "";
        const stack = [];
        let current = el;

        while (current && current.nodeType === 1) {
            let selector = current.tagName.toLowerCase();

            if (current.id) {
                selector += `#${current.id}`;
                stack.unshift(selector);
                break;
            }

            const className = current.className;
            if (className && typeof className === 'string') {
                const validClasses = className.split(/\s+/).filter(c =>
                    c && c.length > 2 && !c.includes('hover') && !c.includes('active')
                ).slice(0, 2);
                if (validClasses.length > 0) {
                    selector += `.${validClasses.join('.')}`;
                }
            }

            stack.unshift(selector);
            current = current.parentElement;

            if (stack.length >= 6) break;
        }

        return stack.join(" > ");
    }

    function highlightElement(el) {
        const rect = el.getBoundingClientRect();
        const box = document.createElement("div");
        Object.assign(box.style, {
            position: "fixed",
            left: rect.left + "px",
            top: rect.top + "px",
            width: rect.width + "px",
            height: rect.height + "px",
            border: "3px solid #00ff00",
            borderRadius: "4px",
            pointerEvents: "none",
            zIndex: 999999,
            backgroundColor: "rgba(0, 255, 0, 0.1)",
            boxShadow: "0 0 0 9999px rgba(0, 0, 0, 0.2)"
        });
        document.body.appendChild(box);
        setTimeout(() => box.remove(), 1500);
        return box;
    }

    function getElementTextContent(el) {
        if (!el) return "";
        const text = el.textContent?.trim() || "";
        if (text) return text.substring(0, 100);

        const childrenWithText = Array.from(el.children || []).find(child =>
            child.textContent?.trim().length > 0
        );
        return childrenWithText?.textContent?.trim().substring(0, 100) || "No text content";
    }

    function showNotification(message, type = "info") {
        const colors = {
            info: "#00e0ff",
            success: "#00ff88",
            warning: "#ffaa00",
            error: "#ff4444"
        };

        const notification = document.createElement("div");
        Object.assign(notification.style, {
            position: "fixed",
            top: "20px",
            right: "20px",
            background: colors[type] || colors.info,
            color: "#000",
            padding: "12px 16px",
            borderRadius: "6px",
            zIndex: 1000003,
            fontFamily: "system-ui, sans-serif",
            fontSize: "14px",
            fontWeight: "bold",
            boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
            border: "1px solid rgba(255,255,255,0.3)"
        });
        notification.textContent = message;
        document.body.appendChild(notification);
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 3000);
    }

    // ===== Input Box =====
    function showInputBox(x, y, target, componentName, domPath) {
        if (activeInputBox) {
            activeInputBox.remove();
            activeInputBox = null;
        }

        const isReference = referenceComponents[componentName];
        const elementText = getElementTextContent(target);

        const box = document.createElement("div");
        box.className = "dev-input-box";
        Object.assign(box.style, {
            position: "fixed",
            left: `${Math.min(x + 10, window.innerWidth - 420)}px`,
            top: `${Math.min(y + 10, window.innerHeight - 280)}px`,
            background: "rgba(25, 25, 35, 0.98)",
            color: "#fff",
            padding: "15px",
            borderRadius: "8px",
            zIndex: 1000000,
            width: "400px",
            fontFamily: "system-ui, sans-serif",
            fontSize: "14px",
            boxShadow: "0 8px 25px rgba(0,0,0,0.5)",
            border: "1px solid #444",
            backdropFilter: "blur(10px)"
        });

        box.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <b style="color: #00e0ff; font-size: 15px;">${componentName}</b>
                <span style="font-size: 11px; color: #888; background: ${isReference ? '#ffaa00' : 'transparent'}; padding: 2px 6px; border-radius: 10px;">
                    ${isReference ? '⭐ Reference' : ''}
                </span>
            </div>
            <div style="font-size: 11px; color: #aaa; margin-bottom: 8px; background: rgba(0,0,0,0.3); padding: 6px; border-radius: 4px; word-break: break-all;">
                ${domPath}
            </div>
            ${elementText ? `<div style="font-size: 12px; color: #ccc; margin-bottom: 8px; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 4px; border-left: 3px solid #666;">
                📝 "${elementText}"
            </div>` : ''}
            <textarea 
                placeholder="Describe what should be changed or added to this component..." 
                style="
                    width: 100%; 
                    margin: 8px 0; 
                    padding: 12px;
                    border: 1px solid #555; 
                    border-radius: 6px;
                    outline: none; 
                    resize: vertical; 
                    height: 80px; 
                    font-size: 14px; 
                    background: #1a1a2a; 
                    color: #fff;
                    font-family: inherit;
                    transition: border-color 0.2s;
                "
            ></textarea>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px;">
                <div>
                    <button id="referenceToggle" style="
                        padding: 8px 12px;
                        background: ${isReference ? '#ffaa00' : '#555'};
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        color: ${isReference ? '#000' : '#fff'};
                        font-size: 12px;
                        font-weight: bold;
                    ">
                        ${isReference ? '⭐ Reference' : '⭐ Set as Reference'}
                    </button>
                </div>
                <div>
                    <button id="cancelBtn" style="
                        padding: 8px 16px;
                        background: #666;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        color: #fff;
                        margin-right: 8px;
                        font-size: 13px;
                    ">Cancel</button>
                    <button id="saveBtn" style="
                        padding: 8px 16px;
                        background: #00e0ff;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        color: #000;
                        font-weight: bold;
                        font-size: 13px;
                    ">💾 Save</button>
                </div>
            </div>
        `;

        document.body.appendChild(box);
        activeInputBox = box;

        const textarea = box.querySelector("textarea");
        textarea.focus();

        // Event handlers
        box.querySelector("#saveBtn").onclick = () => {
            const requirementText = textarea.value.trim();
            if (!requirementText) {
                showNotification("Please describe the requirement", "warning");
                return;
            }

            selections.push({
                component: componentName,
                domPath: domPath,
                text: elementText,
                requirement: requirementText,
                url: window.location.pathname,
                referenceComponent: isReference ? componentName : null
            });

            saveSelections();
            updateCount();
            box.remove();
            activeInputBox = null;
            showNotification(`✅ Requirement saved for ${componentName}`, "success");
        };

        box.querySelector("#referenceToggle").onclick = () => {
            if (referenceComponents[componentName]) {
                delete referenceComponents[componentName];
                showNotification(`❌ ${componentName} removed as reference`, "info");
            } else {
                referenceComponents[componentName] = {
                    name: componentName,
                    text: elementText,
                    domPath: domPath,
                    url: window.location.pathname,
                    timestamp: new Date().toISOString()
                };
                showNotification(`⭐ ${componentName} set as reference component`, "success");
            }
            saveReferenceComponents();
            box.remove();
            activeInputBox = null;
        };

        box.querySelector("#cancelBtn").onclick = () => {
            box.remove();
            activeInputBox = null;
        };

        // Close on outside click
        setTimeout(() => {
            const closeOnOutsideClick = (e) => {
                if (activeInputBox && !activeInputBox.contains(e.target)) {
                    activeInputBox.remove();
                    activeInputBox = null;
                    document.removeEventListener('click', closeOnOutsideClick);
                }
            };
            document.addEventListener('click', closeOnOutsideClick);
        }, 100);
    }

    // ===== Toolbar =====
    function buildToolbar() {
        // Remove existing toolbar if any
        const existingToolbar = document.querySelector(".dev-toolbar");
        if (existingToolbar) {
            existingToolbar.remove();
        }

        toolbar = document.createElement("div");
        toolbar.className = "dev-toolbar";
        Object.assign(toolbar.style, {
            position: "fixed",
            bottom: "20px",
            right: "20px",
            zIndex: 1000001,
            background: "rgba(30, 30, 40, 0.95)",
            color: "#fff",
            padding: "15px",
            borderRadius: "10px",
            fontFamily: "system-ui, sans-serif",
            fontSize: "14px",
            boxShadow: "0 8px 25px rgba(0,0,0,0.4)",
            border: "1px solid #444",
            backdropFilter: "blur(10px)",
            minWidth: "200px"
        });

        const referenceCount = Object.keys(referenceComponents).length;

        toolbar.innerHTML = `
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                <span style="font-weight: bold; color: #00e0ff; font-size: 15px;">🧠 Dev Assistant</span>
                <span id="countBadge" style="
                    background: #00e0ff; 
                    color: #000; 
                    padding: 2px 8px; 
                    border-radius: 12px; 
                    font-size: 12px; 
                    font-weight: bold;
                    min-width: 20px;
                    text-align: center;
                ">${selections.length}</span>
                <span id="refBadge" style="
                    background: #ffaa00; 
                    color: #000; 
                    padding: 2px 8px; 
                    border-radius: 12px; 
                    font-size: 12px; 
                    font-weight: bold;
                    min-width: 20px;
                    text-align: center;
                ">${referenceCount}</span>
            </div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <button id="reviewBtn" title="Review requirements" style="flex: 1;">📝 Review</button>
                <button id="referencesBtn" title="Manage references" style="flex: 1;">⭐ Refs</button>
                <button id="sendBtn" title="Send to backend" style="flex: 1;">🚀 Send</button>
                <button id="clearBtn" title="Clear all" style="flex: 1;">🗑️ Clear</button>
            </div>
            <div style="margin-top: 10px; font-size: 11px; color: #888; text-align: center; padding: 6px; background: rgba(0,0,0,0.3); border-radius: 4px;">
                Ctrl + Click anywhere to add requirement
            </div>
        `;

        document.body.appendChild(toolbar);

        // Style buttons
        toolbar.querySelectorAll("button").forEach(btn => {
            Object.assign(btn.style, {
                padding: "8px 12px",
                border: "none",
                borderRadius: "6px",
                background: "#444",
                color: "#fff",
                cursor: "pointer",
                fontSize: "12px",
                transition: "all 0.2s ease",
                fontWeight: "500"
            });

            btn.onmouseenter = () => {
                btn.style.background = "#555";
                btn.style.transform = "translateY(-1px)";
            };
            btn.onmouseleave = () => {
                btn.style.background = "#444";
                btn.style.transform = "translateY(0)";
            };
        });

        // Specific button styles
        toolbar.querySelector("#sendBtn").style.background = "#00e0ff";
        toolbar.querySelector("#sendBtn").style.color = "#000";
        toolbar.querySelector("#referencesBtn").style.background = "#ffaa00";
        toolbar.querySelector("#referencesBtn").style.color = "#000";

        // Event handlers
        toolbar.querySelector("#reviewBtn").onclick = showReviewModal;
        toolbar.querySelector("#referencesBtn").onclick = showReferencesModal;
        toolbar.querySelector("#sendBtn").onclick = sendToBackend;
        toolbar.querySelector("#clearBtn").onclick = () => {
            if (selections.length > 0 || Object.keys(referenceComponents).length > 0) {
                if (confirm("Clear all requirements and references?")) {
                    clearSelections();
                    referenceComponents = {};
                    saveReferenceComponents();
                    updateCount();
                    showNotification("🧹 All requirements and references cleared", "info");
                }
            } else {
                showNotification("Nothing to clear", "info");
            }
        };

        console.log("✅ Toolbar built successfully");
    }

    function updateCount() {
        if (toolbar) {
            const countBadge = toolbar.querySelector("#countBadge");
            const refBadge = toolbar.querySelector("#refBadge");
            if (countBadge) countBadge.textContent = selections.length;
            if (refBadge) refBadge.textContent = Object.keys(referenceComponents).length;
        }
    }

    // ===== Review Modal =====
    function showReviewModal() {
        const overlay = document.createElement("div");
        Object.assign(overlay.style, {
            position: "fixed",
            left: 0,
            top: 0,
            width: "100%",
            height: "100%",
            background: "rgba(0,0,0,0.8)",
            zIndex: 1000002,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            backdropFilter: "blur(5px)"
        });

        const modal = document.createElement("div");
        Object.assign(modal.style, {
            background: "#1a1a2a",
            color: "#fff",
            padding: "25px",
            borderRadius: "12px",
            width: "90%",
            maxWidth: "600px",
            maxHeight: "80%",
            overflowY: "auto",
            border: "1px solid #444",
            boxShadow: "0 20px 40px rgba(0,0,0,0.5)"
        });

        modal.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid #444; padding-bottom: 15px;">
                <h3 style="margin: 0; color: #00e0ff; font-size: 18px;">📝 Requirements Review</h3>
                <button id="closeReview" style="
                    background: none; 
                    border: none; 
                    color: #fff; 
                    font-size: 24px; 
                    cursor: pointer;
                    padding: 0;
                    width: 30px;
                    height: 30px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                ">×</button>
            </div>
            <div style="margin-bottom: 20px; font-size: 14px; color: #aaa; display: flex; gap: 15px;">
                <span>📋 ${selections.length} requirement(s)</span>
                <span>⭐ ${Object.keys(referenceComponents).length} reference(s)</span>
            </div>
            <div id="requirementsList" style="min-height: 100px;"></div>
            <div style="margin-top: 20px; text-align: right; border-top: 1px solid #444; padding-top: 15px;">
                <button id="exportJson" style="
                    padding: 10px 16px;
                    background: #555;
                    border: none;
                    border-radius: 6px;
                    color: #fff;
                    cursor: pointer;
                    margin-right: 10px;
                    font-size: 13px;
                ">📥 Export JSON</button>
                <button id="closeModal" style="
                    padding: 10px 20px;
                    background: #00e0ff;
                    border: none;
                    border-radius: 6px;
                    color: #000;
                    cursor: pointer;
                    font-weight: bold;
                    font-size: 13px;
                ">Close</button>
            </div>
        `;

        const requirementsList = modal.querySelector("#requirementsList");

        if (selections.length === 0) {
            requirementsList.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #666; background: rgba(255,255,255,0.05); border-radius: 8px;">
                    <div style="font-size: 48px; margin-bottom: 10px;">📝</div>
                    <div style="font-size: 16px; margin-bottom: 8px;">No requirements yet</div>
                    <div style="font-size: 13px; color: #888;">Hold Ctrl and click anywhere to add a requirement</div>
                </div>
            `;
        } else {
            selections.forEach((req, index) => {
                const reqElement = document.createElement("div");
                reqElement.style.cssText = `
                    background: rgba(255,255,255,0.05);
                    padding: 15px;
                    margin-bottom: 12px;
                    border-radius: 8px;
                    border-left: 4px solid #00e0ff;
                    transition: background 0.2s;
                `;

                reqElement.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                        <div style="flex: 1;">
                            <b style="color: #00e0ff; font-size: 15px;">${req.component}</b>
                            <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
                                <small style="color: #888;">${req.url}</small>
                                ${req.referenceComponent ?
                    `<span style="background: #ffaa00; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 10px; font-weight: bold;">REFERENCE</span>` :
                    ''
                }
                            </div>
                        </div>
                        <button class="deleteReq" data-index="${index}" style="
                            background: #ff4444; 
                            color: #fff; 
                            border: none; 
                            padding: 6px 10px; 
                            border-radius: 4px; 
                            cursor: pointer;
                            font-size: 11px;
                            font-weight: bold;
                        ">🗑️ Delete</button>
                    </div>
                    <div style="margin: 10px 0; font-size: 14px; line-height: 1.4; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 4px;">
                        ${req.requirement}
                    </div>
                    <div style="font-size: 11px; color: #666; word-break: break-all; font-family: monospace;">
                        ${req.domPath}
                    </div>
                `;

                requirementsList.appendChild(reqElement);
            });

            // Add delete handlers
            modal.querySelectorAll(".deleteReq").forEach(btn => {
                btn.onclick = (e) => {
                    const index = parseInt(e.target.getAttribute("data-index"));
                    if (confirm("Delete this requirement?")) {
                        selections.splice(index, 1);
                        saveSelections();
                        overlay.remove();
                        updateCount();
                        showReviewModal();
                    }
                };
            });
        }

        // Export JSON
        modal.querySelector("#exportJson").onclick = () => {
            const dataStr = JSON.stringify({ requirements: selections }, null, 2);
            const blob = new Blob([dataStr], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `dev-requirements-${new Date().toISOString().split('T')[0]}.json`;
            a.click();
            URL.revokeObjectURL(url);
            showNotification("📥 Requirements exported", "success");
        };

        // Close handlers
        const closeModal = () => overlay.remove();
        modal.querySelector("#closeReview").onclick = closeModal;
        modal.querySelector("#closeModal").onclick = closeModal;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Close on overlay click
        overlay.onclick = (e) => {
            if (e.target === overlay) {
                closeModal();
            }
        };
    }

    function showReferencesModal() {
        const overlay = document.createElement("div");
        Object.assign(overlay.style, {
            position: "fixed",
            left: 0,
            top: 0,
            width: "100%",
            height: "100%",
            background: "rgba(0,0,0,0.8)",
            zIndex: 1000002,
            display: "flex",
            justifyContent: "center",
            alignItems: "center"
        });

        const modal = document.createElement("div");
        Object.assign(modal.style, {
            background: "#1a1a2a",
            color: "#fff",
            padding: "25px",
            borderRadius: "12px",
            width: "500px",
            maxHeight: "70%",
            overflowY: "auto",
            border: "1px solid #444"
        });

        modal.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid #444; padding-bottom: 15px;">
                <h3 style="color: #ffaa00; margin: 0; font-size: 18px;">⭐ Reference Components</h3>
                <button id="closeRefs" style="
                    background: none; 
                    border: none; 
                    color: #fff; 
                    font-size: 24px; 
                    cursor: pointer;
                ">×</button>
            </div>
            <div id="referencesList"></div>
            <div style="margin-top: 20px; text-align: right; border-top: 1px solid #444; padding-top: 15px;">
                <button id="closeRefsBtn" style="
                    padding: 10px 20px;
                    background: #00e0ff;
                    border: none;
                    border-radius: 6px;
                    color: #000;
                    cursor: pointer;
                    font-weight: bold;
                ">Close</button>
            </div>
        `;

        const refsList = modal.querySelector("#referencesList");
        const refKeys = Object.keys(referenceComponents);

        if (refKeys.length === 0) {
            refsList.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #666;">
                    <div style="font-size: 48px; margin-bottom: 10px;">⭐</div>
                    <div>No reference components set</div>
                    <div style="font-size: 13px; color: #888; margin-top: 8px;">Click "Set as Reference" on any component</div>
                </div>
            `;
        } else {
            refKeys.forEach(refName => {
                const ref = referenceComponents[refName];
                const refElement = document.createElement("div");
                refElement.style.cssText = `
                    background: rgba(255,255,255,0.05);
                    padding: 15px;
                    margin-bottom: 12px;
                    border-radius: 8px;
                    border-left: 4px solid #ffaa00;
                `;

                refElement.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                        <div style="flex: 1;">
                            <b style="color: #ffaa00; font-size: 15px;">${refName}</b>
                            <div style="font-size: 11px; color: #888; margin-top: 4px;">
                                ${new Date(ref.timestamp).toLocaleString()}
                            </div>
                        </div>
                        <button class="removeRef" data-ref="${refName}" style="
                            background: #ff4444; 
                            color: #fff; 
                            border: none; 
                            padding: 6px 10px; 
                            border-radius: 4px; 
                            cursor: pointer;
                            font-size: 11px;
                            font-weight: bold;
                        ">🗑️ Remove</button>
                    </div>
                `;

                refsList.appendChild(refElement);
            });

            modal.querySelectorAll(".removeRef").forEach(btn => {
                btn.onclick = (e) => {
                    const refName = e.target.getAttribute("data-ref");
                    if (confirm(`Remove "${refName}" as reference?`)) {
                        delete referenceComponents[refName];
                        saveReferenceComponents();
                        overlay.remove();
                        updateCount();
                        showReferencesModal();
                    }
                };
            });
        }

        const closeModal = () => overlay.remove();
        modal.querySelector("#closeRefs").onclick = closeModal;
        modal.querySelector("#closeRefsBtn").onclick = closeModal;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);
    }

    // ===== Backend Communication =====
    async function sendToBackend() {
        if (!selections.length) {
            showNotification("No requirements to send!", "warning");
            return;
        }

        try {
            showNotification("📤 Sending requirements to backend...", "info");

            const payload = {
                requirements: selections,
                referenceComponents: referenceComponents,
                metadata: {
                    url: window.location.href,
                    timestamp: new Date().toISOString(),
                    userAgent: navigator.userAgent
                }
            };

            const response = await fetch("http://localhost:8000/api/llm_requirements", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Dev-Assistant": "v2.0"
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log("✅ Backend response:", data);

            showNotification("✅ Requirements sent successfully!", "success");

            if (confirm("Requirements sent successfully! Clear current requirements?")) {
                clearSelections();
                referenceComponents = {};
                saveReferenceComponents();
                updateCount();
            }

        } catch (error) {
            console.error("❌ Send failed:", error);
            showNotification("❌ Failed to send requirements", "error");
        }
    }

    // ===== Event Listeners =====
    function setupEventListeners() {
        // Click handler - Ctrl+Click anywhere
        document.addEventListener("click", (e) => {
            // Ignore clicks on our own UI elements
            if (activeInputBox || e.target.closest(".dev-input-box") || e.target.closest(".dev-toolbar")) {
                return;
            }

            // Use Ctrl+Click to add requirements
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                e.stopPropagation();

                const clickedElement = e.target;
                const componentName = getReactComponentName(clickedElement);
                const domPath = getEnhancedDomPath(clickedElement);

                highlightElement(clickedElement);
                showInputBox(e.clientX, e.clientY, clickedElement, componentName, domPath);
            }
        }, true);

        // Keyboard shortcuts
        document.addEventListener("keydown", (e) => {
            // Escape to close active input box
            if (e.key === "Escape" && activeInputBox) {
                activeInputBox.remove();
                activeInputBox = null;
            }

            // Ctrl+R to show review modal
            if (e.key === "r" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                showReviewModal();
            }
        });

        console.log("✅ Event listeners setup");
    }

    // ===== Initialize =====
    function initialize() {
        console.log("🚀 Initializing Dev Assistant...");

        // Clean up any existing instances
        const existingToolbar = document.querySelector(".dev-toolbar");
        if (existingToolbar) existingToolbar.remove();

        const existingInput = document.querySelector(".dev-input-box");
        if (existingInput) existingInput.remove();

        // Build toolbar
        buildToolbar();

        // Setup event listeners
        setupEventListeners();

        // Show welcome message
        setTimeout(() => {
            showNotification("🧠 Dev Assistant Ready - Ctrl+Click anywhere to add requirements", "success");
        }, 500);

        console.log("✅ Dev Assistant initialized successfully");
        console.log(`📊 ${selections.length} requirements, ${Object.keys(referenceComponents).length} references loaded`);
    }

    // Start initialization when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        // DOM already ready, initialize immediately
        setTimeout(initialize, 100);
    }

})();