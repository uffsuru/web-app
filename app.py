import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, join_room
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_caching import Cache
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import json
from werkzeug.utils import secure_filename
import random
import os
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

app = Flask(__name__)
load_dotenv() # Load environment variables from .env file
app.secret_key = os.getenv('SECRET_KEY', 'a-default-dev-secret-key-that-is-not-secure')

# For production servers like Render using eventlet, we don't need to force 'threading'.
# For platforms like PythonAnywhere, async_mode='threading' is required.
# Let SocketIO auto-detect the best async mode.
socketio = SocketIO(app)

# --- Caching Configuration ---
cache = Cache(app, config={
    "CACHE_TYPE": "FileSystemCache",
    "CACHE_DIR": "/tmp",
    "CACHE_DEFAULT_TIMEOUT": 300
})


# --- SQLAlchemy Configuration for PostgreSQL ---
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    # Render's DATABASE_URL is in the format postgres://... but SQLAlchemy needs postgresql://...
    database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Fallback to local .env configuration for development
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'password')
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_NAME = os.getenv('DB_NAME', 'auction')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'

# These settings are good for production environments to prevent stale connections.
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,        # Detect dead connections
    "pool_recycle": 280,          # Recycle connections
    "pool_size": 5,               # Adjust pool size
    "max_overflow": 10,           # Allow temporary burst
}

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Import models after db is defined to avoid circular imports
from models import User, Auction, Bid, Order, Notification

migrate = Migrate(app, db)
from sqlalchemy import text

# --- Notification Helper ---
def create_notification(user_id, message, link):
    # SQLAlchemy handles connections automatically within the request context
    db.session.execute(text("INSERT INTO notifications (user_id, message, link, created_at) VALUES (:user_id, :message, :link, :created_at)"),
                       {'user_id': user_id, 'message': message, 'link': link, 'created_at': datetime.now()})
    db.session.commit()
    result = db.session.execute(text("SELECT * FROM notifications WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 1"), {'user_id': user_id})
    notification = result.mappings().first() # .mappings() allows dict-like access

    if isinstance(notification['created_at'], datetime):
        notification['created_at'] = notification['created_at'].isoformat()
    socketio.emit('new_notification', notification, room=str(user_id))

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        # Join a room for user-specific notifications
        join_room(str(session['user_id']))

# --- Add get_time_left helper and register as Jinja2 global ---
def get_time_left(end_time_str):
    """Calculate time left for an auction"""
    try:
        if end_time_str is None:
            return "Unknown"
        elif isinstance(end_time_str, str):
            end_time = datetime.fromisoformat(end_time_str)
        else:
            end_time = end_time_str
        now = datetime.now()
        if end_time > now:
            time_diff = end_time - now
            days = time_diff.days
            hours = time_diff.seconds // 3600
            if days > 0:
                return f"{days}d {hours}h left"
            else:
                return f"{hours}h left"
        else:
            return "Ended"
    except Exception:
        return "Unknown"

def get_delivery_date(order_date_str):
    """Calculate expected delivery date (7 days after order)."""
    try:
        if order_date_str is None:
            return "Not available"
        # Handle if the input is already a datetime object from the DB
        elif isinstance(order_date_str, datetime):
            order_date = order_date_str
        else:
            order_date = datetime.fromisoformat(order_date_str)

        delivery_date = order_date + timedelta(days=7)
        return delivery_date.strftime('%A, %b %d')
    except (ValueError, TypeError, AttributeError):
        return "Not available"

app.jinja_env.globals.update(get_time_left=get_time_left, get_delivery_date=get_delivery_date)

# --- Admin Decorator ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            # Redirect non-admins to the homepage
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ...existing code...

