document.addEventListener('DOMContentLoaded', function() {
    const bidForm = document.getElementById('bidForm');
    const auctionId = bidForm ? bidForm.dataset.auctionId : null;

    // --- Socket.IO Setup for Real-Time Updates ---
    if (auctionId) {
        const socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);

        socket.on('connect', function() {
            console.log('Socket connected, joining auction room:', auctionId);
            socket.emit('join_auction', { auction_id: auctionId });
        });

        socket.on('bid_update', function(data) {
            console.log('Received bid update:', data);
            // Update the current price display
            const currentPriceEl = document.getElementById('currentPrice');
            if (currentPriceEl) {
                currentPriceEl.textContent = `₹${parseFloat(data.new_price).toFixed(2)}`;
            }

            // Update minimum bid amount on the form
            const bidAmountInput = document.getElementById('bidAmount');
            if (bidAmountInput) {
                bidAmountInput.min = parseFloat(data.new_price) + 0.01;
                bidAmountInput.placeholder = `Enter bid > ₹${parseFloat(data.new_price).toFixed(2)}`;
            }

            // Add the new bid to the top of the history list
            const bidList = document.getElementById('bidList');
            if (bidList) {
                const newBidItem = document.createElement('div');
                newBidItem.className = 'bid-item';

                // Format time to be more readable
                const bidTime = new Date(data.bid_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

                newBidItem.innerHTML = `
                    <span class="bidder">${escapeHTML(data.bidder_name)}</span>
                    <span class="bid-amount">₹${parseFloat(data.bid_amount).toFixed(2)}</span>
                    <span class="bid-time">${bidTime}</span>
                `;

                // If "No bids yet" message exists, remove it.
                const noBidsMessage = bidList.querySelector('.no-bids-message');
                if (noBidsMessage) {
                    noBidsMessage.remove();
                }

                bidList.prepend(newBidItem);
            }
        });
    }
    
    // --- Helper to prevent XSS ---
    function escapeHTML(str) {
        var p = document.createElement("p");
        p.appendChild(document.createTextNode(str));
        return p.innerHTML;
    }

    // --- Alert Handling ---
    function showAlert(message, type) {
        const successAlert = document.getElementById('successAlert');
        const errorAlert = document.getElementById('errorAlert');
        
        // Hide both alerts first
        successAlert.style.display = 'none';
        errorAlert.style.display = 'none';
        
        const alertToShow = type === 'success' ? successAlert : errorAlert;
        alertToShow.textContent = message;
        alertToShow.style.display = 'block';
        
        setTimeout(() => {
            alertToShow.style.display = 'none';
        }, 5000);
    }
    
    // --- Form Submission ---
    if (bidForm) {
        bidForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const bidAmountInput = document.getElementById('bidAmount');
            const bidAmount = bidAmountInput.value;
            const submitButton = this.querySelector('button[type="submit"]');
            
            if (!bidAmount || parseFloat(bidAmount) <= 0) {
                showAlert('Please enter a valid bid amount', 'error');
                return;
            }
            
            submitButton.disabled = true;
            submitButton.textContent = 'Placing Bid...';
            
            try {
                const response = await fetch('/api/bid', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        auction_id: parseInt(auctionId), 
                        amount: parseFloat(bidAmount)
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showAlert('Bid placed successfully! The page will update.', 'success');
                    // Clear the input field
                    bidAmountInput.value = '';
                    // The UI will now be updated by the 'bid_update' socket event for all users,
                    // including the one who placed the bid. This ensures consistency.
                } else {
                    showAlert(result.message, 'error');
                }
            } catch (error) {
                console.error('Error placing bid:', error);
                showAlert('An error occurred. Please try again.', 'error');
            } finally {
                submitButton.disabled = false;
                submitButton.textContent = 'Place Bid';
            }
        });
    }
});