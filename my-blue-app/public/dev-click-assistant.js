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
    let globalFeatureRequest = "";
    let globalFeatureDetails = "";
    let activeModal = null; // Keeps track of which modal is open


    // ===== New Component Mode State =====
    let isNewComponentMode = false;

    // ===== Utilities =====
    const saveSelections = () => {
        // Ensure referenceComponents exists
        if (!window.referenceComponents) window.referenceComponents = {};

        // Merge reference_components from each requirement into global referenceComponents
        selections.forEach(req => {
            if (req.reference_components && Array.isArray(req.reference_components)) {
                req.reference_components.forEach(refObj => {
                    if (!referenceComponents[refObj.name]) {
                        referenceComponents[refObj.name] = {
                            name: refObj.name,
                            description: refObj.description || "",
                        };
                    } else {
                        // Update description if changed
                        referenceComponents[refObj.name].description = refObj.description || referenceComponents[refObj.name].description;
                    }
                });
            }
        });

        // Save everything together
        const dataToSave = {
            feature_request:  "",
            requirements: selections,
            referenceComponents: referenceComponents,
        };

        localStorage.setItem("dev_requirements", JSON.stringify(dataToSave, null, 2));

        console.log("✅ Saved requirements with reference components:", dataToSave);
    };


    const saveReferenceComponents = () => {
        localStorage.setItem("dev_reference_components", JSON.stringify(referenceComponents));
    };

    function loadSelections() {
        try {
            const saved = localStorage.getItem("dev_requirements");
            if (saved) {
                const parsed = JSON.parse(saved);
                // Ensure selections is an array
                selections = Array.isArray(parsed.requirements) ? parsed.requirements : [];
            } else {
                selections = [];
            }
        } catch (e) {
            console.error("Error loading selections:", e);
            selections = [];
        }
    }