# Add order/payment route after app is defined
# Debug print to confirm route registration
print("Registering /order/<int:auction_id> route")
@app.route('/order/<int:auction_id>', methods=['GET', 'POST'])
def order(auction_id):
    print(f"/order route accessed with auction_id={auction_id}")
    if 'user_id' not in session:
        return redirect(url_for('index'))

    try:
        # Get auction details
        auction_result = db.session.execute(text('SELECT end_time FROM auctions WHERE id = :auction_id'), {'auction_id': auction_id})
        auction = auction_result.mappings().first()
        if not auction:
            return "Auction not found", 404

        # Check if auction ended
        end_time = auction['end_time']
        if not end_time or end_time > datetime.now():
            return "Auction not ended yet", 403

        # Get highest bid (winner)
        winner_result = db.session.execute(text('SELECT user_id, amount FROM bids WHERE auction_id = :auction_id ORDER BY amount DESC, bid_time ASC LIMIT 1'), {'auction_id': auction_id})
        winner = winner_result.mappings().first()
        if not winner or winner['user_id'] != session['user_id']:
            return "You are not the winner of this auction.", 403

        # Check if order already exists
        order_result = db.session.execute(text('SELECT id FROM orders WHERE auction_id = :auction_id AND user_id = :user_id'), {'auction_id': auction_id, 'user_id': session['user_id']})
        if order_result.mappings().first():
            return "Order already placed for this auction.", 400

        if request.method == 'POST':
            address = request.form.get('address')
            payment = request.form.get('payment')
            if address and payment:
                db.session.execute(text('INSERT INTO orders (auction_id, user_id, address, payment_status, order_status, created_at) VALUES (:auction_id, :user_id, :address, :payment_status, :order_status, :created_at)'),
                                  {'auction_id': auction_id, 'user_id': session['user_id'], 'address': address, 'payment_status': 'paid', 'order_status': 'Ordered', 'created_at': datetime.now()})
                db.session.commit()
                delivery_date = get_delivery_date(datetime.now())
                return render_template('order-success.html', delivery_date=delivery_date)
            else:
                return render_template('order.html', error='All fields are required.')

        return render_template('order.html')
    except Exception as e:
        print(f"Error in /order route: {e}")
        return render_template('error.html', message="A database error occurred."), 500


    # ...existing code...

@app.route('/')
@cache.cached(timeout=60, unless=lambda: 'category' in request.args) # Cache for 60s, but not if filtering
def index():
    category = request.args.get('category')
    try:
        query = '''SELECT * FROM auctions WHERE end_time > :now'''
        # Pass the datetime object directly, letting the driver handle formatting. This is more robust.
        params = {'now': datetime.now()}

        if category:
            query += ''' AND category = :category'''
            params['category'] = category

        query += ''' ORDER BY created_at DESC'''

        # Use SQLAlchemy session to execute the query
        result = db.session.execute(text(query), params)
        auctions = result.mappings().all() # .mappings().all() returns a list of dict-like objects

        return render_template('index.html', auctions=auctions)
    except Exception as e:
        print(f"Database error in index route: {e}")
        return render_template('error.html', message="A database error occurred."), 500

@app.route('/auction/<int:auction_id>')
def auction_detail(auction_id):
    try:
        # Get auction details
        auction_result = db.session.execute(text('SELECT * FROM auctions WHERE id = :auction_id'), {'auction_id': auction_id})
        auction = auction_result.mappings().first()

        if not auction:
            return "Auction not found", 404

        # Get bid history
        bids_result = db.session.execute(text('''SELECT b.amount, b.bid_time, u.name FROM bids b
                    JOIN users u ON b.user_id = u.id
                    WHERE b.auction_id = :auction_id ORDER BY b.bid_time DESC LIMIT 10'''), {'auction_id': auction_id})
        bids = bids_result.mappings().all()

        return render_template('auction-detail.html', auction=auction, bids=bids)
    except Exception as e:
        print(f"Error in auction_detail route: {e}")
        return render_template('error.html', message="A database error occurred."), 500

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    # This route now only fetches the FIRST page of the default tab ("My Bids")
    # to ensure the initial page load is extremely fast.
    try:
        page_size = 10  # Define a page size

        my_bids_query = """
            WITH RankedBids AS (
                SELECT b.user_id, b.auction_id, b.amount, b.bid_time,
                    ROW_NUMBER() OVER(PARTITION BY b.auction_id ORDER BY b.amount DESC, b.bid_time ASC) as rn
                FROM bids b WHERE b.user_id = :user_id
            )
            SELECT a.id, a.title, rb.amount, rb.bid_time, a.current_price, a.end_time, (o.id IS NOT NULL) as is_ordered
            FROM RankedBids rb JOIN auctions a ON rb.auction_id = a.id
            LEFT JOIN orders o ON a.id = o.auction_id AND o.user_id = rb.user_id
            WHERE rb.rn = 1 ORDER BY rb.bid_time DESC LIMIT :limit
        """
        # Fetch one extra item to check if there are more pages
        result = db.session.execute(text(my_bids_query), {'user_id': session['user_id'], 'limit': page_size + 1})
        my_bids = result.mappings().all()

        has_more_bids = len(my_bids) > page_size
        my_bids = my_bids[:page_size]

        return render_template('dashboard.html', my_bids=my_bids, has_more_bids=has_more_bids)
    except Exception as e:
        print(f"Error in dashboard route: {e}")
        return render_template('error.html', message="A database error occurred."), 500

