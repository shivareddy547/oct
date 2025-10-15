(() => {
    if (!["localhost", "127.0.0.1"].includes(window.location.hostname)) return;

    console.log("🧠 Dev Click Assistant active");

    // ===== Persistent state =====
    let selections = JSON.parse(localStorage.getItem("dev_requirements") || "[]");
    let activeInputBox = null;
    let toolbar = null;
    let referenceComponent = JSON.parse(localStorage.getItem("dev_reference_component") || "null");

    // ===== Utilities =====
    const saveSelections = () => localStorage.setItem("dev_requirements", JSON.stringify(selections));
    const clearSelections = () => { selections = []; saveSelections(); updateCount(); };

    function getReactComponentName(node) {
        for (const k in node) {
            if (k.startsWith("__reactFiber$")) {
                let fiber = node[k];
                while (fiber) {
                    if (fiber.type && fiber.type.name) return fiber.type.name;
                    fiber = fiber.return;
                }
            }
        }
        return node.getAttribute("data-component") || node.tagName.toLowerCase();
    }

    function domPath(el) {
        const stack = [];
        while (el.parentNode) {
            let sibCount = 0, sibIndex = 0;
            for (let i = 0; i < el.parentNode.childNodes.length; i++) {
                const sib = el.parentNode.childNodes[i];
                if (sib.nodeName === el.nodeName) {
                    if (sib === el) sibIndex = sibCount;
                    sibCount++;
                }
            }
            stack.unshift(el.nodeName.toLowerCase() + (sibCount > 1 ? `[${sibIndex + 1}]` : ""));
            el = el.parentNode;
        }
        return stack.slice(1).join(" > ");
    }

    function highlight(el) {
        const rect = el.getBoundingClientRect();
        const box = document.createElement("div");
        Object.assign(box.style, {
            position: "fixed",
            left: rect.left + "px",
            top: rect.top + "px",
            width: rect.width + "px",
            height: rect.height + "px",
            border: "2px solid #00e0ff",
            borderRadius: "4px",
            pointerEvents: "none",
            zIndex: 999999,
        });
        document.body.appendChild(box);
        setTimeout(() => box.remove(), 2000);
    }

    // ===== Floating input =====
    function showInputBox(x, y, target, comp, path) {
        if (activeInputBox) return; // Prevent multiple boxes

        const box = document.createElement("div");
        box.classList.add("dev-input-box");
        Object.assign(box.style, {
            position: "fixed",
            left: `${x + 10}px`,
            top: `${y + 10}px`,
            background: "rgba(0,0,0,0.9)",
            color: "#fff",
            padding: "10px",
            borderRadius: "6px",
            zIndex: 1000000,
            width: "350px",
            fontFamily: "sans-serif",
            fontSize: "13px",
            boxShadow: "0 2px 10px rgba(0,0,0,0.6)",
        });

        box.innerHTML = `
      <div><b>${comp}</b></div>
      <textarea placeholder="Describe what should be done..." style="
          width:100%; margin-top:6px; padding:6px; border:none; border-radius:4px;
          outline:none; resize:none; height:60px; font-size:13px; background:#222; color:#fff;">
      </textarea>
      <div style="text-align:right;margin-top:6px;">
        <button id="saveBtn" style="padding:4px 8px;background:#00e0ff;border:none;border-radius:4px;cursor:pointer;">Save</button>
        <button id="referenceBtn" style="padding:4px 8px;background:#ffaa00;border:none;border-radius:4px;cursor:pointer;">Use as Reference</button>
        <button id="cancelBtn" style="padding:4px 8px;background:#666;border:none;border-radius:4px;cursor:pointer;color:#fff;">Cancel</button>
      </div>
    `;

        document.body.appendChild(box);
        activeInputBox = box;
        const textarea = box.querySelector("textarea");
        textarea.focus();

        // ===== Save requirement =====
        box.querySelector("#saveBtn").onclick = () => {
            const text = textarea.value.trim();
            if (!text) return alert("Please describe the requirement.");
            selections.push({
                component: comp,
                domPath: path,
                text: target.innerText,
                requirement: text,
                url: window.location.pathname,
                referenceComponent: referenceComponent ? referenceComponent.name : null
            });
            saveSelections();
            updateCount();
            activeInputBox.remove();
            activeInputBox = null;
        };

        // ===== Save as reference component =====
        box.querySelector("#referenceBtn").onclick = () => {
            const text = target.innerText.trim();
            if (!text) return alert("Cannot use empty component as reference.");
            referenceComponent = { name: comp, text };
            localStorage.setItem("dev_reference_component", JSON.stringify(referenceComponent));
            alert(`✅ ${comp} saved as reference component`);
            activeInputBox.remove();
            activeInputBox = null;
        };

        box.querySelector("#cancelBtn").onclick = () => {
            activeInputBox.remove();
            activeInputBox = null;
        };
    }

    // ===== Toolbar =====
    function buildToolbar() {
        toolbar = document.createElement("div");
        toolbar.classList.add("dev-toolbar");
        Object.assign(toolbar.style, {
            position: "fixed",
            bottom: "15px",
            right: "15px",
            zIndex: 1000001,
            background: "rgba(30,30,30,0.95)",
            color: "#fff",
            padding: "10px 12px",
            borderRadius: "6px",
            fontFamily: "sans-serif",
            fontSize: "13px",
            boxShadow: "0 2px 8px rgba(0,0,0,0.5)",
        });
        toolbar.innerHTML = `
      🧠 <b>Agent Assistant</b><br>
      <button id="reviewBtn">Review</button>
      <button id="sendBtn">Send</button>
      <button id="clearBtn">Clear</button>
      <span id="count">(0)</span>
    `;
        document.body.appendChild(toolbar);

        toolbar.querySelectorAll("button").forEach(b => {
            b.style.cssText =
                "margin:2px;padding:4px 8px;border:none;border-radius:4px;background:#00e0ff;color:#000;cursor:pointer;";
        });

        toolbar.querySelector("#reviewBtn").onclick = showReviewModal;
        toolbar.querySelector("#sendBtn").onclick = sendToAgent;
        toolbar.querySelector("#clearBtn").onclick = () => {
            if (confirm("Clear all requirements?")) clearSelections();
        };

        updateCount();
    }

    function updateCount() {
        toolbar.querySelector("#count").textContent = `(${selections.length})`;
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
            background: "rgba(0,0,0,0.7)",
            zIndex: 1000002,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
        });

        const box = document.createElement("div");
        Object.assign(box.style, {
            background: "#222",
            color: "#fff",
            padding: "20px",
            borderRadius: "8px",
            width: "500px",
            maxHeight: "80%",
            overflowY: "auto",
        });
        box.innerHTML = `<h3>📝 Review Requirements</h3><hr style="border-color:#444;">`;

        selections.forEach((s, i) => {
            const item = document.createElement("div");
            item.style.marginBottom = "10px";
            item.innerHTML = `
        <b>${i + 1}. ${s.component}</b> <small style="color:#aaa;">(${s.url})</small>
        <div style="margin:5px 0;">${s.requirement}</div>
        ${s.referenceComponent ? `<small style="color:#0f0;">Reference: ${s.referenceComponent}</small>` : ""}
        <button style="background:#f33;color:#fff;border:none;padding:3px 6px;border-radius:4px;cursor:pointer;">Delete</button>
      `;
            item.querySelector("button").onclick = () => {
                selections.splice(i, 1);
                saveSelections();
                overlay.remove();
                updateCount();
                showReviewModal();
            };
            box.appendChild(item);
        });

        const closeBtn = document.createElement("button");
        closeBtn.innerText = "Close";
        closeBtn.style = "margin-top:10px;padding:6px 12px;background:#666;border:none;border-radius:4px;cursor:pointer;color:#fff;";
        closeBtn.onclick = () => overlay.remove();

        box.appendChild(closeBtn);
        overlay.appendChild(box);
        document.body.appendChild(overlay);
    }

    // ===== Send to backend =====
    async function sendToAgent() {
        if (!selections.length) return alert("No requirements to send!");
        try {
            const res = await fetch("http://localhost:8000/api/llm_requirements", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ requirements: selections }),
            });
            const data = await res.json();
            console.log("✅ Sent to LLM agent:", data);
            alert("✅ Sent successfully!");
            clearSelections();
        } catch (err) {
            console.error("❌ Send failed:", err);
            alert("❌ Failed to send to backend");
        }
    }

    // ===== Click handler =====
    document.addEventListener("click", e => {
        // Ignore clicks inside active input box or toolbar
        if (activeInputBox || e.target.closest(".dev-input-box") || e.target.closest(".dev-toolbar")) return;
        if (e.button !== 0) return; // left click only

        const comp = getReactComponentName(e.target) || "Unknown";
        highlight(e.target);
        const path = domPath(e.target);
        showInputBox(e.clientX, e.clientY, e.target, comp, path);
    }, true);

    // ===== Build toolbar on load =====
    window.addEventListener("DOMContentLoaded", buildToolbar);
})();