// Call this at the start
    loadSelections();

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

    function getAppComponentInfo() {
        // Try to find the main App component
        const rootElement = document.getElementById('root');
        if (!rootElement) return null;

        // Look for React components in the root
        for (const k in rootElement) {
            if (k.startsWith("__reactFiber$") || k.startsWith("__reactInternalInstance$")) {
                let fiber = rootElement[k];
                while (fiber) {
                    if (fiber.type && (fiber.type.name === 'App' || fiber.type.name === 'Router' || fiber.type.displayName === 'Router')) {
                        // Found a router or app component, try to extract route information
                        return extractRouteInfo(fiber);
                    }
                    fiber = fiber.return;
                }
            }
        }

        return null;
    }

    function extractRouteInfo(fiber) {
        const routes = [];
        const components = new Set();

        function traverseFiber(node, depth = 0) {
            if (depth > 10) return; // Prevent infinite recursion

            if (node && node.type) {
                // Check for Route components
                if (node.type.name === 'Route' || node.type.displayName === 'Route') {
                    const props = node.memoizedProps || node.pendingProps || {};
                    if (props.path) {
                        routes.push({
                            path: props.path,
                            element: props.element?.type?.name || 'Unknown'
                        });
                    }
                }

                // Collect component names
                if (node.type.name && node.type.name !== 'Route' && node.type.name !== 'Router') {
                    components.add(node.type.name);
                }

                // Traverse children
                if (node.child) {
                    traverseFiber(node.child, depth + 1);
                }
            }

            // Traverse siblings
            if (node && node.sibling) {
                traverseFiber(node.sibling, depth);
            }
        }

        traverseFiber(fiber);

        return {
            routes: routes,
            components: Array.from(components)
        };
    }

    function generateAppComponentText(routeInfo) {
        if (!routeInfo || routeInfo.routes.length === 0) {
            return "React App with routing configuration";
        }

        const imports = [...new Set(routeInfo.components)].map(comp => `import ${comp} from './components/${comp}';`).join('\n');
        const routes = routeInfo.routes.map(route =>
            `        <Route path="${route.path}" element={<${route.element} />} />`
        ).join('\n');

        return `import React from 'react';\nimport { BrowserRouter as Router, Routes, Route } from 'react-router-dom';\n${imports}\n\nfunction App() {\n  return (\n    <Router>\n      <Routes>\n${routes}\n      </Routes>\n    </Router>\n  );\n}\n\nexport default App;`;
    }

    function createDefaultAppComponent() {
        // Always create a default App component
        const defaultAppCode = `import React from 'react';\nimport { BrowserRouter as Router, Routes, Route } from 'react-router-dom';\n\nfunction App() {\n  return (\n    <Router>\n      <Routes>\n        <Route path="/" element={<div>Home Page</div>} />\n        <Route path="/contact" element={<div>Contact Page</div>} />\n      </Routes>\n    </Router>\n  );\n}\n\nexport default App;`;

        const defaultAppText = "Complete React App with routing";

        // Always add App as reference component
        referenceComponents['App'] = {
            name: 'App',
            text: defaultAppText,
            appCode: defaultAppCode,
            description: "Main App component",
            timestamp: new Date().toISOString()
        };

        // Always add App requirement if not already present
        const hasAppRequirement = selections.some(req => req.component === 'App');
        if (!hasAppRequirement) {
            selections.push({
                component: 'App',
                text: defaultAppText,
                requirement: 'Update App.js routing configuration as needed for new features',
                referenceComponent: 'App',
                appCode: defaultAppCode,
                isNewComponent: false
            });
        }

        saveReferenceComponents();
        saveSelections();
        updateCount();

        console.log("✅ Added default App component to references and requirements");
        return true;
    }

    function parseFeatureDetails(featureDetails) {
        if (!featureDetails || !featureDetails.trim()) return {};

        try {
            // Clean the input - remove extra quotes and fix formatting
            let cleanedDetails = featureDetails.trim();

            // If it looks like JSON but has issues, try to fix common problems
            if (cleanedDetails.includes('{') && cleanedDetails.includes('}')) {
                // Try to parse as JSON first
                try {
                    return JSON.parse(cleanedDetails);
                } catch (e) {
                    console.log("❌ JSON parse failed, trying to fix formatting...");

                    // Fix common JSON formatting issues
                    cleanedDetails = cleanedDetails
                        .replace(/"\s*:\s*"/g, '": "')  // Fix spacing around colons
                        .replace(/,\s*"/g, ', "')        // Fix spacing after commas
                        .replace(/",\s*"/g, '", "')      // Fix spacing between properties
                        .replace(/"\s*}/g, '"}')         // Fix spacing before closing brace
                        .replace(/{\s*"/g, '{"');        // Fix spacing after opening brace

                    try {
                        return JSON.parse(cleanedDetails);
                    } catch (e2) {
                        console.log("❌ Fixed JSON parse also failed, using fallback");
                    }
                }
            }

            // Fallback: treat as plain text description
            return {
                description: featureDetails
            };
        } catch (error) {
            console.error("❌ Feature details parsing error:", error);
            return {
                description: featureDetails
            };
        }
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

    // ===== Input Box with Draggable functionality =====
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
            left: `${Math.min(x + 10, window.innerWidth - 450)}px`,
            top: `${Math.min(y + 10, window.innerHeight - 350)}px`,
            background: "rgba(25, 25, 35, 0.98)",
            color: "#fff",
            padding: "15px",
            borderRadius: "8px",
            zIndex: 1000000,
            width: "430px",
            fontFamily: "system-ui, sans-serif",
            fontSize: "14px",
            boxShadow: "0 8px 25px rgba(0,0,0,0.5)",
            border: "1px solid #444",
            backdropFilter: "blur(10px)",
            cursor: "move"
        });

        box.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; cursor: move;">
                <b style="color: #00e0ff; font-size: 15px;">${componentName}</b>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 11px; color: #888; background: ${isReference ? '#ffaa00' : 'transparent'}; padding: 2px 6px; border-radius: 10px;">
                        ${isReference ? '⭐ Reference' : ''}
                    </span>
                    <button id="closeBox" style="
                        background: none;
                        border: none;
                        color: #fff;
                        font-size: 18px;
                        cursor: pointer;
                        padding: 0;
                        width: 24px;
                        height: 24px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        border-radius: 4px;
                        transition: background 0.2s;
                    " title="Close">×</button>
                </div>
            </div>
            <div style="font-size: 11px; color: #aaa; margin-bottom: 8px; background: rgba(0,0,0,0.3); padding: 6px; border-radius: 4px; word-break: break-all;">
                ${domPath}
            </div>
            ${elementText ? `<div style="font-size: 12px; color: #ccc; margin-bottom: 8px; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 4px; border-left: 3px solid #666;">
                📝 "${elementText}"
            </div>` : ''}
            
            <div style="margin-bottom: 8px;">
                <label style="display: block; font-size: 12px; color: #aaa; margin-bottom: 4px;">Feature Request (Global)</label>
                <input type="text" id="featureRequest" placeholder="Overall feature description..." value="${globalFeatureRequest}" style="
                    width: 100%; 
                    padding: 8px;
                    border: 1px solid #555; 
                    border-radius: 4px;
                    outline: none; 
                    font-size: 13px; 
                    background: #1a1a2a; 
                    color: #fff;
                    font-family: inherit;
                ">
            </div>
            
            <div style="margin-bottom: 8px;">
                <label style="display: block; font-size: 12px; color: #aaa; margin-bottom: 4px;">Feature Details (Global - Use valid JSON)</label>
                <textarea id="featureDetails" placeholder='{"name": "Feature Name", "description": "Feature description", "fields": ["field1", "field2"]}' style="
                    width: 100%; 
                    padding: 8px;
                    border: 1px solid #555; 
                    border-radius: 4px;
                    outline: none; 
                    resize: vertical; 
                    height: 60px; 
                    font-size: 13px; 
                    background: #1a1a2a; 
                    color: #fff;
                    font-family: inherit;
                ">${globalFeatureDetails}</textarea>
            </div>
            
            <textarea 
                id="componentRequirement"
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

        const textarea = box.querySelector("#componentRequirement");
        textarea.focus();

        // ===== Draggable functionality =====
        let isDragging = false;
        let currentX;
        let currentY;
        let initialX;
        let initialY;
        let xOffset = 0;
        let yOffset = 0;

        function dragStart(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'BUTTON') {
                return;
            }

            initialX = e.clientX - xOffset;
            initialY = e.clientY - yOffset;

            if (e.target === box || e.target.closest('div[style*="cursor: move"]')) {
                isDragging = true;
            }
        }

        function dragEnd(e) {
            initialX = currentX;
            initialY = currentY;
            isDragging = false;
        }

        function drag(e) {
            if (isDragging) {
                e.preventDefault();
                currentX = e.clientX - initialX;
                currentY = e.clientY - initialY;

                xOffset = currentX;
                yOffset = currentY;

                setTranslate(currentX, currentY, box);
            }
        }

        function setTranslate(xPos, yPos, el) {
            el.style.transform = `translate3d(${xPos}px, ${yPos}px, 0)`;
        }

        box.addEventListener("mousedown", dragStart);
        document.addEventListener("mouseup", dragEnd);
        document.addEventListener("mousemove", drag);

        // Event handlers
        box.querySelector("#saveBtn").onclick = () => {
            const requirementText = textarea.value.trim();
            const featureRequest = box.querySelector("#featureRequest").value.trim();
            const featureDetails = box.querySelector("#featureDetails").value.trim();

            if (!requirementText) {
                showNotification("Please describe the requirement", "warning");
                return;
            }

            // Update global feature request and details (persist)
            globalFeatureRequest = featureRequest;
            globalFeatureDetails = featureDetails;
            // Save globals to localStorage so they persist across UI interactions
            localStorage.setItem("dev_global_feature_request", globalFeatureRequest);
            localStorage.setItem("dev_global_feature_details", globalFeatureDetails);

            // Push new requirement object (existing component)
            selections.push({
                component: componentName,
                text: elementText,
                requirement: requirementText,
                referenceComponent: isReference ? componentName : null,
                isNewComponent: false // Mark as existing component
            });

            saveSelections();
            updateCount();

            // Clean up event listeners
            box.removeEventListener("mousedown", dragStart);
            document.removeEventListener("mouseup", dragEnd);
            document.removeEventListener("mousemove", drag);

            box.remove();
            activeInputBox = null;
            showNotification(`✅ Requirement saved for ${componentName}`, "success");
        };

        box.querySelector("#referenceToggle").onclick = () => {
            let referenceData = {
                name: componentName,
                text: elementText,
                description: `Reference component: ${componentName}`,
                timestamp: new Date().toISOString()
            };

            if (referenceComponents[componentName]) {
                delete referenceComponents[componentName];
                showNotification(`❌ ${componentName} removed as reference`, "info");
            } else {
                referenceComponents[componentName] = referenceData;
                showNotification(`⭐ ${componentName} set as reference component`, "success");
            }
            saveReferenceComponents();

            // Clean up event listeners
            box.removeEventListener("mousedown", dragStart);
            document.removeEventListener("mouseup", dragEnd);
            document.removeEventListener("mousemove", drag);

            box.remove();
            activeInputBox = null;
        };

        box.querySelector("#cancelBtn").onclick = () => {
            // Clean up event listeners
            box.removeEventListener("mousedown", dragStart);
            document.removeEventListener("mouseup", dragEnd);
            document.removeEventListener("mousemove", drag);

            box.remove();
            activeInputBox = null;
        };

        box.querySelector("#closeBox").onclick = () => {
            // Clean up event listeners
            box.removeEventListener("mousedown", dragStart);
            document.removeEventListener("mouseup", dragEnd);
            document.removeEventListener("mousemove", drag);

            box.remove();
            activeInputBox = null;
        };

        // Remove outside click closing - now only close button closes
        // Add hover effect to close button
        const closeBtn = box.querySelector("#closeBox");
        closeBtn.onmouseenter = () => {
            closeBtn.style.background = "rgba(255,255,255,0.2)";
        };
        closeBtn.onmouseleave = () => {
            closeBtn.style.background = "none";
        };
    }

    // ===== New Component Modal =====
    function showNewComponentModal() {
        if (activeModal) return;
        activeModal = "new_component";

        document.querySelectorAll(".dev-modal-overlay").forEach((el) => el.remove());

        const overlay = document.createElement("div");
        overlay.className = "dev-modal-overlay";
        Object.assign(overlay.style, {
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            background: "rgba(0,0,0,0.75)",
            zIndex: 1000000,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
        });

        const modal = document.createElement("div");
        modal.className = "dev-new-component-modal";
        Object.assign(modal.style, {
            background: "#1a1a2a",
            color: "#fff",
            padding: "25px",
            borderRadius: "12px",
            width: "600px",
            maxHeight: "85%",
            overflowY: "auto",
            border: "1px solid #444",
        });

        modal.innerHTML = `
    <h3 style="color: #00ff88; margin-bottom: 15px;">🆕 Create New Component</h3>

    <label style="display:block; font-size:13px; color:#ccc; margin-bottom:5px;">Component Name</label>
    <input id="newComponentName" style="width:100%; padding:8px; border-radius:6px; border:none; margin-bottom:12px; background:#2a2a3a; color:#fff;" placeholder="e.g. ProductList" />

    <label style="display:block; font-size:13px; color:#ccc; margin-bottom:5px;">Component Type</label>
    <input id="newComponentType" style="width:100%; padding:8px; border-radius:6px; border:none; margin-bottom:12px; background:#2a2a3a; color:#fff;" placeholder="e.g. component / page / context" />

    <label style="display:block; font-size:13px; color:#ccc; margin-bottom:5px;">Requirement / Description</label>
    <textarea id="newComponentRequirement" rows="4" style="width:100%; padding:8px; border-radius:6px; border:none; background:#2a2a3a; color:#fff; resize:vertical; margin-bottom:12px;"></textarea>

    <label style="display:block; font-size:13px; color:#ccc; margin-bottom:5px;">Reference Components (App added by default)</label>
    <select id="newReferenceComponents" multiple style="width:100%; padding:8px; border-radius:6px; border:none; background:#2a2a3a; color:#fff; height:120px; margin-bottom:12px;"></select>

    <div id="referenceDescriptionsContainer" style="margin-bottom:20px;"></div>

    <div style="text-align:right;">
      <button id="cancelNewComponent" style="padding:8px 14px; background:#555; color:#fff; border:none; border-radius:6px; margin-right:10px; cursor:pointer;">Cancel</button>
      <button id="saveNewComponent" style="padding:8px 14px; background:#00ff88; color:#000; border:none; border-radius:6px; font-weight:bold; cursor:pointer;">Save</button>
    </div>
  `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        const refSelect = modal.querySelector("#newReferenceComponents");
        const refDescContainer = modal.querySelector("#referenceDescriptionsContainer");

        // 🧠 Fetch all reference components dynamically (you can modify this list or make it API-based)
        // If you already have them stored somewhere (like `referenceComponents` array), use that instead.
        let availableRefs = [];
        // try {
        //     availableRefs = Object.keys(referenceComponents || {}); // e.g. { App: {...}, Header: {...} }
        // } catch {
        //     availableRefs = ["App", "Header", "ContactForm"]; // fallback
        // }
        availableRefs = ["App", "Header", "ContactForm"];
        // Populate the multi-select
        availableRefs.forEach((ref) => {
            const opt = document.createElement("option");
            opt.value = ref;
            opt.textContent = ref;
            refSelect.appendChild(opt);
        });

        // Create description boxes when selecting components
        refSelect.addEventListener("change", () => {
            refDescContainer.innerHTML = "";
            const selectedRefs = Array.from(refSelect.selectedOptions).map(
                (opt) => opt.value
            );

            selectedRefs.forEach((ref) => {
                const div = document.createElement("div");
                div.style.marginBottom = "10px";
                div.innerHTML = `
        <label style="display:block; font-size:13px; color:#ccc; margin-bottom:3px;">${ref} Description</label>
        <textarea data-ref="${ref}" rows="2" style="width:100%; padding:6px; border-radius:6px; border:none; background:#2a2a3a; color:#fff; resize:vertical;"></textarea>
      `;
                refDescContainer.appendChild(div);
            });
        });

        // Close modal function
        const closeModal = () => {
            overlay.remove();
            activeModal = null;
        };

        // Event handlers - using direct function references
        const cancelHandler = (e) => {
            e.stopPropagation();
            closeModal();
        };

        const saveHandler = (e) => {
            e.stopPropagation();

            const name = modal.querySelector("#newComponentName").value.trim();
            const type = modal.querySelector("#newComponentType").value.trim();
            const req = modal.querySelector("#newComponentRequirement").value.trim();

            if (!name || !req) {
                alert("Please enter component name and requirement");
                return;
            }

            // Gather selected refs + always include App
            const selectedRefs = Array.from(refSelect.selectedOptions).map(
                (opt) => opt.value
            );
            const allRefs = Array.from(new Set(["App", ...selectedRefs])); // ensure no duplicates

            // Build referenceComponents for this requirement
            const reqReferenceComponents = allRefs.map((ref) => {
                const textarea = refDescContainer.querySelector(`textarea[data-ref="${ref}"]`);
                const desc = textarea ? textarea.value.trim() : "";
                // Update global referenceComponents object
                if (!referenceComponents[ref]) {
                    referenceComponents[ref] = {
                        name: ref,
                        description: desc || `Reference for ${ref} component`,
                    };
                }
                return referenceComponents[ref];
            });

            // Push new requirement entry
            const newReq = {
                component: name,
                componentType: type || "component",
                requirement: req,
                referenceComponents: reqReferenceComponents,
                isNewComponent: true,
            };

            selections.push(newReq);

            // Save everything to localStorage
            const dataToSave = {
                feature_request: "", // can add input if needed
                requirements: selections,
                referenceComponents: referenceComponents,
            };
            localStorage.setItem("dev_requirements", JSON.stringify(dataToSave, null, 2));

            closeModal();

            // Update the UI
            updateCount();
            showNotification(`✅ New component "${name}" added`, "success");

            // Show review modal to confirm
            showReviewModal();
        };

        // Attach event listeners directly to buttons
        const cancelBtn = modal.querySelector("#cancelNewComponent");
        const saveBtn = modal.querySelector("#saveNewComponent");

        cancelBtn.addEventListener("click", cancelHandler);
        saveBtn.addEventListener("click", saveHandler);

        // Close when clicking outside the modal
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) {
                closeModal();
            }
        });

        // Prevent modal close when clicking inside modal
        modal.addEventListener("click", (e) => {
            e.stopPropagation();
        });

        // Also close on Escape key
        const escapeHandler = (e) => {
            if (e.key === "Escape") {
                closeModal();
                document.removeEventListener("keydown", escapeHandler);
            }
        };
        document.addEventListener("keydown", escapeHandler);

        // Clean up escape handler when modal closes
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) {
                document.removeEventListener("keydown", escapeHandler);
                closeModal();
            }
        });
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
            
            <!-- Add New Component Mode Toggle -->
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 6px;">
                <span style="font-size: 12px; color: #aaa;">Mode:</span>
                <button id="toggleMode" style="
                    padding: 6px 12px;
                    background: ${isNewComponentMode ? '#00ff88' : '#444'};
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    color: ${isNewComponentMode ? '#000' : '#fff'};
                    font-size: 11px;
                    font-weight: bold;
                    flex: 1;
                ">
                    ${isNewComponentMode ? '🆕 New Component' : '✏️ Edit Existing'}
                </button>
            </div>
            
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <button id="reviewBtn" title="Review requirements" style="flex: 1;">📝 Review</button>
                <button id="referencesBtn" title="Manage references" style="flex: 1;">⭐ Refs</button>
                <button id="sendBtn" title="Send to backend" style="flex: 1;">🚀 Send</button>
                <button id="clearBtn" title="Clear all" style="flex: 1;">🗑️ Clear</button>
            </div>
            
            <!-- New Component Mode Instructions -->
            ${isNewComponentMode ? `
            <div style="margin-top: 10px; font-size: 11px; color: #00ff88; text-align: center; padding: 6px; background: rgba(0,255,136,0.1); border-radius: 4px; border: 1px solid #00ff88;">
                🆕 New Component Mode: Click anywhere to add new component
            </div>
            ` : `
            <div style="margin-top: 10px; font-size: 11px; color: #888; text-align: center; padding: 6px; background: rgba(0,0,0,0.3); border-radius: 4px;">
                ✏️ Edit Mode: Ctrl+Click to modify existing components
            </div>
            `}
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
        toolbar.querySelector("#toggleMode").style.background = isNewComponentMode ? "#00ff88" : "#444";
        toolbar.querySelector("#toggleMode").style.color = isNewComponentMode ? "#000" : "#fff";

        // Event handlers
        toolbar.querySelector("#reviewBtn").onclick = showReviewModal;
        toolbar.querySelector("#referencesBtn").onclick = showReferencesModal;
        toolbar.querySelector("#sendBtn").onclick = sendToBackend;
        toolbar.querySelector("#clearBtn").onclick = () => {
            if (selections.length > 0 || Object.keys(referenceComponents).length > 0) {
                if (confirm("Clear all requirements and references?")) {
                    clearSelections();
                    referenceComponents = {};
                    globalFeatureRequest = "";
                    globalFeatureDetails = "";
                    saveReferenceComponents();
                    updateCount();
                    showNotification("🧹 All requirements and references cleared", "info");
                }
            } else {
                showNotification("Nothing to clear", "info");
            }
        };

        // Add mode toggle handler
        toolbar.querySelector("#toggleMode").onclick = () => {
            isNewComponentMode = !isNewComponentMode;
            buildToolbar(); // Rebuild toolbar to reflect mode change
            showNotification(
                isNewComponentMode ? "🆕 New Component Mode: Click anywhere to add new component" : "✏️ Edit Mode: Ctrl+Click to modify existing components",
                "info"
            );
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
        // Prevent opening if another modal is active
        if (activeModal) return;
        activeModal = 'review';

        // Remove any existing overlay just in case
        document.querySelectorAll(".dev-modal-overlay").forEach(el => el.remove());

        const overlay = document.createElement("div");
        overlay.className = "dev-modal-overlay";
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
            maxWidth: "700px",
            maxHeight: "80%",
            overflowY: "auto",
            border: "1px solid #444",
            boxShadow: "0 20px 40px rgba(0,0,0,0.5)"
        });

        // Separate new and existing components
        const newComponents = selections.filter(req => req.isNewComponent);
        const existingComponents = selections.filter(req => !req.isNewComponent);

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

            <div style="margin-bottom: 20px;">
                <div style="font-size: 14px; color: #aaa; display: flex; gap: 15px; margin-bottom: 15px;">
                    <span>📋 ${selections.length} requirement(s)</span>
                    <span>⭐ ${Object.keys(referenceComponents).length} reference(s)</span>
                    <span>🆕 ${newComponents.length} new component(s)</span>
                    <span>✏️ ${existingComponents.length} existing component(s)</span>
                </div>
                
                <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                    <div style="font-size: 14px; color: #00e0ff; margin-bottom: 8px; font-weight: bold;">Feature Request</div>
                    <div style="font-size: 13px; color: #ccc;">${globalFeatureRequest || "Not set"}</div>
                </div>
                
                <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                    <div style="font-size: 14px; color: #00e0ff; margin-bottom: 8px; font-weight: bold;">Feature Details</div>
                    <div style="font-size: 13px; color: #ccc; white-space: pre-wrap;">${globalFeatureDetails || "Not set"}</div>
                </div>
            </div>
            
            ${newComponents.length > 0 ? `
            <div style="margin-bottom: 20px;">
                <h4 style="color: #00ff88; margin-bottom: 10px; font-size: 16px;">🆕 New Components to Create</h4>
                <div id="newComponentsList"></div>
            </div>
            ` : ''}
            
            ${existingComponents.length > 0 ? `
            <div style="margin-bottom: 20px;">
                <h4 style="color: #00e0ff; margin-bottom: 10px; font-size: 16px;">✏️ Existing Components to Modify</h4>
                <div id="existingComponentsList"></div>
            </div>
            ` : ''}
            
            ${selections.length === 0 ? `
            <div id="emptyState" style="text-align: center; padding: 40px; color: #666; background: rgba(255,255,255,0.05); border-radius: 8px;">
                <div style="font-size: 48px; margin-bottom: 10px;">📝</div>
                <div style="font-size: 16px; margin-bottom: 8px;">No requirements yet</div>
                <div style="font-size: 13px; color: #888;">Use the toolbar to add requirements</div>
            </div>
            ` : ''}
            
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

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        const newComponentsList = modal.querySelector("#newComponentsList");
        const existingComponentsList = modal.querySelector("#existingComponentsList");

        // Render new components
        if (newComponents.length > 0) {
            newComponents.forEach((req, index) => {
                const reqElement = document.createElement("div");
                reqElement.style.cssText = `
                    background: rgba(0,255,136,0.1);
                    padding: 15px;
                    margin-bottom: 12px;
                    border-radius: 8px;
                    border-left: 4px solid #00ff88;
                    transition: background 0.2s;
                `;

                reqElement.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                        <div style="flex: 1;">
                            <b style="color: #00ff88; font-size: 15px;">${req.component}</b>
                            <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
                                <span style="background: #00ff88; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 10px; font-weight: bold;">
                                    NEW ${req.componentType?.toUpperCase() || 'COMPONENT'}
                                </span>
                                ${req.referenceComponent ?
                    `<span style="background: #ffaa00; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 10px; font-weight: bold;">REFERENCE: ${req.referenceComponent}</span>` :
                    ''
                }
                            </div>
                        </div>
                        <button class="deleteReq" data-index="${selections.indexOf(req)}" style="
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
                `;

                newComponentsList.appendChild(reqElement);
            });
        }

        // Render existing components
        if (existingComponents.length > 0) {
            existingComponents.forEach((req, index) => {
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
                                ${req.referenceComponent ?
                    `<span style="background: #ffaa00; color: #000; padding: 2px 6px; border-radius: 10px; font-size: 10px; font-weight: bold;">REFERENCE</span>` :
                    ''
                }
                            </div>
                        </div>
                        <button class="deleteReq" data-index="${selections.indexOf(req)}" style="
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
                    ${req.text ? `
                    <div style="font-size: 12px; color: #ccc; margin-bottom: 8px; padding: 6px; background: rgba(255,255,255,0.05); border-radius: 4px;">
                        📝 "${req.text}"
                    </div>
                    ` : ''}
                `;

                existingComponentsList.appendChild(reqElement);
            });
        }

        // Add delete handlers
        modal.querySelectorAll(".deleteReq").forEach(btn => {
            btn.onclick = (e) => {
                const index = parseInt(e.target.getAttribute("data-index"));
                if (confirm("Delete this requirement?")) {
                    selections.splice(index, 1);
                    saveSelections();
                    overlay.remove();
                    activeModal = null;
                    updateCount();
                    showReviewModal();
                }
            };
        });


        // Export JSON
        modal.querySelector("#exportJson").onclick = () => {
            const dataStr = JSON.stringify({
                requirements: selections,
                globalFeatureRequest,
                globalFeatureDetails,
                referenceComponents
            }, null, 2);
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
        const closeModal = () => {
            overlay.remove();
            activeModal = null;
        };
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
                            <div style="font-size: 12px; color: #ccc; margin-top: 4px;">
                                ${ref.description || "No description"}
                            </div>
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

            // ALWAYS create default App component before sending
            console.log("🔄 Always adding App component to response...");
            createDefaultAppComponent();

            // Parse feature details properly
            const parsedFeatureDetails = parseFeatureDetails(globalFeatureDetails);
            console.log("📋 Parsed feature details:", parsedFeatureDetails);

            // Construct the payload - ALWAYS include App component
            const payload = {
                feature_request: globalFeatureRequest,
                requirements: selections.map(req => ({
                    component: req.component,
                    text: req.text,
                    requirement: req.requirement,
                    referenceComponent: req.referenceComponent,
                    isNewComponent: req.isNewComponent || false, // Include the new component flag
                    componentType: req.componentType || 'component'
                })),
                referenceComponents: Object.keys(referenceComponents).reduce((acc, key) => {
                    const ref = referenceComponents[key];
                    acc[key] = {
                        name: ref.name,
                        text: ref.text,
                        description: ref.description || `Reference component: ${ref.name}`,
                        ...(ref.appCode && { appCode: ref.appCode })
                    };
                    return acc;
                }, {}),
                feature_details: Object.keys(parsedFeatureDetails).length > 0 ? parsedFeatureDetails : undefined
            };

            // ALWAYS ensure App component is in requirements
            const hasAppInRequirements = payload.requirements.some(req => req.component === 'App');
            if (!hasAppInRequirements) {
                payload.requirements.push({
                    component: 'App',
                    text: 'Complete React App with routing',
                    requirement: 'Update App.js routing configuration as needed for new features',
                    referenceComponent: 'App',
                    appCode: referenceComponents['App']?.appCode,
                    isNewComponent: false
                });
            }

            // ALWAYS ensure App component is in referenceComponents
            if (!payload.referenceComponents['App']) {
                payload.referenceComponents['App'] = {
                    name: 'App',
                    text: 'Complete React App with routing',
                    appCode: `import React from 'react';\nimport { BrowserRouter as Router, Routes, Route } from 'react-router-dom';\n\nfunction App() {\n  return (\n    <Router>\n      <Routes>\n        <Route path="/" element={<div>Home Page</div>} />\n        <Route path="/contact" element={<div>Contact Page</div>} />\n      </Routes>\n    </Router>\n  );\n}\n\nexport default App;`,
                    description: "Main App component"
                };
            }

            // Remove feature_details if it's empty
            if (payload.feature_details && Object.keys(payload.feature_details).length === 0) {
                delete payload.feature_details;
            }

            console.log("📤 Final payload being sent:", payload);

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
                globalFeatureRequest = "";
                globalFeatureDetails = "";
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
        // Click handler - different behavior based on mode
        document.addEventListener("click", (e) => {
            // Ignore clicks on our own UI elements, overlays, or modals
            if (activeInputBox || e.target.closest(".dev-input-box") || e.target.closest(".dev-toolbar") || e.target.closest(".dev-modal") || e.target.closest(".dev-modal-overlay")) {
                return;
            }

            if (isNewComponentMode) {
                // In new component mode, show the new component modal on any click
                e.preventDefault();
                e.stopPropagation();
                showNewComponentModal();
            } else {
                // In existing mode, ONLY use Ctrl+Click for existing components
                // Regular clicks should do nothing (allow normal page interaction)
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    e.stopPropagation();

                    const clickedElement = e.target;
                    const componentName = getReactComponentName(clickedElement);
                    const domPath = getEnhancedDomPath(clickedElement);

                    highlightElement(clickedElement);
                    showInputBox(e.clientX, e.clientY, clickedElement, componentName, domPath);
                }
                // If not Ctrl+Click in Edit Mode, do nothing - allow normal page clicks
            }
        }, true);

        // Keyboard shortcuts
        document.addEventListener("keydown", (e) => {
            // Escape to close active input box
            if (e.key === "Escape" && activeInputBox) {
                // Clean up event listeners
                if (activeInputBox) {
                    // Attempt to remove drag listeners if they exist (safe-guard - functions in outer scope)
                    try { activeInputBox.removeEventListener("mousedown", dragStart); } catch(_) {}
                }
                activeInputBox.remove();
                activeInputBox = null;
            }

            // Ctrl+R to show review modal
            if (e.key === "r" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                showReviewModal();
            }

            // Ctrl+N to toggle new component mode
            if (e.key === "n" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                isNewComponentMode = !isNewComponentMode;
                buildToolbar();
                showNotification(
                    isNewComponentMode ? "🆕 New Component Mode: Click anywhere to add new component" : "✏️ Edit Mode: Ctrl+Click to modify existing components",
                    "info"
                );
            }
        });

        console.log("✅ Event listeners setup");
    }

    // ===== Initialize =====
    function initialize() {
        console.log("🚀 Initializing Dev Assistant...");

        // Load saved globals if exist
        globalFeatureRequest = localStorage.getItem("dev_global_feature_request") || globalFeatureRequest;
        globalFeatureDetails = localStorage.getItem("dev_global_feature_details") || globalFeatureDetails;

        // Clean up any existing instances
        const existingToolbar = document.querySelector(".dev-toolbar");
        if (existingToolbar) existingToolbar.remove();

        const existingInput = document.querySelector(".dev-input-box");
        if (existingInput) existingInput.remove();

        // ALWAYS create default App component on initialization
        console.log("🔄 Always adding App component on initialization...");
        createDefaultAppComponent();

        // Build toolbar
        buildToolbar();

        // Setup event listeners
        setupEventListeners();

        // Show welcome message
        setTimeout(() => {
            showNotification("🧠 Dev Assistant Ready - Use Ctrl+Click (Edit Mode) or click anywhere (New Component Mode)", "success");
        }, 500);

        console.log("✅ Dev Assistant initialized successfully");
        console.log(`📊 ${selections.length} requirements, ${Object.keys(referenceComponents).length} references loaded`);
        console.log(`🎯 Current mode: ${isNewComponentMode ? 'New Component' : 'Edit Existing'}`);
    }

    // Start initialization when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        // DOM already ready, initialize immediately
        setTimeout(initialize, 100);
    }

})();