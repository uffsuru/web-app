# AuctionHub - Real-Time Auction Website

AuctionHub is a full-featured, real-time auction website built with Flask and Socket.IO. It provides a platform for users to create auctions, place bids, and manage their activities through a comprehensive dashboard. The application is designed to be robust and scalable, featuring a PostgreSQL backend, connection pooling, and caching strategies.

## Features

- **User Authentication**: Secure registration and login for users.
- **Real-Time Bidding**: Bids update instantly across all connected clients using Flask-SocketIO.
- **Real-Time Notifications**: Users receive instant notifications when they are outbid.
- **Auction Management**: Users can create, edit, and manage their own auctions.
- **Dashboard**: A personalized dashboard for users to track their bids, auctions, and orders.
- **Admin Panel**: A separate interface for administrators to manage users, auctions, and orders.
- **Database**: Uses PostgreSQL with SQLAlchemy for robust data management.
- **Performance**: Implements connection pooling, query indexing, and page caching for a fast user experience.

## Tech Stack

- **Backend**: Flask, Flask-SocketIO, Flask-SQLAlchemy
- **Database**: PostgreSQL
- **Frontend**: HTML, CSS, JavaScript
- **Real-Time Engine**: Socket.IO
- **Caching**: Flask-Caching

## Prerequisites

Before you begin, ensure you have the following installed:
- Python 3.8+
- PostgreSQL

## Setup and Installation

Follow these steps to get your local development environment running.

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/auction-website.git
cd auction-website
```

### 2. Create and Activate a Virtual Environment

It's highly recommended to use a virtual environment to manage project dependencies.

- **On Windows:**
  ```bash
  python -m venv venv
  venv\Scripts\activate
  ```

- **On macOS/Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 3. Install Dependencies

Install all the required Python packages from `requirements.txt`.

```bash
pip install -r requirements.txt
```

### 4. Set Up PostgreSQL Database

You need to have a PostgreSQL server running. Create a new database (e.g., `auction`) and a user with privileges.

### 5. Configure Environment Variables

Copy the example environment file (`.env.example`) to a new file named `.env` and update it with your PostgreSQL connection details.

### 6. Initialize the Database

This project uses Flask-Migrate to manage database schema changes.

**a. Set the FLASK_APP environment variable:**

The Flask command-line tool needs to know where your application is. Before running `flask` commands, set the environment variable in your terminal.

- **On Windows (Command Prompt):**
  ```bash
  set FLASK_APP=app.py
  ```

- **On Windows (PowerShell):**
  ```bash
  $env:FLASK_APP = "app.py"
  ```

- **On macOS/Linux:**
  ```bash
  export FLASK_APP=app.py
  ```

**b. Create the initial database schema:**

If this is your first time setting up the project, you need to initialize the migrations directory and apply the first migration.

```bash
# Run this only once for a new project setup
flask db init

# Generate the initial migration script (based on models.py)
flask db migrate -m "Initial migration."

# Apply the migration to create the tables in your database
flask db upgrade
```

### 7. Run the Application

Start the Flask development server. The application will be available at `http://localhost:5000`.

```bash
python app.py
```