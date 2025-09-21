from app import app, db
from models import User, Auction
from datetime import datetime, timedelta

def create_sample_data():
    """Create sample auction data if database is empty."""
    with app.app_context():
        # Check if auctions exist
        if db.session.query(Auction).count() == 0:
            print("📦 Database is empty. Seeding with sample data...")

            # Create a default user for sample auctions
            demo_user = db.session.query(User).filter_by(email='demo@example.com').first()
            if not demo_user:
                demo_user = User(
                    name="Demo Seller",
                    email="demo@example.com",
                    password="demo",  # ⚠️ In production, hash this
                    created_at=datetime.now()
                )
                db.session.add(demo_user)
                db.session.commit()
                print("👤 Demo user created.")

            # Now seed auctions
            sample_auctions = [
                Auction(
                    title="Vintage Rolex Watch",
                    description="Authentic vintage Rolex Submariner from 1978. In excellent condition.",
                    starting_price=2000,
                    current_price=2500,
                    end_time=(datetime.now() + timedelta(days=2)),
                    seller_id=demo_user.id,
                    category="Watches",
                    image_url="⌚",
                    created_at=datetime.now(),
                    history_link="https://en.wikipedia.org/wiki/Rolex_Submariner"
                ),
                Auction(
                    title="Rare Pokemon Cards Set",
                    description="Complete first edition Pokemon card collection",
                    starting_price=300,
                    current_price=450,
                    end_time=(datetime.now() + timedelta(days=1)),
                    seller_id=demo_user.id,
                    category="Collectibles",
                    image_url="🎮",
                    created_at=datetime.now()
                ),
                Auction(
                    title="Antique Painting",
                    description="18th century oil painting by renowned artist",
                    starting_price=1000,
                    current_price=1200,
                    end_time=(datetime.now() + timedelta(days=5)),
                    seller_id=demo_user.id,
                    category="Art",
                    image_url="🎨",
                    created_at=datetime.now()
                ),
            ]

            db.session.bulk_save_objects(sample_auctions)
            db.session.commit()
            print("✅ Sample data created.")
        else:
            print("ℹ️ Database already contains data. Skipping seed.")

if __name__ == '__main__':
    create_sample_data()
