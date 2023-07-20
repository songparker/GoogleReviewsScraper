from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class DBUser(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    username = db.Column(db.Text(), nullable=False)
    email = db.Column(db.Text(), nullable=False)
    phone = db.Column(db.Text())
    password = db.Column(db.Text(), nullable=False)


class Reviews(db.Model):
    __tablename__ = 'reviews'
    id = db.Column(db.Integer(), primary_key=True)
    review_id = db.Column(db.Integer(), nullable=False)
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'), nullable=False)
    place_name = db.Column(db.Text(), nullable=False)
    reviewer = db.Column(db.Text(), nullable=False)
    rating = db.Column(db.Integer(), nullable=False)
    review_time = db.Column(db.Text(), nullable=False)
    review_content = db.Column(db.Text(), nullable=False)
    owner_response = db.Column(db.Text())


def create_all(app):
    with app.app_context():
        db.create_all()