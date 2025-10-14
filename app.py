import os
from decimal import Decimal

from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

from sqlalchemy import inspect, text, select
from sqlalchemy.exc import NoResultFound

from models import db, User, CommissionPool, TransferHistory, Notification
from forms import RegisterForm, LoginForm, TransferForm
from qrgenerate import generate_qr

def mysql_url_from_railway():
    host = os.getenv("MYSQLHOST")
    user = os.getenv("MYSQLUSER")
    password = os.getenv("MYSQLPASSWORD")
    database = os.getenv("MYSQLDATABASE")
    port = os.getenv("MYSQLPORT", "3306")
    if all([host, user, password, database]):
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
    return os.getenv("DATABASE_URL", "mysql+pymysql://root:password@127.0.0.1:3306/appdb?charset=utf8mb4")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = mysql_url_from_railway()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    with app.app_context():
        db.create_all()

        inspector = inspect(db.engine)

        # user.balance yoksa ekle
        cols = [c["name"] for c in inspector.get_columns("user")]
        if "balance" not in cols:
            db.session.execute(
                text("ALTER TABLE `user` ADD COLUMN `balance` DECIMAL(18,2) NOT NULL DEFAULT 0.00")
            )
            db.session.commit()

        # transfer_history.message yoksa ekle
        cols = [c["name"] for c in inspector.get_columns("transfer_history")]
        if "message" not in cols:
            db.session.execute(
                text("ALTER TABLE transfer_history ADD COLUMN message VARCHAR(500) NULL")
            )
            db.session.commit()

        # Komisyon havuzu tek satır (id=1) yoksa oluştur
        if not db.session.get(CommissionPool, 1):
            db.session.add(CommissionPool(id=1, total=Decimal("0.00")))
            db.session.commit()

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("home"))
        form = RegisterForm()
        if form.validate_on_submit():
            if User.query.filter_by(email=form.email.data).first():
                flash("Email zaten kayıtlı.", "danger")
                return redirect(url_for("register"))
            user = User(email=form.email.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Kayıt başarılı. Giriş yapın.", "success")
            return redirect(url_for("login"))
        return render_template("register.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("home"))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data).first()
            if user and user.check_password(form.password.data):
                login_user(user, remember=True)
                return redirect(request.args.get("next") or url_for("home"))
            flash("Geçersiz bilgiler.", "danger")
        return render_template("login.html", form=form)

    @app.route("/transfer", methods=["GET", "POST"])
    @login_required
    def transfer():
        form = TransferForm()
        if form.validate_on_submit():
            to_email = form.to_email.data.strip().lower()
            amount = (form.amount.data or Decimal("0")).quantize(Decimal("0.01"))

            if to_email == current_user.email.lower():
                flash("Kendinize gönderemezsiniz.", "danger")
                return redirect(url_for("transfer"))

            to_user = User.query.filter_by(email=to_email).first()
            if not to_user:
                flash("Alıcı bulunamadı.", "danger")
                return redirect(url_for("transfer"))

            # Komisyon: %0.2 (1/500). Gönderen öder, alıcı net tutarı alır.
            fee = (amount / Decimal("500")).quantize(Decimal("0.01"))
            total_debit = (amount + fee).quantize(Decimal("0.01"))

            try:
                sender = db.session.execute(
                    select(User).where(User.id == current_user.id).with_for_update()
                ).scalar_one()
                receiver = db.session.execute(
                    select(User).where(User.id == to_user.id).with_for_update()
                ).scalar_one()
                pool = db.session.execute(
                    select(CommissionPool).where(CommissionPool.id == 1).with_for_update()
                ).scalar_one()

                if sender.balance < total_debit:
                    flash("Bakiye yetersiz.", "danger")
                    db.session.rollback()
                    return redirect(url_for("transfer"))

                # Bakiye güncelle
                sender.balance = (Decimal(sender.balance) - total_debit).quantize(Decimal("0.01"))
                receiver.balance = (Decimal(receiver.balance) + amount).quantize(Decimal("0.01"))
                pool.total = (Decimal(pool.total) + fee).quantize(Decimal("0.01"))

                # Geçmiş kaydı
                history = TransferHistory(
                    sender_id=sender.id,
                    receiver_id=receiver.id,
                    amount=amount,
                    commission=fee,
                    message=form.message.data.strip() if getattr(form, "message", None) and form.message.data else None
                )
                db.session.add(history)

                # Bildirim kaydı
                notif = Notification(
                    sender_id=sender.id,
                    receiver_id=receiver.id,
                    amount=amount,
                    message=(form.message.data or "").strip() if getattr(form, "message", None) else None
                )
                db.session.add(notif)

                db.session.commit()
                flash(f"{to_email} adresine {amount} SRDS gönderildi.", "success")
                return redirect(url_for("home"))

            except NoResultFound:
                db.session.rollback()
                flash("İşlem sırasında kullanıcı bulunamadı.", "danger")
            except Exception as e:
                db.session.rollback()
                flash(f"İşlem başarısız: {str(e)}", "danger")

        return render_template("transfer.html", form=form)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("home"))

    @app.route("/history")
    @login_required
    def history():
        stmt = (
            select(TransferHistory, User.email)
            .join(User, User.id == TransferHistory.receiver_id)
            .where(TransferHistory.sender_id == current_user.id)
            .order_by(TransferHistory.created_at.desc())
        )
        results = db.session.execute(stmt).all()

        history_rows = []
        for transfer, to_email in results:
            history_rows.append({
                "to_email": to_email,
                "amount": transfer.amount,
                "commission": transfer.commission,
                "created_at": transfer.created_at
            })

        return render_template("history.html", history=history_rows)

    #qr generation
    @app.route("/qr")
    @login_required
    def qr():
        email = current_user.email
        qr_code = generate_qr(email)  # base64 string
        return render_template("qr.html", qr_code=qr_code, email=email)

    
    @app.route("/notifications")
    @login_required
    def notifications():
        notifs = (
            db.session.query(Notification, User.email)
            .join(User, User.id == Notification.sender_id)
            .filter(Notification.receiver_id == current_user.id)
            .order_by(Notification.created_at.desc())
            .all()
        )
        rows = []
        for notif, sender_email in notifs:
            rows.append({
                "from_email": sender_email,
                "amount": notif.amount,
                "message": notif.message,
                "created_at": notif.created_at
            })
        return render_template("notifications.html", notifications=rows)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
