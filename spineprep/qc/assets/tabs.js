/* Minimal tab switching for QC overlays */
function switchTab(tabName) {
    // Hide all tab contents
    document.querySelectorAll('.tab-content').forEach(el => {
        el.classList.remove('active');
    });
    // Remove active class from all tabs
    document.querySelectorAll('.tab').forEach(el => {
        el.classList.remove('active');
    });
    // Show selected tab content
    const content = document.getElementById(tabName);
    if (content) {
        content.classList.add('active');
    }
    // Activate selected tab
    const tab = document.querySelector(`[data-tab="${tabName}"]`);
    if (tab) {
        tab.classList.add('active');
    }
}

// Activate first tab on load
document.addEventListener('DOMContentLoaded', () => {
    const firstTab = document.querySelector('.tab');
    if (firstTab) {
        const tabName = firstTab.getAttribute('data-tab');
        switchTab(tabName);
    }
});
