from app import app, init_db, create_sample_data


# The app.app_context() is crucial here to make sure SQLAlchemy
# has the application context it needs to connect to the database.
with app.app_context():
    print("Initializing database schema...")
    init_db()
    print("✅ Database schema initialized.")

    print("\nCreating sample data (if database is empty)...")
    create_sample_data()
    print("✅ Sample data check complete.")

print("\nDatabase setup finished.")
print("You can now run the application using: python app.py")