@app.route('/api/dashboard_content')
def get_dashboard_content():
    """API endpoint to fetch paginated content for any dashboard tab."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    tab = request.args.get('tab')
    page = request.args.get('page', 1, type=int)
    page_size = 10
    offset = (page - 1) * page_size

    try:
        user_id = session['user_id']
        print(f"✅ API call for tab '{tab}', page {page}, user_id {user_id}")

        items = []
        template_name = ""
        template_context_key = ""
        query = ""
        params = {}

        if tab == 'my-bids':
            query = """
                WITH RankedBids AS (
                    SELECT b.user_id, b.auction_id, b.amount, b.bid_time,
                        ROW_NUMBER() OVER(PARTITION BY b.auction_id ORDER BY b.amount DESC, b.bid_time ASC) as rn
                    FROM bids b WHERE b.user_id = :user_id
                )
                SELECT a.id, a.title, rb.amount, rb.bid_time, a.current_price, a.end_time, (o.id IS NOT NULL) as is_ordered
                FROM RankedBids rb JOIN auctions a ON rb.auction_id = a.id
                LEFT JOIN orders o ON a.id = o.auction_id AND o.user_id = rb.user_id
                WHERE rb.rn = 1 ORDER BY rb.bid_time DESC LIMIT :limit OFFSET :offset
            """
            params = {'user_id': user_id, 'limit': page_size + 1, 'offset': offset}
            template_name = 'partials/_my_bids.html'
            template_context_key = 'my_bids'
        elif tab == 'my-auctions':
            query = '''SELECT a.*, COUNT(b.id) as bid_count
                         FROM auctions a LEFT JOIN bids b ON a.id = b.auction_id
                         WHERE a.seller_id = :user_id GROUP BY a.id ORDER BY a.created_at DESC
                         LIMIT :limit OFFSET :offset'''
            params = {'user_id': user_id, 'limit': page_size + 1, 'offset': offset}
            template_name = 'partials/_my_auctions.html'
            template_context_key = 'my_auctions'
        elif tab == 'my-orders':
            query = '''SELECT o.id, a.title, o.address, o.payment_status, o.order_status, o.created_at, a.image_url, a.id as auction_id
                         FROM orders o JOIN auctions a ON o.auction_id = a.id WHERE o.user_id = :user_id
                         ORDER BY o.created_at DESC LIMIT :limit OFFSET :offset'''
            params = {'user_id': user_id, 'limit': page_size + 1, 'offset': offset}
            template_name = 'partials/_my_orders.html'
            template_context_key = 'my_orders'
        else:
            return jsonify({'error': 'Invalid tab'}), 400

        result = db.session.execute(text(query), params)
        items = result.mappings().all()
        print(f"   -> Found {len(items) - 1 if len(items) > page_size else len(items)} items for '{tab}'.")

        has_more = len(items) > page_size
        items = items[:page_size]

        html = render_template(template_name, **{template_context_key: items})
        return jsonify({'html': html, 'has_more': has_more})
    except Exception as e:
        # This makes debugging easier by logging the actual error to the server log.
        print(f"❌ Error in /api/dashboard_content for tab '{tab}': {e}")
        # Return a specific error message to the client.
        return jsonify({'error': f'An error occurred while loading content for {tab}.'}), 500

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if not all([name, email, password]):
        return jsonify({'success': False, 'message': 'All fields required'})

    try:
        # Check if user already exists
        user_result = db.session.execute(
            text('SELECT id FROM users WHERE email = :email'),
            {'email': email}
        )
        if user_result.mappings().first():
            return jsonify({'success': False, 'message': 'Email already registered'})

        # Hash password
        hashed_password = generate_password_hash(password)

        # Insert user with email_verified = False
        db.session.execute(
            text('''
                INSERT INTO users (name, email, password, created_at, email_verified)
                VALUES (:name, :email, :password, :created_at, :email_verified)
            '''),
            {
                'name': name,
                'email': email,
                'password': hashed_password,
                'created_at': datetime.now(),
                'email_verified': False   # 👈 boolean, not integer
            }
        )
        db.session.commit()
        return jsonify({'success': True, 'message': 'Registration successful'})

    except SQLAlchemyError as e:
        db.session.rollback()   # 👈 rollback fix
        print(f"Error in register route: {e}")
        return jsonify({'success': False, 'message': 'Database error during registration.'})

    finally:
        db.session.close()  # 👈 cleanup session (good practice)


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user_result = db.session.execute(text('SELECT id, name, password, is_admin FROM users WHERE email = :email'), {'email': email})
    user = user_result.mappings().first()

    # SQLAlchemy automatically handles connection closing
    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        # Store admin status in session for easy access
        session['is_admin'] = user['is_admin']
        return jsonify({'success': True, 'message': 'Login successful'})

    return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/api/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/bid', methods=['POST'])
def place_bid():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})

    try:
        # Check if user is verified
        user_result = db.session.execute(text('SELECT email_verified FROM users WHERE id = :user_id'), {'user_id': session['user_id']})
        user = user_result.mappings().first()
        if not user or not user['email_verified']:
            return jsonify({'success': False, 'message': 'You must verify your email before bidding.'})

        data = request.get_json()
        auction_id = data.get('auction_id')
        bid_amount = float(data.get('amount'))

        # Get current auction details
        auction_result = db.session.execute(text('SELECT title, current_price, end_time, seller_id FROM auctions WHERE id = :auction_id'), {'auction_id': auction_id})
        auction = auction_result.mappings().first()

        if not auction:
            return jsonify({'success': False, 'message': 'Auction not found'})

        # Check if the bidder is the seller
        if auction['seller_id'] == session['user_id']:
            return jsonify({'success': False, 'message': 'You cannot bid on your own auction.'})

        end_time = auction['end_time']
        if end_time < datetime.now():
            return jsonify({'success': False, 'message': 'Auction has ended'})

        if bid_amount <= auction['current_price']:
            return jsonify({'success': False, 'message': 'Bid must be higher than current price'})

        # Get previous highest bidder
        highest_bidder_result = db.session.execute(text("SELECT user_id FROM bids WHERE auction_id = :auction_id ORDER BY amount DESC LIMIT 1"), {'auction_id': auction_id})
        highest_bidder = highest_bidder_result.mappings().first()

        # Place bid
        db.session.execute(text('INSERT INTO bids (auction_id, user_id, amount, bid_time) VALUES (:auction_id, :user_id, :amount, :bid_time)'),
                          {'auction_id': auction_id, 'user_id': session['user_id'], 'amount': bid_amount, 'bid_time': datetime.now()})

        # Update auction current price
        db.session.execute(text('UPDATE auctions SET current_price = :bid_amount WHERE id = :auction_id'), {'bid_amount': bid_amount, 'auction_id': auction_id})

        db.session.commit()

        # Notify previous highest bidder
        if highest_bidder and highest_bidder['user_id'] != session['user_id']:
            create_notification(highest_bidder['user_id'], f"You have been outbid on {auction['title']}.", f"/auction/{auction_id}")

        # Real-time update: broadcast the new bid to all clients in the auction room
        bid_data = {
            'auction_id': auction_id,
            'new_price': float(bid_amount),
            'bidder_name': session.get('user_name', 'Anonymous'),
            'bid_time': datetime.now().isoformat()
        }
        socketio.emit('bid_update', bid_data, room=f"auction_{auction_id}")

        return jsonify({'success': True, 'message': 'Bid placed successfully'})

    except Exception as e:
        print(f"Error in place_bid route: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred while placing the bid.'})

@app.route('/auction/<int:auction_id>/edit', methods=['GET', 'POST'])
def edit_auction(auction_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))

    auction_result = db.session.execute(text('SELECT a.*, (SELECT COUNT(*) FROM bids WHERE auction_id = a.id) as bid_count FROM auctions a WHERE a.id = :auction_id'), {'auction_id': auction_id})
    auction = auction_result.mappings().first()

    if not auction:
        return "Auction not found", 404

    if auction['seller_id'] != session['user_id']:
        return "You are not authorized to edit this auction.", 403

    # Prevent editing if bids have been placed
    if auction['bid_count'] > 0:
        # In a real app, use flash messaging to inform the user why they were redirected.
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            title = request.form.get('title')
            description = request.form.get('description')
            end_time = request.form.get('end_time')
            category = request.form.get('category')
            history_link = request.form.get('history_link')
            file = request.files.get('image_file')

            if file and len(file.read()) > 5 * 1024 * 1024:
                return render_template('edit-auction.html', auction=auction, error='File is too large. The limit is 5MB.')
            file.seek(0)

            if not all([title, description, end_time, category]):
                return render_template('edit-auction.html', auction=auction, error='All fields except image are required.')

            image_url = auction['image_url']
            if file and file.filename:
                allowed_exts = {'jpg', 'jpeg', 'png', 'gif', 'pdf', 'webp', 'bmp', 'tiff', 'svg'}
                ext = file.filename.rsplit('.', 1)[-1].lower()
                if ext in allowed_exts:
                    upload_folder = os.path.join(app.root_path, 'static', 'uploads')
                    os.makedirs(upload_folder, exist_ok=True)
                    filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                    file_path = os.path.join(upload_folder, filename)
                    file.save(file_path)
                    image_url = os.path.join('uploads', filename).replace('\\', '/')

            db.session.execute(text('''UPDATE auctions SET title = :title, description = :desc, end_time = :end_time, category = :cat, history_link = :hist, image_url = :img WHERE id = :id'''),
                                  {'title': title, 'desc': description, 'end_time': end_time, 'cat': category, 'hist': history_link, 'img': image_url, 'id': auction_id})
            db.session.commit()
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            print(f"Error editing auction: {e}")
            return render_template('edit-auction.html', auction=auction, error='An error occurred while saving.')

    # For GET request
    return render_template('edit-auction.html', auction=auction)
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    user_result = db.session.execute(text('SELECT name, email, created_at, email_verified FROM users WHERE id = :user_id'), {'user_id': session['user_id']})
    user = user_result.mappings().first()
    if not user:
        return "User not found", 404
    return render_template('profile.html', user=user)
@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            name = request.form.get('name')
            email = request.form.get('email')
            otp = request.form.get('otp')

            user_result = db.session.execute(text('SELECT name, email FROM users WHERE id = :user_id'), {'user_id': session['user_id']})
            user = user_result.mappings().first()

            if not name or not email:
                return render_template('edit-profile.html', user=user, error='All fields are required.')

            if email != user['email']:
                if 'email_change_otp' not in session or session.get('email_change_new') != email:
                    return render_template('edit-profile.html', user=user, error='Please request OTP for your new email before changing.')
                if not otp or str(otp) != str(session['email_change_otp']):
                    return render_template('edit-profile.html', user=user, error='Invalid OTP for email change.')

                existing_email_result = db.session.execute(text('SELECT id FROM users WHERE email = :email AND id != :user_id'), {'email': email, 'user_id': session['user_id']})
                if existing_email_result.mappings().first():
                    return render_template('edit-profile.html', user=user, error='Email already in use.')

                db.session.execute(text('UPDATE users SET name = :name, email = :email WHERE id = :user_id'), {'name': name, 'email': email, 'user_id': session['user_id']})
                session.pop('email_change_otp', None)
                session.pop('email_change_new', None)
            else:
                db.session.execute(text('UPDATE users SET name = :name WHERE id = :user_id'), {'name': name, 'user_id': session['user_id']})

            db.session.commit()
            session['user_name'] = name
            return redirect(url_for('profile'))
        except Exception as e:
            db.session.rollback()
            print(f"Error editing profile: {e}")
            user_result = db.session.execute(text('SELECT name, email FROM users WHERE id = :user_id'), {'user_id': session['user_id']})
            user = user_result.mappings().first()
            return render_template('edit-profile.html', user=user, error='An error occurred while saving.')
    else:
        user_result = db.session.execute(text('SELECT name, email FROM users WHERE id = :user_id'), {'user_id': session['user_id']})
        user = user_result.mappings().first()
        return render_template('edit-profile.html', user=user)

# Route to request OTP for email change
@app.route('/profile/request-email-change-otp', methods=['POST'])
def request_email_change_otp():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    new_email = request.form.get('new_email')
    if not new_email:
        return redirect(url_for('edit_profile'))
    # Generate OTP and store in session
    otp = random.randint(100000, 999999)
    session['email_change_otp'] = otp
    session['email_change_new'] = new_email
    print(f"[DEMO] OTP for changing email to {new_email}: {otp}")
    return redirect(url_for('edit_profile'))
# Profile page route
@app.route('/users')
def list_users():
    users_result = db.session.execute(text('SELECT id, name, email, created_at FROM users ORDER BY created_at ASC'))
    users = users_result.mappings().all()
    return render_template('users.html', users=users)


# --- OTP Email Verification Demo ---
# Route to request email verification (send OTP)
@app.route('/profile/request-verify', methods=['POST'])
def request_email_verification():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    # Generate a 6-digit OTP
    otp = random.randint(100000, 999999)
    session['otp'] = otp
    session['otp_user_id'] = session['user_id']
    print(f"[DEMO] OTP for user {session['user_id']}: {otp}")  # In real app, send via email
    return redirect(url_for('verify_otp'))

# Route to show OTP entry form
@app.route('/profile/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'user_id' not in session or 'otp' not in session or session.get('otp_user_id') != session['user_id']:
        return redirect(url_for('profile'))
    error = None
    if request.method == 'POST':
        entered_otp = request.form.get('otp')
        if entered_otp and str(entered_otp) == str(session['otp']):
            db.session.execute(text('UPDATE users SET email_verified = 1 WHERE id = :user_id'), {'user_id': session['user_id']})
            db.session.commit()

            session.pop('otp', None)
            session.pop('otp_user_id', None)
            return redirect(url_for('profile'))
        else:
            error = 'Invalid OTP. Please try again.'
    return render_template('verify-otp.html', error=error)

# --- Admin Panel Routes ---

@app.route('/admin')
@admin_required
def admin_dashboard():
    user_count = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    auction_count = db.session.execute(text("SELECT COUNT(*) FROM auctions")).scalar()
    order_count = db.session.execute(text("SELECT COUNT(*) FROM orders")).scalar()
    return render_template('admin/dashboard.html', user_count=user_count, auction_count=auction_count, order_count=order_count)

@app.route('/admin/users')
@admin_required
def admin_users():
    users_result = db.session.execute(text("SELECT * FROM users ORDER BY created_at DESC"))
    users = users_result.mappings().all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin_status(user_id):
    # Prevent an admin from demoting themselves to avoid getting locked out
    if user_id == session.get('user_id'):
        return redirect(url_for('admin_users'))

    user_result = db.session.execute(text("SELECT is_admin FROM users WHERE id = :user_id"), {'user_id': user_id})
    user = user_result.first()
    if user:
        new_status = not user[0]
        db.session.execute(text("UPDATE users SET is_admin = :status WHERE id = :user_id"), {'status': new_status, 'user_id': user_id})
        db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/admin/auctions')
@admin_required
def admin_auctions():
    auctions_result = db.session.execute(text("SELECT a.*, u.name as seller_name FROM auctions a JOIN users u ON a.seller_id = u.id ORDER BY a.created_at DESC"))
    auctions = auctions_result.mappings().all()
    return render_template('admin/auctions.html', auctions=auctions)

@app.route('/admin/auction/<int:auction_id>/delete', methods=['POST'])
@admin_required
def delete_auction(auction_id):
    try:
        db.session.execute(text("DELETE FROM bids WHERE auction_id = :auction_id"), {'auction_id': auction_id})
        db.session.execute(text("DELETE FROM auctions WHERE id = :auction_id"), {'auction_id': auction_id})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting auction: {e}")
    return redirect(url_for('admin_auctions'))

@app.route('/admin/orders')
@admin_required
def admin_orders():
    orders_result = db.session.execute(text("SELECT o.*, a.title as auction_title, u.name as buyer_name FROM orders o JOIN auctions a ON o.auction_id = a.id JOIN users u ON o.user_id = u.id ORDER BY o.created_at DESC"))
    orders = orders_result.mappings().all()
    order_statuses = ['Ordered', 'Picked', 'Shipped', 'Delivered', 'Cancelled']
    return render_template('admin/orders.html', orders=orders, statuses=order_statuses)

@app.route('/admin/order/<int:order_id>/update_status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    new_status = request.form.get('status')
    db.session.execute(text("UPDATE orders SET order_status = :status WHERE id = :order_id"), {'status': new_status, 'order_id': order_id})
    db.session.commit()

    order_result = db.session.execute(text("SELECT user_id FROM orders WHERE id = :order_id"), {'order_id': order_id})
    order = order_result.mappings().first()
    if order:
        create_notification(order['user_id'], f"Your order #{order_id} has been updated to {new_status}.", f"/dashboard")

    socketio.emit('status_update', {'order_id': order_id, 'status': new_status})
    return redirect(url_for('admin_orders'))

@app.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_as_read():
    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    db.session.execute(text("UPDATE notifications SET is_read = 1 WHERE user_id = :user_id"), {'user_id': session['user_id']})
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/notifications/summary')
def notifications_summary():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    unread_count_result = db.session.execute(text("SELECT COUNT(*) as count FROM notifications WHERE user_id = :user_id AND is_read = 0"), {'user_id': session['user_id']})
    unread_count = unread_count_result.scalar()

    notifications_result = db.session.execute(text("SELECT * FROM notifications WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 10"), {'user_id': session['user_id']})
    notifications = notifications_result.mappings().all()

    # Ensure datetime objects are JSON serializable
    for notification in notifications:
        if isinstance(notification.get('created_at'), datetime):
            notification['created_at'] = notification['created_at'].isoformat()

    return jsonify({'success': True, 'unread_count': unread_count, 'notifications': notifications})

@socketio.on('join_auction')
def handle_join_auction(data):
    """Client joins a room for a specific auction to receive real-time bid updates."""
    auction_id = data.get('auction_id')
    if auction_id:
        room = f"auction_{auction_id}"
        join_room(room)


if __name__ == '__main__':
    # This block is for local development only.
    # For production, a Gunicorn server is used as defined in render.yaml.
    print("🚀 Starting AuctionHub development server...")
    print("✅ Make sure your PostgreSQL server is running and configured in .env")
    print("➡️  Run `flask db upgrade` to set up/update the database.")
    print("➡️  Open your browser and go to: http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

