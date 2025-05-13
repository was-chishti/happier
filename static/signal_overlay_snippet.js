
/**
 * Signal Overlay Module for HappierClient
 * Detects tone repetition, passive copy, weak CTAs and suggests behavioral shifts
 */

const signalBox = document.createElement("div");
signalBox.id = "signal-overlay";
signalBox.style = `
  position: fixed;
  bottom: 100px;
  left: 24px;
  max-width: 300px;
  padding: 12px 16px;
  background: #fffbe6;
  border: 1px solid #f4e2a0;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  font-family: 'Inter', sans-serif;
  font-size: 14px;
  color: #333333;
  z-index: 1002;
  display: none;
`;

document.body.appendChild(signalBox);

function updateSignalOverlay(text) {
  const weakCTA = /(let me know|just checking|hope this helps)/i.test(text);
  const repetitive = /(again|as mentioned earlier|to reiterate)/i.test(text);
  const passiveTone = /(you might want to|consider|could be)/i.test(text);

  const alerts = [];
  if (weakCTA) alerts.push("⚠️ Weak CTA detected. Try a stronger close.");
  if (repetitive) alerts.push("🔁 Repetitive structure. Reframe for freshness.");
  if (passiveTone) alerts.push("🪶 Passive tone. Use more decisive voice.");

  if (alerts.length > 0) {
    signalBox.innerHTML = `<strong>Signal Overlay</strong><ul style="padding-left: 20px; margin: 8px 0;">` +
      alerts.map(a => `<li>${a}</li>`).join("") + `</ul>`;
    signalBox.style.display = "block";
  } else {
    signalBox.style.display = "none";
  }
}

// Hook into bot reply insertion
const originalAppend = Element.prototype.appendChild;
Element.prototype.appendChild = function(child) {
  if (child && child.className === "msg bot") {
    updateSignalOverlay(child.textContent || "");
  }
  return originalAppend.call(this, child);
};
