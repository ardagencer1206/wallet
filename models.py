from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Numeric(18, 2), nullable=False, server_default="0.00")
    try_balance = db.Column(db.Numeric(18, 2), nullable=False, server_default="0.00")  # yeni eklendi

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class CommissionPool(db.Model):
    __tablename__ = "commission_pool"

    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Numeric(18, 2), nullable=False, server_default="0.00")


class CirculatingSupply(db.Model):
    __tablename__ = "circulating_supply"

    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Numeric(20, 2), nullable=False, server_default="0.00")


class SrdsValue(db.Model):
    __tablename__ = "srds_value"

    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.Numeric(20, 8), nullable=False, server_default="0.00")  # oranı daha hassas tut


class TransferHistory(db.Model):
    __tablename__ = "transfer_history"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    commission = db.Column(db.Numeric(18, 2), nullable=False)
    message = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Notification(db.Model):
    __tablename__ = "notification"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    message = db.Column(db.String(255), nullable=True)


class ExchangeHistory(db.Model):
    __tablename__ = "exchange_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    side = db.Column(db.String(4), nullable=False)  # BUY / SELL
    amount_try = db.Column(db.Numeric(18, 2), nullable=False)      # kullanıcının ödediği/aldığı TRY
    amount_srds = db.Column(db.Numeric(18, 8), nullable=False)     # aldığı/sattığı SRDS (8 hane tutuyoruz)
    fee_srds = db.Column(db.Numeric(18, 8), nullable=False)        # havuza giden komisyon (SRDS)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", foreign_keys=[user_id])

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])
