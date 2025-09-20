document.addEventListener('DOMContentLoaded', function() {
    const tabs = document.querySelectorAll('.tab-link');
    const tabContents = document.querySelectorAll('.tab-content');
    const dashboardContainer = document.querySelector('.dashboard-container');
    const helpModal = document.getElementById('orderHelpModal');
    const closeHelpModal = document.getElementById('closeHelpModal');
    const helpOrderIdSpan = document.getElementById('helpOrderId');

    // --- Tab Switching and Lazy Loading ---
    tabs.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            const tabId = this.dataset.tab;

            tabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            tabContents.forEach(content => content.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');

            const contentList = document.querySelector(`#${tabId} .order-list, #${tabId} .auction-list, #${tabId} .bid-list`);
            // Load content only if the list has no element children (for lazy-loaded tabs)
            if (contentList && contentList.children.length === 0) {
                loadTabContent(tabId, 1);
            }
        });
    });

    // --- "Load More" and Help Modal button logic (using event delegation) ---
    if (dashboardContainer) {
        dashboardContainer.addEventListener('click', async function(event) {
            // Handle "Load More" clicks
            if (event.target.classList.contains('load-more-btn')) {
                const button = event.target;
                const tabId = button.dataset.tab;
                const nextPage = parseInt(button.dataset.nextPage, 10);

                button.disabled = true;
                button.textContent = 'Loading...';

                await loadTabContent(tabId, nextPage);
            }

            // Handle "Need Help?" clicks
            if (event.target.classList.contains('help-btn')) {
                const orderId = event.target.dataset.orderId;
                if (helpOrderIdSpan) helpOrderIdSpan.textContent = orderId;
                if (helpModal) helpModal.style.display = 'block';
            }
        });
    }

    async function loadTabContent(tabId, page) {
        const contentContainer = document.querySelector(`#${tabId} .order-list, #${tabId} .auction-list, #${tabId} .bid-list`);
        const loadMoreContainer = contentContainer.nextElementSibling;
        const button = loadMoreContainer ? loadMoreContainer.querySelector('.load-more-btn') : null;

        // Show spinner only on the first page load of a lazy tab
        if (page === 1) {
            contentContainer.innerHTML = '<div class="loading-spinner"></div>';
        }

        try {
            const response = await fetch(`/api/dashboard_content?tab=${tabId}&page=${page}`);
            if (!response.ok) throw new Error('Network response was not ok');

            const data = await response.json();

            if (page === 1) {
                contentContainer.innerHTML = data.html; // Replace spinner with content
            } else {
                contentContainer.insertAdjacentHTML('beforeend', data.html); // Append new items
            }

            // Manage the "Load More" button
            if (data.has_more) {
                const buttonHTML = `<button class="btn btn-secondary load-more-btn" data-tab="${tabId}" data-next-page="${page + 1}">Load More</button>`;
                loadMoreContainer.innerHTML = buttonHTML;
            } else {
                loadMoreContainer.innerHTML = ''; // No more items, remove the button
            }

            // Display empty state message if first page has no content
            if (page === 1 && !data.html.trim()) {
                const emptyMessages = {
                    'my-auctions': `<h3>You haven't created any auctions</h3><p>List an item to start selling.</p><a href="/create-auction" class="btn btn-primary">Create Auction</a>`,
                    'my-orders': `<h3>No orders yet</h3><p>Win an auction to see your orders here.</p><a href="/#auctions" class="btn btn-primary">Find Auctions</a>`
                };
                contentContainer.innerHTML = `<div class="empty-state">${emptyMessages[tabId] || ''}</div>`;
            }
        } catch (error) {
            console.error('Failed to load tab content:', error);
            contentContainer.innerHTML = '<div class="empty-state"><p>Could not load content. Please try again.</p></div>';
        }
    }

    if (closeHelpModal) {
        closeHelpModal.onclick = () => { if (helpModal) helpModal.style.display = 'none'; };
    }
    window.onclick = function(event) {
        if (event.target == helpModal) helpModal.style.display = 'none';
    };
});